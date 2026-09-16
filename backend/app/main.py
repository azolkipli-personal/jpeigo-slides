"""
FastAPI endpoints for PPTX translation.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.qa import jobs as qa_jobs
from app.qa import render as qa_render
from app.qa import translation_review, vision_qa
from typing import Optional
import uuid
import os
import re
import asyncio
import time
from datetime import datetime, timedelta
from pathlib import Path
import shutil
from contextlib import asynccontextmanager

from app.config import Settings, get_settings
from app.qa import client as qa_client
from app.model_catalog import DEFAULT_VISION_MODEL, catalog_payload, is_vision_model
from app.core.extractor import extract_pptx
from app.core.injector import inject_translations
from app.core.fonts import check_jp_font
from app.translators.service import TranslationService
from app.utils.cache import get_translation_memory
from app.models import (
    PPTXDocument,
    TranslationRequest,
    TranslationJob,
    TranslatedRun,
    ExportRequest,
)

# Google Slides integration
from app.google_slides.oauth import (
    get_auth_url, handle_callback, is_authenticated, clear_credentials
)
from app.google_slides.service import (
    list_presentations, extract_slide_text,
    flatten_runs_for_translation, build_translated_runs_from_result,
    create_translated_presentation,
)


# ── Increase default multipart part size from 1MB → 100MB ──
# Starlette's MultiPartParser (used by Request.form()) rejects parts >1MB by default.
# The app-level max_file_size (100MB in config.py) never gets reached because
# this multipart parser limit fires first with "There was an error parsing the body".
from starlette.requests import Request as StarletteRequest

_orig_get_form = StarletteRequest._get_form

async def _patched_get_form(self, *, max_files=1000, max_fields=1000, max_part_size=100 * 1024 * 1024):
    return await _orig_get_form(self, max_files=max_files, max_fields=max_fields, max_part_size=max_part_size)

StarletteRequest._get_form = _patched_get_form

# Create FastAPI app
app = FastAPI(
    title="PPTX Translator API",
    description="API for translating PowerPoint presentations while preserving formatting",
    version="1.0.0",
)

# Load settings
settings = get_settings()

# Font availability: the injector writes this family into every translated run and
# the frontend renders previews through LibreOffice, which substitutes a missing
# family silently. Report it at startup and in /api/health so a wrong typeface is
# a visible fact rather than a preview nobody can explain.
FONT_STATUS = check_jp_font()
if FONT_STATUS.get('substituted'):
    print(f"[FONTS] {FONT_STATUS['requested']} is not installed — previews will render as {FONT_STATUS['resolved']}")

# Configure CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create directories
Path(settings.upload_dir).mkdir(exist_ok=True)
Path(settings.output_dir).mkdir(exist_ok=True)

# Translation service
translation_service = TranslationService(settings)

# Model IDs: a provider that does not know the configured model fails every
# request and, because the failover chain then supplies another provider, the job
# finishes with original text and success=False. That reads as a bad translation
# rather than a bad configuration. Probe each configured model once when
# VALIDATE_MODELS_ON_STARTUP=1; /api/health reports runtime failures either way.
VALIDATE_MODELS_ON_STARTUP = os.environ.get('VALIDATE_MODELS_ON_STARTUP', '') not in ('', '0', 'false', 'False')


async def probe_configured_models() -> None:
    """Opt-in probe of every configured translation model.

    Called from `lifespan`, not `@app.on_event("startup")`: this app installs its
    own lifespan_context, which replaces the default lifespan that runs on_event
    hooks — a startup hook here would silently never fire.
    """
    if not VALIDATE_MODELS_ON_STARTUP:
        return
    print("[MODELS] Probing every configured model (VALIDATE_MODELS_ON_STARTUP=1)…")
    problems = await translation_service.validate_models()
    for model, reason in problems.items():
        print(f"[MODELS]   {model}: {reason}")
    if problems:
        print(f"[MODELS] {len(problems)} configured model(s) failed — jobs will fall back or keep original text")
    else:
        print("[MODELS] All configured models responded")

# Translation memory
tm = get_translation_memory()

# Job persistence (SQLite — survives restarts)
from app.job_store import get_job_store

job_store = get_job_store()


CLEANUP_INTERVAL = 3600  # Run cleanup every hour


def cleanup_old_files():
    """Delete uploaded and output files older than 24 hours."""
    cutoff = datetime.now() - timedelta(hours=24)
    for dir_path in [Path(settings.upload_dir), Path(settings.output_dir)]:
        if not dir_path.exists():
            continue
        for item in dir_path.iterdir():
            if item.is_file():
                mtime = datetime.fromtimestamp(item.stat().st_mtime)
                if mtime < cutoff:
                    item.unlink()
                    print(f"  [CLEANUP] Deleted old file: {item}")
    # Prune stale job rows (files are gone; jobs are useless without them)
    try:
        pruned = job_store.delete_old(hours=24)
        if pruned:
            print(f"  [CLEANUP] Pruned {pruned} old job row(s)")
    except Exception as e:
        print(f"  [CLEANUP] Job store prune error: {e}")


async def run_cleanup_periodically():
    """Run cleanup_old_files every CLEANUP_INTERVAL seconds."""
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        try:
            cleanup_old_files()
        except Exception as e:
            print(f"  [CLEANUP] Error during cleanup: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start and stop background cleanup task with the app."""
    # Hydrate in-memory jobs from SQLite (restart recovery)
    try:
        restored = job_store.load_all()
        if restored:
            jobs.update(restored)
            print(f"  [JOBSTORE] Restored {len(restored)} job(s) from SQLite")
    except Exception as e:
        print(f"  [JOBSTORE] Startup hydration failed: {e}")

    # Probe configured model IDs in the background: it spends one request per
    # configured model, which must not hold the port closed.
    model_probe_task = asyncio.create_task(probe_configured_models())

    cleanup_task = asyncio.create_task(run_cleanup_periodically())
    yield
    for task in (cleanup_task, model_probe_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app.router.lifespan_context = lifespan


async def verify_api_key(request: Request, x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    """Dependency to verify API key on protected endpoints.

    Requests from localhost are always trusted (backend is bound to 127.0.0.1).
    External requests require X-API-Key header if API_KEY is configured.
    """
    # Requests from localhost are always trusted (backend is bound to 127.0.0.1)
    if request.client and request.client.host in ("127.0.0.1", "::1", "localhost"):
        return x_api_key
    if settings.api_key:
        if not x_api_key:
            raise HTTPException(status_code=401, detail="API key required. Set X-API-Key header.")
        if x_api_key != settings.api_key:
            raise HTTPException(status_code=403, detail="Invalid API key.")
    # If no api_key is configured, allow unrestricted access.
    return x_api_key


def sanitize_translation(text: str, original: str) -> str:
    """
    Sanitize translation output by removing contamination like:
    - Arrow notation (→) from glossary patterns
    - Duplicate original text
    - Metadata labels like "Translation:" or "Text:"
    """
    result = text.strip()
    
    # 1. Remove leading labels like "Translation:" or "Translated text:"
    for label in ['Translation:', 'Translated text:', 'Output:', 'Result:', 'Translated:']:
        if label in result:
            # Take everything after the LAST occurrence of the label
            result = result.split(label)[-1].strip()
    
    # 2. If the result contains "original → translation" or "original = translation" pattern
    # where original matches the source text, extract just the translation side
    for sep in [' → ', ' = ']:
        if sep in result and original in result:
            # Split by lines and find the line with the match
            lines = result.split('\n')
            cleaned_lines = []
            for line in lines:
                line = line.strip()
                if sep in line and original in line:
                    # Extract the part after the separator
                    parts = line.split(sep)
                    line = parts[-1].strip()
                cleaned_lines.append(line)
            result = '\n'.join(cleaned_lines)
    
    # 3. If result starts with the original text verbatim, try to extract just the translation
    if result.startswith(original) and len(result) > len(original) + 2:
        remainder = result[len(original):].strip()
        # Check if remainder is separated by →, =, : or just whitespace
        if remainder.startswith('→') or remainder.startswith('='):
            remainder = remainder[1:].strip()
        if remainder:  # Only use if there's something after the original
            result = remainder
    
    # 4. Remove any "KEYWORD → KEYWORD" patterns (duplicate word on both sides)
    import re
    result = re.sub(r'\b(\w+)\s*[→=]\s*\1\b', r'\1', result)
    
    # 5. If result contains the phrase "Context:" or "CRITICAL:" or "glossary", strip it all out
    for poison in ['Context:', 'CRITICAL:', 'glossary', 'Translate the following', 'Text to translate']:
        if poison in result:
            # Take everything before the poison word (it's usually at the start)
            result = result.split(poison)[0].strip()
    
    # 6. Final cleanup
    result = result.strip()
    result = result.strip('"\'')
    result = result.strip()
    
    return result if result else original


def sanitize_translated_runs(translated_runs: list[TranslatedRun], glossary: Optional[list[str]] = None) -> list[TranslatedRun]:
    """Sanitize all translated runs to remove contamination + enforce glossary terms."""
    for tr in translated_runs:
        cleaned = sanitize_translation(tr.translated_text, tr.original_text)
        if cleaned != tr.translated_text:
            print(f"  [SANITIZE] Run {tr.run_id}: stripped contamination: {tr.translated_text[:50]} → {cleaned[:50]}")
        # Glossary enforcement (post-pass): restore any term the model translated anyway.
        # Only applies to terms actually present in this run's source text.
        if glossary and tr.original_text:
            for term in glossary:
                if term.lower() in tr.original_text.lower() and term not in cleaned:
                    # Case-normalize occurrences already present (e.g. "apple" -> "Apple").
                    cleaned = re.sub(re.escape(term), term, cleaned, flags=re.IGNORECASE)
                    if term not in cleaned:
                        # Model translated the term away entirely; restoration
                        # without re-translating isn't possible — log it so the
                        # gap is visible instead of silently claiming success.
                        print(f"  [GLOSSARY] Run {tr.run_id}: term '{term}' not restorable (translated away)")
                    else:
                        print(f"  [GLOSSARY] Run {tr.run_id}: enforced term '{term}'")
        tr.translated_text = cleaned
    return translated_runs
jobs: dict[str, TranslationJob] = {}
# job_id -> monotonic timestamp when translation started (for notify timing)
_job_started_at: dict[str, float] = {}
# In-flight translation tasks. Held in a set because a bare create_task() result
# can be garbage-collected mid-run, and per job so a duplicate POST can be
# answered from the run that is already going instead of starting a second one.
_bg_tasks: set[asyncio.Task] = set()
_active_translations: dict[str, asyncio.Task] = {}


def load_job(job_id: str):
    """Look up a job in memory, falling back to the SQLite store.

    Memory is not authoritative: a restart, an out-of-band clear, or a prune can
    leave the record on disk only. Translate reads the job opportunistically and
    the status endpoint already rehydrates this way, but export required the
    in-memory entry on its own — so a session could translate fine and then
    answer "Job not found" the moment the user pressed Download.
    """
    job = jobs.get(job_id)
    if job is None:
        job = job_store.load(job_id)
        if job is not None:
            jobs[job_id] = job  # rehydrate memory
    return job


class UploadResponse(BaseModel):
    """Response after file upload."""
    job_id: str
    filename: str
    total_slides: int
    total_text_boxes: int
    total_runs: int
    slides: list[dict]


class TranslateResponse(BaseModel):
    """Response after translation."""
    job_id: str
    status: str
    progress: float
    total_runs: int
    translated_runs: list[dict]


class ExportResponse(BaseModel):
    """Response for export."""
    download_url: str


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "PPTX Translator API"}


@app.post("/api/upload", response_model=UploadResponse)
async def upload_pptx(file: UploadFile = File(...)):
    """
    Upload a PPTX file and extract text runs.
    
    Returns structured data about all text in the presentation.
    """
    # Validate file type
    if not file.filename or not file.filename.endswith('.pptx'):
        raise HTTPException(status_code=400, detail="Only .pptx files are supported")
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Save uploaded file
    file_path = Path(settings.upload_dir) / f"{job_id}_{file.filename}"
    
    try:
        # Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Check file size
        file_size = os.path.getsize(file_path)
        if file_size > settings.max_file_size:
            os.remove(file_path)
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {settings.max_file_size / (1024*1024):.0f}MB"
            )
        
        # Extract text runs
        document = extract_pptx(str(file_path), generate_preview=True)
        
        # Store job info
        jobs[job_id] = TranslationJob(
            job_id=job_id,
            filename=file.filename,
            status="uploaded",
            total_runs=document.total_runs,
            translated_runs=[],
            progress=0.0,
            slides=document.slides, # Store extracted slides for rehydration
        )
        job_store.save(jobs[job_id])
        
        # Prepare response
        slides_data = [
            {
                "slide_index": s.slide_index,
                "slide_id": s.slide_id,
                "text_boxes": [
                    {
                        "box_id": tb.box_id,
                        "shape_type": tb.shape_type,
                        "runs": [
                            {
                                "run_id": r.run_id,
                                "text": r.text,
                                "style": r.style.model_dump(),
                                "slide_index": r.slide_index,
                                "shape_index": r.shape_index,
                                "paragraph_index": r.paragraph_index,
                                "run_index": r.run_index,
                                "xml_path": r.xml_path,
                                "merged_span": r.merged_span,
                            }
                            for r in tb.runs
                        ],
                        "constraints": tb.constraints.model_dump(),
                    }
                    for tb in s.text_boxes
                ],
            }
            for s in document.slides
        ]
        
        return UploadResponse(
            job_id=job_id,
            filename=file.filename,
            total_slides=len(document.slides),
            total_text_boxes=sum(len(s.text_boxes) for s in document.slides),
            total_runs=document.total_runs,
            slides=slides_data,
        )
        
    except Exception as e:
        # Clean up on error
        if file_path.exists():
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@app.post("/api/translate", response_model=TranslateResponse)
async def translate_pptx(request: TranslationRequest):
    """Start translating a job's text runs and return immediately.

    The translation itself runs as a background task; clients follow it through
    GET /api/jobs/{job_id}. Nothing here waits for the work.

    Why it is not synchronous: a 1000+ run deck with a cold cache translates for
    10+ minutes, and holding an HTTP request open that long is fragile. The
    Next.js proxy in front of this service cut the upstream fetch at undici's
    300 s (5 min) headers timeout, so the browser reported "translation failed"
    at the 5-minute mark while this backend went on to finish the job correctly.
    """
    # Use provided job_id (from upload) or create a new one
    job_id = request.job_id or str(uuid.uuid4())

    running = _active_translations.get(job_id)
    if running is not None and not running.done():
        # Duplicate POST (double click, retry): report the run already in flight
        # instead of translating the same job twice.
        current = load_job(job_id)
        return TranslateResponse(
            job_id=job_id,
            status=current.status if current else "processing",
            progress=current.progress if current else 0.0,
            total_runs=len(request.runs),
            translated_runs=[],
        )

    # Initialize or update job
    if job_id in jobs:
        jobs[job_id].status = "processing"
        jobs[job_id].error = None
        jobs[job_id].total_runs = len(request.runs)
        jobs[job_id].progress = 0.0
    else:
        # On new job creation in translate endpoint, filename and slides are unknown.
        # Should be rare, as translate usually follows upload.
        jobs[job_id] = TranslationJob(
            job_id=job_id,
            filename="",
            status="processing",
            total_runs=len(request.runs),
            translated_runs=[],
            progress=0.0,
            slides=[],  # No slides available during translate-only creation
        )
    job_store.save(jobs[job_id])

    task = asyncio.create_task(_run_translation_job(job_id, request))
    _bg_tasks.add(task)
    _active_translations[job_id] = task
    task.add_done_callback(lambda t: _on_translation_done(job_id, t))

    return TranslateResponse(
        job_id=job_id,
        status="processing",
        progress=0.0,
        total_runs=len(request.runs),
        translated_runs=[],
    )


async def _run_translation_job(job_id: str, request: TranslationRequest) -> None:
    """Translate one job's runs, reporting progress on the job as it goes.

    Detached from the request that started it: results are read back from the job
    record, and a crash is recorded by the task's done-callback
    (_on_translation_done) so a job can never hang at "processing" forever.
    """
    # Remember wall-clock start for completion notifications
    _job_started_at[job_id] = time.monotonic()

    # Process translations in batch with concurrency
    translated_runs = []
    tm = get_translation_memory()
    
    # Build context from translation memory + user custom context
    glossary_context = tm.build_context_prompt(request.source_language, request.target_language)
    if request.context:
        if glossary_context:
            context = f"{request.context.strip()}\n\nAlso use this terminology:\n{glossary_context}"
        else:
            context = request.context.strip()
    else:
        context = glossary_context

    # User glossary: instruct the model to preserve these terms verbatim
    if request.glossary:
        glossary_list = "\n".join(f"- {term}" for term in request.glossary)
        glossary_instruction = (
            "CRITICAL: The following terms are brand names / product names. "
            "Do NOT translate them. Copy them EXACTLY as written wherever they appear:\n"
            f"{glossary_list}"
        )
        context = f"{context}\n\n{glossary_instruction}" if context else glossary_instruction

    # Prepare texts for batch translation
    texts_to_translate = [(run.run_id, run.text) for run in request.runs]

    # Coalesced run groups carry the run-index range they cover, so the injector
    # knows to write the translation into the first run and blank the rest. The
    # spans come from the extraction stored on the job rather than from the
    # client payload: a client that re-posts runs without the field would lose
    # the span, and the merged translation would then be written next to the
    # source fragments instead of replacing them.
    stored_job = load_job(job_id)
    span_by_run = {
        run.run_id: run.merged_span
        for slide in (stored_job.slides if stored_job else [])
        for box in slide.text_boxes
        for run in box.runs
    }
    for run in request.runs:
        span_by_run.setdefault(run.run_id, run.merged_span)
    
    # Check cache first and collect uncached texts
    uncached = []
    for run_id, text in texts_to_translate:
        cached = tm.get(text, request.source_language, request.target_language)
        if cached:
            cleaned = sanitize_translation(cached, text)
            if cleaned != cached:
                print(f"  [SANITIZE] Cache hit for run {run_id}: stripped contamination")
            translated_runs.append(TranslatedRun(
                run_id=run_id,
                original_text=text,
                translated_text=cleaned,
                source_language=request.source_language,
                target_language=request.target_language,
                model_used="cache",
            ))
        else:
            uncached.append((run_id, text))
    
    # Translate uncached texts in batch with concurrency
    if uncached:
        uncached_texts = [t[1] for t in uncached]
        cached_count = len(translated_runs)

        def report_batch_progress(done: int):
            pct = (cached_count + done) / len(request.runs) * 100
            jobs[job_id].progress = round(min(pct, 99.0), 1)
            job_store.save(jobs[job_id])  # throttled inside the store

        batch_results = await translation_service.batch_translate(
            texts=uncached_texts,
            source_lang=request.source_language,
            target_lang=request.target_language,
            model=request.model,
            context=context,
            concurrency=5,
            progress_callback=report_batch_progress,
        )
        
        for (run_id, text), (translated_text, model_used, success) in zip(uncached, batch_results):
            # Cache successful translations
            if success:
                tm.set(
                    text=text,
                    translated_text=translated_text,
                    source_lang=request.source_language,
                    target_lang=request.target_language,
                    model_used=model_used,
                )
            
            translated_runs.append(TranslatedRun(
                run_id=run_id,
                original_text=text,
                translated_text=translated_text,
                source_language=request.source_language,
                target_language=request.target_language,
                model_used=model_used,
                success=success,
            ))
    
    # Sort by run_id to maintain original order
    translated_runs.sort(key=lambda tr: tr.run_id)
    
    # Sanitize all translations to strip contamination + enforce glossary
    translated_runs = sanitize_translated_runs(translated_runs, request.glossary)
    
    # Attach the coalesced run span to each unit. Done after sanitisation so a
    # rebuild inside it cannot drop the field, and in one place so both the
    # cache-hit and the freshly-translated branches stay untouched.
    for tr in translated_runs:
        tr.merged_span = span_by_run.get(tr.run_id)

    # Update job progress
    jobs[job_id].translated_runs = translated_runs
    jobs[job_id].progress = 100.0
    
    # Mark job as completed
    jobs[job_id].status = "completed"
    jobs[job_id].progress = 100.0
    job_store.save(jobs[job_id])

    # Telegram ping for long jobs (fire-and-forget, >60s only)
    from app.notify import maybe_notify_job_done
    started = _job_started_at.pop(job_id, None)
    if started is not None:
        # Count only runs where every provider failed (success=False →
        # original text passed through). Identity outputs from successful
        # calls (numbers, dates, brand names) are NOT failures.
        failed_count = sum(
            1 for tr in translated_runs
            if not tr.success and tr.original_text == tr.translated_text
        )
        maybe_notify_job_done(
            jobs[job_id].filename or "presentation.pptx",
            len(translated_runs),
            started,
            failed_count,
        )

    # No response object to build here: the job record (status="completed" plus
    # translated_runs, saved just above) is what the client polls for.


def _on_translation_done(job_id: str, task: asyncio.Task) -> None:
    """Record a crashed background translation on the job instead of leaving it hanging.

    Without this the UI would poll a job stuck at "processing" forever and the
    exception would exist only as a line in the service journal.
    """
    _bg_tasks.discard(task)
    _active_translations.pop(job_id, None)
    if task.cancelled():
        detail = "cancelled"
    else:
        error = task.exception()
        if error is None:
            return
        detail = f"{type(error).__name__}: {error}"
    print(f"  [JOB {job_id}] translation failed: {detail}")
    job = jobs.get(job_id) or load_job(job_id)
    if job is None:
        return
    job.status = "failed"
    job.error = detail
    jobs[job_id] = job
    job_store.save(job)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job status. Falls back to SQLite if not in memory (post-restart)."""
    job = load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    # Return full job (translated runs included) so a refreshed browser
    # can recover its session without re-translating.
    return job


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """Forget a job (memory + SQLite). Files on disk are left for the hourly cleanup."""
    jobs.pop(job_id, None)
    job_store.delete(job_id)
    return {"ok": True}


@app.post("/api/export")
async def export_pptx(request: ExportRequest):
    """
    Export translated PPTX file.
    
    Takes the job ID and returns the translated file.
    """
    job_id = request.job_id
    
    job = load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job not completed")
    
    # Find uploaded file
    upload_dir = Path(settings.upload_dir)
    input_files = list(upload_dir.glob(f"{job_id}_*.pptx"))
    
    if not input_files:
        raise HTTPException(status_code=404, detail="Original file not found")
    
    input_path = input_files[0]
    output_filename = request.filename or f"translated_{job.filename}"
    output_path = Path(settings.output_dir) / output_filename
    
    try:
        # Inject translations
        success, failed = inject_translations(
            str(input_path),
            str(output_path),
            job.translated_runs,
            None,  # Original document not needed for injection
        )
        
        if not success:
            # Injection failures used to be printed and the file served anyway, so a
            # partially-translated deck looked like a clean export. Surface the count
            # to the UI via headers, since the response body is the PPTX itself.
            for run in failed:
                print(f"Failed to inject: {run.run_id}")
        
        # Return file
        return FileResponse(
            path=str(output_path),
            filename=output_filename,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={
                "X-Injection-Failed": str(len(failed)),
                "X-Injection-Total": str(len(job.translated_runs)),
                "Access-Control-Expose-Headers": "X-Injection-Failed, X-Injection-Total",
            },
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting file: {str(e)}")


@app.get("/api/cache")
async def get_translation_cache(_auth: str = Depends(verify_api_key)):
    """Get cached translations."""
    tm = get_translation_memory()
    return tm.export()


@app.delete("/api/cache")
async def clear_translation_cache(_auth: str = Depends(verify_api_key)):
    """Clear translation memory."""
    tm = get_translation_memory()
    tm.clear()
    return {"status": "cleared"}


# ── Verification passes (Layer 2 and Layer 3) ─────────────────────────────────


@app.get("/api/models")
async def list_models(_auth: str = Depends(verify_api_key)):
    """The models the UI may offer, from one place.

    The picker used to carry its own hardcoded list, and it had already drifted from
    the registry behind it: it still offered "Kimi K2.5" and "DeepSeek V4" while the
    backend was calling kimi-k3 and deepseek-v4-flash. A label that disagrees with
    the model actually used is worse than a short list, so the page renders from
    this endpoint and tests/test_model_catalog.py fails if the two drift again.
    """
    return catalog_payload()


class QARequest(BaseModel):
    """An opt-in review pass over a job that has already been translated."""
    job_id: str
    which: str = 'translated'   # translated | original
    model: Optional[str] = None
    max_slides: Optional[int] = None
    limit: Optional[int] = None
    # A full-deck check on a slow-but-accurate model outlives one HTTP request, so the
    # caller may drive it in absolute chunks and run every chunk. Coverage is not
    # negotiable; only the request size is.
    first_slide: Optional[int] = None
    last_slide: Optional[int] = None


def _deck_path_for(job_id: str, which: str = 'translated') -> Path:
    """Resolve the deck a pass should look at.

    'translated' is what export_pptx writes and 'original' is the file the job was
    uploaded from; having both on disk is what makes a before/after pair possible.
    """
    job = jobs.get(job_id) or load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")

    upload_dir = Path(settings.upload_dir)
    output_dir = Path(settings.output_dir)
    stem = Path(job.filename).stem

    if which == 'original':
        candidates = sorted(upload_dir.glob(f"{job_id}_*")) or sorted(upload_dir.glob(f"*{stem}*"))
    else:
        candidates = [output_dir / f"translated_{job.filename}", output_dir / job.filename]
        candidates = [path for path in candidates if path.exists()] or sorted(output_dir.glob(f"*{stem}*"))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise HTTPException(status_code=404, detail=f"No {which} deck on disk for job {job_id}")


def _save_qa_report(job_id: str, pass_name: str, report: dict) -> None:
    """Attach a report to its job. Report-only: QA never fails a job."""
    job = jobs.get(job_id)
    if job is None:
        return
    job.qa_reports[pass_name] = report
    try:
        job_store.save(job)
    except Exception as exc:
        print(f"[QA] could not persist the {pass_name} report for {job_id}: {exc}")


@app.post("/api/qa/vision")
async def qa_vision(request: QARequest, _auth: str = Depends(verify_api_key)):
    """Layer 2: render the deck and report layout damage per slide.

    Deliberately not part of export: it costs one vision call per slide, and its
    findings are advisory. Report-only — the deck is never touched.
    """
    model = _vision_model_for(request)
    deck = _deck_path_for(request.job_id, request.which)
    try:
        report = await vision_qa.review_deck(deck, model=model,
                                             max_slides=request.max_slides,
                                             first_slide=request.first_slide,
                                             last_slide=request.last_slide)
    except qa_render.RenderError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    report['deck_kind'] = request.which
    report['deck_file'] = deck.name
    _save_qa_report(request.job_id, 'vision', report)
    return report


def _vision_model_for(request: QARequest) -> str:
    """The model this check will use, or the reason it cannot run at all."""
    model = request.model or DEFAULT_VISION_MODEL
    if not is_vision_model(model):
        # The translation models cannot look at slides at all: the two this app used
        # to ship, deepseek-v4-flash and minimax-m2.5, answered HTTP 400 for image
        # content. A blind model asked about layout invents a verdict, which is worse
        # than an error, so reject the model instead of guessing at a reading.
        raise HTTPException(
            status_code=400,
            detail=f"{model} cannot read slide images; pick one from GET /api/models",
        )
    problem = qa_client.key_problem(model)
    if problem:
        raise HTTPException(status_code=503, detail=problem)
    return model


@app.post("/api/qa/vision/start")
async def qa_vision_start(request: QARequest, _auth: str = Depends(verify_api_key)):
    """Start a whole-deck slide check and return straight away; the caller polls.

    A 19-slide deck is minutes of vision calls (~85 s each, three at a time), which no
    proxy will hold open. Detaching the check also buys real progress — the user watches
    slides land — instead of one spinner that a gateway timeout can throw away.
    """
    model = _vision_model_for(request)
    deck = _deck_path_for(request.job_id, request.which)
    if not deck.exists():
        raise HTTPException(status_code=404,
                            detail=f'no {request.which} deck for {request.job_id}')
    check = qa_jobs.start(
        request.job_id, deck, model, which=request.which,
        on_finish=lambda report: _save_qa_report(request.job_id, 'vision', report),
    )
    return {'state': check.state, 'job_id': request.job_id, 'which': request.which,
            'model': model, 'checked': 0, 'total': check.total}


@app.get("/api/qa/vision/status")
async def qa_vision_status(job_id: str, which: str = 'translated',
                           _auth: str = Depends(verify_api_key)):
    """Progress of a background slide check: running, done or failed.

    Returns the report as it stands, so the UI shows findings from slides already
    reviewed rather than nothing until the last slide finishes.
    """
    check = qa_jobs.get(job_id, which)
    if check is None:
        raise HTTPException(status_code=404,
                            detail=f'no slide check for {job_id} ({which})')
    return {'state': check.state, 'job_id': job_id, 'which': which, 'model': check.model,
            'checked': check.checked, 'total': check.total, 'error': check.error,
            'report': check.report}


@app.post("/api/qa/review")
async def qa_review(request: QARequest, _auth: str = Depends(verify_api_key)):
    """Layer 3: terminology, register and leftover review of the job's units."""
    job = jobs.get(request.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {request.job_id}")
    units = [{'original_text': run.original_text, 'translated_text': run.translated_text}
             for run in job.translated_runs]
    if request.limit:
        units = units[:request.limit]
    if not units:
        raise HTTPException(status_code=400, detail="This job has no translation units to review")
    report = await translation_review.review_units(units, model=request.model)
    _save_qa_report(request.job_id, 'translation_review', report)
    return report


@app.get("/api/qa/reports/{job_id}")
async def qa_reports(job_id: str, _auth: str = Depends(verify_api_key)):
    """Reports already produced for a job, so the UI never has to re-run a pass."""
    job = jobs.get(job_id) or load_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job {job_id}")
    return job.qa_reports


@app.get("/api/source")
async def get_source_deck(job_id: str, _auth: str = Depends(verify_api_key)):
    """The deck this job was uploaded from.

    The preview path needs it to render the before side of a before/after pair; the
    translated side already comes from /api/export.
    """
    path = _deck_path_for(job_id, 'original')
    return FileResponse(
        path=str(path),
        filename=Path(path).name,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@app.get("/api/health")
async def health_check(_auth: str = Depends(verify_api_key)):
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "settings": {
            "gemini_configured": bool(settings.gemini_api_key),
            "google_cloud_configured": bool(settings.google_cloud_api_key),
            "opencode_configured": bool(settings.opencode_api_key),
            "glm_configured": bool(settings.glm_api_key),
            "kimi_configured": bool(settings.kimi_api_key),
            "minimax_configured": bool(settings.minimax_api_key),
            "qwen_configured": bool(settings.qwen_api_key),
            "ollama_configured": bool(settings.ollama_url),
            "default_model": settings.default_model,
        },
        # Which font the injector writes and whether this machine can render it;
        # fontconfig substitutes silently, so this is the only place it surfaces.
        "jp_font": FONT_STATUS,
        # Last failure per model name. Failover hides provider errors, and a wrong
        # model ID looks exactly like a bad translation from the outside, so the
        # reasons are collected here instead of only going to stdout.
        "model_errors": translation_service.model_errors,
    }


# ──────────────────────────────────────────────────────────────────────
#  Google Slides Native Integration
# ──────────────────────────────────────────────────────────────────────


class SlidesAuthUrlResponse(BaseModel):
    url: str


class SlidesAuthCallbackRequest(BaseModel):
    code: str


class SlidesAuthStatusResponse(BaseModel):
    authenticated: bool


class SlidesPresentationListResponse(BaseModel):
    presentations: list[dict]


class SlidesExtractResponse(BaseModel):
    presentation_id: str
    title: str
    total_slides: int
    total_runs: int
    slides: list[dict]
    runs: list[dict]


class SlidesTranslateRequest(BaseModel):
    presentation_id: str
    source_language: str = "ja"
    target_language: str = "en"
    model: str = "gemini-flash-lite"
    context: Optional[str] = None
    new_title: Optional[str] = None


class SlidesTranslateResponse(BaseModel):
    new_presentation_id: str
    new_title: str
    new_url: str
    total_runs: int
    translated_runs: int
    model_used: str


@app.get("/api/slides/auth/url", response_model=SlidesAuthUrlResponse)
async def slides_get_auth_url():
    """
    Get the Google OAuth authorization URL.
    Redirect the user's browser to this URL.
    """
    try:
        url = get_auth_url()
        return SlidesAuthUrlResponse(url=url)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/slides/auth/callback", response_model=SlidesAuthStatusResponse)
async def slides_auth_callback(request: SlidesAuthCallbackRequest):
    """
    Handle the OAuth callback from Google.
    Exchange the authorization code for tokens.
    """
    try:
        result = handle_callback(request.code)
        return SlidesAuthStatusResponse(authenticated=result["authenticated"])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Auth failed: {str(e)}")


@app.get("/api/slides/auth/status", response_model=SlidesAuthStatusResponse)
async def slides_auth_status():
    """Check if we have valid Google credentials."""
    return SlidesAuthStatusResponse(authenticated=is_authenticated())


@app.post("/api/slides/auth/logout")
async def slides_auth_logout():
    """Clear stored credentials (logout)."""
    clear_credentials()
    return {"status": "logged_out"}


@app.get("/api/slides/presentations", response_model=SlidesPresentationListResponse)
async def slides_list_presentations():
    """List Google Slides presentations from Drive."""
    try:
        presentations = list_presentations()
        return SlidesPresentationListResponse(presentations=presentations)
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/slides/read/{presentation_id}", response_model=SlidesExtractResponse)
async def slides_read_presentation(presentation_id: str):
    """
    Extract all text runs from a Google Slides presentation.
    Returns the text content organized by slide, ready for translation.
    """
    try:
        pres_data = extract_slide_text(presentation_id)
        runs = flatten_runs_for_translation(pres_data)
        
        slides_json = []
        for slide in pres_data.slides:
            slide_runs = [
                r for r in runs
                if r.get("_slides_meta", {}).get("slide_object_id") == slide.slide_object_id
            ]
            slides_json.append({
                "slide_index": slide.slide_index,
                "slide_object_id": slide.slide_object_id,
                "text_boxes": [
                    {
                        "page_element_id": tb.page_element_id,
                        "shape_type": tb.shape_type,
                        "runs": [
                            r for r in slide_runs
                            if r.get("_slides_meta", {}).get("page_element_id") == tb.page_element_id
                        ],
                    }
                    for tb in slide.text_boxes
                ],
            })
        
        return SlidesExtractResponse(
            presentation_id=pres_data.presentation_id,
            title=pres_data.title,
            total_slides=len(pres_data.slides),
            total_runs=len(runs),
            slides=slides_json,
            runs=runs,
        )
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/slides/translate", response_model=SlidesTranslateResponse)
async def slides_translate(request: SlidesTranslateRequest):
    """
    Translate a Google Slides presentation end-to-end:
      1. Read the presentation text
      2. Translate all text runs
      3. Create a new translated presentation copy
      4. Return the new presentation URL
    """
    try:
        # 1. Extract text from the original presentation
        pres_data = extract_slide_text(request.presentation_id)
        original_runs = flatten_runs_for_translation(pres_data)
        
        if not original_runs:
            raise HTTPException(
                status_code=400,
                detail="No text runs found in this presentation"
            )
        
        # 2. Translate using existing translation service (batched)
        texts_to_translate = [run["text"] for run in original_runs]
        
        batch_results = await translation_service.batch_translate(
            texts=texts_to_translate,
            source_lang=request.source_language,
            target_lang=request.target_language,
            model=request.model,
            context=request.context,
        )
        # batch_results: [(translated_text, model_used, success), ...]
        
        # 3. Build translated runs matching original structure
        translated = []
        model_used = request.model
        for i, (orig_run, (translated_text, used_model, success)) in enumerate(
            zip(original_runs, batch_results)
        ):
            model_used = used_model
            translated.append({
                "run_id": orig_run["run_id"],
                "original_text": orig_run["text"],
                "translated_text": translated_text if success else orig_run["text"],
                "source_language": request.source_language,
                "target_language": request.target_language,
                "model_used": used_model,
            })
        
        if not translated:
            raise HTTPException(
                status_code=500,
                detail="Translation produced no results"
            )
        
        # 3. Build batch update data for Google Slides
        slide_batch = build_translated_runs_from_result(original_runs, translated)
        
        # 4. Create the translated presentation
        result = create_translated_presentation(
            source_presentation_id=request.presentation_id,
            translated_runs=slide_batch,
            new_title=request.new_title,
        )
        
        return SlidesTranslateResponse(
            new_presentation_id=result["id"],
            new_title=result["title"],
            new_url=result["url"],
            total_runs=len(original_runs),
            translated_runs=sum(
                1 for t in slide_batch if t["translated_text"] != t["original_text"]
            ),
            model_used=model_used,
        )
        
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Translation failed: {str(e)}")


# Run with: uvicorn app.main:app --reload --port 8000
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8002)