<script lang="ts">
  // Per-type settings form, generated from the card meta's `settings` descriptor. Every edit is run through the
  // type's sanitize before it is reported, so a bad value cannot leave the form. Viewers get it read-only.
  import { REGISTRY, SERIES_SOURCES, type Config, type SettingField } from '../lib/cards/registry';
  import { flightSchema } from '../lib/link';
  import { quantityNames, unitOptions } from '../lib/units';

  let { type, title, config, readonly, onchange }: {
    type: string; title: string | null; config: Config; readonly: boolean;
    onchange: (next: { title: string | null; config: Config }) => void;
  } = $props();

  const meta = $derived(REGISTRY[type]);
  const fields = $derived($flightSchema?.fields ?? []);
  const METRICS = ['m.rssi', 'm.noise', 'm.snr', 'm.df'];
  const SOURCE_LABELS: Record<string, string> = { best: 'Best', A: 'A', B: 'B', both: 'A and B' };
  const quantities = quantityNames().filter((q) => unitOptions(q).length > 1);
  const id = (key: string) => `cs-${type}-${key}`;

  function set(key: string, value: unknown) {
    onchange({ title, config: meta.sanitize({ ...config, [key]: value }) });
  }
  function onTitle(value: string) {
    onchange({ title: value.trim() === '' ? null : value.slice(0, 40), config });
  }
  function selectValue(f: SettingField, raw: string) {
    const o = f.options?.find((x) => String(x.value) === raw);
    set(f.key, o ? o.value : raw);
  }
  function series(): { field: string; source: string }[] {
    return (config.series as { field: string; source: string }[]) ?? [];
  }
  function setSeries(i: number, patch: Partial<{ field: string; source: string }>) {
    set('series', series().map((s, j) => (j === i ? { ...s, ...patch } : s)));
  }
  const units = () => (config.units as Record<string, string>) ?? {};
  function setUnit(q: string, u: string) {
    const next = { ...units() };
    if (u) next[q] = u;
    else delete next[q];
    set('units', next);
  }
</script>

{#if !meta}
  <p class="note">Unsupported card type '{type}'. Its settings are kept as they are.</p>
{:else}
  <div class="stack">
    {#if readonly}<p class="note">Read-only. The operator can change card settings.</p>{/if}
    <div class="field">
      <label for={id('title')}>Title</label>
      <input id={id('title')} type="text" maxlength="40" disabled={readonly} placeholder={meta.title}
        value={title ?? ''} onchange={(e) => onTitle(e.currentTarget.value)} />
    </div>
    {#each meta.settings as f (f.key)}
      {#if f.kind === 'select'}
        <div class="field">
          <label for={id(f.key)}>{f.label}</label>
          <select id={id(f.key)} disabled={readonly} value={String(config[f.key])}
            onchange={(e) => selectValue(f, e.currentTarget.value)}>
            {#each f.options ?? [] as o (o.value)}<option value={String(o.value)}>{o.label}</option>{/each}
          </select>
        </div>
      {:else if f.kind === 'number'}
        <div class="field">
          <label for={id(f.key)}>{f.label}</label>
          <input id={id(f.key)} type="number" min={f.min} max={f.max} disabled={readonly}
            value={config[f.key] ?? ''}
            onchange={(e) => set(f.key, e.currentTarget.value === '' ? null : e.currentTarget.valueAsNumber)} />
        </div>
      {:else if f.kind === 'bool'}
        <div class="field">
          <label for={id(f.key)}>{f.label}</label>
          <input id={id(f.key)} type="checkbox" disabled={readonly} checked={config[f.key] === true}
            onchange={(e) => set(f.key, e.currentTarget.checked)} />
        </div>
      {:else if f.kind === 'text'}
        <div class="field">
          <label for={id(f.key)}>{f.label}</label>
          <input id={id(f.key)} type="text" disabled={readonly} value={(config[f.key] as string | null) ?? ''}
            onchange={(e) => set(f.key, e.currentTarget.value.trim() === '' ? null : e.currentTarget.value.trim())} />
        </div>
      {:else if f.kind === 'field'}
        <div class="field">
          <label for={id(f.key)}>{f.label}</label>
          <select id={id(f.key)} disabled={readonly} value={String(config[f.key])}
            onchange={(e) => set(f.key, e.currentTarget.value)}>
            {#if !fields.some((x) => x.key === config[f.key])}<option value={String(config[f.key])}>{config[f.key]}</option>{/if}
            {#each fields as x (x.key)}<option value={x.key}>{x.label}</option>{/each}
          </select>
        </div>
      {:else if f.kind === 'series'}
        <fieldset class="series">
          <legend>{f.label} (up to 6)</legend>
          {#each series() as s, i (i)}
            <div class="row">
              <select aria-label="Series {i + 1} field" disabled={readonly} value={s.field}
                onchange={(e) => setSeries(i, { field: e.currentTarget.value })}>
                {#if !fields.some((x) => x.key === s.field) && !METRICS.includes(s.field)}<option value={s.field}>{s.field}</option>{/if}
                {#each fields as x (x.key)}<option value={x.key}>{x.label}</option>{/each}
                {#each METRICS as m (m)}<option value={m}>Link {m.slice(2)}</option>{/each}
              </select>
              <select aria-label="Series {i + 1} source" disabled={readonly} value={s.source}
                onchange={(e) => setSeries(i, { source: e.currentTarget.value })}>
                {#each SERIES_SOURCES as src (src)}<option value={src}>{SOURCE_LABELS[src]}</option>{/each}
              </select>
              {#if !readonly}<button class="btn" aria-label="Remove series {i + 1}" disabled={series().length <= 1}
                onclick={() => set('series', series().filter((_, j) => j !== i))}>Remove</button>{/if}
            </div>
          {/each}
          {#if !readonly}<button class="btn" disabled={series().length >= 6}
            onclick={() => set('series', [...series(), { field: fields[0]?.key ?? 'alt_agl_m', source: 'best' }])}>Add series</button>{/if}
        </fieldset>
      {:else if f.kind === 'units'}
        <fieldset class="series">
          <legend>{f.label} (blank follows the viewer)</legend>
          {#each quantities as q (q)}
            <div class="field">
              <label for={id(`unit-${q}`)}>{q.replace('_', ' ')}</label>
              <select id={id(`unit-${q}`)} disabled={readonly} value={units()[q] ?? ''}
                onchange={(e) => setUnit(q, e.currentTarget.value)}>
                <option value="">Viewer default</option>
                {#each unitOptions(q) as u (u.id)}<option value={u.id}>{u.label}</option>{/each}
              </select>
            </div>
          {/each}
        </fieldset>
      {/if}
    {/each}
  </div>
{/if}

<style>
  .field input[type='checkbox'] { width: auto; justify-self: end; }
  .series { border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; display: grid; gap: 6px; margin: 0; }
  .series legend { font-size: 13px; color: var(--muted); padding: 0 4px; }
  .series select { background: var(--bg); border: 1px solid var(--line-2); border-radius: 4px; padding: 3px 7px; font: 13px var(--f-mono); }
</style>
