/**
 * Client half of the preview delivery contract.
 *
 * The index endpoint answers 202 while a deck renders in the background and
 * 200 with one URL per slide once it is cached, so this loop keeps every
 * request short: no call stays open for the length of a LibreOffice run, and
 * the images themselves are fetched one at a time by the viewer.
 *
 * Kept out of the page component because the page is already long and because
 * the polling rules (when to retry, which failure message a user should see)
 * are worth testing on their own.
 */

export type PreviewIndex = {
  images: string[];
  total?: number;
  cached?: boolean;
  which?: string;
  pending?: boolean;
};

/**
 * A failure the *server* explained. The page shows `serverMessage` when there
 * is one (a conversion timeout, a non-2xx from the backend) and otherwise
 * falls back to its own translated message — a dropped connection should not
 * surface to the user as a raw browser error string.
 */
export class PreviewRequestError extends Error {
  readonly serverMessage: string;

  constructor(serverMessage: string) {
    super(serverMessage || 'preview request failed');
    this.name = 'PreviewRequestError';
    this.serverMessage = serverMessage;
  }
}

const DEFAULT_POLL_MS = 1000;
const DEFAULT_MAX_ATTEMPTS = 240;

export async function fetchPreviewIndex(
  jobId: string,
  filename: string,
  which: 'translated' | 'original',
  options: { pollMs?: number; maxAttempts?: number; fetchImpl?: typeof fetch } = {},
): Promise<string[]> {
  const {
    pollMs = DEFAULT_POLL_MS,
    maxAttempts = DEFAULT_MAX_ATTEMPTS,
    fetchImpl = fetch,
  } = options;

  let data: PreviewIndex | null = null;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    if (attempt > 0) await new Promise((r) => setTimeout(r, pollMs));
    const res = await fetchImpl('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: jobId, filename, which }),
    });
    if (!res.ok) {
      const detail = (await res.json().catch(() => null)) as { error?: string } | null;
      throw new PreviewRequestError((detail?.error || '').trim());
    }
    data = (await res.json()) as PreviewIndex;
    if (!data?.pending) break;
  }

  if (!data || data.pending) {
    // The route caps a generation at ~2.5 minutes of conversion timeouts; if we
    // are still being told "pending" after that, stop asking.
    throw new PreviewRequestError('');
  }
  return data.images || [];
}
