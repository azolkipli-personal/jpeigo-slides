import { formatVersion } from '@/lib/version';

describe('formatVersion', () => {
  it('shows the bare tag when the build is exactly at it', () => {
    expect(formatVersion('v1.4.0')).toBe('v1.4.0');
  });

  it('shows how far past the tag a build is, with the commit it came from', () => {
    expect(formatVersion('v1.4.0-3-g947a30d')).toBe('v1.4.0+3 (947a30d)');
  });

  it('admits a build made from uncommitted changes', () => {
    expect(formatVersion('v1.4.0-dirty')).toBe('v1.4.0 dirty');
    expect(formatVersion('v1.4.0-3-g947a30d-dirty')).toBe('v1.4.0+3 (947a30d) dirty');
  });

  it('falls back to a bare sha when no tag is reachable', () => {
    expect(formatVersion('947a30d')).toBe('947a30d');
  });

  it('returns empty when the build had no git, so callers hide the label', () => {
    expect(formatVersion('')).toBe('');
    expect(formatVersion('   ')).toBe('');
  });
});
