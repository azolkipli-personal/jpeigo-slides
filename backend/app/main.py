"""
FastAPI endpoints for PPTX translation.
"""
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import uuid
import os
import asyncio
import subprocess
import json
from pathlib import Path
import shutil
import tempfile

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


# Create FastAPI app
app = FastAPI(
    title="PPTX Translator API",
    description="API for translating PowerPoint presentations while preserving formatting",
    version="1.0.0",
)

# Load settings
settings = get_settings()

# Configure CORS
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
    
    # 1. Remove leading labels
    for label in ['Translation:', 'Translated text:', 'Output:', 'Result:', 'Translated:']:
        if label in result:
            result = result.split(label)[-1].strip()
    
    # 2. Handle "original → translation" patterns
    for sep in [' → ', ' = ']:
        if sep in result and original in result:
            lines = result.split('\n')
            cleaned_lines = []
            for line in lines:
                line = line.strip()
                if sep in line and original in line:
                    parts = line.split(sep)
                    line = parts[-1].strip()
                cleaned_lines.append(line)
            result = '\n'.join(cleaned_lines)
    
    # 3. Strip leading original text
    if result.startswith(original) and len(result) > len(original) + 2:
        remainder = result[len(original):].strip()
        if remainder.startswith('→') or remainder.startswith('='):
            remainder = remainder[1:].strip()
        if remainder:
            result = remainder
    
    # 4. Remove duplicate-word patterns
    import re
    result = re.sub(r'\b(\w+)\s*[→=]\s*\1\b', r'\1', result)
    
    # 5. Strip contamination phrases
    for poison in ['Context:', 'CRITICAL:', 'glossary', 'Translate the following', 'Text to translate']:
        if poison in result:
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
PREVIEW_CACHE_DIR = Path("/tmp/pptx-preview-cache")
PREVIEW_CACHE_DIR.mkdir(exist_ok=True)


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


# ---------------------------------------------------------------------------
# Static frontend (portable build only)
# ---------------------------------------------------------------------------
FRONTEND_DIR = Path(__file__).parent / "frontend"
if FRONTEND_DIR.exists():
    # Mount subdirectories for static assets
    if (FRONTEND_DIR / "_next").exists():
        app.mount("/_next", StaticFiles(directory=str(FRONTEND_DIR / "_next")), name="next")
    if (FRONTEND_DIR / "translator").exists():
        app.mount("/translator", StaticFiles(directory=str(FRONTEND_DIR / "translator"), html=True), name="translator")
    if (FRONTEND_DIR / "showcase").exists():
        app.mount("/showcase", StaticFiles(directory=str(FRONTEND_DIR / "showcase"), html=True), name="showcase")
    # Serve root-level static assets (favicon, icons)
    if (FRONTEND_DIR / "favicon.ico").exists():

        @app.get("/favicon.ico")
        async def _favicon():
            return FileResponse(str(FRONTEND_DIR / "favicon.ico"))


@app.get("/")
async def serve_frontend():
    """Serve the frontend app, or fall back to API health."""
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text(encoding="utf-8"))
    # Fallback: serve the translator as the main page
    translator = FRONTEND_DIR / "translator" / "index.html"
    if translator.exists():
        return HTMLResponse(content=translator.read_text(encoding="utf-8"))
    return {"status": "ok", "service": "PPTX Translator API"}


@app.get("/setup")
async def setup_guide():
    """Serve the in-app setup guide for API keys."""
    setup_path = Path(__file__).parent / "templates" / "setup.html"
    if setup_path.exists():
        return HTMLResponse(content=setup_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Setup Guide</h1><p>See backend/.env.example for configuration.</p>")


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.post("/api/upload", response_model=UploadResponse)
async def upload_pptx(file: UploadFile = File(...)):
    """Upload a PPTX file and extract text runs."""
    if not file.filename or not file.filename.endswith('.pptx'):
        raise HTTPException(status_code=400, detail="Only .pptx files are supported")
    
    job_id = str(uuid.uuid4())
    file_path = Path(settings.upload_dir) / f"{job_id}_{file.filename}"
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = os.path.getsize(file_path)
        if file_size > settings.max_file_size:
            os.remove(file_path)
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {settings.max_file_size / (1024*1024):.0f}MB"
            )
        
        document = extract_pptx(str(file_path), generate_preview=True)
        
        jobs[job_id] = TranslationJob(
            job_id=job_id,
            filename=file.filename,
            status="uploaded",
            total_runs=document.total_runs,
            translated_runs=[],
            progress=0.0,
        )
        
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
        
    except HTTPException:
        raise
    except Exception as e:
        if file_path.exists():
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@app.post("/api/translate", response_model=TranslateResponse)
async def translate_pptx(request: TranslationRequest, background_tasks: BackgroundTasks):
    """Translate text runs in a PPTX file."""
    job_id = request.job_id or str(uuid.uuid4())
    
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
    
    translated_runs = []
    tm = get_translation_memory()
    
    glossary_context = tm.build_context_prompt(request.source_language, request.target_language)
    if request.context:
        if glossary_context:
            context = f"{request.context.strip()}\n\nAlso use this terminology:\n{glossary_context}"
        else:
            context = request.context.strip()
    else:
        context = glossary_context
    
    texts_to_translate = [(run.run_id, run.text) for run in request.runs]
    
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
    
    translated_runs.sort(key=lambda tr: tr.run_id)
    translated_runs = sanitize_translated_runs(translated_runs)
    
    jobs[job_id].translated_runs = translated_runs
    jobs[job_id].progress = 100.0
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
    """Export translated PPTX file."""
    job_id = request.job_id
    
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job not completed")
    
    upload_dir = Path(settings.upload_dir)
    input_files = list(upload_dir.glob(f"{job_id}_*.pptx"))
    
    if not input_files:
        raise HTTPException(status_code=404, detail="Original file not found")
    
    input_path = input_files[0]
    output_filename = request.filename or f"translated_{job.filename}"
    output_path = Path(settings.output_dir) / output_filename
    
    try:
        success, failed = inject_translations(
            str(input_path),
            str(output_path),
            job.translated_runs,
            None,
        )
        
        if not success:
            for run in failed:
                print(f"Failed to inject: {run.run_id}")
        
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


# ---------------------------------------------------------------------------
# Preview images (LibreOffice required for rendering)
# ---------------------------------------------------------------------------

def _preview_cache_dir(job_id: str) -> Path:
    return PREVIEW_CACHE_DIR / job_id


def _load_cached_preview(job_id: str) -> Optional[list[str]]:
    cache_dir = _preview_cache_dir(job_id)
    if not cache_dir.exists():
        return None
    pngs = sorted(
        [f for f in cache_dir.iterdir() if f.suffix == ".png"],
        key=lambda f: int(f.stem.split("-")[1]) if "-" in f.stem and f.stem.split("-")[1].isdigit() else 0,
    )
    if not pngs:
        return None
    import base64
    return [f"data:image/png;base64,{base64.b64encode(p.read_bytes()).decode()}" for p in pngs]


def _find_libreoffice() -> Optional[str]:
    """Find LibreOffice executable on any platform."""
    candidates = ["soffice", "libreoffice"]
    if os.name == "nt":  # Windows
        candidates = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ] + candidates
    for cmd in candidates:
        try:
            subprocess.run([cmd, "--help"], capture_output=True, timeout=5)
            return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


@app.post("/api/preview")
async def generate_preview(request: dict):
    """Generate slide preview images from a translated PPTX."""
    job_id = request.get("job_id")
    filename = request.get("filename", "translated.pptx")
    
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    # Check cache first
    cached = _load_cached_preview(job_id)
    if cached:
        return {"images": cached, "total": len(cached), "cached": True}
    
    # Check LibreOffice availability
    lo = _find_libreoffice()
    if not lo:
        raise HTTPException(status_code=503, detail="Preview requires LibreOffice. Install from libreoffice.org")
    
    # Get the translated PPTX
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job not completed")
    
    upload_dir = Path(settings.upload_dir)
    input_files = list(upload_dir.glob(f"{job_id}_*.pptx"))
    if not input_files:
        raise HTTPException(status_code=404, detail="Original file not found")
    
    output_path = Path(settings.output_dir) / filename
    success, failed = inject_translations(
        str(input_files[0]), str(output_path), job.translated_runs, None
    )
    
    if not output_path.exists():
        raise HTTPException(status_code=500, detail="Failed to generate translated file")
    
    # Convert to preview images
    work_dir = Path(tempfile.mkdtemp(prefix="pptx-preview-"))
    try:
        pptx_path = work_dir / "slides.pptx"
        shutil.copy2(output_path, pptx_path)
        
        # LibreOffice: PPTX → PDF
        subprocess.run(
            [lo, "--headless", "--convert-to", "pdf", "--outdir", str(work_dir), str(pptx_path)],
            timeout=60, capture_output=True,
        )
        
        pdf_path = work_dir / "slides.pdf"
        if not pdf_path.exists():
            raise HTTPException(status_code=500, detail="LibreOffice conversion failed")
        
        # pdftoppm: PDF → PNGs
        subprocess.run(
            ["pdftoppm", "-png", "-r", "150", str(pdf_path), str(work_dir / "slide")],
            timeout=60, capture_output=True,
        )
        
        # Collect PNGs
        png_files = sorted(
            [f for f in work_dir.iterdir() if f.name.startswith("slide-") and f.suffix == ".png"],
            key=lambda f: int(f.stem.split("-")[1]) if "-" in f.stem and f.stem.split("-")[1].isdigit() else 0,
        )
        
        if not png_files:
            raise HTTPException(status_code=500, detail="No preview images generated")
        
        import base64
        images = [
            f"data:image/png;base64,{base64.b64encode(p.read_bytes()).decode()}"
            for p in png_files
        ]
        
        # Cache for next time
        cache_dir = _preview_cache_dir(job_id)
        cache_dir.mkdir(parents=True, exist_ok=True)
        for p in png_files:
            shutil.copy2(p, cache_dir / p.name)
        
        return {"images": images, "total": len(images), "cached": False}
        
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
