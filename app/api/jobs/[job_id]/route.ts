/**
 * Proxy API route for job status polling.
 * Forwards to Python FastAPI backend GET /api/jobs/{job_id}.
 *
 * Two consumers pull on this route and they need different things:
 *  - the progress poll runs every 2s while a translation is in flight and only
 *    needs status/progress/total_runs;
 *  - restore (page reload) rebuilds the whole editor from one response, so it
 *    needs the extracted slides and the translated runs.
 * Sending runs on every poll would push thousands of runs over the wire, so the
 * full record is opt-in via `?full=1`.
 */
import { NextRequest, NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ job_id: string }> }
) {
  const { job_id } = await params;
  try {
    const res = await fetch(`${PYTHON_BACKEND_URL}/api/jobs/${encodeURIComponent(job_id)}`, {
      cache: 'no-store',
    });
    if (!res.ok) {
      return NextResponse.json({ error: 'Job not found' }, { status: res.status });
    }
    const data = await res.json();

    if (request.nextUrl.searchParams.get('full') === '1') {
      const slides = Array.isArray(data.slides) ? data.slides : [];
      return NextResponse.json({
        job_id: data.job_id,
        filename: data.filename,
        status: data.status,
        progress: data.progress,
        total_runs: data.total_runs,
        total_slides: slides.length,
        slides,
        translated_runs: data.translated_runs ?? [],
        error: data.error ?? null,
      });
    }

    // Only expose lightweight status fields
    return NextResponse.json({
      status: data.status,
      progress: data.progress,
      total_runs: data.total_runs,
    });
  } catch {
    return NextResponse.json({ error: 'Backend unavailable' }, { status: 502 });
  }
}
