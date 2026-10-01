import type { ReceiverProfile, Role, SourceState } from './types';

export type ControlLevel = 'good' | 'warn' | 'bad' | 'info';

const withError = (name: string, error: string | undefined) => (error ? `${name}: ${error}` : name);

/** Text chip for the tuning control state (spec 14). A request is never "applied" without an ack or report. */
export function controlStateText(source: SourceState | undefined): { text: string; level: ControlLevel } {
  const state = source?.control_state ?? 'detecting';
  const error = source?.control_error;
  switch (state) {
    case 'detecting': return { text: 'Detecting receiver', level: 'info' };
    case 'pending': return { text: 'Sent, awaiting acknowledgement', level: 'info' };
    case 'applied': {
      const by = source?.applied?.confirmed_by;
      return by === 'ack'
        ? { text: 'Applied (acknowledged)', level: 'good' }
        : { text: 'Applied (receiver report)', level: 'good' };
    }
    case 'reported': return { text: 'Receiver reported settings', level: 'info' };
    case 'rejected': return { text: withError('rejected', error), level: 'bad' };
    case 'timeout': return { text: withError('timeout', error), level: 'bad' };
    case 'out_of_sync': return { text: withError('out_of_sync', error), level: 'warn' };
    case 'unsupported': return { text: withError('unsupported', error), level: 'warn' };
    default: return { text: withError(state, error), level: 'warn' };
  }
}

export function profileOf(source: SourceState | undefined): ReceiverProfile {
  return source?.profile ?? { id: 'unknown', label: 'Unknown receiver profile' };
}

export const roleLabel = (role: Role | undefined): 'Operator' | 'Viewer' => (role === 'admin' ? 'Operator' : 'Viewer');
