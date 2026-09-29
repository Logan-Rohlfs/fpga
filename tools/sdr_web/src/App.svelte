<script lang="ts">
  import logoLight from './assets/space-raiders-logo.png';
  import logoDark from './assets/space-raiders-logo-on-dark.png';
</script>

<header class="top">
  <span class="brand">
    <img class="logo light" src={logoLight} alt="Space Raiders" />
    <img class="logo dark" src={logoDark} alt="Space Raiders" />
    <span class="product">SDR</span>
  </span>
</header>
<main class="pb"><p class="note">Connecting…</p></main>

<style>
  .top { display: flex; align-items: center; padding: 10px 16px; background: var(--panel); border-bottom: 1px solid var(--line); }
  .brand { display: flex; align-items: center; gap: 10px; }
  .logo { height: 22px; width: auto; }
  .logo.dark { display: var(--logo-dark); }
  .logo.light { display: var(--logo-light); }
  .product { font: 600 13px var(--f-ui); letter-spacing: 0.2em; color: var(--brand); border-left: 1px solid var(--line-2); padding-left: 10px; }
</style>
