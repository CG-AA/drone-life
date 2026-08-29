/** Stable per-drone accent colors: golden-angle hues so neighbors differ,
 * lifted until each one is legible on the arena floor. */

/** The floor drones and their name tags are read against — mirrors
 * COLORS.floor in shared/theme.ts (--bg-panel). */
const FLOOR = 0x151b28;

/** WCAG AA for the tag text, which is small. */
const MIN_CONTRAST = 4.5;

export function slotColor(sysid: number): number {
  const hue = ((sysid - 1) * 137.508) % 360;
  // A single lightness can't serve every hue: at l=0.62 a yellow lands near
  // 11:1 on the floor while a blue-violet sits at 3.3:1, below AA and the
  // first thing a washed-out projector loses. Walk the hue up until it clears.
  for (let l = 0.62; l < 0.85; l += 0.02) {
    const c = hslToHex(hue, 0.7, l);
    if (contrastRatio(c, FLOOR) >= MIN_CONTRAST) return c;
  }
  return hslToHex(hue, 0.7, 0.85); // every hue clears AA well before here
}

/** WCAG relative luminance of a packed 24-bit color. */
export function relativeLuminance(rgb: number): number {
  const chan = (v: number): number => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * chan((rgb >> 16) & 0xff) +
    0.7152 * chan((rgb >> 8) & 0xff) +
    0.0722 * chan(rgb & 0xff);
}

/** WCAG contrast ratio between two packed colors: 1 (identical) to 21. */
export function contrastRatio(a: number, b: number): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** "#rrggbb" (any case) → packed 24-bit color, or null for anything else —
 * the wire carries a pilot's bought colour as text, and a bad one must fall
 * back to the slot colour rather than paint the drone black. */
export function parseHex(text: unknown): number | null {
  if (typeof text !== "string") return null;
  const m = /^#([0-9a-f]{6})$/i.exec(text.trim());
  return m ? parseInt(m[1], 16) : null;
}

function hslToHex(h: number, s: number, l: number): number {
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    return l - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1)));
  };
  return (Math.round(f(0) * 255) << 16) | (Math.round(f(8) * 255) << 8) |
    Math.round(f(4) * 255);
}
