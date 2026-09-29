/** Waterfall colormap: perceptual, monotonic lightness (same in both themes). */
const STOPS: [number, [number, number, number]][] = [
  [0, [4, 6, 18]], [0.22, [40, 18, 84]], [0.45, [122, 30, 108]],
  [0.65, [206, 64, 70]], [0.82, [248, 142, 30]], [1, [252, 250, 170]],
];

export const LUT: Uint8ClampedArray = (() => {
  const out = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    let k = 0;
    while (STOPS[k + 1][0] < t) k++;
    const [t0, a] = STOPS[k];
    const [t1, b] = STOPS[k + 1];
    const u = (t - t0) / (t1 - t0);
    for (let c = 0; c < 3; c++) out[i * 3 + c] = a[c] + (b[c] - a[c]) * u;
  }
  return out;
})();
