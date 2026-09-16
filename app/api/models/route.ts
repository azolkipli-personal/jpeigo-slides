/**
 * Model catalog.
 *
 * Proxies the backend's /api/models so the picker never carries its own copy of
 * the list. The previous hardcoded list had drifted from the registry behind it
 * (it still offered "Kimi K2.5" and "DeepSeek V4", neither of which exists), so a
 * chosen label and the model actually used could disagree.
 */
import { NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';

export async function GET() {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (process.env.BACKEND_API_KEY) {
    headers['X-API-Key'] = process.env.BACKEND_API_KEY;
  }

  try {
    const response = await fetch(`${PYTHON_BACKEND_URL}/api/models`, {
      method: 'GET',
      headers,
      cache: 'no-store',
    });
    if (!response.ok) {
      return NextResponse.json({ error: 'model catalog unavailable' }, { status: 502 });
    }
    return NextResponse.json(await response.json());
  } catch (error) {
    return NextResponse.json(
      { error: `model catalog unreachable: ${(error as Error).message}` },
      { status: 502 },
    );
  }
}
