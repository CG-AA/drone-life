/** The pilot's own coins, from their drone row's `pilot` field (siege). */

/** "12 coins" / "1 coin", or "" when the mission publishes no wallet. */
export function walletText(pilot: Record<string, unknown> | undefined): string {
  const coins = pilot?.wallet;
  if (typeof coins !== "number" || !Number.isFinite(coins)) return "";
  const n = Math.max(0, Math.round(coins));
  return `🪙 ${n} coin${n === 1 ? "" : "s"}`;
}
