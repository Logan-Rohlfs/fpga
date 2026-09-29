<script lang="ts">
  import { onMount } from 'svelte';
  import logoLight from './assets/space-raiders-logo.png';
  import logoDark from './assets/space-raiders-logo-on-dark.png';
  import Notices from './components/Notices.svelte';
  import RoleMenu from './components/RoleMenu.svelte';
  import StatusBar from './components/StatusBar.svelte';
  import { connection, frozen, link, stats } from './lib/link';
  import { type ThemeChoice, applyTheme, loadTheme, nextTheme, refreshAppearance } from './lib/theme';
  import Telemetry from './pages/Telemetry.svelte';
  import Tune from './pages/Tune.svelte';

  const PAGES = [{ id: 'tune', text: 'Tune' }, { id: 'telemetry', text: 'Telemetry' }] as const;
  type PageId = (typeof PAGES)[number]['id'];
  const fromHash = (): PageId => (location.hash === '#telemetry' ? 'telemetry' : 'tune');

  let page = $state<PageId>(fromHash());
  let theme = $state<ThemeChoice>(loadTheme());

  onMount(() => {
    link.start();
    const media = matchMedia('(prefers-color-scheme: light)');
    media.addEventListener('change', refreshAppearance);
    document.fonts.ready.then(refreshAppearance);
    const onHash = () => (page = fromHash());
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.code === 'Space' && !t.closest('input, select, textarea, button, [role="spinbutton"]')) {
        e.preventDefault();
        frozen.update((f) => !f);
      }
    };
    addEventListener('hashchange', onHash);
    addEventListener('keydown', onKey);
    return () => {
      removeEventListener('hashchange', onHash);
      removeEventListener('keydown', onKey);
      media.removeEventListener('change', refreshAppearance);
      link.stop();
    };
  });

  function go(id: PageId) {
    location.hash = id;
    page = id;
  }
  function cycleTheme() {
    theme = nextTheme(theme);
    applyTheme(theme);
  }
</script>

<header class="top">
  <a class="brand" href="#tune" onclick={() => go('tune')} aria-label="Space Raiders SDR home">
    <img class="logo light" src={logoLight} alt="Space Raiders" />
    <img class="logo dark" src={logoDark} alt="Space Raiders" />
    <span class="product">SDR</span>
  </a>
  <nav class="tabs" aria-label="Pages">
    {#each PAGES as p (p.id)}
      <button aria-current={page === p.id ? 'page' : undefined} onclick={() => go(p.id)}>{p.text}</button>
    {/each}
  </nav>
  <div class="status">
    <StatusBar />
    <button class="btn" aria-pressed={$frozen} onclick={() => frozen.update((f) => !f)}
      title="Freeze the display (Space). Receiving continues.">{$frozen ? 'Frozen' : 'Freeze'}</button>
    <button class="btn" onclick={cycleTheme} title="Theme: follow the system, dark, or light">
      {theme === 'system' ? 'Auto' : theme === 'dark' ? 'Dark' : 'Light'}
    </button>
    <RoleMenu />
  </div>
</header>

{#if $connection !== 'open'}<p class="connection-note" role="status">Disconnected — retrying. Showing last received data.</p>
{:else if $stats && $stats.source.state !== 'running'}<p class="connection-note" role="status">Source {$stats.source.state}: {$stats.source.detail}. Showing last received data.</p>{/if}
<main class:stale={$connection !== 'open' || (!!$stats && $stats.source.state !== 'running')}>
  {#if page === 'tune'}<Tune />{:else}<Telemetry />{/if}
</main>
<Notices />

<style>
  .top { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 10; display: flex; flex-wrap: wrap; align-items: center;
    gap: 10px 20px; padding: 10px 16px; background: var(--panel); border-bottom: 1px solid var(--line); }
  .brand { display: flex; align-items: center; gap: 10px; text-decoration: none; color: inherit; }
  .logo { height: 22px; width: auto; }
  .logo.dark { display: var(--logo-dark); }
  .logo.light { display: var(--logo-light); }
  .product { font: 600 13px var(--f-ui); letter-spacing: 0.2em; color: var(--brand); border-left: 1px solid var(--line-2); padding-left: 10px; }
  .tabs { display: flex; gap: 2px; background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 2px; }
  .tabs button { border: 0; background: none; padding: 6px 16px; border-radius: 4px; cursor: pointer; font: 600 13px var(--f-ui);
    letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); }
  .tabs button[aria-current='page'] { background: var(--panel-2); color: var(--fg); box-shadow: inset 0 -2px 0 var(--brand); }
  .status { margin-left: auto; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .stale { opacity: 0.55; }
  .connection-note { margin: 0; padding: 8px 16px; color: var(--warn); background: var(--panel); }
  main { padding: 14px 16px 24px; }
  @media (max-width: 700px) { .status { margin-left: 0; } }
</style>
