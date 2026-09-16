"""The progressive deck review and the job registry that drives it.

Why this is tested: a chunked/one-shot check could lose slides it never reached and
still report clean. These cover the two properties that protect against that — a deck
is walked to the end even when one slide errors, and the job reports progress while it
runs so a caller never has to hold a request open for minutes.
"""
import asyncio
from pathlib import Path

import pytest

from app.qa import jobs, vision_qa


@pytest.fixture(autouse=True)
def _clean_registry():
    jobs.clear()
    yield
    jobs.clear()


@pytest.fixture
def no_key_problem(monkeypatch):
    monkeypatch.setattr(vision_qa.client, 'key_problem', lambda model: None)


def _render(tmp_path: Path, count: int) -> list[Path]:
    """Stand-in for rendered slides — names carry the absolute slide number."""
    images = []
    for number in range(1, count + 1):
        path = tmp_path / f'slide-{number:02d}.png'
        path.write_bytes(b'png')
        images.append(path)
    return images


def test_progressive_reviews_every_slide_and_survives_one_failure(tmp_path, monkeypatch,
                                                                 no_key_problem):
    async def fake(model, image, number, total, semaphore, usage=None):
        if number == 2:
            raise RuntimeError('finish_reason: length — empty content')
        if number == 3:
            return {'slide': number, 'verdict': 'major', 'summary': 'overflow',
                    'issues': [{'slide': number, 'type': 'overflow', 'severity': 'high',
                                'where': 'top-right box', 'detail': 'text past border'}]}
        return {'slide': number, 'verdict': 'ok', 'summary': '', 'issues': []}

    monkeypatch.setattr(vision_qa, 'review_slide', fake)
    seen: list[tuple[int, int]] = []

    report = asyncio.run(vision_qa.review_deck_progressive(
        tmp_path / 'deck.pptx', model='kimi-k3', images=_render(tmp_path, 4),
        concurrency=1, on_progress=lambda r: seen.append((r['slides_checked'], len(r['errors'])))))

    assert report['slides_checked'] == 3, 'one bad slide must not drop the other three'
    assert report['slides_rendered'] == 4
    assert [error['slide'] for error in report['errors']] == [2]
    assert [issue['slide'] for issue in report['issues']] == [3]
    assert [slide['slide'] for slide in report['flagged_slides']] == [3]
    assert len(seen) == 4, 'progress is published for every finished slide'
    assert seen[-1] == (3, 1)
    assert 'review errors' in report['summary'], 'the summary must admit the gap'


def test_slide_numbers_stay_absolute_when_a_range_is_rendered(tmp_path, monkeypatch,
                                                              no_key_problem):
    """A sliced check must attribute findings to real slide numbers."""
    async def fake(model, image, number, total, semaphore, usage=None):
        return {'slide': number, 'verdict': 'minor', 'summary': '',
                'issues': [{'slide': number, 'type': 'overlap', 'severity': 'low',
                            'where': 'footer', 'detail': 'touching'}]}

    monkeypatch.setattr(vision_qa, 'review_slide', fake)
    images = _render(tmp_path, 3)
    images = [images[0].rename(tmp_path / 'slide-11.png'),
              images[1].rename(tmp_path / 'slide-12.png'),
              images[2].rename(tmp_path / 'slide-13.png')]

    report = asyncio.run(vision_qa.review_deck(tmp_path / 'deck.pptx', model='kimi-k3',
                                               images=images, concurrency=1))

    assert [issue['slide'] for issue in report['issues']] == [11, 12, 13]
    assert (report['first_slide'], report['last_slide']) == (11, 13)


def test_a_model_without_a_key_is_not_a_clean_deck(tmp_path, monkeypatch):
    monkeypatch.setattr(vision_qa.client, 'key_problem',
                        lambda model: 'no OpenCode key configured')

    report = asyncio.run(vision_qa.review_deck(tmp_path / 'deck.pptx', model='kimi-k3',
                                               images=_render(tmp_path, 2), concurrency=1))

    assert report['slides_checked'] == 0
    assert report['issues'] == []
    assert report['errors'][0]['error'] == 'no OpenCode key configured'
    assert report['summary'] == 'no OpenCode key configured'


def test_job_registry_runs_detached_and_reports_progress(tmp_path, monkeypatch):
    async def fake_progressive(deck, model=None, on_progress=None):
        report = vision_qa.new_report(deck, model or 'kimi-k3')
        report.update({'slides_rendered': 2, 'slides_checked': 2, 'deck_slides': 2})
        report['issues'].append({'slide': 1, 'type': 'overflow', 'severity': 'high',
                                 'where': 'box', 'detail': 'past border'})
        if on_progress:
            on_progress(report)
        return vision_qa.summarize(report)

    monkeypatch.setattr(vision_qa, 'review_deck_progressive', fake_progressive)
    saved: list[dict] = []

    async def scenario():
        check = jobs.start('job-1', tmp_path / 'deck.pptx', 'kimi-k3',
                           on_finish=lambda report: saved.append(report))
        running_state = check.state
        assert check.task is not None
        await check.task
        return running_state, check

    running_state, check = asyncio.run(scenario())

    assert running_state == 'running', 'start() must not block on the check'
    assert check.state == 'done'
    assert (check.checked, check.total) == (2, 2)
    assert jobs.get('job-1') is check
    assert jobs.get('job-1', 'original') is None
    assert len(saved) == 1, 'the finished report is handed to the job store'


def test_token_usage_becomes_a_cost_estimate(tmp_path, monkeypatch, no_key_problem):
    """The check's spend has to be visible: counts in, dollars out.

    OpenCode Go bills per token against a dollar limit per model, so reviewing a deck
    is real money. These totals are what made the choice of default model a question
    of cost rather than taste.
    """
    async def fake(model, image, number, total, semaphore, usage=None):
        # The token profile measured on a real slide with kimi-k3.
        usage['prompt_tokens'] = usage.get('prompt_tokens', 0) + 1987
        usage['completion_tokens'] = usage.get('completion_tokens', 0) + 1304
        return {'slide': number, 'verdict': 'ok', 'summary': '', 'issues': []}

    monkeypatch.setattr(vision_qa, 'review_slide', fake)
    report = asyncio.run(vision_qa.review_deck(tmp_path / 'deck.pptx', model='kimi-k3',
                                               images=_render(tmp_path, 3), concurrency=1))

    assert report['usage'] == {'prompt_tokens': 1987 * 3, 'completion_tokens': 1304 * 3}
    per_slide = (1987 * 3.00 + 1304 * 15.00) / 1_000_000
    assert report['estimated_cost_usd'] == pytest.approx(round(per_slide * 3, 5))
    assert 'est. $' in report['summary'], 'the panel shows the summary, so the cost rides on it'


def test_a_model_without_a_published_price_reports_no_cost(tmp_path, monkeypatch,
                                                           no_key_problem):
    """No invented numbers: an unpriced model reports None, not a guess."""
    async def fake(model, image, number, total, semaphore, usage=None):
        usage['completion_tokens'] = usage.get('completion_tokens', 0) + 10
        return {'slide': number, 'verdict': 'ok', 'summary': '', 'issues': []}

    monkeypatch.setattr(vision_qa, 'review_slide', fake)
    report = asyncio.run(vision_qa.review_deck(tmp_path / 'deck.pptx', model='omen-alpha',
                                               images=_render(tmp_path, 2), concurrency=1))

    assert report['estimated_cost_usd'] is None
    assert 'est. $' not in report['summary']

