/**
 * API route for generating slide preview images from a translated PPTX.
 * Converts PPTX → PDF → individual page PNGs using LibreOffice + pdftoppm.
 * Results are cached by job_id so repeated requests skip the heavy conversion.
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

function loadCachedImages(jobId: string): string[] | null {
  const cacheDir = join(CACHE_DIR, jobId);
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

function saveToCache(jobId: string, sourceDir: string, fileNames: string[]): void {
  try {
    const cacheDir = join(CACHE_DIR, jobId);
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
    const { job_id, filename } = await request.json();
    if (!job_id) {
      return NextResponse.json({ error: 'job_id is required' }, { status: 400 });
    }

    // --- Check cache first ---
    const cached = loadCachedImages(job_id);
    if (cached) {
      return NextResponse.json({ images: cached, total: cached.length, cached: true });
    }

    // --- Generate fresh ---
    // 1. Download the translated PPTX from Python backend
    const exportRes = await fetch(`${PYTHON_BACKEND_URL}/api/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id, filename: filename || `translated_${job_id}.pptx` }),
    });
    if (!exportRes.ok) {
      return NextResponse.json({ error: 'Failed to fetch translated PPTX' }, { status: 500 });
    }
    const pptxBuffer = Buffer.from(await exportRes.arrayBuffer());

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
    saveToCache(job_id, workDir, files);

    // 7. Cleanup work dir + sweep old cache entries
    rmSync(workDir, { recursive: true, force: true });
    sweepCache();

    return NextResponse.json({ images, total: images.length, cached: false });

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
