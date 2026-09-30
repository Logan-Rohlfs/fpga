<script lang="ts">
  import { signedKhz } from '../../lib/format';
  import { metricsView as metrics } from '../../lib/link';
  import type { Channel } from '../../lib/types';
  const CHANNELS: Channel[] = ['A', 'B'];
</script>

<table class="tbl mono">
  <thead><tr><th>Ch</th><th>Signal</th><th>SNR dB</th><th>Δf</th><th>good</th><th>bad</th></tr></thead>
  <tbody>
    {#each CHANNELS as ch (ch)}
      {@const f = $metrics[ch]?.fields}
      <tr>
        <td><span class="sw" style="background: var(--ch-{ch.toLowerCase()})"></span>{ch}</td>
        <td>{f ? `${f.rssi_dbm.toFixed(1)} ${f.power_unit ?? 'dBm'}` : '—'}</td><td>{f ? f.snr_db.toFixed(1) : '—'}</td>
        <td>{f ? signedKhz(f.freq_offset_hz) : '—'}</td><td>{f?.crc_good ?? '—'}</td><td>{f?.crc_bad ?? '—'}</td>
      </tr>
    {/each}
  </tbody>
</table>

<style>
  .tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  .tbl th { font: 600 11px var(--f-ui); letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); text-align: right; padding: 2px 6px; }
  .tbl td { text-align: right; padding: 3px 6px; border-top: 1px solid var(--line); }
  .tbl th:first-child, .tbl td:first-child { text-align: left; }
  .sw { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 6px; }
</style>
