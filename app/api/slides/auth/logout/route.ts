/**
 * Proxy: Clear stored Google credentials
 */
import { NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';

export async function POST() {
  try {
    const response = await fetch(`${PYTHON_BACKEND_URL}/api/slides/auth/logout`, {
      method: 'POST',
    });
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Slides logout error:', error);
    return NextResponse.json({ status: 'error' }, { status: 500 });
  }
}
