#!/usr/bin/env python3
"""Golden-deck test: extract -> translate (stubbed) -> inject -> assert parity.

Standalone — no pytest, no network, no API keys:

    cd backend && venv/bin/python tests/test_golden_deck.py

Why this exists: every format defect in REVIEW-format-integrity-2026-09-16.md —
per-run font scaling, SmartArt nodes written in the wrong order, the unreachable
append block, a lost `<a:ea>` slot — was invisible until a real deck was opened by
hand. This runs the real extractor, the real job pipeline and the real injector
over a fixed deck and asserts the structure survived, so a regression fails here
instead of in a client's deck.

Only the network call is stubbed (translation_service.batch_translate). Each unit
gets its own source text wrapped in ⟦…⟧, which makes the mapping exact: the
envelope identifies which unit a node holds, so a unit written to the wrong node
cannot pass. The stub also lengthens every string, so the box-fit machinery runs.
"""
import asyncio
import shutil
import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(TESTS))

from app.core.extractor import extract_pptx
from app.models import ExportRequest, TranslationJob, TranslationRequest
import app.main as app_main
from verify_translation_roundtrip import compare, inspect_deck, read_deck

SOURCE = BACKEND / 'test_real.pptx'
OPEN, CLOSE = '\u27e6', '\u27e7'  # ⟦ ⟧
FAILURES: list[str] = []
CHECKS = 0


def check(name, ok, detail=''):
    global CHECKS
    CHECKS += 1
    print(('  PASS  ' if ok else '  FAIL  ') + name + (f'  — {detail}' if detail else ''))
    if not ok:
        FAILURES.append(name)


def envelope(text: str) -> str:
    return f'{OPEN}{text}{CLOSE}'


class StubTranslationMemory:
    """Cache-free stand-in for the translation memory.

    The real memory answers units from earlier jobs, which would bypass the stub
    and make the result depend on unrelated history — a test that changes its
    mind is worse than no test. It also keeps this test from writing into the
    production cache.
    """

    def get(self, *args, **kwargs):
        return None

    def set(self, *args, **kwargs):
        return None

    def build_context_prompt(self, *args, **kwargs):
        return ''


def make_stub():
    async def stub_batch_translate(texts, source_lang=None, target_lang=None, model=None,
                                  context=None, concurrency=5, progress_callback=None,
                                  **kwargs):
        results = []
        for index, text in enumerate(texts, start=1):
            results.append((envelope(text), 'stub-deterministic', True))
            if progress_callback is not None:
                progress_callback(index)
        return results

    return stub_batch_translate


def filled_texts_by_slide(deck) -> list[list[str]]:
    """Non-empty node texts per slide, in the walker's document order."""
    per_slide: dict[int, list[str]] = {}
    for key in sorted(deck.paragraphs, key=lambda k: (k[0], str(k[1]), k[2])):
        slide_index = key[0]
        for run in deck.paragraphs[key]:
            if run.text.strip():
                per_slide.setdefault(slide_index, []).append(run.text)
    return [per_slide.get(i, []) for i in range(deck.slides)]


def expected_by_slide(document) -> list[list[str]]:
    """The envelopes a correct injection produces, per slide, in extraction order.

    Units are read in the same order the extractor walked the deck, which is the
    order the injector resolves them in; a SmartArt node numbered differently on
    either side therefore shows up as a shifted sequence rather than passing.
    """
    per_slide: dict[int, list[tuple[int, int, int, int, str]]] = {}
    for slide in document.slides:
        for box in slide.text_boxes:
            for run in box.runs:
                per_slide.setdefault(slide.slide_index, []).append(
                    (box.slide_index, box.shape_index, run.paragraph_index, run.run_index, run.text)
                )
    return [
        [envelope(text) for *_, text in sorted(per_slide.get(i, []))]
        for i in range(len(document.slides))
    ]


async def run_pipeline(tag: str) -> dict:
    job_id = f'golden-{tag}-{uuid.uuid4().hex[:8]}'
    upload_dir = Path(app_main.settings.upload_dir)
    output_dir = Path(app_main.settings.output_dir)
    upload_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    upload = upload_dir / f'{job_id}_{SOURCE.name}'
    shutil.copy(SOURCE, upload)
    out_name = f'_golden_{tag}.pptx'
    out_path = output_dir / out_name

    document = extract_pptx(str(upload), generate_preview=False)
    app_main.jobs[job_id] = TranslationJob(
        job_id=job_id,
        filename=SOURCE.name,
        status='pending',
        total_runs=document.total_runs,
        slides=document.slides,
    )
    app_main.job_store.save(app_main.jobs[job_id])

    runs = [run for slide in document.slides for box in slide.text_boxes for run in box.runs]
    request = TranslationRequest(
        runs=runs,
        source_language='ja',
        target_language='en',
        model='stub',
        job_id=job_id,
    )

    await app_main.translate_pptx(request)  # the real endpoint: queues the worker
    task = app_main._active_translations.get(job_id)
    if task is not None:
        await task  # and the real worker, which is where translation happens

    response = await app_main.export_pptx(ExportRequest(job_id=job_id, filename=out_name))
    return {
        'job_id': job_id,
        'job': app_main.jobs[job_id],
        'document': document,
        'upload': upload,
        'out_path': out_path,
        'failed': int(response.headers.get('x-injection-failed', '0')),
        'total': int(response.headers.get('x-injection-total', '0')),
    }


def cleanup(result: dict) -> None:
    job_id = result['job_id']
    for path in (result['out_path'], result['upload']):
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
    app_main.jobs.pop(result['job_id'], None)
    delete = getattr(app_main.job_store, 'delete', None)
    if delete is not None:
        try:
            delete(job_id)
        except Exception as exc:  # the test's own row must not linger
            print(f'  (store row {job_id} left in place: {exc})')


async def run_checks() -> None:
    if not SOURCE.exists():
        print(f'SOURCE MISSING: {SOURCE}')
        FAILURES.append('source deck present')
        return

    # Only the network call and the cache are replaced; everything else is the
    # production path.
    app_main.get_translation_memory = lambda: StubTranslationMemory()
    app_main.translation_service.batch_translate = make_stub()

    source_deck = read_deck(SOURCE)

    print('\n[1] pipeline: extract -> stub translate -> inject -> export')
    first = await run_pipeline('run1')
    try:
        check('job completed', first['job'].status == 'completed', first['job'].status)
        check('exported deck written', first['out_path'].exists(), str(first['out_path'].name))
        units = first['job'].translated_runs
        failed, total = first['failed'], first['total']
        check('injector reported no failures', failed == 0, f'failed={failed} total={total}')
        check('units match the injected run count',
              len(units) > 0 and total == len(units),
              f'units={len(units)} total={total}')

        check('every unit carries the stub model',
              all(tr.model_used == 'stub-deterministic' for tr in units))
        check('no provider failure was recorded',
              all(tr.success for tr in units),
              f'{sum(1 for tr in units if not tr.success)} failed')

        out_deck = read_deck(first['out_path'])

        print('\n[2] structural parity against the source deck')
        violations, warnings, stats = compare(source_deck, out_deck)
        check('verifier reports no violations', not violations, '; '.join(violations[:3]))
        for warning in warnings[:3]:
            print(f'         (warning) {warning}')

        print('\n[3] unit -> node mapping')
        actual = filled_texts_by_slide(out_deck)
        expected = expected_by_slide(first['document'])
        filled = sum(len(nodes) for nodes in actual)
        check('one filled node per translation unit',
              filled == len(units), f'filled={filled} units={len(units)}')

        translations = {tr.translated_text for tr in units}
        stray = [t for nodes in actual for t in nodes if t not in translations]
        check('every non-empty node holds a unit translation', not stray,
              f'{len(stray)} stray, e.g. {stray[:2]}')

        originals = {tr.original_text for tr in units}
        leftover = [t for nodes in actual for t in nodes if t in originals]
        check('no source text survived untranslated', not leftover,
              f'{len(leftover)} leftover, e.g. {leftover[:2]}')

        mismatch = [i for i in range(len(expected)) if sorted(expected[i]) != sorted(actual[i])]
        check('per-slide node contents match the expected envelopes', not mismatch,
              f'slides differing: {mismatch[:5]}' if mismatch else '')

        signals = inspect_deck(out_deck)
        print(f'         (signals) {signals}')
    finally:
        cleanup(first)

    print('\n[4] determinism: the same deck twice')
    second = await run_pipeline('run2')
    third = await run_pipeline('run3')
    try:
        second_deck = read_deck(second['out_path'])
        third_deck = read_deck(third['out_path'])
        check('two runs produce identical node text sequences',
              filled_texts_by_slide(second_deck) == filled_texts_by_slide(third_deck))
        check('two runs produce the same filled-node count',
              sum(len(n) for n in filled_texts_by_slide(second_deck)) ==
              sum(len(n) for n in filled_texts_by_slide(third_deck)))
    finally:
        cleanup(second)
        cleanup(third)


def main() -> int:
    asyncio.run(run_checks())

    print(f'\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed')
    if FAILURES:
        print('FAILED:')
        for name in FAILURES:
            print(f'  - {name}')
        return 1
    print('Golden-deck parity holds.')
    return 0


def test_golden_deck_parity() -> None:
    """`pytest tests/` runs the same checks as the script.

    Deck parity is the regression net for the extractor/injector pair, so it must not
    depend on someone remembering a second command.
    """
    asyncio.run(run_checks())
    assert not FAILURES, f'golden-deck checks failed: {FAILURES}'


if __name__ == '__main__':
    sys.exit(main())
