export const mhz = (hz: number, digits = 6) => (hz / 1e6).toFixed(digits);
export const khz = (hz: number, digits = 1) => `${(hz / 1e3).toFixed(digits)} kHz`;
export const signedKhz = (hz: number, digits = 1) => `${hz >= 0 ? '+' : '−'}${Math.abs(hz / 1e3).toFixed(digits)} kHz`;
export const hzText = (hz: number) => (Math.abs(hz) >= 1e3 ? khz(hz, 3) : `${hz.toFixed(1)} Hz`);
export const hex32 = (v: number) => '0x' + (v >>> 0).toString(16).toUpperCase().padStart(8, '0');
export const clockTime = (epochS: number) =>
  new Date(epochS * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
