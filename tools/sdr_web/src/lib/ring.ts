/** Fixed-size history (sparklines). */
export class Ring {
  private buf: number[] = [];
  constructor(readonly size: number) {}
  push(v: number): void {
    this.buf.push(v);
    if (this.buf.length > this.size) this.buf.shift();
  }
  values(): readonly number[] {
    return this.buf;
  }
  get last(): number | undefined {
    return this.buf[this.buf.length - 1];
  }
  clear(): void {
    this.buf = [];
  }
}
