/** Memoized lazy loading of card components: one promise per type, so re-renders never reload or remount a card. */
import type { Component } from 'svelte';
import { REGISTRY } from './registry';

type Loaded = Component<any>;
const promises = new Map<string, Promise<Loaded>>();

/** The component loader for a type, called at most once per type. Undefined when the type has no component yet. */
export function loadComponent(type: string, registry = REGISTRY, cache = promises): Promise<Loaded> | undefined {
  const load = registry[type]?.component;
  if (!load) return undefined;
  let p = cache.get(type);
  if (!p) {
    p = load().then((m) => m.default);
    cache.set(type, p);
  }
  return p;
}
