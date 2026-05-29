/**
 * Proxy API route to Python FastAPI backend.
 * Uploads PPTX and returns extracted text runs.
 */
import { NextRequest, NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';
const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100MB
const UPLOAD_TIMEOUT = 120_000; // 120s for large files

export async function POST(request: NextRequest) {
  try {
    // Check content-length header early
    const contentLength = request.headers.get('content-length');
    if (contentLength && parseInt(contentLength) > MAX_FILE_SIZE) {
      return NextResponse.json(
        { error: `File too large. Maximum size is 100MB` },
        { status: 413 }
      );
    }

    const formData = await request.formData();
    const file = formData.get('file') as File;

    if (!file) {
      return NextResponse.json(
        { error: 'No file provided' },
        { status: 400 }
      );
    }

    // Check actual file size
    if (file.size > MAX_FILE_SIZE) {
      return NextResponse.json(
        { error: `File too large. Maximum size is 100MB` },
        { status: 413 }
      );
    }

    // Forward to Python backend with timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT);

    try {
      const pythonFormData = new FormData();
      pythonFormData.append('file', file);

      const response = await fetch(`${PYTHON_BACKEND_URL}/api/upload`, {
        method: 'POST',
        body: pythonFormData,
        signal: controller.signal,
      });

      if (!response.ok) {
        const error = await response.text();
        return NextResponse.json(
          { error: error.includes('File too large') ? error : `Upload failed: ${error}` },
          { status: response.status }
        );
      }

      const data = await response.json();
      return NextResponse.json(data);
    } finally {
      clearTimeout(timeoutId);
    }

  } catch (error) {
    console.error('Upload proxy error:', error);
    const message = error instanceof Error ? error.message : 'Upload failed';
    
    // Check for abort (timeout)
    if (error instanceof DOMException && error.name === 'AbortError') {
      return NextResponse.json(
        { error: 'Upload timed out. The file may be too large or the connection is slow.' },
        { status: 408 }
      );
    }

    return NextResponse.json(
      { error: `${message}. Make sure the Python backend is running on port 8002.` },
      { status: 500 }
    );
  }
}

// Increase body size limit for Next.js
export const config = {
  api: {
    bodyParser: false,
  },
};
