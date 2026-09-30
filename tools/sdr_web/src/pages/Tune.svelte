<script lang="ts">
  import ChannelQuality from '../components/ChannelQuality.svelte';
  import FreqPlan from '../components/FreqPlan.svelte';
  import LinkStatsBar from '../components/LinkStatsBar.svelte';
  import NcoPanel from '../components/NcoPanel.svelte';
  import Panel from '../components/Panel.svelte';
  import ReceiverPanel from '../components/ReceiverPanel.svelte';
  import ScalePanel from '../components/ScalePanel.svelte';
  import Segmented from '../components/Segmented.svelte';
  import SendPanel from '../components/SendPanel.svelte';
  import SynthPanel from '../components/SynthPanel.svelte';
  import TuningDigits from '../components/TuningDigits.svelte';
  import Waterfall from '../components/Waterfall.svelte';
  import type { Overlay } from '../lib/draw';
  import { khz, mhz, signedKhz } from '../lib/format';
  import { connection, hello, link, metrics, role, stats, tuning } from '../lib/link';
  import type { Channel, SpectrumMsg, TuningChanges } from '../lib/types';
  import { scaleOverride, tuneChannel } from '../lib/view';

  const CHANNELS: { value: Channel; text: string }[] = [{ value: 'A', text: 'Ch A' }, { value: 'B', text: 'Ch B' }];
  const COLOR: Record<Channel, string> = { A: '--ch-a', B: '--ch-b' };

  const disabled = $derived($role?.role !== 'admin' || $connection !== 'open');
  const source = $derived($stats?.source ?? $hello?.source);
  const t = $derived($tuning);
  const m = $derived($metrics[$tuneChannel]?.fields);
  let row = $state<SpectrumMsg | null>(null);
  let ncoDrag: number | null = null;

  const tune = (changes: TuningChanges) => link.tune(changes);

  const overlays = $derived.by((): Overlay[] => {
    if (!t) return [];
    const s = t.state;
    return [
      { band: [s.target_if_hz - s.window_hz, s.target_if_hz + s.window_hz], colorVar: '--if', alpha: 0.07 },
      { band: [s.nco_hz - s.filter_hz, s.nco_hz + s.filter_hz], colorVar: '--if', alpha: 0.14 },
      { at: s.target_if_hz, colorVar: '--muted', dash: [2, 3], label: 'target', labelBottom: true },
      { at: s.nco_hz, colorVar: '--if', width: 1.5, label: 'NCO', onFall: true },
    ];
  });

  function dragNco(deltaHz: number) {
    if (!t || disabled) return;
    ncoDrag = (ncoDrag ?? t.state.nco_hz) + deltaHz;
    tune({ nco_hz: Math.min(t.state.fs_hz / 2 - 1, Math.max(0, ncoDrag)) });
  }
  function selectChannel(ch: Channel) {
    tuneChannel.set(ch);
    row = null;
  }
</script>

{#if !t}
  <p class="note">Waiting for the server…</p>
{:else}
  <p class="note assumptions">{source?.kind === 'serial' && source.responds_to_tuning ? 'ADC input is simulated; filtering, demodulation, decoding and measurements run in RTL. Rate and filter profile are fixed by this bitstream.' : 'Requested frequency plan. Hardware data is projected into RF only with a known acquisition reference.'}</p>
  <div class="tune">
    <div class="main">
      <Panel title="Frequency plan" sub={disabled ? 'RF domain' : 'RF domain · drag or scroll to move the LO'}>
        {#snippet actions()}
          {#if t.derived.warnings.length === 0}<span class="chip good">plan OK</span>{/if}
        {/snippet}
        <FreqPlan {t} {row} colorVar={COLOR[$tuneChannel]} {disabled} ontune={(lo) => tune({ lo_hz: lo })} />
        <div class="readouts">
          <div class="ro"><span class="k">LO (requested model)</span>
            <TuningDigits revision={t} hz={t.derived.lo_hz} stepHz={t.derived.lo_step_hz} {disabled} onchange={(hz) => tune({ lo_hz: hz })} /></div>
          <div class="ro"><span class="k">Carrier (nominal)</span><span class="v">{mhz(t.state.carrier_hz)}</span></div>
          <div class="ro"><span class="k">Expected IF</span><span class="v">{khz(t.derived.expected_if_hz)}</span></div>
          <div class="ro"><span class="k">Image at</span><span class="v">{mhz(t.derived.image_hz)}</span></div>
        </div>
        {#if t.derived.warnings.length || (source && !source.responds_to_tuning)}
          <div class="warnings">
            {#each t.derived.warnings as w (w)}<span class="chip warn">{w}</span>{/each}
            {#if source && !source.responds_to_tuning}
              <p class="note">This source has not confirmed tuning support. The plan follows requested settings; received data keeps its acquisition reference.</p>
            {/if}
          </div>
        {/if}
      </Panel>

      <Panel title="IF spectrum" sub={disabled ? 'received IF data' : 'received IF data · drag to move the NCO'}>
        {#snippet actions()}
          <Segmented label="Channel shown" options={CHANNELS} value={$tuneChannel} onselect={selectChannel} />
        {/snippet}
        <Waterfall channel={$tuneChannel} colorVar={COLOR[$tuneChannel]} {overlays} draggable={!disabled}
          ondrag={dragNco} ondragend={() => (ncoDrag = null)} onrow={(r) => (row = r)} />
        <div class="chanbar mono">
          <span>Ch {$tuneChannel}</span>
          <span>RSSI <b>{m ? `${m.rssi_dbm.toFixed(1)} ${m.power_unit ?? 'dBm'}` : '—'}</b></span>
          <span>SNR <b>{m ? `${m.snr_db.toFixed(1)} dB` : '—'}</b></span>
          <span>Δf from NCO <b>{m ? signedKhz(m.freq_offset_hz) : '—'}</b></span>
          {#if row}<span>scale <b>{($scaleOverride.mode === 'manual' ? $scaleOverride.low : row.low).toFixed(0)}…{($scaleOverride.mode === 'manual' ? $scaleOverride.high : row.high).toFixed(0)} dBFS</b></span>{/if}
        </div>
      </Panel>

      <div class="quality">
        <ChannelQuality channel="A" colorVar="--ch-a" name="Channel A" antenna="receiver A" />
        <ChannelQuality channel="B" colorVar="--ch-b" name="Channel B" antenna="receiver B" />
        <div class="wide"><LinkStatsBar /></div>
      </div>
    </div>

    <aside class="rail">
      {#if disabled}
        <p class="note viewer">Viewing only. Log in as Admin (top right) to change tuning.</p>
      {/if}
      <ReceiverPanel {t} {disabled} fixedProfile={source?.kind === 'serial' && !!source.responds_to_tuning} ontune={tune} />
      <SynthPanel {t} {disabled} ontune={tune} />
      <NcoPanel {t} {disabled} fixedProfile={source?.kind === 'serial' && !!source.responds_to_tuning} ontune={tune} />
      <ScalePanel current={row ? [row.low, row.high] : null} />
      <SendPanel {source} {disabled} />
    </aside>
  </div>
{/if}

<style>
  .assumptions { margin-bottom: 10px; }
  .tune { display: grid; grid-template-columns: minmax(0, 1fr) 330px; gap: 14px; align-items: start; }
  .main, .rail { display: grid; gap: 14px; min-width: 0; }
  .quality { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
  .wide { grid-column: 1 / -1; }
  .readouts { display: flex; flex-wrap: wrap; gap: 10px 26px; align-items: flex-end; padding: 12px; border-top: 1px solid var(--line); }
  .ro { display: grid; gap: 2px; }
  .k { font: 600 11px var(--f-ui); letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); }
  .v { font: 500 18px var(--f-mono); font-variant-numeric: tabular-nums; }
  .warnings { display: flex; flex-wrap: wrap; gap: 6px 10px; padding: 0 12px 12px; }
  .chanbar { display: flex; flex-wrap: wrap; gap: 6px 22px; padding: 8px 12px; border-top: 1px solid var(--line); font-size: 13px; color: var(--muted); }
  .chanbar b { color: var(--fg); font-weight: 500; }
  .viewer { padding: 8px 12px; border: 1px dashed var(--line-2); border-radius: 8px; }
  @media (max-width: 1100px) {
    .assumptions { margin-bottom: 10px; }
  .tune { grid-template-columns: minmax(0, 1fr); }
    .rail { grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
  }
  @media (max-width: 760px) { .quality { grid-template-columns: minmax(0, 1fr); } }
</style>
