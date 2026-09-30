import { describe, expect, it } from 'vitest';
import { channelsFor } from './subscriptions';

describe('channelsFor', () => {
  it('subscribes Tune to its shown spectrum, both IQ channels and link', () => {
    expect(channelsFor('tune', { tuneChannel: 'B', cardChannels: [], hidden: false }))
      .toEqual(['events', 'flight', 'iq.A', 'iq.B', 'link', 'spectrum.B']);
  });

  it('drops spectrum and IQ while the page is hidden', () => {
    expect(channelsFor('telemetry', { tuneChannel: 'A', cardChannels: ['spectrum.A', 'frames'], hidden: true }))
      .toEqual(['events', 'flight', 'frames']);
    expect(channelsFor('tune', { tuneChannel: 'A', cardChannels: [], hidden: true }))
      .toEqual(['events', 'flight', 'link']);
  });

  it('is sorted and unique on Telemetry', () => {
    expect(channelsFor('telemetry', { tuneChannel: 'A', cardChannels: ['link', 'frames', 'link', 'flight'], hidden: false }))
      .toEqual(['events', 'flight', 'frames', 'link']);
  });
});
