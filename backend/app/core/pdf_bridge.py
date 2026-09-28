"""PDF <-> PPTX conversion through LibreOffice — the PDF bridge.

The whole app (extractor, coalescing, injector, font scaling, cache, QA, job
store) is built on one PPTX pipeline. A PDF upload therefore converts to a PPTX
once at upload time and everything downstream runs unchanged; the exported deck
converts back to PDF at download time. Writing a second, PDF-native path would
duplicate all of that and lose formatting fidelity for nothing.

Both conversions invoke soffice the way `app.qa.render` already does:

* an absolute binary path — the systemd *user* unit's PATH is not guaranteed to
  contain /usr/bin, so a bare `soffice` reports "not installed" on a machine
  where it works in a terminal;
* a **private profile** (`-env:UserInstallation=...`) inside a fresh temp dir —
  the app converts decks concurrently (preview route, QA renders), and a shared
  default profile makes concurrent invocations fail or silently attach to a
  running instance.

Honest limit: the intermediate PPTX is LibreOffice's *reconstruction* of the
PDF. Text position and content survive (backend/tests/pdf_bridge_probe.sh);
vector graphics, tables drawn as images and exotic fonts may shift or rasterize
versus the original PDF. Do not claim otherwise.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.qa.render import soffice_path

# Bounded so a wedged LibreOffice cannot pin an upload/export request open.
SOFFICE_TIMEOUT = 120

# Impress's PDF import filter: without it LibreOffice guesses, and some builds
# land the import in Draw with different object semantics.
PDF_IMPORT_FILTER = 'impress_pdf_import'


class PdfBridgeError(RuntimeError):
    """A conversion failed. `status_code` is the HTTP status the API should answer.

    Raised instead of letting subprocess errors surface as bare tracebacks: the
    caller turns this into an HTTPException with a message a user can act on.
    """

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


def _stderr_tail(data, limit: int = 400) -> str:
    text = (data or b'').decode('utf-8', errors='replace') if isinstance(data, bytes) else (data or '')
    text = text.strip()
    return text[-limit:]


def _run_soffice(cmd: list[str], *, timeout: float, source: Path) -> subprocess.CompletedProcess:
    """Run one soffice command, mapping every failure to a PdfBridgeError."""
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PdfBridgeError(
            f'LibreOffice timed out after {timeout:g}s while converting {source.name}',
            status_code=504,
        ) from None
    except OSError as exc:
        # soffice resolved but could not be executed (permissions, gone binary).
        raise PdfBridgeError(
            f'could not run LibreOffice to convert {source.name}: {exc}',
            status_code=503,
        ) from None


def _require_soffice() -> str:
    binary = soffice_path()
    if not binary:
        raise PdfBridgeError(
            'LibreOffice (soffice) is not installed — PDF conversion is unavailable',
            status_code=503,
        )
    return binary


def pdf_to_pptx(pdf_path, workdir, timeout: float = SOFFICE_TIMEOUT) -> Path:
    """Convert `pdf_path` into `<workdir>/<name>.pdf.pptx` and return that path.

    The result is named after the *whole* source filename (deck.pdf ->
    deck.pdf.pptx) so a stored PDF and its intermediate can never be confused
    for each other in the upload directory. The conversion happens in a private
    temp dir and is moved into `workdir` only on success, so a failed conversion
    leaves no half-written deck behind.
    """
    pdf = Path(pdf_path)
    workdir = Path(workdir)
    soffice = _require_soffice()
    if not pdf.exists():
        raise PdfBridgeError(f'PDF to convert not found: {pdf}')

    tmp = Path(tempfile.mkdtemp(prefix='pdf-bridge-'))
    # Private profile inside the per-call temp dir: unique per invocation, so
    # concurrent conversions (preview, QA, parallel uploads) never share state.
    profile = tmp / f'lo_{os.getpid()}'
    try:
        profile.mkdir(parents=True, exist_ok=True)
        cmd = [
            soffice, f'-env:UserInstallation=file://{profile}', '--headless',
            f'--infilter={PDF_IMPORT_FILTER}',
            '--convert-to', 'pptx', '--outdir', str(tmp), str(pdf),
        ]
        result = _run_soffice(cmd, timeout=timeout, source=pdf)
        if result.returncode != 0:
            raise PdfBridgeError(
                f'LibreOffice could not convert {pdf.name} to PPTX: '
                f'{_stderr_tail(result.stderr) or f"exit code {result.returncode}"}'
            )
        produced = tmp / f'{pdf.stem}.pptx'
        if not produced.exists():
            candidates = sorted(tmp.glob('*.pptx'))
            if not candidates:
                raise PdfBridgeError(f'LibreOffice produced no PPTX for {pdf.name}')
            produced = candidates[0]
        target = workdir / f'{pdf.name}.pptx'
        workdir.mkdir(parents=True, exist_ok=True)
        # move, not replace: the temp dir may be on another filesystem
        shutil.move(str(produced), str(target))
        return target
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def pptx_to_pdf(pptx_path, workdir, timeout: float = SOFFICE_TIMEOUT) -> Path:
    """Convert `pptx_path` into `<workdir>/<stem>.pdf` and return that path.

    `workdir` is where the finished PDF lands (the caller owns it); the private
    profile lives in a separate temp dir that is always removed.
    """
    pptx = Path(pptx_path)
    workdir = Path(workdir)
    soffice = _require_soffice()
    if not pptx.exists():
        raise PdfBridgeError(f'PPTX to convert not found: {pptx}')

    workdir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='pdf-bridge-'))
    profile = tmp / f'lo_{os.getpid()}'
    try:
        profile.mkdir(parents=True, exist_ok=True)
        cmd = [
            soffice, f'-env:UserInstallation=file://{profile}', '--headless',
            '--convert-to', 'pdf', '--outdir', str(workdir), str(pptx),
        ]
        result = _run_soffice(cmd, timeout=timeout, source=pptx)
        if result.returncode != 0:
            raise PdfBridgeError(
                f'LibreOffice could not convert {pptx.name} to PDF: '
                f'{_stderr_tail(result.stderr) or f"exit code {result.returncode}"}'
            )
        produced = workdir / f'{pptx.stem}.pdf'
        if not produced.exists():
            candidates = sorted(workdir.glob(f'{pptx.stem}*.pdf'))
            if not candidates:
                raise PdfBridgeError(f'LibreOffice produced no PDF for {pptx.name}')
            produced = candidates[0]
        return produced
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
