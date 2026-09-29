import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { connection, LinkClient, role, resetState } from './link';

class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 1;
  sent: any[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: {data: string}) => void) | null = null;
  constructor(public url: string) { Socket.instances.push(this); }
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; this.onclose?.(); }
}
let client: LinkClient;
beforeEach(() => {
  vi.useFakeTimers(); vi.stubGlobal('WebSocket', Socket); Socket.instances = []; resetState();
  client = new LinkClient(); client.start('ws://test/ws'); Socket.instances[0].onopen?.();
  role.set({type:'role', role:'admin', admin:null, can_admin:true, reason:'login'});
});
afterEach(() => { client.stop(); vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });
it('does not reconnect after stopping during the retry delay', () => {
  Socket.instances[0].close(); client.stop(); vi.advanceTimersByTime(9000);
  expect(Socket.instances).toHaveLength(1);
});
it('cancels pending tuning on logout', () => {
  client.tune({nco_hz:100}); client.tune({nco_hz:200}); client.logout(); vi.advanceTimersByTime(100);
  expect(Socket.instances[0].sent.filter(m => m.type === 'tune')).toEqual([{type:'tune',changes:{nco_hz:100}}]);
});
it('rejects tuning while disconnected and resets the role on drop', () => {
  Socket.instances[0].close(); client.tune({nco_hz:300});
  expect(get(connection)).toBe('closed'); expect(get(role)?.role).not.toBe('admin');
  vi.advanceTimersByTime(500); Socket.instances[1].onopen?.(); vi.advanceTimersByTime(100);
  expect(Socket.instances[1].sent.filter(m => m.type==='tune')).toEqual([]);
});
it('starts only one connection even when called twice', () => {
  client.start('ws://test/ws'); expect(Socket.instances).toHaveLength(1);
});
it('limits default tune sends to 30 per second', () => {
  for(let i=0;i<1000;i++){ client.tune({nco_hz:i}); vi.advanceTimersByTime(1); }
  expect(Socket.instances[0].sent.length).toBeLessThanOrEqual(30);
});
