<script lang="ts">
  import { link } from '../lib/link';
  import { controlStateText } from '../lib/receiver';
  import type { SourceState } from '../lib/types';

  let { source, disabled = true }: { source: SourceState | undefined; disabled?: boolean } = $props();
  const control = $derived(controlStateText(source));
</script>

<section class="panel pb stack" aria-label="Receiver tuning status">
  {#if source?.kind === 'serial' && source.responds_to_tuning}
    <strong>ADC test carrier + real RTL</strong>
    <span class="chip {control.level}">{control.text}</span>
    <p class="note">LO and NCO changes apply automatically.
      Only a matching acknowledgement confirms application. No physical PLL is controlled.</p>
    <button class="btn" {disabled} onclick={() => link.send({ type: 'use_compiled_profile' })}>Use compiled profile</button>
    <p class="note">Restore 1 MS/s, low-side injection, 100 kHz IF and ±35 kHz window/filter. An out-of-range saved NCO resets to 100 kHz.</p>
    {#if source.applied?.inferred}<p class="note">Initial RF reference inferred from the nominal test carrier.</p>{/if}
  {:else if source?.kind === 'sim'}
    <strong>Host UI simulator</strong>
    <p class="note">These controls change the legacy GUI demonstration. No FPGA processing is involved.</p>
  {:else if source?.kind === 'demo'}
    <strong>Host flight demo (no FPGA)</strong>
    <p class="note">The replay ROM is sent as the demo bitstream would send it. Signal, noise, spectrum and I/Q are modelled; tuning is not applied.</p>
  {:else}
    <strong>View only · receiver control unavailable</strong>
    <p class="note">Tuning changes the requested plan only. The IF spectrum remains visible; RF projection needs a confirmed acquisition reference.</p>
  {/if}
</section>
