import { describe, expect, it } from 'vitest';
import preset from '../../../../sdr_cli/presets/flight.json';
import { reflow, sanitizeGrid } from '../grid';
import { cardChannels, minOfType, sanitizeConfig } from './registry';

const cards = preset.cards as unknown as { id: string; type: string; x: number; y: number; w: number; h: number; title: string | null; config: Record<string, unknown> }[];

describe('default Flight preset', () => {
  it('identifies itself and has no triggers', () => {
    expect(preset.id).toBe('flight');
    expect(preset.name).toBe('Flight');
    expect(preset.grid.cols).toBe(24);
    expect(preset.triggers).toEqual([]);
  });

  it('carries complete configs: sanitize leaves each unchanged', () => {
    for (const c of cards) expect(sanitizeConfig(c.type, c.config), c.id).toEqual(c.config);
  });

  it('keeps every position without overlap or repair', () => {
    expect(sanitizeGrid(cards, minOfType).map(({ id, x, y, w, h }) => ({ id, x, y, w, h })))
      .toEqual(cards.map(({ id, x, y, w, h }) => ({ id, x, y, w, h })));
  });

  it('subscribes to the expected channels', () => {
    expect(cardChannels(cards)).toEqual(['events', 'flight', 'link', 'spectrum.A', 'spectrum.B']);
  });

  it('starts the one-column layout with the state card', () => {
    expect(reflow(cards, 1, minOfType)[0].type).toBe('state');
  });
});
