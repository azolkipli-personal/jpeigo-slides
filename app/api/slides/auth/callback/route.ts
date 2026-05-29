/**
 * Proxy: Handle Google OAuth callback
 * Called by Google after user consents — redirect URL points here.
 */
import { NextRequest, NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8002';

export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get('code');
  const error = request.nextUrl.searchParams.get('error');

  if (error) {
    return NextResponse.redirect(new URL('/translator?auth_error=' + error, request.url));
  }

  if (!code) {
    return NextResponse.redirect(new URL('/translator?auth_error=no_code', request.url));
  }

  try {
    const response = await fetch(`${PYTHON_BACKEND_URL}/api/slides/auth/callback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    });

    if (!response.ok) {
      return NextResponse.redirect(new URL('/translator?auth_error=exchange_failed', request.url));
    }

    // Redirect back to translator page — frontend will check auth status
    return NextResponse.redirect(new URL('/translator?auth=success', request.url));
  } catch (error) {
    console.error('Slides auth callback error:', error);
    return NextResponse.redirect(new URL('/translator?auth_error=server_error', request.url));
  }
}
