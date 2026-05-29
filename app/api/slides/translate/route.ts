/**
 * Proxy: Translate a Google Slides presentation end-to-end
 */
import { NextRequest, NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { presentation_id, source_language, target_language, model, context, new_title } = body;

    if (!presentation_id) {
      return NextResponse.json({ error: 'presentation_id is required' }, { status: 400 });
    }

    const response = await fetch(`${PYTHON_BACKEND_URL}/api/slides/translate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        presentation_id,
        source_language: source_language || 'ja',
        target_language: target_language || 'en',
        model: model || 'gemini-flash-lite',
        context: context || null,
        new_title: new_title || null,
      }),
    });

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
    console.error('Slides translate error:', error);
    return NextResponse.json({ error: 'Failed to translate presentation' }, { status: 500 });
  }
}
