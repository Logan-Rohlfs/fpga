<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import logoLight from './assets/space-raiders-logo.png';
  import logoDark from './assets/space-raiders-logo-on-dark.png';
  import Notices from './components/Notices.svelte';
  import RoleMenu from './components/RoleMenu.svelte';
  import StatusBar from './components/StatusBar.svelte';
  import { connection, frozen, hello, link, stats } from './lib/link';
  import { bindFrozen } from './lib/frame';
  import { connectionBanner } from './lib/status';
  import { channelsFor } from './lib/subscriptions';
  import { type ThemeChoice, applyTheme, loadTheme, nextTheme, refreshAppearance } from './lib/theme';
  import { telemetryChannels, tuneChannel } from './lib/view';
  import { enterFullscreen, exitFullscreen, fullscreen } from './lib/fullscreen';
  import Telemetry from './pages/Telemetry.svelte';
  import Tune from './pages/Tune.svelte';

  const PAGES = [{ id: 'tune', text: 'Tune' }, { id: 'telemetry', text: 'Telemetry' }] as const;
  type PageId = (typeof PAGES)[number]['id'];
  const fromHash = (): PageId => (location.hash === '#telemetry' ? 'telemetry' : 'tune');

  let page = $state<PageId>(fromHash());
  let theme = $state<ThemeChoice>(loadTheme());
  let hidden = $state(document.hidden);
  const banner = $derived(connectionBanner($connection, $stats?.source ?? $hello?.source));
  // Full screen is a Telemetry-only view: the header goes, the cards take the whole window.
  const full = $derived(page === 'telemetry' && $fullscreen);
  $effect(() => { if (page !== 'telemetry' && $fullscreen) exitFullscreen(); });

  $effect(() => {
    link.setSubscriptions(channelsFor(page, { tuneChannel: $tuneChannel, cardChannels: $telemetryChannels, hidden }));
  });

  onMount(() => {
    const unbindFrozen = bindFrozen(frozen);
    link.start();
    const media = matchMedia('(prefers-color-scheme: light)');
    media.addEventListener('change', refreshAppearance);
    document.fonts.ready.then(refreshAppearance);
    const onHash = () => (page = fromHash());
    const onVisibility = () => (hidden = document.hidden);
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = !!t.closest('input, select, textarea, [contenteditable], [role="spinbutton"]');
      if (e.code === 'Space' && !typing && !t.closest('button')) {
        e.preventDefault();
        frozen.update((f) => !f);
      } else if (e.key.toLowerCase() === 'f' && !typing && !e.ctrlKey && !e.metaKey && !e.altKey && page === 'telemetry') {
        e.preventDefault();
        if (get(fullscreen)) exitFullscreen(); else enterFullscreen();
      } else if (e.key === 'Escape' && get(fullscreen) && !document.fullscreenElement && !t.closest('[role="dialog"]')) {
        exitFullscreen();
      }
    };
    // Leaving the browser's full screen (Esc, or its own UI) leaves the mode too.
    let browserFull = false;
    const onFullChange = () => {
      if (document.fullscreenElement) browserFull = true;
      else if (browserFull) { browserFull = false; fullscreen.set(false); }
    };
    document.addEventListener('fullscreenchange', onFullChange);
    addEventListener('hashchange', onHash);
    addEventListener('keydown', onKey);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      document.removeEventListener('fullscreenchange', onFullChange);
      removeEventListener('hashchange', onHash);
      removeEventListener('keydown', onKey);
      media.removeEventListener('change', refreshAppearance);
      link.stop();
      unbindFrozen();
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

{#if !full}
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
      title="Freeze the display (Space). Data keeps arriving.">{$frozen ? 'Frozen' : 'Freeze'}</button>
    <button class="btn" onclick={cycleTheme} title="Theme: follow the system, dark, or light">
      {theme === 'system' ? 'Auto' : theme === 'dark' ? 'Dark' : 'Light'}
    </button>
    <RoleMenu />
  </div>
</header>
{:else}
  <button class="exit-full" onclick={exitFullscreen} title="Exit full screen (F or Esc)">Exit full screen</button>
{/if}

{#if banner}<p class="connection-note {banner.level}" role="status">{banner.text}</p>{/if}
<main class:stale={!!banner} class:full>
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
  .connection-note { margin: 0; padding: 8px 16px; color: var(--muted); background: var(--panel); }
  .connection-note.warn { color: var(--warn); }
  .connection-note.bad { color: var(--bad); }
  main { padding: 14px 16px 24px; }
  main.full { padding: 8px; }
  .exit-full { position: fixed; top: 8px; left: 50%; transform: translateX(-50%); z-index: 20; padding: 4px 12px; font: 600 11px var(--f-ui);
    letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); background: color-mix(in srgb, var(--panel) 85%, transparent);
    border: 1px solid var(--line-2); border-radius: 999px; cursor: pointer; opacity: 0; transition: opacity 0.2s; }
  .exit-full:hover, .exit-full:focus-visible { opacity: 1; color: var(--fg); }
  /* Touch screens have no hover, so the button stays faintly visible there. */
  @media (hover: none) { .exit-full { opacity: 0.6; } }
  @media (max-width: 700px) { .status { margin-left: 0; } }
</style>
