#!/usr/bin/env python3
"""PDF upload -> extract -> translate -> export PDF, and the PPTX path beside it.

Standalone — no pytest, no network, no API keys:

    cd backend && venv/bin/python tests/test_pdf_roundtrip.py

Runs the *real* endpoints (upload, translate worker, export) twice: once with
the sample deck as .pptx, once as .PDF (uppercase, to pin the case-insensitive
gate). Only the network call is stubbed — each unit's translation is
`T%04d <original text>`, which is short, ASCII and contamination-free, so the
assertion is exact: every unit's translated text must be extractable from the
exported PDF with pdftotext.

What this pins:

  * .pptx behaves as it does today (response shape, source_format, PPTX export)
  * a PDF upload converts to the intermediate PPTX, extracts, and answers with
    the byte-identical response shape
  * the export for a PDF job is a real PDF (media type + %PDF magic + text
    readable by pdftotext) carrying every translated unit
  * the 400 gate names both supported types
"""
import asyncio
import io
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(TESTS))

from fastapi import HTTPException, UploadFile

from app.core.pdf_bridge import pptx_to_pdf
from app.models import ExportRequest, TranslationRequest
import app.main as app_main

SAMPLE = BACKEND.parent / 'public' / 'sample-deck.pptx'
FAILURES: list[str] = []
CHECKS = 0
CLEANUP: list[tuple[str, str]] = []  # (kind, id) — kinds: job | file | output


def check(name, ok, detail=''):
    global CHECKS
    CHECKS += 1
    print(('  PASS  ' if ok else '  FAIL  ') + name + (f'  — {detail}' if detail else ''))
    if not ok:
        FAILURES.append(name)


class StubTranslationMemory:
    """Cache-free stand-in: a real cache hit would answer from unrelated jobs."""

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
            results.append((f'T{index:04d} {text}', 'stub-deterministic', True))
            if progress_callback is not None:
                progress_callback(index)
        return results

    return stub_batch_translate


async def upload(filename: str, path: Path):
    handle = UploadFile(file=io.BytesIO(path.read_bytes()), filename=filename)
    return await app_main.upload_pptx(file=handle)


async def translate_and_export(export_name: str):
    """Translate through the real endpoint (async worker), then export."""
    job = app_main.jobs[_last_job_id]
    runs = [run for slide in job.slides for box in slide.text_boxes for run in box.runs]
    request = TranslationRequest(runs=runs, source_language='en', target_language='ja',
                                 model='stub', job_id=job.job_id)
    await app_main.translate_pptx(request)
    task = app_main._active_translations.get(job.job_id)
    if task is not None:
        await task
    response = await app_main.export_pptx(
        ExportRequest(job_id=job.job_id, filename=export_name))
    return job, response


_last_job_id = ''


async def do_upload(filename: str, path: Path):
    global _last_job_id
    response = await upload(filename, path)
    _last_job_id = response.job_id
    CLEANUP.append(('job', response.job_id))
    CLEANUP.append(('file', response.job_id))
    return response


def pdftotext(path: Path) -> str:
    result = subprocess.run(['pdftotext', str(path), '-'],
                            capture_output=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f'pdftotext failed: {result.stderr.decode(errors="replace")}')
    return result.stdout.decode('utf-8', errors='replace')


def squash(text: str) -> str:
    """Alphanumerics only, lowercased.

    pdftotext reflows narrow text boxes: a wrapped line can split a marker
    mid-token ("T001" / "2 Q1"), a hyphen at a line end can vanish
    ("ready-to-present" -> "ready-topresent") and bullet glyphs are dropped.
    The text is in the PDF in all three cases, so the assertion compares
    content, not layout.
    """
    return ''.join(ch for ch in text.lower() if ch.isalnum())


def shape_of(response) -> dict:
    """Structural fingerprint of an upload response, for the byte-identical check."""
    slide = response.slides[0] if response.slides else {}
    box = slide.get('text_boxes', [{}])[0] if slide else {}
    run = box.get('runs', [{}])[0] if box else {}
    return {
        'top': sorted(response.model_dump().keys()),
        'slide': sorted(slide.keys()),
        'box': sorted(box.keys()),
        'run': sorted(run.keys()),
    }


async def run_checks() -> None:
    if not SAMPLE.exists():
        print(f'SOURCE MISSING: {SAMPLE}')
        FAILURES.append('sample deck present')
        return

    app_main.get_translation_memory = lambda: StubTranslationMemory()
    app_main.translation_service.batch_translate = make_stub()

    upload_dir = Path(app_main.settings.upload_dir)
    output_dir = Path(app_main.settings.output_dir)
    upload_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix='pdf-roundtrip-'))
    try:
        print('\n[1] upload gate: rejects other types, names both supported ones')
        try:
            await upload('notes.txt', SAMPLE)
            check('non-deck upload rejected', False, 'no exception raised')
        except HTTPException as exc:
            detail = str(exc.detail)
            check('non-deck upload rejected with 400', exc.status_code == 400,
                  f'status={exc.status_code}')
            check('rejection names both supported types',
                  '.pptx' in detail and '.pdf' in detail, detail)

        print('\n[2] pptx path: upload -> translate -> export (unchanged behaviour)')
        pptx_resp = await do_upload('sample-deck.pptx', SAMPLE)
        check('pptx upload extracts the deck',
              pptx_resp.total_slides == 3 and pptx_resp.total_runs > 0,
              f'slides={pptx_resp.total_slides} runs={pptx_resp.total_runs}')
        pptx_job, pptx_export = await translate_and_export('translated_sample-deck.pptx')
        check('pptx job records source_format=pptx', pptx_job.source_format == 'pptx',
              pptx_job.source_format)
        check('pptx export serves the presentation media type',
              pptx_export.media_type
              == 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
              str(pptx_export.media_type))
        check('pptx export reports its injection counts',
              pptx_export.headers.get('x-injection-failed') == '0'
              and int(pptx_export.headers.get('x-injection-total', '0')) > 0,
              f"failed={pptx_export.headers.get('x-injection-failed')} "
              f"total={pptx_export.headers.get('x-injection-total')}")
        pptx_out = output_dir / 'translated_sample-deck.pptx'
        check('pptx export file written', pptx_out.exists())
        check('pptx export file is a real PPTX',
              pptx_out.exists() and zipfile.is_zipfile(pptx_out))
        CLEANUP.append(('output', pptx_out.name))

        print('\n[3] pdf path: uppercase .PDF upload -> intermediate -> extraction')
        pdf_source = work / 'sample-deck.pdf'
        pptx_to_pdf(SAMPLE, work)  # makes work/sample-deck.pdf
        if not pdf_source.exists():
            produced = sorted(work.glob('*.pdf'))
            check('test PDF produced from the sample deck', False,
                  f'expected {pdf_source}, got {produced}')
            return
        pdf_resp = await do_upload('sample-deck.PDF', pdf_source)
        check('pdf upload extracts the deck',
              pdf_resp.total_slides == 3 and pdf_resp.total_runs > 0,
              f'slides={pdf_resp.total_slides} runs={pdf_resp.total_runs}')
        check('upload response shape is identical for pptx and pdf',
              shape_of(pdf_resp) == shape_of(pptx_resp))
        pdf_job = app_main.jobs[pdf_resp.job_id]
        check('job records source_format=pdf', pdf_job.source_format == 'pdf',
              pdf_job.source_format)
        check('job records the original upload name',
              pdf_job.source_filename == 'sample-deck.PDF',
              str(pdf_job.source_filename))
        intermediate = upload_dir / f'{pdf_resp.job_id}_sample-deck.PDF.pptx'
        check('intermediate PPTX written next to the PDF upload',
              intermediate.exists(), str(intermediate.name))

        print('\n[4] translate + export a PDF job')
        pdf_job, pdf_export = await translate_and_export('sample-deck.pdf')
        units = pdf_job.translated_runs
        check('translation ran with the stubbed model',
              len(units) > 0 and all(u.model_used == 'stub-deterministic' for u in units),
              f'units={len(units)}')
        check('export serves application/pdf', pdf_export.media_type == 'application/pdf',
              str(pdf_export.media_type))
        check('export reports its injection counts',
              pdf_export.headers.get('x-injection-failed') == '0'
              and int(pdf_export.headers.get('x-injection-total', '0')) == len(units),
              f"failed={pdf_export.headers.get('x-injection-failed')} "
              f"total={pdf_export.headers.get('x-injection-total')}")
        pdf_out = output_dir / 'sample-deck.pdf'
        CLEANUP.append(('output', pdf_out.name))
        check('exported PDF written', pdf_out.exists(), str(pdf_out.name))
        check('exported file really starts with %PDF',
              pdf_out.exists() and pdf_out.read_bytes()[:4] == b'%PDF')

        print('\n[5] pdftotext: every translated unit is readable in the PDF')
        flat_squashed = squash(pdftotext(pdf_out))
        missing = [u.translated_text for u in units
                   if squash(u.translated_text) not in flat_squashed]
        check('every translated unit present in the exported PDF', not missing,
              f'{len(missing)}/{len(units)} missing, e.g. {missing[:2]}')
        markers = {u.translated_text.split(' ', 1)[0] for u in units}
        found = {m for m in markers if squash(m) in flat_squashed}
        check('unit markers all present', found == markers,
              f'{len(found)}/{len(markers)} markers, missing {sorted(markers - found)}')

        if shutil.which('pdfinfo'):
            info = subprocess.run(['pdfinfo', str(pdf_out)], capture_output=True,
                                  timeout=30).stdout.decode(errors='replace')
            pages = next((line.split(':')[1].strip() for line in info.splitlines()
                          if line.startswith('Pages:')), '?')
            check('exported PDF has one page per slide',
                  str(pptx_resp.total_slides) == pages,
                  f'pages={pages} slides={pptx_resp.total_slides}')

        print('\n[6] the intermediate stays usable after export (re-export works)')
        check('intermediate PPTX still present and valid after export',
              intermediate.exists() and zipfile.is_zipfile(intermediate))
        again = await app_main.export_pptx(
            ExportRequest(job_id=pdf_job.job_id, filename='sample-deck-again.pdf'))
        again_path = output_dir / 'sample-deck-again.pdf'
        CLEANUP.append(('output', again_path.name))
        check('a second export of the same job succeeds',
              again_path.exists() and again_path.read_bytes()[:4] == b'%PDF')
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cleanup() -> None:
    upload_dir = Path(app_main.settings.upload_dir)
    output_dir = Path(app_main.settings.output_dir)
    for kind, ident in reversed(CLEANUP):
        try:
            if kind == 'job':
                app_main.jobs.pop(ident, None)
                app_main.job_store.delete(ident)
            elif kind == 'file':
                for stale in upload_dir.glob(f'{ident}_*'):
                    stale.unlink()
            elif kind == 'output':
                (output_dir / ident).unlink(missing_ok=True)
        except Exception as exc:  # the test's own litter must not fail the run
            print(f'  (cleanup {kind} {ident}: {exc})')


async def run() -> None:
    try:
        await run_checks()
    finally:
        cleanup()


def main() -> int:
    asyncio.run(run())
    print(f'\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed')
    if FAILURES:
        print('FAILED:')
        for name in FAILURES:
            print(f'  - {name}')
        return 1
    print('PDF and PPTX round trips both hold.')
    return 0


def test_pdf_roundtrip() -> None:
    """`pytest tests/` runs the same checks as the script."""
    assert main() == 0, 'pdf round-trip checks failed'


if __name__ == '__main__':
    sys.exit(main())
