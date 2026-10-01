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
export interface RfReference { lo_hz: number; injection: Injection; inferred?: boolean; confirmed_by?: 'ack' | 'report' }
export interface ReceiverProfile {
  id: string; label: string; rf_label?: string;
  /** Demo profile: flight-schema keys the demo ROM generator emulates (absent from the flight log). */
  emulated_fields?: string[]; emulated_note?: string; replay_note?: string;
}
export interface SourceState {
  profile?: ReceiverProfile;
  control_state?: string; control_error?: string; applied?: RfReference | null;
  /** Serial: running, waiting, busy, reconnecting, down or stopped. Others: running, down, ended, stopped, starting. */
  kind: 'serial' | 'replay' | 'sim' | 'demo' | 'none'; state: string; detail: string; responds_to_tuning: boolean;
  /** Serial only: the port device, and seconds until the supervisor's next open attempt (spec 18). */
  port?: string; retry_in_s?: number;
}
export interface RecordJson {
  t: number; type: string; seq: number; flags: number; synthetic: boolean;
  // Field names follow tools/sdr_cli/protocol.py SCHEMAS after unit conversion.
  fields: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  raw: string | null;
}

export type Budget = 'operator' | 'viewer';

/** hello.flight_schema (spec section 4): field order of every FLIGHT_ROWS row. */
export interface FlightField {
  key: string; label: string; quantity: string; digits?: number;
  enum?: string[]; enum_map?: Record<string, string>; bits?: Record<string, string>;
}
export interface FlightSchema { version: number; fields: FlightField[] }

/** A derived event (spec section 10). Flight and link events share the `events` channel. */
export interface GuiEvent {
  id: number; t: number; kind: string; category: 'flight' | 'link'; text: string;
  channel: Channel | null; value: number | null; quantity: string | null; segment: number; synthetic: boolean;
}

export interface TuningMsg { type: 'tuning'; state: TuningState; derived: Derived }
export interface RoleMsg {
  type: 'role'; role: Role; budget: Budget; admin: AdminInfo | null; can_admin: boolean; reason: string; token?: string; by?: string;
}
export interface HelloMsg {
  type: 'hello'; server_version: string; protocol_version: number; source: SourceState; role: RoleMsg; tuning: TuningMsg;
  flight_schema: FlightSchema; channels: string[]; budget: Budget; sites: unknown[];
}
export interface RecordMsg { type: 'record'; record: RecordJson; text: string }
/** Decoded SPECTRUM_ROW binary frame (spec 3.4); the server no longer sends it as JSON. */
export interface SpectrumMsg {
  rf_reference: RfReference | null;
  type: 'spectrum'; channel: Channel; row: number; t_us: number; f0_hz: number; bin_hz: number; bins: number;
  db10: Int16Array; low: number; high: number; synthetic: boolean;
}
export interface StatsMsg {
  type: 'stats'; byte_rate: number; rates: Record<string, number>; source: SourceState;
  decoder: { bytes: number; messages: number; crc_errors: number; cobs_errors: number; length_errors: number;
    resync_bytes: number; seq_gaps: number; synthetic: number; by_type: Record<string, number> };
  clients?: { operators: number; viewers: number };
}
export interface TakeoverMsg { type: 'takeover_required'; held_by: string; since: number }
export interface ErrorMsg { type: 'error'; code: string; text: string }
export interface SubscribedMsg { type: 'subscribed'; channels: string[] }
/** Snapshot start: the channel's store is cleared, and the following rows are its history. */
export interface HistoryMsg { type: 'history'; channel: string; count: number }
export interface EventsMsg { type: 'events'; items: GuiEvent[]; reset: boolean }
/** Link snapshot for sparklines; null stands in for a non-finite value. */
export interface MetricsHistoryMsg {
  type: 'metrics_history'; channel: Channel; t: number[]; rssi: (number | null)[]; noise: (number | null)[];
  snr: (number | null)[]; df: (number | null)[]; crc_good: (number | null)[]; crc_bad: (number | null)[];
  power_unit: string | null;
}
/** A stored preset as the server sends it (sdr_cli/presets.py message()). Cards are untrusted until sanitizeGrid. */
export interface PresetItem {
  schema: number; id: string; name: string; revision: number; builtin: boolean;
  grid: { cols: number }; cards: unknown[]; triggers: unknown[];
}
export interface PresetsMsg { type: 'presets'; items: PresetItem[]; live: string; default: string; auto_switch: boolean }
export interface NoticeMsg { type: 'notice'; text: string }
export interface DroppedMsg { type: 'dropped'; channel: 'frames'; count: number }
export type ServerMsg = HelloMsg | RecordMsg | StatsMsg | TuningMsg | RoleMsg | TakeoverMsg | ErrorMsg
  | SubscribedMsg | HistoryMsg | EventsMsg | MetricsHistoryMsg | DroppedMsg | PresetsMsg | NoticeMsg | { type: 'pong' };

export type ClientMsg =
  | { type: 'login'; password: string; label: string; takeover: boolean }
  | { type: 'resume'; token: string }
  | { type: 'logout' }
  | { type: 'tune'; changes: TuningChanges }
  | { type: 'reconnect_source' }
  | { type: 'use_compiled_profile' }
  | { type: 'ping' }
  | { type: 'subscribe'; channels: string[] }
  | { type: 'preset_save'; preset: unknown; base_revision: number | null }
  | { type: 'preset_delete'; id: string }
  | { type: 'preset_set_live'; id: string }
  | { type: 'preset_set_default'; id: string }
  | { type: 'preset_auto_switch'; enabled: boolean };
