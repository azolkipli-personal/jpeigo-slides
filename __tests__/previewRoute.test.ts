/**
 * @jest-environment node
 *
 * The preview index is a delivery contract, not a rendering one: it answers
 * with a slide count and one URL per slide, and it answers *fast* — a cold
 * deck comes back as 202 `pending` while the conversion runs in the
 * background, never as a request held open for the length of a LibreOffice
 * run.
 *
 * The conversion itself is deliberately stubbed out here (the lock never
 * settles), so these tests pin the statuses and the payload shape without
 * spawning anything.
 */
import { NextRequest } from 'next/server';
import { POST } from '../app/api/preview/route';
import {
  cachedSlideCount, claimGeneration, clearGeneration, failGeneration, withRenderLock,
} from '../lib/previewStore';

jest.mock('../lib/previewStore', () => {
  const actual = jest.requireActual('../lib/previewStore');
  return {
    ...actual,
    cachedSlideCount: jest.fn(() => 0),
    // Never runs the callback: no fetch, no LibreOffice, no disk.
    withRenderLock: jest.fn(() => new Promise(() => {})),
  };
});

const mockCachedSlideCount = cachedSlideCount as jest.Mock;
const mockWithRenderLock = withRenderLock as jest.Mock;

const call = (body: unknown) =>
  POST(new NextRequest('http://localhost:3000/api/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }));

beforeEach(() => {
  mockCachedSlideCount.mockClear();
  mockCachedSlideCount.mockReturnValue(0);
  mockWithRenderLock.mockClear();
  clearGeneration('job-1');
  clearGeneration('job-1--original');
});

afterEach(() => {
  clearGeneration('job-1');
  clearGeneration('job-1--original');
});

describe('POST /api/preview', () => {
  it('rejects a missing job id', async () => {
    const res = await call({ which: 'translated' });
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe('job_id is required');
  });

  it('rejects a job id that could address a path outside the cache', async () => {
    const res = await call({ job_id: '../..', which: 'translated' });
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe('job_id is not a valid job identifier');
    expect(mockWithRenderLock).not.toHaveBeenCalled();
  });

  it('answers a warm cache with the index alone — no images in the body', async () => {
    mockCachedSlideCount.mockImplementation((key: string) => (key === 'job-1' ? 26 : 0));
    const res = await call({ job_id: 'job-1', which: 'translated' });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.total).toBe(26);
    expect(body.cached).toBe(true);
    expect(body.which).toBe('translated');
    expect(body.images).toHaveLength(26);
    expect(body.images[0]).toBe('/api/preview/slide?job_id=job-1&which=translated&n=1');
    expect(body.images[25]).toBe('/api/preview/slide?job_id=job-1&which=translated&n=26');
    expect(JSON.stringify(body)).not.toContain('data:image');
    expect(mockWithRenderLock).not.toHaveBeenCalled();
  });

  it('reads the before side from its own cache key', async () => {
    mockCachedSlideCount.mockImplementation((key: string) => (key === 'job-1--original' ? 26 : 0));
    const res = await call({ job_id: 'job-1', which: 'original' });
    expect(mockCachedSlideCount).toHaveBeenCalledWith('job-1--original');
    const body = await res.json();
    expect(body.which).toBe('original');
    expect(body.images[0]).toBe('/api/preview/slide?job_id=job-1&which=original&n=1');
  });

  it('returns 202 immediately on a cold key and starts one generation', async () => {
    const res = await call({ job_id: 'job-1', which: 'translated' });
    expect(res.status).toBe(202);
    expect(await res.json()).toEqual({ pending: true, total: 0, which: 'translated' });
    expect(mockWithRenderLock).toHaveBeenCalledTimes(1);
    expect(claimGeneration('job-1')).toBe(false);
  });

  it('does not start a second generation while one is running', async () => {
    const first = await call({ job_id: 'job-1', which: 'translated' });
    expect(first.status).toBe(202);
    const second = await call({ job_id: 'job-1', which: 'translated' });
    expect(second.status).toBe(202);
    expect(mockWithRenderLock).toHaveBeenCalledTimes(1);
  });

  it('reports the real conversion failure once, then allows a retry', async () => {
    claimGeneration('job-1');
    failGeneration('job-1', 'LibreOffice conversion (PPTX → PDF) timed out after 60s');

    const res = await call({ job_id: 'job-1', which: 'translated' });
    expect(res.status).toBe(500);
    expect((await res.json()).error).toBe('LibreOffice conversion (PPTX → PDF) timed out after 60s');

    // The key is released by that reply, so the next request renders again
    // instead of returning the same dead error forever.
    expect(claimGeneration('job-1')).toBe(true);
    clearGeneration('job-1');
  });
});
