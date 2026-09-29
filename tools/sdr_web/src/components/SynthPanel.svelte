<script lang="ts">
  import { hzText, mhz } from '../lib/format';
  import type { TuningChanges, TuningMsg } from '../lib/types';
  import NumberField from './NumberField.svelte';
  import Panel from './Panel.svelte';
  import SelectField from './SelectField.svelte';

  let { t, disabled, ontune }: { t: TuningMsg; disabled: boolean; ontune: (c: TuningChanges) => void } = $props();
  const OUT_DIVS = [1, 2, 4, 8, 16, 32, 64] as const;   // freqplan.OUT_DIVS
  const s = $derived(t.state);
  const d = $derived(t.derived);
  const vcoOk = $derived(d.vco_hz >= s.vco_min_hz && d.vco_hz <= s.vco_max_hz);
</script>

<Panel title="LO synthesizer">
  {#snippet actions()}<span class="tag" title="The synthesizer part is not chosen yet">generic frac-N</span>{/snippet}
  <div class="pb stack">
    <NumberField id="ref" label="Reference (MHz)" value={s.ref_hz} scale={1e6} digits={3} step={0.001} {disabled}
      oncommit={(v) => ontune({ ref_hz: v })} />
    <NumberField id="rdiv" label="R divider" value={s.r_div} {disabled} oncommit={(v) => ontune({ r_div: v })} />
    <NumberField id="nint" label="N (integer)" value={s.n_int} {disabled} oncommit={(v) => ontune({ n_int: v })} />
    <NumberField id="frac" label="FRAC" value={s.frac} {disabled} oncommit={(v) => ontune({ frac: v })} />
    <NumberField id="mod" label="MOD" value={s.mod} {disabled} oncommit={(v) => ontune({ mod: v })} />
    <SelectField id="odiv" label="Output divider" value={s.out_div} options={OUT_DIVS} {disabled}
      oncommit={(v) => ontune({ out_div: v })} />
    <NumberField id="vco-min" label="VCO min (MHz)" value={s.vco_min_hz} scale={1e6} {disabled}
      oncommit={(v) => ontune({ vco_min_hz: v })} />
    <NumberField id="vco-max" label="VCO max (MHz)" value={s.vco_max_hz} scale={1e6} {disabled}
      oncommit={(v) => ontune({ vco_max_hz: v })} />
    <dl class="derived">
      <dt>PFD</dt><dd>{mhz(d.pfd_hz, 3)} MHz</dd>
      <dt>VCO</dt><dd>{mhz(d.vco_hz, 3)} MHz</dd>
      <dt>LO step</dt><dd>{hzText(d.lo_step_hz)}</dd>
      <dt>VCO range</dt><dd>{#if vcoOk}<span class="chip good">in range</span>{:else}<span class="chip bad">out of range</span>{/if}</dd>
    </dl>
  </div>
</Panel>
