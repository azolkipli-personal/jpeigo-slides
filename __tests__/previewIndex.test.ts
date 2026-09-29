/**
 * @jest-environment node
 *
 * The page must never hold a connection open for the length of a conversion:
 * this loop is what turns a 10-second LibreOffice run into a series of short
 * polls plus one small index reply, and it decides which failure text the user
 * actually sees (the server's explanation when there is one, otherwise the
 * translated message the page falls back to).
 */
import { PreviewRequestError, fetchPreviewIndex } from '../lib/previewIndex';

type Res = { ok: boolean; status: number; json: () => Promise<unknown> };

const respond = (status: number, body: unknown): Res => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

const unparseable = (status: number): Res => ({
  ok: false,
  status,
  json: async () => { throw new Error('not json'); },
});

describe('fetchPreviewIndex', () => {
  it('takes a warm index in a single request', async () => {
    const fetchImpl = jest.fn().mockResolvedValue(respond(200, {
      images: ['/api/preview/slide?job_id=job-1&which=translated&n=1'],
      total: 1,
      cached: true,
    }));

    const images = await fetchPreviewIndex('job-1', 'deck.pptx', 'translated', { fetchImpl });

    expect(images).toEqual(['/api/preview/slide?job_id=job-1&which=translated&n=1']);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('posts the deck identity the route validates', async () => {
    const fetchImpl = jest.fn().mockResolvedValue(respond(200, { images: [] }));
    await fetchPreviewIndex('job-1', 'deck.pptx', 'original', { fetchImpl });

    expect(fetchImpl).toHaveBeenCalledWith('/api/preview', expect.objectContaining({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: 'job-1', filename: 'deck.pptx', which: 'original' }),
    }));
  });

  it('keeps polling while the route answers 202, then returns the index', async () => {
    const fetchImpl = jest.fn()
      .mockResolvedValueOnce(respond(202, { pending: true }))
      .mockResolvedValueOnce(respond(202, { pending: true }))
      .mockResolvedValueOnce(respond(202, { pending: true }))
      .mockResolvedValueOnce(respond(200, { images: ['u1', 'u2'], total: 2 }));

    const started = Date.now();
    const images = await fetchPreviewIndex('job-1', 'deck.pptx', 'translated', {
      fetchImpl,
      pollMs: 5,
    });
    const elapsed = Date.now() - started;

    expect(images).toEqual(['u1', 'u2']);
    expect(fetchImpl).toHaveBeenCalledTimes(4);
    // Three gaps of pollMs: the loop waits between polls instead of hammering.
    expect(elapsed).toBeGreaterThanOrEqual(15);
    expect(elapsed).toBeLessThan(3000);
  });

  it('stops when the deck never becomes ready', async () => {
    const fetchImpl = jest.fn().mockResolvedValue(respond(202, { pending: true }));

    await expect(fetchPreviewIndex('job-1', 'deck.pptx', 'translated', {
      fetchImpl,
      pollMs: 1,
      maxAttempts: 3,
    })).rejects.toBeInstanceOf(PreviewRequestError);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it('surfaces the server explanation for a failed generation', async () => {
    const fetchImpl = jest.fn().mockResolvedValue(respond(500, {
      error: 'LibreOffice conversion (PPTX → PDF) timed out after 60s',
    }));

    const failure = await fetchPreviewIndex('job-1', 'deck.pptx', 'translated', { fetchImpl })
      .catch((err: unknown) => err);

    expect(failure).toBeInstanceOf(PreviewRequestError);
    expect((failure as PreviewRequestError).serverMessage).toBe(
      'LibreOffice conversion (PPTX → PDF) timed out after 60s',
    );
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('reports no server message when the failure has none to give', async () => {
    const fetchImpl = jest.fn().mockResolvedValue(unparseable(502));

    const failure = await fetchPreviewIndex('job-1', 'deck.pptx', 'translated', { fetchImpl })
      .catch((err: unknown) => err);

    expect(failure).toBeInstanceOf(PreviewRequestError);
    expect((failure as PreviewRequestError).serverMessage).toBe('');
  });

  it('lets a network failure through untouched, for the page to translate', async () => {
    const networkError = new TypeError('Failed to fetch');
    const fetchImpl = jest.fn().mockRejectedValue(networkError);

    await expect(fetchPreviewIndex('job-1', 'deck.pptx', 'translated', { fetchImpl }))
      .rejects.toBe(networkError);
  });
});
