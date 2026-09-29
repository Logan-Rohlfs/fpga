<script lang="ts">
  import CardGrid from '../components/CardGrid.svelte';
  import type { CardDef } from '../lib/cards';
  import ChannelsCard from './telemetry/ChannelsCard.svelte';
  import DeviceCard from './telemetry/DeviceCard.svelte';
  import FlightCard from './telemetry/FlightCard.svelte';
  import FrameLogCard from './telemetry/FrameLogCard.svelte';
  import LatestFrameCard from './telemetry/LatestFrameCard.svelte';
  import LinkCard from './telemetry/LinkCard.svelte';

  // v1 mirrors the terminal dashboard; ground-station plots replace these as real frames arrive.
  const CARDS: CardDef[] = [
    { id: 'latest', title: 'Latest frame', sub: 'BEST_TELEM', w: 2, h: 1, component: LatestFrameCard },
    { id: 'device', title: 'Device', sub: 'STATUS · 1 Hz', w: 1, h: 2, component: DeviceCard },
    { id: 'link', title: 'Link', sub: 'LINK_STATS', w: 1, h: 2, component: LinkCard },
    { id: 'channels', title: 'Channels', sub: 'CHAN_METRICS', w: 2, h: 1, component: ChannelsCard },
    { id: 'flight', title: 'Flight data', sub: 'APEX FLIGHT', w: 2, h: 2, component: FlightCard },
    { id: 'log', title: 'Frame log', sub: 'CHAN_FRAME A/B', w: 2, h: 2, component: FrameLogCard },
  ];
</script>

<CardGrid cards={CARDS} storageKey="sdr.telemetry.layout" />
