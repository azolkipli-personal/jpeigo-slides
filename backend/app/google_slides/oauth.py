"""
Google OAuth 2.0 for Web Application Flow
===========================================
Handles authorization code flow for Google Slides API access.

Flow:
  1. Browser redirects to Google consent screen (via get_auth_url)
  2. Google redirects back with ?code=... (via callback endpoint)
  3. Backend exchanges code for refresh + access tokens
  4. Tokens stored in a JSON file for reuse
  5. get_credentials() loads stored creds (auto-refreshes if expired)
"""
import json
import os
import logging
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

# File where we persist the user's OAuth tokens
TOKEN_FILE = Path(__file__).parent.parent.parent / ".slides_token.json"

# Required scopes for Google Slides + broader access
# Include common gog scopes since Google merges previously-granted scopes
SCOPES = [
    "https://www.googleapis.com/auth/presentations",      # read/write slides
    "https://www.googleapis.com/auth/drive.file",          # create & access files app creates
    "https://www.googleapis.com/auth/drive.readonly",      # list presentations
    "https://www.googleapis.com/auth/drive",               # full drive access (gog)
    "https://www.googleapis.com/auth/gmail.readonly",      # gog
    "https://www.googleapis.com/auth/gmail.modify",        # gog
    "https://www.googleapis.com/auth/gmail.send",          # gog
    "https://www.googleapis.com/auth/gmail.settings.basic",# gog
    "https://www.googleapis.com/auth/gmail.settings.sharing",# gog
    "https://www.googleapis.com/auth/calendar",            # gog
    "https://www.googleapis.com/auth/contacts.readonly",   # gog
    "https://www.googleapis.com/auth/chat.spaces",         # gog
    "https://www.googleapis.com/auth/chat.messages",       # gog
    "https://www.googleapis.com/auth/chat.memberships",    # gog
    "https://www.googleapis.com/auth/chat.users.readstate.readonly",# gog
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

from app.config import get_settings

# Where Google will redirect the user after consent
_settings = get_settings()
REDIRECT_URI = _settings.google_slides_redirect_uri or "http://localhost:3002/api/slides/auth/callback"


def get_client_config() -> dict:
    """
    Load OAuth client configuration.
    
    Looks for GOOGLE_OAUTH_CLIENT_CONFIG env var (JSON string) or
    a client_secret.json file in the backend directory.
    """
    env_config = os.environ.get("GOOGLE_OAUTH_CLIENT_CONFIG")
    if env_config:
        try:
            return json.loads(env_config)
        except json.JSONDecodeError:
            logger.error("GOOGLE_OAUTH_CLIENT_CONFIG is not valid JSON")
    
    # Fallback: look for client_secret.json in backend directory
    secrets_path = Path(__file__).parent.parent.parent / "client_secret.json"
    if secrets_path.exists():
        with open(secrets_path) as f:
            return json.load(f)
    
    raise RuntimeError(
        "Google OAuth not configured. "
        "Set GOOGLE_OAUTH_CLIENT_CONFIG env var or place client_secret.json "
        "in the backend/ directory.\n\n"
        "To get credentials:\n"
        "1. Go to https://console.cloud.google.com/apis/credentials\n"
        "2. Create OAuth 2.0 Client ID → Web application\n"
        "3. Add redirect URI: http://localhost:3002/api/slides/auth/callback\n"
        "4. Download JSON and save as backend/client_secret.json\n"
        "   OR paste the JSON into GOOGLE_OAUTH_CLIENT_CONFIG env var"
    )


def get_auth_url() -> str:
    """
    Generate the Google OAuth authorization URL.
    Returns the URL the browser should redirect to.
    """
    client_config = get_client_config()
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI
    
    # Disable PKCE for local single-user app (stateless OAuth flow)
    flow.autogenerate_code_verifier = False
    flow.code_verifier = None
    
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # Force to get refresh_token every time
    )
    return auth_url


def handle_callback(authorization_code: str) -> dict:
    """
    Exchange the authorization code for tokens.
    Stores the tokens and returns user info.
    """
    client_config = get_client_config()
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI
    
    # Must match auth URL: no PKCE verifier
    flow.autogenerate_code_verifier = False
    flow.code_verifier = None
    
    flow.fetch_token(code=authorization_code)
    credentials = flow.credentials
    
    # Persist tokens
    save_credentials(credentials)
    
    return {
        "authenticated": True,
        "email": getattr(credentials, "id_token", None) or "unknown",
    }


def get_credentials() -> Optional[Credentials]:
    """
    Load stored credentials. Auto-refreshes if expired.
    Returns None if no stored credentials or refresh failed.
    """
    if not TOKEN_FILE.exists():
        return None
    
    try:
        with open(TOKEN_FILE) as f:
            token_data = json.load(f)
        
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        
        # Auto-refresh if expired
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            save_credentials(creds)  # Save refreshed tokens
            return creds
        
        return creds
        
    except Exception as e:
        logger.warning(f"Failed to load credentials: {e}")
        return None


def save_credentials(credentials: Credentials):
    """Persist credentials to disk as JSON."""
    token_data = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes,
        "id_token": getattr(credentials, "id_token", None),
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)
    logger.info(f"Credentials saved to {TOKEN_FILE}")


def is_authenticated() -> bool:
    """Check if we have valid stored credentials."""
    creds = get_credentials()
    return creds is not None and creds.valid


def clear_credentials():
    """Remove stored tokens (logout)."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        logger.info("Credentials cleared")
