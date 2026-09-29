<script lang="ts">
  import { linkStats } from '../../lib/link';
  const f = $derived($linkStats?.fields);
</script>

{#if f}
  <table class="tbl mono">
    <tbody>
      <tr><td>from A</td><td>{f.from_a}</td></tr>
      <tr><td>from B</td><td>{f.from_b}</td></tr>
      <tr><td>both OK</td><td>{f.both_ok}</td></tr>
      <tr><td>neither</td><td>{f.neither_ok}</td></tr>
      <tr><td>best sent</td><td>{f.best_sent}</td></tr>
    </tbody>
  </table>
{:else}
  <div class="empty"><strong>No LINK_STATS yet</strong>Sent once per second.</div>
{/if}

<style>
  .tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  .tbl td { padding: 3px 4px; border-top: 1px solid var(--line); text-align: right; }
  .tbl td:first-child { text-align: left; color: var(--muted); font-family: var(--f-ui); }
</style>
