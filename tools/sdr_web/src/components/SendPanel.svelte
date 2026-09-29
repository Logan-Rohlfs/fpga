<script lang="ts">
  let { respondsToTuning }: { respondsToTuning: boolean } = $props();
</script>

<section class="panel pb stack" aria-label="Send settings to the FPGA">
  <button class="btn" disabled>Send to FPGA</button>
  <p class="note">Sending settings needs the FPGA command link (UART RX, command decoder and acknowledgements), which is
    not built yet. These settings change the frequency plan{respondsToTuning ? ' and the host simulator' : ''} only.</p>
</section>
