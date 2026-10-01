import { describe, expect, it } from 'vitest';
import { controlStateText, profileOf, roleLabel } from './receiver';
import type { SourceState } from './types';

const src = (control_state?: string, extra: Partial<SourceState> = {}): SourceState => ({
  kind: 'serial', state: 'running', detail: '', responds_to_tuning: true, control_state, ...extra,
});
const applied = (confirmed_by: string) => ({ lo_hz: 1, injection: 'low', confirmed_by }) as unknown as SourceState['applied'];

describe('controlStateText', () => {
  it('treats a missing source or state as detecting', () => {
    expect(controlStateText(undefined)).toEqual({ text: 'Detecting receiver', level: 'info' });
    expect(controlStateText(src('detecting')).text).toBe('Detecting receiver');
  });
  it('never calls a sent request applied', () => {
    expect(controlStateText(src('pending'))).toEqual({ text: 'Sent, awaiting acknowledgement', level: 'info' });
  });
  it('distinguishes acknowledgement from receiver report', () => {
    expect(controlStateText(src('applied', { applied: applied('ack') })).text).toBe('Applied (acknowledged)');
    expect(controlStateText(src('applied', { applied: applied('report') })).text).toBe('Applied (receiver report)');
    expect(controlStateText(src('applied', { applied: null })).text).toBe('Applied (receiver report)');
  });
  it('reports receiver-reported settings', () => {
    expect(controlStateText(src('reported')).text).toBe('Receiver reported settings');
  });
  it('shows the state name and error for failures', () => {
    expect(controlStateText(src('timeout', { control_error: 'No ack' }))).toEqual({ text: 'timeout: No ack', level: 'bad' });
    expect(controlStateText(src('rejected', { control_error: 'no' })).level).toBe('bad');
    expect(controlStateText(src('out_of_sync', { control_error: 'moved' })).text).toBe('out_of_sync: moved');
    expect(controlStateText(src('unsupported', { control_error: 'fs' })).text).toBe('unsupported: fs');
    expect(controlStateText(src('timeout')).text).toBe('timeout');
  });
});

describe('profileOf and roleLabel', () => {
  it('returns the server profile or an unknown placeholder', () => {
    expect(profileOf(src('applied', { profile: { id: 'apex_demo', label: 'L', rf_label: 'R' } })).rf_label).toBe('R');
    expect(profileOf(undefined).id).toBe('unknown');
  });
  it('labels the admin wire role Operator', () => {
    expect(roleLabel('admin')).toBe('Operator');
    expect(roleLabel('viewer')).toBe('Viewer');
    expect(roleLabel(undefined)).toBe('Viewer');
  });
});
