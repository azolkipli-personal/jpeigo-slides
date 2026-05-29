"""
FastAPI endpoints for PPTX translation.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import uuid
import os
import asyncio
from pathlib import Path
import shutil

from app.config import Settings, get_settings
from app.core.extractor import extract_pptx
from app.core.injector import inject_translations
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


# Create FastAPI app
app = FastAPI(
    title="PPTX Translator API",
    description="API for translating PowerPoint presentations while preserving formatting",
    version="1.0.0",
)

# Load settings
settings = get_settings()

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

# Translation memory
tm = get_translation_memory()

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


def sanitize_translated_runs(translated_runs: list[TranslatedRun]) -> list[TranslatedRun]:
    """Sanitize all translated runs to remove contamination."""
    for tr in translated_runs:
        cleaned = sanitize_translation(tr.translated_text, tr.original_text)
        if cleaned != tr.translated_text:
            print(f"  [SANITIZE] Run {tr.run_id}: stripped contamination: {tr.translated_text[:50]} → {cleaned[:50]}")
        tr.translated_text = cleaned
    return translated_runs
jobs: dict[str, TranslationJob] = {}


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
        )
        
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
async def translate_pptx(request: TranslationRequest, background_tasks: BackgroundTasks):
    """
    Translate text runs in a PPTX file.
    
    The translation is processed in the background for large files.
    """
    # Use provided job_id (from upload) or create a new one
    job_id = request.job_id or str(uuid.uuid4())
    
    # Initialize or update job
    if job_id in jobs:
        jobs[job_id].status = "processing"
        jobs[job_id].total_runs = len(request.runs)
        jobs[job_id].progress = 0.0
    else:
        jobs[job_id] = TranslationJob(
            job_id=job_id,
            filename="",
            status="processing",
            total_runs=len(request.runs),
            translated_runs=[],
            progress=0.0,
        )
    
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
    
    # Prepare texts for batch translation
    texts_to_translate = [(run.run_id, run.text) for run in request.runs]
    
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
        batch_results = await translation_service.batch_translate(
            texts=uncached_texts,
            source_lang=request.source_language,
            target_lang=request.target_language,
            model=request.model,
            context=context,
            concurrency=5,
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
            ))
    
    # Sort by run_id to maintain original order
    translated_runs.sort(key=lambda tr: tr.run_id)
    
    # Sanitize all translations to strip contamination
    translated_runs = sanitize_translated_runs(translated_runs)
    
    # Update job progress
    jobs[job_id].translated_runs = translated_runs
    jobs[job_id].progress = 100.0
    
    # Mark job as completed
    jobs[job_id].status = "completed"
    jobs[job_id].progress = 100.0
    
    return TranslateResponse(
        job_id=job_id,
        status="completed",
        progress=100.0,
        total_runs=len(request.runs),
        translated_runs=[tr.model_dump() for tr in translated_runs],
    )


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job status."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return jobs[job_id]


@app.post("/api/export")
async def export_pptx(request: ExportRequest):
    """
    Export translated PPTX file.
    
    Takes the job ID and returns the translated file.
    """
    job_id = request.job_id
    
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    
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
            # Log failed runs
            for run in failed:
                print(f"Failed to inject: {run.run_id}")
        
        # Return file
        return FileResponse(
            path=str(output_path),
            filename=output_filename,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting file: {str(e)}")


@app.get("/api/cache")
async def get_translation_cache():
    """Get cached translations."""
    tm = get_translation_memory()
    return tm.export()


@app.delete("/api/cache")
async def clear_translation_cache():
    """Clear translation memory."""
    tm = get_translation_memory()
    tm.clear()
    return {"status": "cleared"}


@app.get("/api/health")
async def health_check():
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
    uvicorn.run(app, host="0.0.0.0", port=8002)