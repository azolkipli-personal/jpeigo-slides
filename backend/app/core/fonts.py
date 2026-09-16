"""Font availability checks for the preview renderer.

The injector writes `JP_FONT_FAMILY` into the East-Asian and complex-script slots
of every translated run, and the frontend renders previews by asking LibreOffice
for a PDF. When that family is missing on the machine doing the rendering,
fontconfig substitutes another face and *nothing says so* — the preview looks
fine while showing a different typeface than the file requests. That is how
"Yu Gothic" silently became Noto on this server.

`resolve_family()` asks fontconfig what a name really resolves to;
`check_jp_font()` turns that into a fact the app can log and expose.
"""
import os
import shutil
import subprocess

# Family written into translated runs — keep in step with injector.JP_FONT_FAMILY.
DEFAULT_JP_FONT = 'Yu Gothic'

# fc-match lives in /usr/sbin on Fedora, which is not on a systemd *user* unit's PATH
# (the backend unit's PATH is the venv plus ~/.config). Relying on a bare name meant
# the check reported "cannot verify" on a machine where fc-match works fine, so the
# absolute locations are tried as well.
FC_MATCH_CANDIDATES = ('fc-match', '/usr/sbin/fc-match', '/usr/bin/fc-match')


def _fc_match_binary() -> str | None:
    """Path to fc-match, or None if this machine really has no fontconfig."""
    for candidate in FC_MATCH_CANDIDATES:
        if candidate.startswith('/'):
            if os.path.exists(candidate):
                return candidate
            continue
        found = shutil.which(candidate)
        if found:
            return found
    return None


def configured_jp_font() -> str:
    return os.environ.get('JP_FONT_FAMILY', DEFAULT_JP_FONT)


def resolve_family(family: str, timeout: float = 5.0) -> str | None:
    """Family fontconfig actually resolves `family` to, or None if fc-match is absent."""
    binary = _fc_match_binary()
    if binary is None:
        return None
    try:
        result = subprocess.run(
            [binary, '-f', '%{family}', family],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    return (result.stdout or '').strip() or None


def check_jp_font(family: str | None = None) -> dict:
    """Report whether the configured Japanese family is really installed.

    fontconfig returns every name of a matched face as a comma-separated list
    ("Yu Gothic,游ゴシック"), and either the English or the localized name counts as
    installed — the deck may ask for either. `substituted=True` is the case worth
    reporting: the renderer will show a different face than the file names.
    """
    requested = family or configured_jp_font()
    resolved = resolve_family(requested)
    if resolved is None:
        return {
            'requested': requested,
            'resolved': None,
            'available': None,
            'substituted': None,
            'detail': 'fc-match unavailable — cannot verify',
        }
    names = [name.strip().lower() for name in resolved.split(',')]
    available = requested.strip().lower() in names
    return {
        'requested': requested,
        'resolved': resolved,
        'available': available,
        'substituted': not available,
        'detail': 'installed' if available else f'renderer substitutes {resolved}',
    }
