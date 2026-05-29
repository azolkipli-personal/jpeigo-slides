/**
 * Proxy: Get Google OAuth authorization URL
 */
import { NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';

export async function GET() {
  try {
    const response = await fetch(`${PYTHON_BACKEND_URL}/api/slides/auth/url`);
    if (!response.ok) {
      const error = await response.text();
      return NextResponse.json({ error: `Backend error: ${error}` }, { status: response.status });
    }
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Slides auth URL error:', error);
    return NextResponse.json({ error: 'Failed to get auth URL' }, { status: 500 });
  }
}
