/**
 * Health check endpoint.
 * Proxies to Python FastAPI backend health.
 */
import { NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';

export async function GET() {
  try {
    const response = await fetch(`${PYTHON_BACKEND_URL}/api/health`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      return NextResponse.json(
        { status: 'degraded', detail: 'Python backend unreachable' },
        { status: 200 }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { status: 'degraded', detail: 'Python backend unreachable' },
      { status: 200 }
    );
  }
}
