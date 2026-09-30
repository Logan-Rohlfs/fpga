<script lang="ts">
  import { link } from '../lib/link';
  import type { SourceState } from '../lib/types';
  let { source, disabled = true }: { source: SourceState | undefined; disabled?: boolean } = $props();
</script>

<section class="panel pb stack" aria-label="Receiver tuning status">
  {#if source?.kind === 'serial' && source.responds_to_tuning}
    <strong>ADC test carrier + real RTL</strong>
    <p class="note">LO and NCO changes apply automatically. Receiver: {source.control_state ?? 'detecting'}.
      Only a matching acknowledgement confirms application. No physical PLL is controlled.</p>
    <button class="btn" {disabled} onclick={() => link.send({ type: 'use_compiled_profile' })}>Use compiled profile</button>
    <p class="note">Restore 1 MS/s, low-side injection, 100 kHz IF and ±35 kHz window/filter. An out-of-range saved NCO resets to 100 kHz.</p>
    {#if source.control_error}<p class="note">{source.control_error}</p>{/if}
    {#if source.applied?.inferred}<p class="note">Initial RF reference inferred from the nominal test carrier.</p>{/if}
  {:else if source?.kind === 'sim'}
    <strong>Host UI simulator</strong>
    <p class="note">These controls change the legacy GUI demonstration. No FPGA processing is involved.</p>
  {:else}
    <strong>View only · receiver control unavailable</strong>
    <p class="note">Tuning changes the requested plan only. The IF spectrum remains visible; RF projection needs a confirmed acquisition reference.</p>
  {/if}
</section>
