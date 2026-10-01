import { describe, expect, it } from 'vitest';
import type { GuiEvent } from './types';
import { latestSegmentStart } from './events';

const ev = (t: number, kind: string, category = 'flight'): GuiEvent => ({ t, kind, category } as unknown as GuiEvent);

describe('latestSegmentStart', () => {
  it('is the newest flight_reset, or null', () => {
    expect(latestSegmentStart([])).toBeNull();
    expect(latestSegmentStart([ev(1, 'launch')])).toBeNull();
    expect(latestSegmentStart([ev(5, 'flight_reset'), ev(6, 'launch'), ev(90, 'flight_reset'), ev(91, 'phase')])).toBe(90);
    expect(latestSegmentStart([ev(5, 'flight_reset', 'link')])).toBeNull();
  });
});

