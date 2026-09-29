<script lang="ts">
  import { frameLog } from '../../lib/link';
</script>

{#if $frameLog.length}
  <pre class="log">{$frameLog.slice(0, 60).join('\n')}</pre>
{:else}
  <div class="empty"><strong>No frames yet</strong>CHAN_FRAME lines appear here, newest first, as in <code>./sdr receive</code>.</div>
{/if}

<style>
  .log { margin: 0; font: 12px/1.55 var(--f-mono); white-space: pre; color: var(--muted); }
</style>
