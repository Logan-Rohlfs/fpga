export type Channel = 'A' | 'B';
export type Role = 'viewer' | 'admin';
export type Injection = 'low' | 'high';

export interface TuningState {
  carrier_hz: number; injection: Injection; target_if_hz: number; window_hz: number;
  ref_hz: number; r_div: number; n_int: number; frac: number; mod: number; out_div: number;
  vco_min_hz: number; vco_max_hz: number; nco_hz: number; fs_hz: number; filter_hz: number;
}
export type TuningChanges = Partial<TuningState> & { lo_hz?: number };
export interface Derived {
  pfd_hz: number; vco_hz: number; lo_hz: number; lo_step_hz: number; expected_if_hz: number;
  image_hz: number; nco_ftw: number; nco_resolution_hz: number; warnings: string[];
}
export interface AdminInfo { label: string; since: number }
export interface SourceState {
  kind: 'serial' | 'replay' | 'sim' | 'none'; state: string; detail: string; responds_to_tuning: boolean;
}
export interface RecordJson {
  t: number; type: string; seq: number; flags: number; synthetic: boolean;
  // Field names follow tools/sdr_cli/protocol.py SCHEMAS after unit conversion.
  fields: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  raw: string | null;
}

export interface TuningMsg { type: 'tuning'; state: TuningState; derived: Derived }
export interface RoleMsg {
  type: 'role'; role: Role; admin: AdminInfo | null; can_admin: boolean; reason: string; token?: string; by?: string;
}
export interface HelloMsg {
  type: 'hello'; server_version: string; protocol_version: number; source: SourceState; role: RoleMsg; tuning: TuningMsg;
}
export interface RecordMsg { type: 'record'; record: RecordJson; text: string }
export interface SpectrumMsg {
  type: 'spectrum'; channel: Channel; row: number; t_us: number; f0_hz: number; bin_hz: number; bins: number;
  db10: number[]; low: number; high: number; synthetic: boolean;
}
export interface StatsMsg {
  type: 'stats'; byte_rate: number; rates: Record<string, number>; source: SourceState;
  decoder: { bytes: number; messages: number; crc_errors: number; cobs_errors: number; length_errors: number;
    resync_bytes: number; seq_gaps: number; synthetic: number; by_type: Record<string, number> };
}
export interface TakeoverMsg { type: 'takeover_required'; held_by: string; since: number }
export interface ErrorMsg { type: 'error'; code: string; text: string }
export type ServerMsg = HelloMsg | RecordMsg | SpectrumMsg | StatsMsg | TuningMsg | RoleMsg | TakeoverMsg | ErrorMsg
  | { type: 'pong' };

export type ClientMsg =
  | { type: 'login'; password: string; label: string; takeover: boolean }
  | { type: 'resume'; token: string }
  | { type: 'logout' }
  | { type: 'tune'; changes: TuningChanges }
  | { type: 'reconnect_source' }
  | { type: 'ping' };
