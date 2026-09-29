/**
 * @jest-environment node
 *
 * The preview store owns two contracts the UI and the routes depend on:
 *
 * - the cache keys are `<job_id>` and `<job_id>--original`, one entry per side
 *   of the before/after view, and they are also directory names, so a job_id
 *   that could climb out of the cache directory has to be refused; and
 * - a deck is claimed by exactly one generation at a time (two concurrent
 *   POSTs for the same cold key must not both launch LibreOffice), while the
 *   render lock keeps concurrent conversions — which share one LibreOffice
 *   profile — strictly serialised.
 *
 * Nothing here touches the disk: these are the in-memory halves.
 */
import {
  cacheKeyFor, claimGeneration, clearGeneration, failGeneration, getGeneration,
  isSafeJobId, parseDeckKind, withRenderLock,
} from '@/lib/previewStore';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe('cache keys', () => {
  it('keeps the original contract: <job_id> and <job_id>--original', () => {
    expect(cacheKeyFor('abc-123', 'translated')).toBe('abc-123');
    expect(cacheKeyFor('abc-123', 'original')).toBe('abc-123--original');
  });

  it('treats anything but "original" as the translated side', () => {
    expect(parseDeckKind('original')).toBe('original');
    expect(parseDeckKind('translated')).toBe('translated');
    expect(parseDeckKind(undefined)).toBe('translated');
    expect(parseDeckKind('nonsense')).toBe('translated');
  });
});

describe('job id validation', () => {
  it('accepts the uuid job ids the backend hands out', () => {
    expect(isSafeJobId('fcd8af95-ecec-4af2-b674-3bab02367a15')).toBe(true);
  });

  it('refuses anything that could address a path outside the cache', () => {
    expect(isSafeJobId('..')).toBe(false);
    expect(isSafeJobId('../..')).toBe(false);
    expect(isSafeJobId('a/../../etc')).toBe(false);
    expect(isSafeJobId('a\\b')).toBe(false);
    expect(isSafeJobId('job id')).toBe(false);
    expect(isSafeJobId('')).toBe(false);
    expect(isSafeJobId(undefined)).toBe(false);
    expect(isSafeJobId(42)).toBe(false);
    expect(isSafeJobId('x'.repeat(129))).toBe(false);
  });
});

describe('generation claim', () => {
  it('is claimed by exactly one caller until it is cleared', () => {
    const key = 'claim-test-job';
    clearGeneration(key);
    expect(claimGeneration(key)).toBe(true);
    expect(claimGeneration(key)).toBe(false);
    expect(getGeneration(key)?.status).toBe('running');
    clearGeneration(key);
    expect(claimGeneration(key)).toBe(true);
    clearGeneration(key);
  });

  it('surfaces a failure once, then lets the key be retried', () => {
    const key = 'failing-test-job';
    clearGeneration(key);
    expect(claimGeneration(key)).toBe(true);
    failGeneration(key, 'LibreOffice conversion (PPTX → PDF) timed out after 60s');
    expect(getGeneration(key)).toEqual({
      status: 'error',
      message: 'LibreOffice conversion (PPTX → PDF) timed out after 60s',
    });
    // The route reports the error and releases the key, so the next request
    // regenerates instead of returning the same failure forever.
    clearGeneration(key);
    expect(claimGeneration(key)).toBe(true);
    clearGeneration(key);
  });
});

describe('render lock', () => {
  it('runs conversions one at a time, in the order they asked', async () => {
    const order: string[] = [];
    const first = withRenderLock(async () => {
      await sleep(30);
      order.push('first');
      return 1;
    });
    const second = withRenderLock(async () => {
      order.push('second');
      return 2;
    });
    await expect(Promise.all([first, second])).resolves.toEqual([1, 2]);
    expect(order).toEqual(['first', 'second']);
  });

  it('keeps the queue usable after a conversion fails', async () => {
    await expect(
      withRenderLock(() => Promise.reject(new Error('PDF rendering (pdftoppm) timed out after 60s'))),
    ).rejects.toThrow('timed out');
    await expect(withRenderLock(async () => 'next deck')).resolves.toBe('next deck');
  });
});
