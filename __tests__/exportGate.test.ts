/**
 * @jest-environment node
 *
 * The gate between a user's Download and the preview's own backend export has
 * one hard rule and one deliberate asymmetry:
 *
 * - a preview must not run its export while a download is in flight, and
 * - a download must never wait for anything, because that is exactly how the
 *   524 happened.
 *
 * Both halves are pinned here; a symmetric mutex would still pass the first
 * property and fail the second.
 */
import { beginExport, whenExportsIdle } from '@/lib/exportGate';

const tick = () => Promise.resolve().then(() => Promise.resolve());

describe('export gate', () => {
  it('lets a preview through immediately when nothing is exporting', async () => {
    let resolved = false;
    void whenExportsIdle().then(() => { resolved = true; });
    await tick();
    expect(resolved).toBe(true);
  });

  it('holds a preview until every in-flight export has released', async () => {
    const releaseA = beginExport();
    const releaseB = beginExport();

    let resolved = false;
    const waiter = whenExportsIdle().then(() => { resolved = true; });

    await tick();
    expect(resolved).toBe(false);

    // One export finishing is not enough while another is still running.
    releaseA();
    await tick();
    expect(resolved).toBe(false);

    releaseB();
    await waiter;
    expect(resolved).toBe(true);
  });

  it('does not queue a new download behind the ones already running', () => {
    const releaseFirst = beginExport();
    const t0 = Date.now();
    const releaseSecond = beginExport();
    // beginExport has no await in it: a download starts on the spot.
    expect(Date.now() - t0).toBeLessThan(50);
    releaseFirst();
    releaseSecond();
  });

  it('wakes queued previews in step with the exports, not before', async () => {
    const releaseA = beginExport();
    const first = whenExportsIdle();
    let secondResolved = false;
    const second = whenExportsIdle().then(() => { secondResolved = true; });

    releaseA();
    await first;
    await tick();
    expect(secondResolved).toBe(true);

    // A stray second release must not drive the counter negative and leak a
    // preview that then waits forever.
    releaseA();
    await expect(whenExportsIdle()).resolves.toBeUndefined();

    const releaseB = beginExport();
    let blocked = true;
    void whenExportsIdle().then(() => { blocked = false; });
    await tick();
    expect(blocked).toBe(true);
    releaseB();
    await second;
    await tick();
    expect(blocked).toBe(false);
  });
});
