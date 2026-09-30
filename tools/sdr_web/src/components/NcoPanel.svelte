<script lang="ts">
  import { hex32 } from '../lib/format';
  import type { TuningChanges, TuningMsg } from '../lib/types';
  import NumberField from './NumberField.svelte';
  import Panel from './Panel.svelte';

  let { t, disabled, ontune, fixedProfile = false }: { t: TuningMsg; disabled: boolean; fixedProfile?: boolean; ontune: (c: TuningChanges) => void } = $props();
</script>

<Panel title="Digital downconversion">
  <div class="pb stack">
    {#if fixedProfile}<p class="note">Sample rate and channel filter are compiled into this bitstream.</p>{/if}
    <NumberField id="nco" label="NCO (kHz)" value={t.state.nco_hz} scale={1e3} digits={1} step={0.1} {disabled}
      oncommit={(v) => ontune({ nco_hz: v })} />
    <NumberField id="fs" label="XADC rate (kS/s)" value={t.state.fs_hz} scale={1e3} disabled={disabled || fixedProfile}
      oncommit={(v) => ontune({ fs_hz: v })} />
    <NumberField id="filter" label="Channel filter ± (kHz)" value={t.state.filter_hz} scale={1e3} digits={1} step={0.5}
      disabled={disabled || fixedProfile} oncommit={(v) => ontune({ filter_hz: v })} />
    <dl class="derived">
      <dt>NCO tuning word</dt><dd>{hex32(t.derived.nco_ftw)}</dd>
      <dt>NCO resolution</dt><dd>{(t.derived.nco_resolution_hz * 1e3).toFixed(3)} mHz</dd>
    </dl>
  </div>
</Panel>
