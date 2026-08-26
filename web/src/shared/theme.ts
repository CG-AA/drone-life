/** Canvas-side mirror of the design tokens in theme.css — keep them in sync
 * (same contract as hex.ts ↔ hex.py: one source per language, one comment tie).
 */

export const COLORS = {
  bg: 0x0e1116,           // --bg
  floor: 0x151b28,        // --bg-panel
  grid: 0x263149,
  gridBorder: 0x3b4a6b,
  ink: 0x0b0e14,          // dark outlines on sprites
  label: 0x7b8dad,        // grid coordinate labels
  labelBright: 0x8ea3c7,  // N/E axis arrows
  accent: 0x4a9eff,       // --accent
  ok: 0x4ade80,           // --ok
  danger: 0xff5c5c,       // --danger
  gold: 0xffd23f,         // --gold
  warn: 0xffb347,         // --warn
  disarmed: 0x39445c,     // drone hull when disarmed
} as const;

export const FONT_UI =
  'system-ui, "Segoe UI", Roboto, "Helvetica Neue", sans-serif'; // --font-ui

/** Gate for decorative motion (flickers, pulses). Position/score updates are
 * meaningful motion and stay; ~4 Hz flicker effects must respect this. */
export const REDUCED_MOTION =
  typeof matchMedia !== "undefined" &&
  matchMedia("(prefers-reduced-motion: reduce)").matches;
