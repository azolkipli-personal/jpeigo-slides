"""Layer 3 — translation-quality review: terminology, register, leftovers.

Opt-in and report-only, served from the job's own translation units so the review
looks at what was actually written into the deck.

Split deliberately, the same way format integrity is split in §3 of the review:

- **Deterministic half** (`scan_leftovers`): Japanese characters left in the
  target text, empty translations, source==target pairs. Exact, free, no model —
  so the model is never asked to do a job a regex does better.
- **Model half** (`review_units`): the judgement calls — one source term rendered
  several different ways across the deck, register that shifts mid-deck, content
  that was dropped or invented.

Usage:

    cd backend && venv/bin/python -m app.qa.translation_review --from-job JOB_ID
    cd backend && venv/bin/python -m app.qa.translation_review --from-file units.json
"""
import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

from app.config import get_settings
from app.qa import client

DEFAULT_MODEL = os.environ.get('REVIEW_MODEL', 'gemini-3.1-pro-preview')
BATCH_SIZE = 60

CJK = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]')
# Money, units and product codes are legitimately left alone; a review that flags
# them every time is noise, and noise is what makes a report unreadable.
LEFTOVER_EXEMPT = re.compile(r'^[\s\d\.,\-–—/%()+¥$€円個件名様分秒年月日:：]*$')

FINDING_TYPES = (
    'terminology', 'register', 'omission', 'addition', 'leftover_japanese',
    'empty_translation', 'untranslated_pair', 'other',
)

PROMPT = """You are reviewing an automated Japanese -> English translation of a \
business presentation. Below are {count} translation units from one deck, as \
"<index> | <source> | <translation>".

Report only these, and only when the evidence is in the text itself:

1. terminology — the same source term translated inconsistently across these \
units (e.g. one term rendered three different ways). Name the source term, list \
the variants, and give the indices.
2. register — the tone shifting between units in a way that would read as \
inconsistent in one document (abrupt switch between formal and casual, or a \
heading rendered as a sentence).
3. omission — meaning present in the source that is missing from the translation.
4. addition — content the translation invents that the source does not say.
5. other — a clear error that fits none of the above.

Rules: do not comment on layout or formatting. Do not rewrite the translation. \
Do not report a single isolated awkward phrase unless it changes the meaning. If \
these units are consistent, say so — an empty findings list is a valid answer.

Answer with JSON only, no prose:
{{"findings": [{{"type": "terminology | register | omission | addition | other",
                 "severity": "low | medium | high",
                 "detail": "what is inconsistent or wrong, in one sentence",
                 "indices": [1, 4],
                 "examples": ["source | translation", "..."]}}],
  "summary": "one sentence on the quality of these units"}}
"""


def scan_leftovers(units: list[dict]) -> list[dict]:
    """Deterministic findings: leftovers, empties, unchanged pairs.

    `units` is a list of {'original_text', 'translated_text', optional 'slide'}.
    """
    findings: list[dict] = []
    leftovers, empties, unchanged = [], [], []
    for index, unit in enumerate(units, start=1):
        source = (unit.get('original_text') or '').strip()
        target = (unit.get('translated_text') or '').strip()

        if source and not target:
            empties.append(index)
            continue
        if source and source == target and CJK.search(source):
            unchanged.append(index)
            continue
        if target and CJK.search(target) and not LEFTOVER_EXEMPT.match(target):
            leftovers.append(index)

    if leftovers:
        findings.append({
            'type': 'leftover_japanese', 'severity': 'high',
            'detail': f'{len(leftovers)} unit(s) still contain Japanese characters in the '
                      f'translated text, so these runs stay Japanese in the exported deck',
            'indices': leftovers[:20], 'examples': [],
        })
    if empties:
        findings.append({
            'type': 'empty_translation', 'severity': 'high',
            'detail': f'{len(empties)} unit(s) have source text but an empty translation',
            'indices': empties[:20], 'examples': [],
        })
    if unchanged:
        findings.append({
            'type': 'untranslated_pair', 'severity': 'medium',
            'detail': f'{len(unchanged)} unit(s) came back identical to the Japanese source',
            'indices': unchanged[:20], 'examples': [],
        })
    return findings


def build_prompt(batch: list[tuple[int, dict]]) -> str:
    lines = []
    for index, unit in batch:
        source = ' '.join((unit.get('original_text') or '').split())
        target = ' '.join((unit.get('translated_text') or '').split())
        lines.append(f'{index} | {source} | {target}')
    return PROMPT.format(count=len(batch)) + '\n' + '\n'.join(lines)


async def review_units(units: list[dict], model: str | None = None,
                       batch_size: int = BATCH_SIZE) -> dict:
    """Deterministic scan plus a batched model review of the same units."""
    settings = get_settings()
    model = model or DEFAULT_MODEL
    report = {
        'model': model,
        'units_reviewed': len(units),
        'batches': 0,
        'findings': scan_leftovers(units),
        'errors': [],
    }
    report['deterministic_findings'] = len(report['findings'])

    batches = [(start + 1, units[start:start + batch_size])
               for start in range(0, len(units), batch_size)]

    async def one_batch(number: int, batch: list[dict]) -> dict:
        numbered = [(number + offset, unit) for offset, unit in enumerate(batch)]
        answer = await client.generate(model, build_prompt(numbered))
        return client.load_json(answer)

    results = await asyncio.gather(
        *(one_batch(number, batch) for number, batch in batches),
        return_exceptions=True,
    )

    for (number, batch), result in zip(batches, results):
        if isinstance(result, BaseException):
            report['errors'].append({'first_index': number, 'error': str(result)[:300]})
            continue
        report['batches'] += 1
        for finding in result.get('findings') or []:
            if not isinstance(finding, dict):
                continue
            finding_type = str(finding.get('type', 'other'))
            report['findings'].append({
                'type': finding_type if finding_type in FINDING_TYPES else 'other',
                'severity': str(finding.get('severity', 'low')),
                'detail': str(finding.get('detail', '')),
                'indices': [i for i in (finding.get('indices') or []) if isinstance(i, int)],
                'examples': [str(e) for e in (finding.get('examples') or [])][:5],
            })

    high = sum(1 for f in report['findings'] if f['severity'] == 'high')
    report['summary'] = (
        f'{report["units_reviewed"]} units in {report["batches"]} batch(es); '
        f'{len(report["findings"])} findings ({high} high)'
    )
    if report['errors']:
        report['summary'] += f'; {len(report["errors"])} review errors'
    return report


def units_from_job(job_id: str) -> list[dict]:
    """Read a job's units from the store — what the deck actually contains."""
    from app.job_store import JobStore

    job = JobStore().load(job_id)
    if job is None:
        raise SystemExit(f'no job {job_id} in the store')
    return [{'original_text': run.original_text, 'translated_text': run.translated_text,
             'model_used': run.model_used, 'success': run.success}
            for run in job.translated_runs]


def _print(report: dict) -> None:
    print(report['summary'])
    print(f'model: {report["model"]}')
    for finding in report['findings']:
        print(f'  [{finding["severity"]}/{finding["type"]}] {finding["detail"]}')
        if finding['indices']:
            print(f'      units: {finding["indices"][:10]}')
        for example in finding['examples'][:3]:
            print(f'      e.g. {example}')
    for error in report['errors']:
        print(f'  batch at unit {error["first_index"]}: review error — {error["error"]}')


def main() -> int:
    parser = argparse.ArgumentParser(description='Layer 3 translation review')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--from-job', help='job_id to read units from the job store')
    source.add_argument('--from-file', help='JSON file: a list of {original_text, translated_text}')
    parser.add_argument('--model', default=None)
    parser.add_argument('--limit', type=int, default=None,
                        help='review only the first N units (cost control on long decks)')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    if args.from_job:
        units = units_from_job(args.from_job)
    else:
        units = json.loads(Path(args.from_file).read_text())

    if not units:
        print('no translation units to review')
        return 2
    if args.limit:
        units = units[:args.limit]

    report = asyncio.run(review_units(units, model=args.model))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print(report)
    return 1 if report['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
