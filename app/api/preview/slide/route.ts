/**
 * Slide preview — image endpoint.
 *
 * One request, one PNG. The index route hands out these URLs and the viewer
 * fetches only the slide it is showing, so a deck of any size costs the client
 * one screenful of images instead of a multi-megabyte JSON blob, and navigation
 * is on demand.
 *
 * The file comes straight from the shared disk cache, so a slide that has been
 * rendered once is served for the hour the cache lives without touching
 * LibreOffice or the backend again.
 */
import { NextRequest, NextResponse } from 'next/server';
import { readFile } from 'fs/promises';
import {
  MAX_SLIDES, type DeckKind, cacheKeyFor, isSafeJobId, parseDeckKind, resolveSlideFile,
} from '@/lib/previewStore';

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;

  const jobId = params.get('job_id');
  if (!jobId) {
    return NextResponse.json({ error: 'job_id is required' }, { status: 400 });
  }
  if (!isSafeJobId(jobId)) {
    return NextResponse.json({ error: 'job_id is not a valid job identifier' }, { status: 400 });
  }

  const kind: DeckKind = parseDeckKind(params.get('which'));

  const raw = params.get('n');
  const n = Number(raw);
  if (!raw || !Number.isInteger(n) || n < 1 || n > MAX_SLIDES) {
    return NextResponse.json(
      { error: `n must be a slide number between 1 and ${MAX_SLIDES}` },
      { status: 400 },
    );
  }

  const file = resolveSlideFile(cacheKeyFor(jobId, kind), n);
  if (!file) {
    return NextResponse.json(
      { error: 'No such slide in this preview (generate the preview first)' },
      { status: 404 },
    );
  }

  try {
    const data = await readFile(file);
    return new NextResponse(new Uint8Array(data), {
      headers: {
        'Content-Type': 'image/png',
        'Content-Length': String(data.byteLength),
        // The deck behind a key is immutable for the life of the cache, so the
        // browser can reuse a slide the user has already paged past.
        'Cache-Control': 'private, max-age=3600',
        'X-Slide-Number': String(n),
        'X-Slide-Which': kind,
      },
    });
  } catch {
    return NextResponse.json({ error: 'Slide image could not be read' }, { status: 404 });
  }
}
