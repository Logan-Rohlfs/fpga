<script lang="ts">
  import { hex32 } from '../../lib/format';
  import { statsView as stats, statusView as status } from '../../lib/link';
  const f = $derived($status?.fields);
  const channels = $derived(f ? ['A', 'B'].filter((_, n) => (f.channels >> n) & 1).join('') || '-' : '');
</script>

{#if f}
  <table class="tbl mono">
    <tbody>
      <tr><td>protocol</td><td>v{f.version}</td></tr>
      <tr><td>uptime</td><td>{(f.uptime_ms / 1000).toFixed(0)} s</td></tr>
      <tr><td>build</td><td>{hex32(f.build_id)}</td></tr>
      <tr><td>channels</td><td>{channels}</td></tr>
      <tr><td>dropped</td><td>{f.dropped}</td></tr>
      <tr><td>seq gaps</td><td>{$stats?.decoder.seq_gaps ?? 0}</td></tr>
    </tbody>
  </table>
{:else}
  <div class="empty"><strong>No STATUS yet</strong>Sent once per second by the FPGA.</div>
{/if}

<style>
  .tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  .tbl td { padding: 3px 4px; border-top: 1px solid var(--line); text-align: right; }
  .tbl td:first-child { text-align: left; color: var(--muted); font-family: var(--f-ui); }
</style>
