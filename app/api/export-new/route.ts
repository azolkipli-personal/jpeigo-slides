/**
 * Proxy API route for exporting translated PPTX.
 * Forwards to Python FastAPI backend.
 */
import { NextRequest, NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { job_id, filename } = body;

    if (!job_id) {
      return NextResponse.json(
        { error: 'job_id is required' },
        { status: 400 }
      );
    }

    // Forward to Python backend
    const response = await fetch(`${PYTHON_BACKEND_URL}/api/export`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ job_id, filename }),
    });

    if (!response.ok) {
      const error = await response.text();
      // A job record that no longer exists (cleared store, expired session)
      // used to surface as raw JSON: Export error: {"detail":"Job not found"}.
      // Nothing there tells the user what to do, so say it.
      if (response.status === 404) {
        return NextResponse.json(
          {
            error:
              'This session is no longer on the server (its job was cleared), so there is nothing to export. Re-upload the file and translate again.',
          },
          { status: 404 }
        );
      }
      let detail = error;
      try {
        detail = (JSON.parse(error) as { detail?: string })?.detail ?? error;
      } catch {
        /* not JSON — keep the raw text */
      }
      return NextResponse.json(
        { error: `Export error: ${detail}` },
        { status: response.status }
      );
    }

    // Get the binary PPTX file
    const arrayBuffer = await response.arrayBuffer();

    // Content-Disposition header must be ASCII. For non-ASCII (e.g. Japanese)
    // filenames, use RFC 5987 filename*=UTF-8''encoding with an ASCII fallback,
    // otherwise Next.js throws "Cannot convert argument to a ByteString" -> 500.
    const asciiFallback = 'translated.pptx';
    const encodedFilename = encodeURIComponent(filename || asciiFallback);
    const contentDisposition = `attachment; filename="${asciiFallback}"; filename*=UTF-8''${encodedFilename}`;

    return new NextResponse(arrayBuffer, {
      status: 200,
      headers: {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'Content-Disposition': contentDisposition,
        // Injection failures are reported by the backend as headers (the body is
        // the PPTX). Re-emit them or the UI can never see a partial export.
        ...(response.headers.get('X-Injection-Failed')
          ? {
              'X-Injection-Failed': response.headers.get('X-Injection-Failed') as string,
              'X-Injection-Total': response.headers.get('X-Injection-Total') as string,
            }
          : {}),
      },
    });

  } catch (error) {
    console.error('Export proxy error:', error);
    return NextResponse.json(
      { error: 'Failed to export file' },
      { status: 500 }
    );
  }
}