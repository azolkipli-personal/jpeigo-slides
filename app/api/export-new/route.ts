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
      return NextResponse.json(
        { error: `Export error: ${error}` },
        { status: response.status }
      );
    }

    // Get the binary PPTX file
    const arrayBuffer = await response.arrayBuffer();

    return new NextResponse(arrayBuffer, {
      status: 200,
      headers: {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'Content-Disposition': `attachment; filename="${filename || 'translated.pptx'}"`,
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