<script lang="ts">
  import { bestView as best } from '../../lib/link';
  const apex = $derived($best?.fields.apex);
</script>

{#if $best && apex}
  <div class="big">APEX {apex.kind} · seq {apex.fields.seq ?? '—'}</div>
  <div class="mono muted row">
    {#if apex.fields.text}<span>"{apex.fields.text}"</span>{/if}
    <span>source {$best.fields.source}</span>
    <span>{apex.crc_ok ? 'CRC ok' : 'CRC bad'}</span>
    {#if $best.synthetic}<span class="pill synth">SIMULATED</span>{/if}
  </div>
{:else}
  <div class="empty"><strong>No telemetry yet</strong>Frames appear here as BEST_TELEM messages arrive.</div>
{/if}
