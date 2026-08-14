/** Stable per-drone accent colors: golden-angle hues so neighbors differ. */

export function slotColor(sysid: number): number {
  const hue = ((sysid - 1) * 137.508) % 360;
  return hslToHex(hue, 0.7, 0.62);
}

export function hslToHex(h: number, s: number, l: number): number {
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    return l - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1)));
  };
  return (Math.round(f(0) * 255) << 16) | (Math.round(f(8) * 255) << 8) |
    Math.round(f(4) * 255);
}
