/**
 * Proxy: Check Google authentication status
 */
import { NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';

export async function GET() {
  try {
    const response = await fetch(`${PYTHON_BACKEND_URL}/api/slides/auth/status`);
    if (!response.ok) {
      return NextResponse.json({ authenticated: false });
    }
    const data = await response.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ authenticated: false });
  }
}
