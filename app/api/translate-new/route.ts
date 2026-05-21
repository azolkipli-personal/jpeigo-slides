/**
 * Proxy API route for translation.
 * Forwards to Python FastAPI backend.
 */
import { NextRequest, NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    // Forward to Python backend
    const response = await fetch(`${PYTHON_BACKEND_URL}/api/translate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const error = await response.text();
      return NextResponse.json(
        { error: `Translation error: ${error}` },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);

  } catch (error) {
    console.error('Translate proxy error:', error);
    return NextResponse.json(
      { error: 'Failed to communicate with translation service' },
      { status: 500 }
    );
  }
}