import { writable } from 'svelte/store';

// Redraw canvases when CSS colours or bundled fonts change, including while frozen.
export const appearanceVersion = writable(0);
export const refreshAppearance = () => appearanceVersion.update(v => v + 1);

export type ThemeChoice = 'system' | 'dark' | 'light';

const KEY = 'sdr.theme';

export function loadTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'dark' || v === 'light' ? v : 'system';
  } catch {
    return 'system';
  }
}

export function applyTheme(choice: ThemeChoice): void {
  refreshAppearance();
  const root = document.documentElement;
  if (choice === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', choice);
  try {
    localStorage.setItem(KEY, choice);
  } catch {
    /* per-device convenience only */
  }
}

export const nextTheme = (c: ThemeChoice): ThemeChoice => (c === 'system' ? 'dark' : c === 'dark' ? 'light' : 'system');
