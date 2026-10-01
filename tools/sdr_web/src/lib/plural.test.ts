import { describe, expect, it } from 'vitest';
import { countLabel } from './plural';

describe('countLabel', () => {
  it('uses the singular only for exactly one', () => {
    expect(countLabel(0, 'viewer')).toBe('0 viewers');
    expect(countLabel(1, 'viewer')).toBe('1 viewer');
    expect(countLabel(2, 'viewer')).toBe('2 viewers');
  });
});
