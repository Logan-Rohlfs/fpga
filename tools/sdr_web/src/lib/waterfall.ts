import { LUT } from './colormap';

/** Write one spectrum row (dBFS×10) into RGBA pixels using the low..high dBFS scale. */
export function paintRow(out: Uint8ClampedArray, db10: ArrayLike<number>, low: number, high: number): void {
  const span = high - low || 1;
  for (let k = 0; k < db10.length; k++) {
    const n = Math.min(1, Math.max(0, (db10[k] / 10 - low) / span));
    const i = Math.round(n * 255) * 3;
    out[k * 4] = LUT[i];
    out[k * 4 + 1] = LUT[i + 1];
    out[k * 4 + 2] = LUT[i + 2];
    out[k * 4 + 3] = 255;
  }
}

/** Scrolling offscreen image: one pixel column per bin, newest row on top. */
export class WaterfallImage {
  readonly canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private row: ImageData;

  constructor(readonly bins: number, readonly rows: number) {
    this.canvas = document.createElement('canvas');
    this.canvas.width = bins;
    this.canvas.height = rows;
    this.ctx = this.canvas.getContext('2d')!;
    this.ctx.fillStyle = '#04060f';
    this.ctx.fillRect(0, 0, bins, rows);
    this.row = this.ctx.createImageData(bins, 1);
  }

  push(db10: ArrayLike<number>, low: number, high: number): void {
    this.ctx.drawImage(this.canvas, 0, 0, this.bins, this.rows - 1, 0, 1, this.bins, this.rows - 1);
    paintRow(this.row.data, db10, low, high);
    this.ctx.putImageData(this.row, 0, 0);
  }
}
