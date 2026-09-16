"""In-process registry for slide checks that outlive one HTTP request.

A full-deck check costs one vision call per slide. Measured on the FADC deck: ~13 s to
render plus ~85 s for a single `kimi-k3` call, and calls already run three at a time —
so a request is bounded below by one call, not by how many slides it asks for. Chunking
the deck therefore does not make a request survivable; it only loses whichever slides
the request never reached. The check runs as a background task instead, and the UI polls.

Deliberately not a queue: one running check per (job, which) is enough for a single-user
app, starting a new one supersedes the old, and a backend restart loses a running check.
That is acceptable for an advisory pass whose final report is also written to the job
store — the loss is a re-run, not a bad report.
"""
import asyncio
from dataclasses import dataclass, field

from app.qa import vision_qa


@dataclass
class Check:
    """One running or finished slide check."""

    key: str
    job_id: str
    which: str
    deck: str
    model: str
    state: str = 'running'              # running | done | failed
    error: str | None = None
    report: dict = field(default_factory=dict)
    task: asyncio.Task | None = None

    @property
    def checked(self) -> int:
        return int(self.report.get('slides_checked') or 0)

    @property
    def total(self) -> int | None:
        """Slides the deck holds — unknown until the deck is rendered/counted."""
        return self.report.get('deck_slides') or self.report.get('slides_rendered') or None


_checks: dict[str, Check] = {}


def key_for(job_id: str, which: str = 'translated') -> str:
    return f'{job_id}:{which}'


def get(job_id: str, which: str = 'translated') -> Check | None:
    return _checks.get(key_for(job_id, which))


def start(job_id: str, deck, model: str, which: str = 'translated',
          on_finish=None) -> Check:
    """Kick off a check, superseding any check already running for this deck."""
    key = key_for(job_id, which)
    previous = _checks.get(key)
    if previous and previous.task and not previous.task.done():
        previous.task.cancel()

    check = Check(key=key, job_id=job_id, which=which, deck=str(deck), model=model)
    check.task = asyncio.create_task(_run(check, on_finish))
    _checks[key] = check
    return check


async def _run(check: Check, on_finish=None) -> None:
    def progress(report: dict) -> None:
        # Hand the live dict to the poller; the report is only read, never mutated by
        # the caller, and it keeps one source of truth instead of a partial copy.
        check.report = report

    try:
        report = await vision_qa.review_deck_progressive(
            check.deck, model=check.model, on_progress=progress)
    except asyncio.CancelledError:
        raise
    except Exception as exc:                                  # noqa: BLE001 — surfaced to the UI
        check.state = 'failed'
        check.error = str(exc)[:300]
        return

    check.report = report
    check.state = 'done'
    if on_finish:
        try:
            on_finish(report)
        except Exception:                                     # noqa: BLE001 — a report that
            pass                                              # cannot be stored is still shown


def clear() -> None:
    """Test helper: forget every check."""
    _checks.clear()
