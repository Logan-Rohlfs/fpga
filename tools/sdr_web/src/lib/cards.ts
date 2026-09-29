import type { Component } from 'svelte';

/** A Telemetry card: default span (w columns × h rows) and the component that fills it. */
export interface CardDef { id: string; title: string; sub: string; w: number; h: number; component: Component }
