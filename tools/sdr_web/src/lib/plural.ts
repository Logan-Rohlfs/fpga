/** "1 viewer" / "2 viewers". */
export function countLabel(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? '' : 's'}`;
}
