/**
 * Proxy: Extract text from a Google Slides presentation
 */
import { NextRequest, NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  try {
    const response = await fetch(`${PYTHON_BACKEND_URL}/api/slides/read/${encodeURIComponent(id)}`);
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
    console.error('Read presentation error:', error);
    return NextResponse.json({ error: 'Failed to read presentation' }, { status: 500 });
  }
}
