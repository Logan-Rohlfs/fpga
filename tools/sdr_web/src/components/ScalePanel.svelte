<script lang="ts">
  // Waterfall scale is a per-viewer preference: Auto uses the server's display.WaterfallScale.
  import { notify } from '../lib/link';
  import { scaleOverride } from '../lib/view';
  import NumberField from './NumberField.svelte';
  import Panel from './Panel.svelte';
  import Segmented from './Segmented.svelte';

  let { current }: { current: [number, number] | null } = $props();
  const MODES: { value: 'auto' | 'manual'; text: string }[] = [{ value: 'auto', text: 'Auto' }, { value: 'manual', text: 'Manual' }];
  const shown = $derived($scaleOverride.mode === 'manual' ? [$scaleOverride.low, $scaleOverride.high] : (current ?? [-110, -45]));

  function setMode(mode: 'auto' | 'manual') {
    if (mode === 'auto') scaleOverride.set({ mode: 'auto' });
    else scaleOverride.set({ mode: 'manual', low: Math.round(shown[0]), high: Math.round(shown[1]) });
  }
  function setLimit(which: 'low' | 'high', v: number) {
    const s = $scaleOverride;
    if (s.mode !== 'manual') return;
    const next = { ...s, [which]: v };
    if (next.high - next.low < 5) {
      notify('The scale needs the peak at least 5 dB above the floor.', 'warn');
      return;
    }
    scaleOverride.set(next);
  }
</script>

<Panel title="Waterfall" sub="this device only">
  <div class="pb stack">
    <div class="field">
      <span class="label">Scale</span>
      <Segmented label="Waterfall scale" options={MODES} value={$scaleOverride.mode} onselect={setMode} />
    </div>
    <NumberField id="scale-low" label="Floor (dBFS)" value={shown[0]} disabled={$scaleOverride.mode === 'auto'}
      oncommit={(v) => setLimit('low', v)} />
    <NumberField id="scale-high" label="Peak (dBFS)" value={shown[1]} disabled={$scaleOverride.mode === 'auto'}
      oncommit={(v) => setLimit('high', v)} />
    <p class="note mono">Showing {shown[0].toFixed(0)} to {shown[1].toFixed(0)} dBFS ({$scaleOverride.mode}).</p>
  </div>
</Panel>

<style>
  .label { color: var(--muted); font-size: 13.5px; }
</style>
