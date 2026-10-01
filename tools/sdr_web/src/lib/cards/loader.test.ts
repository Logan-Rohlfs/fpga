import { describe, expect, it, vi } from 'vitest';
import { loadComponent } from './loader';
import type { CardMeta } from './registry';

describe('loadComponent', () => {
  it('calls each type loader once and returns the same promise', async () => {
    const comp = () => null;
    const component = vi.fn(async () => ({ default: comp as never }));
    const registry = { plot: { component } as unknown as CardMeta, camera: {} as CardMeta };
    const cache = new Map();
    const a = loadComponent('plot', registry, cache);
    expect(loadComponent('plot', registry, cache)).toBe(a);
    expect(await a).toBe(comp);
    expect(component).toHaveBeenCalledTimes(1);
  });
  it('is undefined for types without a component or unknown types', () => {
    expect(loadComponent('camera', { camera: {} as CardMeta }, new Map())).toBeUndefined();
    expect(loadComponent('nope', {}, new Map())).toBeUndefined();
  });
});
