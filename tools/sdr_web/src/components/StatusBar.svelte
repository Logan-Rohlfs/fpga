<script lang="ts">
  import { hello, link, role, stats, status, synthetic } from '../lib/link';
  import { countLabel } from '../lib/plural';
  import { sourcePillText } from '../lib/status';

  const src = $derived($stats?.source ?? $hello?.source);
  const dot = $derived(src?.state === 'running' ? 'good' : src?.state === 'down' || src?.state === 'busy' ? 'bad' : 'warn');
  const kB = $derived((($stats?.byte_rate ?? 0) / 1000).toFixed(1));
  const errors = $derived($stats ? $stats.decoder.crc_errors + $stats.decoder.cobs_errors + $stats.decoder.length_errors : 0);
  const versionMismatch = $derived(!!$status && !!$hello && $status.fields.version !== $hello.protocol_version);
  // The operator may force an immediate retry whenever the source is not running.
  const canReconnect = $derived($role?.role === 'admin' && !!src && src.state !== 'running');
</script>

{#if $synthetic}
  <span class="pill synth" title="This session includes SYNTHETIC stand-in data, not RF measurements">SIMULATED</span>
{/if}
<span class="pill" title={src?.detail ?? ''}><span class="dot {dot}"></span>{sourcePillText(src)}</span>
<span class="pill">{kB} kB/s · {$stats?.decoder.seq_gaps ?? 0} gaps · {errors} err</span>
{#if versionMismatch}
  <span class="chip bad">FPGA protocol v{$status?.fields.version}: rebuild and program</span>
{/if}
{#if $stats?.clients}<span class="pill" title="{$stats.clients.operators} operator(s) connected">{countLabel($stats.clients.viewers, 'viewer')}</span>{/if}
{#if canReconnect}<button class="btn" onclick={() => link.reconnectSource()}>Reconnect</button>{/if}
