/** The pilot's own coins, from their drone row's `pilot` field (siege). */

const ROMAN = ["", "I", "II", "III", "IV", "V"];
const TIERS = ["zap", "speed", "tower"] as const;

/** "12 coins" / "1 coin", or "" when the mission publishes no wallet. */
export function walletText(pilot: Record<string, unknown> | undefined): string {
  const coins = pilot?.wallet;
  if (typeof coins !== "number" || !Number.isFinite(coins)) return "";
  const n = Math.max(0, Math.round(coins));
  return `🪙 ${n} coin${n === 1 ? "" : "s"}`;
}

/** " · zap II · speed I" for bought tiers, "" when none (or no shop). */
export function upgradesText(pilot: Record<string, unknown> | undefined): string {
  if (!pilot) return "";
  const parts: string[] = [];
  for (const item of TIERS) {
    const tier = pilot[item];
    if (typeof tier === "number" && tier >= 1) {
      parts.push(`${item} ${ROMAN[Math.min(ROMAN.length - 1, Math.floor(tier))]}`);
    }
  }
  return parts.map((p) => ` · ${p}`).join("");
}
