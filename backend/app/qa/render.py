"""Deck rendering for QA and previews: PPTX -> PDF -> PNG.

One code path renders decks for every consumer (before/after previews, Layer 2
vision QA) so a rendering change cannot fix one and silently miss the other. It
shells out to LibreOffice and pdftoppm — the same tools the preview route uses —
and reports *why* rendering is unavailable rather than returning an empty list,
because "no images" and "no renderer" are different problems.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

DEFAULT_DPI = 110

# soffice and pdftoppm live in /usr/sbin (symlinked from /usr/bin) on Fedora, and a
# systemd *user* unit does not inherit the login PATH — the backend unit's PATH is the
# venv plus ~/.config. A bare name therefore reported "not installed" on a machine
# where both are installed, so absolute locations are tried too.
BINARY_CANDIDATES = {
    'soffice': ('soffice', 'libreoffice', '/usr/bin/soffice', '/usr/sbin/soffice',
                '/usr/bin/libreoffice', '/usr/sbin/libreoffice'),
    'pdftoppm': ('pdftoppm', '/usr/bin/pdftoppm', '/usr/sbin/pdftoppm'),
}


class RenderError(RuntimeError):
    """Rendering is impossible here (missing tool) or the deck failed to convert."""


def _resolve(name: str) -> str | None:
    for candidate in BINARY_CANDIDATES[name]:
        if candidate.startswith('/'):
            if Path(candidate).exists():
                return candidate
            continue
        found = shutil.which(candidate)
        if found:
            return found
    return None


def soffice_path() -> str | None:
    return _resolve('soffice')


def pdftoppm_path() -> str | None:
    return _resolve('pdftoppm')


def render_available() -> bool:
    return bool(soffice_path() and pdftoppm_path())


def render_deck(pptx_path, dpi: int = DEFAULT_DPI, max_slides: int | None = None,
                first_slide: int | None = None, last_slide: int | None = None,
                timeout: int = 180) -> list[Path]:
    """Render slides of `pptx_path` to PNG, in slide order.

    `first_slide`/`last_slide` are absolute slide numbers passed to pdftoppm, which
    keeps numbering absolute — a range render of slides 7-9 yields files named for 7,
    8, 9, so a caller can chunk a long deck without losing the mapping to PowerPoint.
    `max_slides` applies after the range.

    Returns paths inside a fresh temporary directory; the caller owns that
    directory and is responsible for removing it (see `render_deck_files` for the
    common case of "I only need the images for this call").
    """
    pptx = Path(pptx_path)
    if not pptx.exists():
        raise RenderError(f'deck not found: {pptx}')
    soffice, pdftoppm = soffice_path(), pdftoppm_path()
    if not soffice or not pdftoppm:
        missing = ', '.join(n for n, p in (('soffice', soffice), ('pdftoppm', pdftoppm)) if not p)
        raise RenderError(f'cannot render slides: {missing} not installed')

    work = Path(tempfile.mkdtemp(prefix='qa-render-'))
    profile = work / 'lo-profile'  # separate profile: a running LibreOffice on the
    profile.mkdir()                # default profile makes --headless hang

    subprocess.run(
        [soffice, f'-env:UserInstallation=file://{profile}', '--headless',
         '--convert-to', 'pdf', '--outdir', str(work), str(pptx)],
        check=True, capture_output=True, timeout=timeout,
    )
    pdf = work / f'{pptx.stem}.pdf'
    if not pdf.exists():  # LibreOffice names the PDF after the file it was given
        candidates = list(work.glob('*.pdf'))
        if not candidates:
            raise RenderError(f'LibreOffice produced no PDF for {pptx.name}')
        pdf = candidates[0]

    page_range: list[str] = []
    if first_slide:
        page_range += ['-f', str(first_slide)]
    if last_slide:
        page_range += ['-l', str(last_slide)]
    subprocess.run(
        [pdftoppm, '-png', '-r', str(dpi), *page_range, str(pdf), str(work / 'slide')],
        check=True, capture_output=True, timeout=timeout,
    )

    pages = sorted(work.glob('slide-*.png'), key=lambda p: int(p.stem.split('-')[-1]))
    if not pages:
        raise RenderError(f'pdftoppm produced no pages for {pptx.name}')
    return pages[:max_slides] if max_slides else pages
