/**
 * Slide check (vision QA).
 *
 * Proxies the backend's slide check. Opt-in and report-only: the pass renders the
 * translated deck and asks a vision model what looks broken, and the report comes back
 * here to be displayed. It never edits the deck or blocks an export.
 *
 * POST starts a check and returns immediately; GET polls it. The pass is minutes long
 * (one vision call per slide), so holding one request open would just hand the run to a
 * gateway timeout — and the polling shape shows findings as slides land.
 *
 * The model is passed through unchanged from the picker (which is fed by /api/models).
 * The backend rejects a model that cannot read images rather than letting it invent
 * layout findings.
 */
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const maxDuration = 300;

export async function POST(request: NextRequest) {
  const backend = process.env.PYTHON_BACKEND_URL || 'http://127.0.0.1:8002';

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid JSON body' }, { status: 400 });
  }

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (process.env.BACKEND_API_KEY) headers['X-API-Key'] = process.env.BACKEND_API_KEY;

  try {
    const res = await fetch(`${backend}/api/qa/vision/start`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });

    const text = await res.text();
    if (!res.ok) {
      return NextResponse.json({ error: extractDetail(text) }, { status: res.status });
    }
    return NextResponse.json(JSON.parse(text), { status: 202 });
  } catch (error) {
    return NextResponse.json(
      { error: `slide check unreachable: ${error instanceof Error ? error.message : 'unknown'}` },
      { status: 502 },
    );
  }
}

/** Progress of a running check, including the report so far. Never cached. */
export async function GET(request: NextRequest) {
  const backend = process.env.PYTHON_BACKEND_URL || 'http://127.0.0.1:8002';
  const jobId = request.nextUrl.searchParams.get('job_id');
  const which = request.nextUrl.searchParams.get('which') || 'translated';
  if (!jobId) {
    return NextResponse.json({ error: 'job_id is required' }, { status: 400 });
  }

  const headers: Record<string, string> = {};
  if (process.env.BACKEND_API_KEY) headers['X-API-Key'] = process.env.BACKEND_API_KEY;

  try {
    const res = await fetch(
      `${backend}/api/qa/vision/status?job_id=${encodeURIComponent(jobId)}&which=${encodeURIComponent(which)}`,
      { headers, cache: 'no-store' },
    );
    const text = await res.text();
    if (!res.ok) {
      return NextResponse.json({ error: extractDetail(text) }, { status: res.status });
    }
    return NextResponse.json(JSON.parse(text), { status: 200, headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    return NextResponse.json(
      { error: `slide check unreachable: ${error instanceof Error ? error.message : 'unknown'}` },
      { status: 502 },
    );
  }
}

/** FastAPI puts the reason in `detail`; surface it instead of a generic 502. */
function extractDetail(raw: string): string {
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed?.detail === 'string') return parsed.detail;
    if (typeof parsed?.error === 'string') return parsed.error;
  } catch {
    /* not JSON — fall through to the raw text */
  }
  return raw.slice(0, 300) || 'slide check failed';
}
