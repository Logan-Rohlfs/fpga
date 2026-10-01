<script lang="ts">
  // Per-channel signal quality and the combiner split. Numbers come from the metrics rings; "now" is the server clock.
  import { signedKhz } from '../lib/format';
  import { badRatio, combinerShare, frameRate, powerLabel } from '../lib/cards/linkq';
  import { dataVersion, frozen, linkStatsRing, metricsStores, powerUnit, serverNow, synthetic } from '../lib/link';
  import type { Channel } from '../lib/types';

  let { config }: { id: string; config: { channels?: string[]; window_s?: number } } = $props();

  interface Col {
    ch: Channel; rssi: number; noise: number; snr: number; df: number; good: number; bad: number;
    rate: number | null; ratio: number | null;
  }
  const windowS = $derived(config.window_s ?? 10);
  const chans = $derived((config.channels ?? ['A', 'B']).filter((c): c is Channel => c === 'A' || c === 'B'));

  let cols = $state<Col[]>([]);
  let share = $state<{ a: number; b: number } | null>(null);

  // Freeze holds the displayed numbers; the rings keep filling underneath.
  $effect(() => {
    void $dataVersion;
    void $linkStatsRing;
    if ($frozen) return;
    const now = serverNow();
    const next: Col[] = [];
    for (const ch of chans) {
      const s = metricsStores[ch];
      const l = s.latest();
      if (!l) continue;
      const v = l.values;
      next.push({
        ch, rssi: v[0], noise: v[1], snr: v[2], df: v[3], good: v[4], bad: v[5],
        rate: frameRate(s, windowS, now), ratio: badRatio(s, windowS, now),
      });
    }
    cols = next;
    share = combinerShare($linkStatsRing, windowS, now);
  });

  const fix = (x: number, d = 1) => (Number.isFinite(x) ? x.toFixed(d) : '—');
  const pct = (x: number) => `${(x * 100).toFixed(0)}%`;
</script>

<div class="lq">
  {#if $synthetic}<p class="note syn">Simulated data</p>{/if}
  {#if !cols.length}
    <p class="note empty">Waiting for channel metrics</p>
  {:else}
    <div class="cols" style="--n: {cols.length}">
      {#each cols as c (c.ch)}
        <div class="col">
          <h4>Channel {c.ch}</h4>
          <dl>
            <dt>Signal</dt><dd>{fix(c.rssi)} <small>{powerLabel($powerUnit ?? undefined, true)}</small></dd>
            <dt>Noise</dt><dd>{fix(c.noise)} <small>{powerLabel($powerUnit ?? undefined, true)}</small></dd>
            <dt>SNR</dt><dd>{fix(c.snr)} <small>dB</small></dd>
            <dt>Δf</dt><dd>{Number.isFinite(c.df) ? signedKhz(c.df) : '—'}</dd>
            <dt>CRC good</dt><dd>{fix(c.good, 0)}</dd>
            <dt>CRC bad</dt><dd>{fix(c.bad, 0)}</dd>
            <dt>Bad ratio</dt><dd>{c.ratio === null ? '—' : `${(c.ratio * 100).toFixed(1)}%`}</dd>
            <dt>Frame rate</dt><dd>{c.rate === null ? '—' : c.rate.toFixed(1)} <small>/s</small></dd>
          </dl>
        </div>
      {/each}
    </div>
    <p class="note unit">Power is {powerLabel($powerUnit ?? undefined)}; rates over {windowS} s.</p>
  {/if}
  <div class="comb">
    <div class="k">Combiner</div>
    {#if share}
      <div class="bar" role="img" aria-label="Frames taken from A {pct(share.a)}, from B {pct(share.b)}">
        <span class="a" style="width: {share.a * 100}%"></span><span class="b" style="width: {share.b * 100}%"></span>
      </div>
      <div class="pct"><span>A {pct(share.a)}</span><span>B {pct(share.b)}</span></div>
    {:else}
      <p class="note">No combiner frames in the last {windowS} s</p>
    {/if}
  </div>
</div>

<style>
  .lq { display: grid; gap: 12px; padding: 12px; align-content: start; }
  .note { margin: 0; }
  .cols { display: grid; grid-template-columns: repeat(var(--n), minmax(0, 1fr)); gap: 12px; }
  h4 { margin: 0 0 6px; font: 600 11px var(--f-ui); letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); }
  dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 10px; margin: 0; }
  dt { font: 12px var(--f-ui); color: var(--muted); }
  dd { margin: 0; text-align: right; font: 500 14px var(--f-mono); font-variant-numeric: tabular-nums; }
  dd small { font-size: 11px; color: var(--muted); }
  .k { font: 600 11px var(--f-ui); letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); margin-bottom: 6px; }
  .bar { display: flex; height: 14px; border-radius: 3px; overflow: hidden; background: var(--line, #8883); }
  .bar .a { background: var(--ch-a, #4c8bf5); }
  .bar .b { background: var(--ch-b, #e8963a); }
  .pct { display: flex; justify-content: space-between; font: 12px var(--f-mono); margin-top: 4px; }
  @media (max-width: 600px) { .cols { grid-template-columns: minmax(0, 1fr); } }
</style>
