/**
 * Proxy API route to Python FastAPI backend.
 * Uploads PPTX and returns extracted text runs.
 */
import { NextRequest, NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get('file') as File;

    if (!file) {
      return NextResponse.json(
        { error: 'No file provided' },
        { status: 400 }
      );
    }

    // Forward to Python backend
    const pythonFormData = new FormData();
    pythonFormData.append('file', file);

    const response = await fetch(`${PYTHON_BACKEND_URL}/api/upload`, {
      method: 'POST',
      body: pythonFormData,
    });

    if (!response.ok) {
      const error = await response.text();
      return NextResponse.json(
        { error: `Python backend error: ${error}` },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);

  } catch (error) {
    console.error('Upload proxy error:', error);
    return NextResponse.json(
      { error: 'Failed to communicate with Python backend. Make sure it is running on http://localhost:8000' },
      { status: 500 }
    );
  }
}