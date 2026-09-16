/**
 * The version label shown in the app's wordmark lines.
 *
 * `next.config.ts` injects the raw `git describe` output at build time, so the
 * label names the build that is actually serving. `formatVersion` is kept pure
 * and separate from the constant so it can be unit tested.
 */

/**
 * Turn raw `git describe --tags --always --dirty` output into something worth
 * showing a human:
 *
 *   v1.4.0                     → v1.4.0            (built exactly at the tag)
 *   v1.4.0-3-g947a30d          → v1.4.0+3 (947a30d)  (three commits past it)
 *   v1.4.0-3-g947a30d-dirty    → v1.4.0+3 (947a30d) dirty
 *   947a30d                    → 947a30d           (no tag reachable)
 *   ""                         → ""                (no git: callers hide the label)
 */
export function formatVersion(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return '';
  const dirty = trimmed.endsWith('-dirty');
  const base = dirty ? trimmed.slice(0, -'-dirty'.length) : trimmed;
  const ahead = base.match(/^(v[\d.]+)-(\d+)-g([0-9a-f]+)$/);
  const version = ahead ? `${ahead[1]}+${ahead[2]} (${ahead[3]})` : base;
  return dirty ? `${version} dirty` : version;
}

/** Baked in by next.config.ts; empty when the build had no git to ask. */
export const APP_VERSION = formatVersion(process.env.NEXT_PUBLIC_APP_VERSION ?? '');
