<script lang="ts">
  import { appearanceVersion } from '../lib/theme';
  import { onMount } from 'svelte';
  import { drawConstellation, drawSparkline, fitCanvas } from '../lib/draw';
  import { signedKhz } from '../lib/format';
  import { powerLabel } from '../lib/cards/linkq';
  import { SPARK_POINTS, dataVersion, frozen, iqSnapsView as iqSnaps, metricsNow, metricsTail, powerUnit } from '../lib/link';
  import type { Channel } from '../lib/types';
  import Panel from './Panel.svelte';

  const SIGNAL_SNR_DB = 6;   // display threshold for the "signal" chip only; not a receiver setting

  let { channel, colorVar, name, antenna }: { channel: Channel; colorVar: string; name: string; antenna: string } = $props();

  let iqCv: HTMLCanvasElement;
  let rssiCv: HTMLCanvasElement;
  let snrCv: HTMLCanvasElement;
  const m = $derived($metricsNow[channel]);
  const hasSignal = $derived(!!m && m.snr >= SIGNAL_SNR_DB);
  const unit = $derived(powerLabel($powerUnit ?? undefined, true));
  const fix = (x: number | undefined, d = 1) => (x !== undefined && Number.isFinite(x) ? x.toFixed(d) : '—');

  function drawIq() {
    if (!iqCv) return;
    const { ctx, w } = fitCanvas(iqCv);
    drawConstellation(ctx, w, $iqSnaps[channel] ?? [], colorVar);
  }
  // Freeze stops drawing only: the rings keep filling, and a copy taken at freeze time is drawn instead.
  let still: { rssi: readonly number[]; snr: readonly number[] } | null = null;
  function drawHistory() {
    if (!rssiCv || !snrCv) return;
    const rssi = still?.rssi ?? metricsTail(channel, 0, SPARK_POINTS);
    const snr = still?.snr ?? metricsTail(channel, 2, SPARK_POINTS);
    const r = fitCanvas(rssiCv);
    drawSparkline(r.ctx, r.w, r.h, rssi, colorVar, $powerUnit === 'dBm' ? [-115, -70] : [-90, 0], SPARK_POINTS);
    const s = fitCanvas(snrCv);
    drawSparkline(s.ctx, s.w, s.h, snr, colorVar, [0, 40], SPARK_POINTS);
  }
  $effect(() => {
    still = $frozen ? { rssi: metricsTail(channel, 0, SPARK_POINTS), snr: metricsTail(channel, 2, SPARK_POINTS) } : null;
    drawHistory();
  });

  $effect(() => {
    void $appearanceVersion;
    void $iqSnaps;
    drawIq();
  });
  $effect(() => {
    void $appearanceVersion;
    void $dataVersion;
    drawHistory();
  });
  onMount(() => {
    const ro = new ResizeObserver(() => {
      drawIq();
      drawHistory();
    });
    ro.observe(iqCv);
    ro.observe(rssiCv);
    return () => ro.disconnect();
  });
</script>

<Panel title={name} sub={antenna} swatch={colorVar}>
  {#snippet actions()}
    {#if !m}<span class="chip warn">waiting</span>
    {:else if hasSignal}<span class="chip good">signal</span>
    {:else}<span class="chip bad">no signal</span>{/if}
  {/snippet}
  <div class="grid">
    <figure>
      <canvas class="iq" bind:this={iqCv} aria-label="Channel {channel} constellation"></canvas>
      <figcaption>I/Q · last 4 snapshots</figcaption>
    </figure>
    <div class="side">
      <div class="kv">
        <div><div class="k">RSSI</div><div class="v">{fix(m?.rssi)} <small>{unit}</small></div></div>
        <div><div class="k">SNR</div><div class="v">{fix(m?.snr)} <small>dB</small></div></div>
        <div><div class="k">Δf from NCO</div><div class="v">{m && Number.isFinite(m.df) ? signedKhz(m.df) : '—'}</div></div>
        <div><div class="k">Noise</div><div class="v">{fix(m?.noise)} <small>{unit}</small></div></div>
        <div><div class="k">CRC good</div><div class="v">{fix(m?.crc_good, 0)}</div></div>
        <div><div class="k">CRC bad</div><div class="v">{fix(m?.crc_bad, 0)}</div></div>
      </div>
      <div>
        <canvas class="spark" bind:this={rssiCv} aria-label="Channel {channel} RSSI history"></canvas>
        <div class="cap"><span>RSSI, last 30 s</span><span>{m ? `${fix(m.rssi)} ${unit}` : ''}</span></div>
      </div>
      <div>
        <canvas class="spark" bind:this={snrCv} aria-label="Channel {channel} SNR history"></canvas>
        <div class="cap"><span>SNR, last 30 s</span><span>{m ? `${fix(m.snr)} dB` : ''}</span></div>
      </div>
    </div>
  </div>
</Panel>

<style>
  .grid { display: grid; grid-template-columns: 170px minmax(0, 1fr); gap: 12px; padding: 12px; }
  figure { margin: 0; }
  .iq { display: block; width: 100%; max-width: 170px; aspect-ratio: 1; }
  figcaption, .cap { display: flex; justify-content: space-between; font: 11px var(--f-mono); color: var(--muted); margin-top: 6px; }
  .side { display: grid; gap: 12px; min-width: 0; }
  .kv { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
  .k { font: 600 11px var(--f-ui); letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); }
  .v { font: 500 17px var(--f-mono); font-variant-numeric: tabular-nums; }
  .v small { font-size: 11px; color: var(--muted); }
  .spark { display: block; width: 100%; height: 46px; }
  @media (max-width: 600px) {
    .grid { grid-template-columns: minmax(0, 1fr); }
    .kv { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
</style>
