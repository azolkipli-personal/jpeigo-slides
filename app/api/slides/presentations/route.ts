/**
 * Proxy: List Google Slides presentations from Drive
 */
import { NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';

export async function GET() {
  try {
    const response = await fetch(`${PYTHON_BACKEND_URL}/api/slides/presentations`);
    if (!response.ok) {
      const error = await response.text();
      if (response.status === 401) {
        return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
      }
      return NextResponse.json({ error: `Backend error: ${error}` }, { status: response.status });
    }
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('List presentations error:', error);
    return NextResponse.json({ error: 'Failed to list presentations' }, { status: 500 });
  }
}
