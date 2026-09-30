<script lang="ts">
  import type { Injection, TuningChanges, TuningMsg } from '../lib/types';
  import NumberField from './NumberField.svelte';
  import Panel from './Panel.svelte';
  import Segmented from './Segmented.svelte';

  let { t, disabled, ontune, fixedProfile = false }: { t: TuningMsg; disabled: boolean; fixedProfile?: boolean; ontune: (c: TuningChanges) => void } = $props();
  const SIDES: { value: Injection; text: string }[] = [{ value: 'low', text: 'Low' }, { value: 'high', text: 'High' }];
</script>

<Panel title="Receiver">
  <div class="pb stack">
    {#if fixedProfile}<p class="note">Injection, IF target and window describe the compiled receiver profile.</p>{/if}
    <div class="field">
      <span class="label">Mixer injection</span>
      <Segmented label="Mixer injection side" options={SIDES} value={t.state.injection} disabled={disabled || fixedProfile}
        onselect={(v) => ontune({ injection: v })} />
    </div>
    <NumberField id="carrier" label="Carrier (MHz)" value={t.state.carrier_hz} scale={1e6} digits={6} step={0.001}
      {disabled} oncommit={(v) => ontune({ carrier_hz: v })} />
    <NumberField id="target-if" label="Target IF (kHz)" value={t.state.target_if_hz} scale={1e3} digits={1} step={0.1}
      disabled={disabled || fixedProfile} oncommit={(v) => ontune({ target_if_hz: v })} />
    <NumberField id="window" label="XADC window ± (kHz)" value={t.state.window_hz} scale={1e3} digits={1} step={0.5}
      disabled={disabled || fixedProfile} oncommit={(v) => ontune({ window_hz: v })} />
  </div>
</Panel>

<style>
  .label { color: var(--muted); font-size: 13.5px; }
</style>
