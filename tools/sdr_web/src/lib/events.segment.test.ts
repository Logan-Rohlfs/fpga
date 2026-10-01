import { describe, expect, it } from 'vitest';
import type { GuiEvent } from './types';
import { latestSegmentStart } from './events';

const ev = (t: number, kind: string, category = 'flight', prev_phase: string | null = 'LANDED'): GuiEvent =>
  ({ t, kind, category, prev_phase } as unknown as GuiEvent);

describe('latestSegmentStart', () => {
  it('is the newest flight_reset, or null', () => {
    expect(latestSegmentStart([])).toBeNull();
    expect(latestSegmentStart([ev(1, 'launch')])).toBeNull();
    expect(latestSegmentStart([ev(5, 'flight_reset'), ev(6, 'launch'), ev(90, 'flight_reset'), ev(91, 'phase')])).toBe(90);
    expect(latestSegmentStart([ev(5, 'flight_reset', 'link')])).toBeNull();
  });

  it('ignores a reset from a mid-flight phase (reboot), keeping the earlier landed reset', () => {
    expect(latestSegmentStart([ev(5, 'flight_reset'), ev(90, 'flight_reset', 'flight', 'COAST')])).toBe(5);
    expect(latestSegmentStart([ev(90, 'flight_reset', 'flight', 'BOOST')])).toBeNull();
    expect(latestSegmentStart([ev(90, 'flight_reset', 'flight', 'DESCENT')])).toBeNull();
    expect(latestSegmentStart([ev(90, 'flight_reset', 'flight', null)])).toBeNull();
    expect(latestSegmentStart([ev(90, 'flight_reset', 'flight', 'LANDED')])).toBe(90);
  });
});
