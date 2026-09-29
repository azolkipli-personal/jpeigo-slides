/**
 * @jest-environment node
 *
 * One request, one PNG. This is the endpoint the index route points the viewer
 * at, so everything about it is a contract with a browser: validation happens
 * before any disk access, a missing slide is a 404 (never a 500 or a blank
 * image), and a hit carries the headers that make paging back and forth cheap.
 */
import { NextRequest } from 'next/server';
import { GET } from '../app/api/preview/slide/route';
import { MAX_SLIDES, resolveSlideFile } from '../lib/previewStore';
import { readFile } from 'fs/promises';

jest.mock('../lib/previewStore', () => {
  const actual = jest.requireActual('../lib/previewStore');
  return { ...actual, resolveSlideFile: jest.fn(() => null) };
});

jest.mock('fs/promises', () => ({ readFile: jest.fn() }));

const mockResolveSlideFile = resolveSlideFile as jest.Mock;
const mockReadFile = readFile as jest.Mock;

const call = (query: string) => GET(new NextRequest(`http://localhost:3000/api/preview/slide?${query}`));

beforeEach(() => {
  mockResolveSlideFile.mockClear();
  mockResolveSlideFile.mockReturnValue(null);
  mockReadFile.mockClear();
  mockReadFile.mockResolvedValue(Buffer.from('png-bytes'));
});

describe('GET /api/preview/slide', () => {
  it('requires a job id before it touches the cache', async () => {
    const res = await call('which=translated&n=1');
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe('job_id is required');
    expect(mockResolveSlideFile).not.toHaveBeenCalled();
  });

  it('refuses a job id that could address a path outside the cache', async () => {
    const res = await call('job_id=../../etc&which=translated&n=1');
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe('job_id is not a valid job identifier');
    expect(mockResolveSlideFile).not.toHaveBeenCalled();
  });

  it.each([
    ['n is missing', 'job_id=job-1&which=translated'],
    ['n is not a number', 'job_id=job-1&which=translated&n=abc'],
    ['n is zero', 'job_id=job-1&which=translated&n=0'],
    ['n is negative', 'job_id=job-1&which=translated&n=-3'],
    ['n is beyond the deck cap', `job_id=job-1&which=translated&n=${MAX_SLIDES + 1}`],
  ])('rejects an unusable slide number: %s', async (_label, query) => {
    const res = await call(query);
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe(
      `n must be a slide number between 1 and ${MAX_SLIDES}`,
    );
    expect(mockResolveSlideFile).not.toHaveBeenCalled();
  });

  it('answers 404 for a slide the preview does not have', async () => {
    const res = await call('job_id=job-1&which=translated&n=99');
    expect(res.status).toBe(404);
    expect((await res.json()).error).toBe(
      'No such slide in this preview (generate the preview first)',
    );
    expect(mockReadFile).not.toHaveBeenCalled();
  });

  it('serves a cached slide with the headers a browser needs', async () => {
    mockResolveSlideFile.mockReturnValue('/tmp/cache/job-1/slide-7.png');
    const res = await call('job_id=job-1&which=translated&n=7');

    expect(res.status).toBe(200);
    expect(mockResolveSlideFile).toHaveBeenCalledWith('job-1', 7);
    expect(mockReadFile).toHaveBeenCalledWith('/tmp/cache/job-1/slide-7.png');
    expect(res.headers.get('content-type')).toBe('image/png');
    expect(res.headers.get('content-length')).toBe(String('png-bytes'.length));
    expect(res.headers.get('cache-control')).toBe('private, max-age=3600');
    expect(res.headers.get('x-slide-number')).toBe('7');
    expect(res.headers.get('x-slide-which')).toBe('translated');
    expect(Buffer.from(await res.arrayBuffer()).toString()).toBe('png-bytes');
  });

  it('reads the before side from its own cache key', async () => {
    mockResolveSlideFile.mockReturnValue('/tmp/cache/job-1--original/slide-1.png');
    const res = await call('job_id=job-1&which=original&n=1');
    expect(res.status).toBe(200);
    expect(mockResolveSlideFile).toHaveBeenCalledWith('job-1--original', 1);
    expect(res.headers.get('x-slide-which')).toBe('original');
  });

  it('turns an unreadable file into a 404 rather than a crash', async () => {
    mockResolveSlideFile.mockReturnValue('/tmp/cache/job-1/slide-2.png');
    mockReadFile.mockRejectedValue(Object.assign(new Error('ENOENT'), { code: 'ENOENT' }));
    const res = await call('job_id=job-1&which=translated&n=2');
    expect(res.status).toBe(404);
    expect((await res.json()).error).toBe('Slide image could not be read');
  });
});
