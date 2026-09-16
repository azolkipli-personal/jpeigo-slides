/**
 * API route for generating slide preview images from a PPTX.
 * Converts PPTX → PDF → individual page PNGs using LibreOffice + pdftoppm.
 * Results are cached per deck (job_id + which) so repeated requests skip the heavy
 * conversion. Pass which: 'original' to render the deck as uploaded, 'translated'
 * (default) to render the exported deck — that pair is the before/after view.
 */
import { NextRequest, NextResponse } from 'next/server';
import { execSync } from 'child_process';
import {
  mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync, existsSync,
} from 'fs';
import { join } from 'path';
import { randomUUID } from 'crypto';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';
const CACHE_DIR = '/tmp/pptx-preview-cache';
const CACHE_TTL_MS = 3600_000; // 1 hour

/** Quick stat for TTL check — no extra deps needed. */
function mtimeMs(p: string): number {
  try {
    const { statSync } = require('fs') as typeof import('fs');
    return statSync(p).mtimeMs;
  } catch { return 0; }
}

/** Sweep cache entries older than TTL (fire-and-forget). */
function sweepCache(): void {
  try {
    const dir = readdirSync(CACHE_DIR, { withFileTypes: true });
    const now = Date.now();
    for (const entry of dir) {
      if (entry.isDirectory()) {
        const full = join(CACHE_DIR, entry.name);
        if (now - mtimeMs(full) > CACHE_TTL_MS) {
          rmSync(full, { recursive: true, force: true });
        }
      }
    }
  } catch { /* first call or race — ignore */ }
}

function loadCachedImages(cacheKey: string): string[] | null {
  const cacheDir = join(CACHE_DIR, cacheKey);
  if (!existsSync(cacheDir)) return null;

  const files = readdirSync(cacheDir)
    .filter((f) => f.endsWith('.png'))
    .sort((a, b) => {
      const nA = parseInt(a.match(/slide-(\d+)\.png$/)?.[1] || '0');
      const nB = parseInt(b.match(/slide-(\d+)\.png$/)?.[1] || '0');
      return nA - nB;
    });

  if (files.length === 0) return null;

  return files.map((f) => {
    const data = readFileSync(join(cacheDir, f));
    return `data:image/png;base64,${data.toString('base64')}`;
  });
}

function saveToCache(cacheKey: string, sourceDir: string, fileNames: string[]): void {
  try {
    const cacheDir = join(CACHE_DIR, cacheKey);
    mkdirSync(cacheDir, { recursive: true });
    for (const f of fileNames) {
      const src = join(sourceDir, f);
      if (existsSync(src)) {
        writeFileSync(join(cacheDir, f), readFileSync(src));
      }
    }
    // Update mtime on the dir so TTL sweep works
    const now = new Date();
    const { utimesSync } = require('fs') as typeof import('fs');
    try { utimesSync(cacheDir, now, now); } catch { /* ok */ }
  } catch {
    // Non-fatal — next request will regenerate
  }
}

export async function POST(request: NextRequest) {
  const workDir = join('/tmp', `pptx-preview-${randomUUID()}`);

  try {
    const { job_id, filename, which } = await request.json();
    if (!job_id) {
      return NextResponse.json({ error: 'job_id is required' }, { status: 400 });
    }
    // 'translated' (default) renders the exported deck, 'original' the deck as uploaded;
    // the two are cached separately so switching back and forth is instant.
    const deckKind: 'original' | 'translated' = which === 'original' ? 'original' : 'translated';
    const cacheKey = deckKind === 'original' ? `${job_id}--original` : job_id;

    // --- Check cache first ---
    const cached = loadCachedImages(cacheKey);
    if (cached) {
      return NextResponse.json({ images: cached, total: cached.length, cached: true, which: deckKind });
    }

    // --- Generate fresh ---
    // 1. Download the deck from the Python backend. The translated side is built on
    //    demand by POST /api/export; the original side is the upload returned as-is,
    //    which is the whole reason both can be shown side by side.
    const deckRes = deckKind === 'original'
      ? await fetch(`${PYTHON_BACKEND_URL}/api/source?job_id=${encodeURIComponent(job_id)}`)
      : await fetch(`${PYTHON_BACKEND_URL}/api/export`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ job_id, filename: filename || `translated_${job_id}.pptx` }),
        });
    if (!deckRes.ok) {
      return NextResponse.json(
        { error: `Failed to fetch the ${deckKind} PPTX` }, { status: 500 },
      );
    }
    const pptxBuffer = Buffer.from(await deckRes.arrayBuffer());

    // 2. Save to work dir
    mkdirSync(workDir, { recursive: true });
    const pptxPath = join(workDir, 'slides.pptx');
    writeFileSync(pptxPath, pptxBuffer);

    // 3. Convert PPTX → PDF using LibreOffice
    execSync(
      `soffice --headless --convert-to pdf --outdir "${workDir}" "${pptxPath}"`,
      { timeout: 60_000, stdio: 'pipe' },
    );

    const pdfPath = join(workDir, 'slides.pdf');

    // 4. Convert PDF → individual PNGs using pdftoppm
    execSync(
      `pdftoppm -png -r 150 "${pdfPath}" "${workDir}/slide"`,
      { timeout: 60_000, stdio: 'pipe' },
    );

    // 5. Read back the generated PNG files
    const files = readdirSync(workDir)
      .filter((f: string) => f.startsWith('slide-') && f.endsWith('.png'))
      .sort((a: string, b: string) => {
        const numA = parseInt(a.match(/slide-(\d+)\.png$/)?.[1] || '0');
        const numB = parseInt(b.match(/slide-(\d+)\.png$/)?.[1] || '0');
        return numA - numB;
      });

    const images = files.map((f: string) => {
      const data = readFileSync(join(workDir, f));
      return `data:image/png;base64,${data.toString('base64')}`;
    });

    // 6. Cache the generated PNGs for next time
    saveToCache(cacheKey, workDir, files);

    // 7. Cleanup work dir + sweep old cache entries
    rmSync(workDir, { recursive: true, force: true });
    sweepCache();

    return NextResponse.json({ images, total: images.length, cached: false, which: deckKind });

  } catch (error) {
    try { rmSync(workDir, { recursive: true, force: true }); } catch { /* ok */ }
    console.error('Preview generation error:', error);
    return NextResponse.json(
      {
        error: 'Failed to generate preview images: ' +
          (error instanceof Error ? error.message : 'Unknown error'),
      },
      { status: 500 },
    );
  }
}
