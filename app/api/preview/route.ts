/**
 * Slide preview — index endpoint.
 *
 * POST answers with an *index* of the deck: how many slides there are and a URL
 * per slide (`/api/preview/slide?…&n=k`, served by the sibling route). It never
 * returns image bytes, so a 26-slide deck is a ~2 kB reply instead of the 12 MB
 * base64 blob this route used to build, and each request does a bounded amount
 * of work.
 *
 * Generation itself (fetch deck → LibreOffice → pdftoppm) runs in the
 * background and answers 202 `pending: true` until the cache is populated, so
 * no request is ever held open for the length of a conversion — and, crucially,
 * the conversions are spawned asynchronously instead of `execSync`-ed, so the
 * server's event loop keeps serving the rest of the app (the Download button
 * included) while a preview renders.
 *
 * Cache keys are unchanged: `<job_id>` for the translated deck, `<job_id>--original`
 * for the deck as uploaded, one directory of PNGs each.
 */
import { NextRequest, NextResponse } from 'next/server';
import { existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from 'fs';
import { join } from 'path';
import { randomUUID } from 'crypto';
import { whenExportsIdle } from '@/lib/exportGate';
import { runCommand } from '@/lib/runCommand';
import {
  type DeckKind, cachedSlideCount, cacheKeyFor, claimGeneration, clearGeneration,
  failGeneration, getGeneration, isSafeJobId, parseDeckKind, saveToCache,
  sortSlideFiles, sweepCache, withRenderLock,
} from '@/lib/previewStore';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';

const SOFFICE_TIMEOUT_MS = 60_000;
const PDFTOPPM_TIMEOUT_MS = 60_000;
const DECK_FETCH_TIMEOUT_MS = 60_000;

function pendingResponse(kind: DeckKind): NextResponse {
  return NextResponse.json({ pending: true, total: 0, which: kind }, { status: 202 });
}

function indexResponse(jobId: string, kind: DeckKind, total: number, cached: boolean): NextResponse {
  const images = Array.from({ length: total }, (_, i) =>
    `/api/preview/slide?job_id=${encodeURIComponent(jobId)}&which=${kind}&n=${i + 1}`);
  return NextResponse.json({ images, total, cached, which: kind });
}

/**
 * Pull the deck from the backend. The translated side is built on demand by
 * POST /api/export; the original side is the upload as it arrived, which is
 * what makes the before/after pair comparable.
 */
async function fetchDeck(jobId: string, filename: string, kind: DeckKind): Promise<Buffer> {
  const deckRes = kind === 'original'
    ? await fetch(
        `${PYTHON_BACKEND_URL}/api/source?job_id=${encodeURIComponent(jobId)}`,
        { signal: AbortSignal.timeout(DECK_FETCH_TIMEOUT_MS) },
      )
    : await fetch(`${PYTHON_BACKEND_URL}/api/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId, filename: filename || `translated_${jobId}.pptx` }),
        signal: AbortSignal.timeout(DECK_FETCH_TIMEOUT_MS),
      });
  if (!deckRes.ok) {
    throw new Error(`Failed to fetch the ${kind} PPTX from the backend (HTTP ${deckRes.status})`);
  }
  return Buffer.from(await deckRes.arrayBuffer());
}

/** PPTX → PDF → PNGs. Both converters are spawned, so the event loop keeps serving. */
async function renderSlides(pptxBuffer: Buffer, workDir: string): Promise<string[]> {
  mkdirSync(workDir, { recursive: true });
  const pptxPath = join(workDir, 'slides.pptx');
  writeFileSync(pptxPath, pptxBuffer);

  await runCommand(
    'soffice',
    ['--headless', '--convert-to', 'pdf', '--outdir', workDir, pptxPath],
    SOFFICE_TIMEOUT_MS,
    'LibreOffice conversion (PPTX → PDF)',
  );

  const pdfPath = join(workDir, 'slides.pdf');
  if (!existsSync(pdfPath)) {
    throw new Error('LibreOffice conversion (PPTX → PDF) produced no PDF');
  }

  await runCommand(
    'pdftoppm',
    ['-png', '-r', '150', pdfPath, join(workDir, 'slide')],
    PDFTOPPM_TIMEOUT_MS,
    'PDF rendering (pdftoppm)',
  );

  const files = sortSlideFiles(readdirSync(workDir).filter((f) => /^slide-\d+\.png$/.test(f)));
  if (files.length === 0) {
    throw new Error('PDF rendering (pdftoppm) produced no slide images');
  }
  return files;
}

/**
 * Render one deck into the cache. Runs detached from the request that started
 * it: the client polls until the cache exists, so the work survives the reply
 * and no connection stays open for the duration.
 */
async function generatePreview(jobId: string, filename: string, kind: DeckKind, cacheKey: string): Promise<void> {
  const workDir = join('/tmp', `pptx-preview-${randomUUID()}`);
  try {
    await withRenderLock(async () => {
      // Someone else may have finished this key while we queued.
      if (cachedSlideCount(cacheKey) > 0) return;

      // A download in flight has priority: the preview must not ask the backend
      // to build a deck while a user's export is running. Downloads never wait
      // on previews (see lib/exportGate.ts for why the gate is one-way).
      await whenExportsIdle();

      const pptxBuffer = await fetchDeck(jobId, filename, kind);
      const files = await renderSlides(pptxBuffer, workDir);

      // Publish atomically (staged rename) and clean up after ourselves.
      saveToCache(cacheKey, workDir, files);
    });
    clearGeneration(cacheKey);
    sweepCache();
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('Preview generation error:', message);
    failGeneration(cacheKey, message);
  } finally {
    try { rmSync(workDir, { recursive: true, force: true }); } catch { /* ok */ }
  }
}

export async function POST(request: NextRequest) {
  let body: { job_id?: unknown; filename?: unknown; which?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid request body' }, { status: 400 });
  }

  const { job_id, filename, which } = body;
  if (job_id === undefined || job_id === null || job_id === '') {
    return NextResponse.json({ error: 'job_id is required' }, { status: 400 });
  }
  if (!isSafeJobId(job_id)) {
    return NextResponse.json({ error: 'job_id is not a valid job identifier' }, { status: 400 });
  }

  const kind = parseDeckKind(which);
  const cacheKey = cacheKeyFor(job_id, kind);

  // Ready: the index (slide count + per-slide URLs) and nothing heavier.
  const total = cachedSlideCount(cacheKey);
  if (total > 0) {
    return indexResponse(job_id, kind, total, true);
  }

  const state = getGeneration(cacheKey);
  if (state?.status === 'error') {
    // Surface the real failure (timeout, non-2xx backend, no output) once, then
    // release the key so the next request can try again.
    clearGeneration(cacheKey);
    return NextResponse.json({ error: state.message }, { status: 500 });
  }
  if (state?.status === 'running') {
    return pendingResponse(kind);
  }

  // Claim before awaiting anything: check-and-set in a single tick, so two
  // concurrent POSTs for the same deck cannot both start a conversion.
  if (!claimGeneration(cacheKey)) {
    return pendingResponse(kind);
  }
  void generatePreview(job_id, typeof filename === 'string' ? filename : '', kind, cacheKey);
  return pendingResponse(kind);
}
