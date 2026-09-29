/**
 * Everything the two preview routes share: the on-disk cache layout, job-id
 * validation (the cache key is a directory name, so it must never contain a
 * path), the per-key generation registry, and the render lock.
 *
 * The mutable parts live on `globalThis` rather than in module variables —
 * Next bundles each route handler on its own, so a module-level `let` would be
 * a different copy per route and `/api/preview` and `/api/preview/slide` would
 * disagree about what is running.
 *
 * Cache keys are unchanged from the original implementation: `<job_id>` for the
 * translated side and `<job_id>--original` for the side as uploaded, one
 * directory of `slide-*.png` per key under CACHE_DIR.
 */
import { randomUUID } from 'crypto';
import {
  copyFileSync, existsSync, mkdirSync, readdirSync, renameSync, rmSync,
  statSync, utimesSync,
} from 'fs';
import { join } from 'path';

export const CACHE_DIR = '/tmp/pptx-preview-cache';
const CACHE_TTL_MS = 3600_000; // 1 hour

/** Upper bound on slides one preview may ever ask for. */
export const MAX_SLIDES = 500;

/** How long a generation may claim a key before it is considered abandoned. */
const RUNNING_TTL_MS = 10 * 60_000;

export type DeckKind = 'original' | 'translated';

/** `<job_id>` for the after side, `<job_id>--original` for the before side. */
export function cacheKeyFor(jobId: string, kind: DeckKind): string {
  return kind === 'original' ? `${jobId}--original` : jobId;
}

/**
 * Job ids become directory names, so only `[A-Za-z0-9._-]` is accepted and a
 * `..` component is refused outright. Anything else would let a crafted
 * job_id read or write outside the cache directory.
 */
export function isSafeJobId(jobId: unknown): jobId is string {
  return (
    typeof jobId === 'string' &&
    jobId.length > 0 &&
    jobId.length <= 128 &&
    /^[\w.-]+$/.test(jobId) &&
    !jobId.includes('..')
  );
}

export function parseDeckKind(which: unknown): DeckKind {
  return which === 'original' ? 'original' : 'translated';
}

/** Sort `slide-1.png`, `slide-02.png`, … by slide number, not lexicographically. */
export function sortSlideFiles(files: string[]): string[] {
  const number = (f: string) => parseInt(f.match(/slide-(\d+)\.png$/)?.[1] ?? '0', 10);
  return [...files].sort((a, b) => number(a) - number(b));
}

/** `slide-1.png`, `slide-02.png`, … sorted by slide number, not lexicographically. */
export function listSlideFiles(cacheKey: string): string[] {
  const dir = join(CACHE_DIR, cacheKey);
  if (!existsSync(dir)) return [];
  try {
    return sortSlideFiles(readdirSync(dir).filter((f) => /^slide-\d+\.png$/.test(f)));
  } catch {
    return [];
  }
}

export function cachedSlideCount(cacheKey: string): number {
  return listSlideFiles(cacheKey).length;
}

/** The nth (1-based) cached slide, or null when it does not exist. */
export function resolveSlideFile(cacheKey: string, n: number): string | null {
  if (!Number.isInteger(n) || n < 1 || n > MAX_SLIDES) return null;
  const files = listSlideFiles(cacheKey);
  if (n > files.length) return null;
  return join(CACHE_DIR, cacheKey, files[n - 1]);
}

/**
 * Publish a finished render under its cache key. The copy goes to a staging
 * directory first and is renamed into place, so a request can never see a
 * half-copied deck (the old file-by-file copy could).
 */
export function saveToCache(cacheKey: string, sourceDir: string, fileNames: string[]): void {
  const finalDir = join(CACHE_DIR, cacheKey);
  const staging = join(CACHE_DIR, `.staging-${randomUUID()}`);
  try {
    mkdirSync(staging, { recursive: true });
    for (const f of fileNames) {
      const src = join(sourceDir, f);
      if (existsSync(src)) copyFileSync(src, join(staging, f));
    }
    rmSync(finalDir, { recursive: true, force: true });
    renameSync(staging, finalDir);
    const now = new Date();
    try { utimesSync(finalDir, now, now); } catch { /* best effort */ }
  } catch {
    // Non-fatal: the next request regenerates.
    try { rmSync(staging, { recursive: true, force: true }); } catch { /* ok */ }
  }
}

function dirMtimeMs(p: string): number {
  try { return statSync(p).mtimeMs; } catch { return 0; }
}

/** Sweep cache entries older than TTL (fire-and-forget). */
export function sweepCache(): void {
  try {
    const now = Date.now();
    for (const entry of readdirSync(CACHE_DIR, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const full = join(CACHE_DIR, entry.name);
      if (now - dirMtimeMs(full) > CACHE_TTL_MS) {
        rmSync(full, { recursive: true, force: true });
      }
    }
  } catch { /* first call or race — ignore */ }
}

/* ── generation registry ─────────────────────────────────────────────── */

export type GenerationState =
  | { status: 'running'; startedAt: number }
  | { status: 'error'; message: string };

type StoreState = { generations: Map<string, GenerationState>; renderQueue: Promise<unknown> };

const STATE_KEY = '__jpeigoPreviewStore';

function store(): StoreState {
  const g = globalThis as unknown as { [STATE_KEY]?: StoreState };
  if (!g[STATE_KEY]) g[STATE_KEY] = { generations: new Map(), renderQueue: Promise.resolve() };
  return g[STATE_KEY] as StoreState;
}

export function getGeneration(cacheKey: string): GenerationState | undefined {
  const state = store().generations.get(cacheKey);
  if (state?.status === 'running' && Date.now() - state.startedAt > RUNNING_TTL_MS) {
    // The process did not die (we are still here) but the generation stopped
    // reporting in. Let a new attempt claim the key instead of polling a 202
    // until the client gives up.
    store().generations.delete(cacheKey);
    return undefined;
  }
  return state;
}

/** Claim a key. Returns false if someone else is already generating it. */
export function claimGeneration(cacheKey: string): boolean {
  const s = store();
  if (getGeneration(cacheKey)?.status === 'running') return false;
  s.generations.set(cacheKey, { status: 'running', startedAt: Date.now() });
  return true;
}

export function failGeneration(cacheKey: string, message: string): void {
  store().generations.set(cacheKey, { status: 'error', message });
}

export function clearGeneration(cacheKey: string): void {
  store().generations.delete(cacheKey);
}

/**
 * Serialise the heavy conversion: LibreOffice refuses to run two instances
 * against one user profile, and the synchronous version of this route got that
 * for free by blocking the event loop. Queueing instead keeps the loop free.
 */
export function withRenderLock<T>(fn: () => Promise<T>): Promise<T> {
  const s = store();
  const result = s.renderQueue.then(fn, fn);
  s.renderQueue = result.then(() => undefined, () => undefined);
  return result;
}
