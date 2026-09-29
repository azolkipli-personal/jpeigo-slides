/**
 * One-way gate between the two callers that both want the Python backend's
 * `POST /api/export` for the same job at the same time: a user's Download and
 * the preview route (which exports the deck it is about to render).
 *
 * Direction matters, and it is deliberate:
 *
 * - **Downloads never wait.** `beginExport()` only records that an export is
 *   running; it blocks on nothing. The acceptance rule is that a download must
 *   not be delayed by a preview in flight, and a preview can run for tens of
 *   seconds, so letting an export queue behind one would put the 524 back.
 * - **Previews wait.** The preview calls `whenExportsIdle()` before it asks the
 *   backend to build a deck, so it never starts an export while a download is
 *   in flight — the two would otherwise inject into the same job concurrently.
 *
 * The state lives on `globalThis`, not in a module variable: Next bundles each
 * route handler separately, so a module-level `let` would be a different copy
 * per route and the two sides would never see each other. One Node process per
 * `next start` is what makes the global shared; if handlers ever move to
 * separate processes this degrades to "the gate does nothing", never to a
 * blocked download.
 */

type GateState = {
  /** Exports currently holding the gate. */
  active: number;
  /** Preview-side continuations to wake when `active` reaches 0. */
  idleWaiters: Array<() => void>;
};

const STATE_KEY = '__jpeigoExportGate';

function gateState(): GateState {
  const g = globalThis as unknown as { [STATE_KEY]?: GateState };
  if (!g[STATE_KEY]) {
    g[STATE_KEY] = { active: 0, idleWaiters: [] };
  }
  return g[STATE_KEY] as GateState;
}

/**
 * Mark an export as in flight. Returns the release function; call it exactly
 * once, in a `finally`, or previews will wait forever for an export that has
 * already finished.
 */
export function beginExport(): () => void {
  const s = gateState();
  s.active += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    s.active -= 1;
    if (s.active <= 0) {
      s.active = 0;
      const waiters = s.idleWaiters;
      s.idleWaiters = [];
      for (const wake of waiters) wake();
    }
  };
}

/** Resolves once no export is in flight (immediately, if none is). */
export function whenExportsIdle(): Promise<void> {
  const s = gateState();
  if (s.active === 0) return Promise.resolve();
  return new Promise<void>((resolve) => {
    s.idleWaiters.push(resolve);
  });
}
