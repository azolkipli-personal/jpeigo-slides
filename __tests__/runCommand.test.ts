/**
 * @jest-environment node
 *
 * Every preview conversion goes through this helper, and two properties of it
 * are load-bearing: a step that never finishes still finishes the request
 * (timeout, with a message that names the step), and a step that dies says so
 * instead of leaving the caller with a bare 500. Both are the difference
 * between a preview that reports why it failed and one that hangs until
 * Cloudflare gives up.
 */
import { runCommand } from '../lib/runCommand';

describe('runCommand', () => {
  it('resolves when the command exits cleanly', async () => {
    await expect(runCommand('true', [], 5_000, 'clean step')).resolves.toBeUndefined();
  });

  it('names the step and the exit code when the command fails', async () => {
    await expect(runCommand('false', [], 5_000, 'PDF rendering (pdftoppm)')).rejects.toThrow(
      'PDF rendering (pdftoppm) failed (exit 1)',
    );
  });

  it('kills a step that hangs, and says how long it was given', async () => {
    const startedAt = Date.now();
    await expect(runCommand('sleep', ['30'], 1_000, 'LibreOffice conversion (PPTX → PDF)')).rejects.toThrow(
      'LibreOffice conversion (PPTX → PDF) timed out after 1s',
    );
    // The 30 s child must not be waited out — the request has to return.
    expect(Date.now() - startedAt).toBeLessThan(5_000);
  });

  it('reports a command the machine does not have', async () => {
    await expect(
      runCommand('jpeigo-no-such-binary', [], 1_000, 'LibreOffice conversion (PPTX → PDF)'),
    ).rejects.toThrow('LibreOffice conversion (PPTX → PDF) could not start');
  });

  it('passes arguments without a shell', async () => {
    // Through a shell `echo >` is a syntax error and would fail; as an
    // argument it prints a redirection character and exits 0 — so this pins
    // that nothing client-influenced is ever interpreted.
    await expect(runCommand('echo', ['>'], 5_000, 'echo')).resolves.toBeUndefined();
  });
});
