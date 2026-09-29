/**
 * Run one conversion tool as a child process without blocking the event loop.
 *
 * This exists because the preview route used `execSync` for LibreOffice and
 * pdftoppm: while either ran, *every* other request through the Next server —
 * the user's Download among them — waited on it, which is how a healthy
 * backend still produced a Cloudflare 524. `spawn` + a promise keeps the loop
 * free, the timer guarantees a request can never hang forever, and every exit
 * path yields a message that names the step that died.
 *
 * Arguments are passed as an array, so nothing here goes through a shell — the
 * paths involved (job ids, work directories) are client-influenced.
 */
import { spawn } from 'child_process';

export function runCommand(file: string, args: string[], timeoutMs: number, label: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(file, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let stderr = '';
    let timedOut = false;
    let settled = false;

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGTERM');
      setTimeout(() => { try { child.kill('SIGKILL'); } catch { /* already gone */ } }, 5_000).unref();
    }, timeoutMs);

    const settle = (finish: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      finish();
    };

    child.stderr?.on('data', (chunk: Buffer) => {
      if (stderr.length < 4096) stderr += chunk.toString();
    });
    child.stdout?.on('data', () => { /* converted output goes to the outdir, not stdout */ });

    child.on('error', (err) => {
      settle(() => reject(new Error(`${label} could not start: ${err.message}`)));
    });
    child.on('close', (code, signal) => {
      settle(() => {
        if (timedOut) {
          reject(new Error(`${label} timed out after ${Math.round(timeoutMs / 1000)}s`));
        } else if (code === 0) {
          resolve();
        } else {
          const tail = stderr.trim().slice(-400);
          reject(new Error(`${label} failed (exit ${code ?? signal ?? 'unknown'})${tail ? `: ${tail}` : ''}`));
        }
      });
    });
  });
}
