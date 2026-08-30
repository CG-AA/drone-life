/** REST helpers for the instructor page. Admin token lives in sessionStorage —
 * deliberately not localStorage, since instructor machines are often shared. */

import { request } from "../shared/http";
import type { AdminInfo, BanList, BotsResult, Health, RestartResult, Roster } from "../shared/protocol";

export { ApiFailure } from "../shared/http";

const TOKEN_KEY = "dl_admin_token";

export const getToken = (): string => sessionStorage.getItem(TOKEN_KEY) ?? "";

/** Why a pasted token cannot be the token, or null when it could be. An
 * ADMIN_TOKEN is printable ASCII (openssl rand -base64); anything else would
 * make fetch() reject the header before the request leaves the browser, which
 * the console then misreported as a server outage. The commonest paste is a
 * row of password-mask bullets copied from a masked field. */
export function tokenProblem(raw: string): string | null {
  if (!raw) return "paste the admin token";
  if (/[\u2022\u25cf\u00b7*]{3,}/.test(raw)) {
    return "that is the masked dots, not the token — reveal or copy the plain text";
  }
  if (!/^[\x21-\x7e]+$/.test(raw)) {
    return "the token is plain ASCII with no spaces — check what got pasted";
  }
  return null;
}
export const setToken = (t: string): void => sessionStorage.setItem(TOKEN_KEY, t);
export const clearToken = (): void => sessionStorage.removeItem(TOKEN_KEY);

function admin<T>(method: string, path: string, body?: unknown): Promise<T> {
  return request<T>(method, `/api/v1/admin${path}`, { "X-Admin-Token": getToken() }, body);
}

export const fetchRoster = () => admin<Roster>("GET", "/students");
// /healthz sits outside the admin router and takes no token
export const fetchHealth = () => request<Health>("GET", "/healthz", {});
export const killScript = (studentId: string) =>
  admin<{ stopped: boolean }>("POST", "/kill", { student_id: studentId });
export const kickStudent = (studentId: string) =>
  admin<{ ok: boolean }>("POST", "/kick", { student_id: studentId });
export const banStudent = (studentId: string) =>
  admin<{ ok: boolean; address_locked: boolean }>("POST", "/ban", { student_id: studentId });
export const resetWorld = () => admin<{ ok: boolean; epoch: number }>("POST", "/reset");
export const spawnBots = (count: number, mode: string, script: string) =>
  admin<BotsResult>("POST", "/bots", { count, mode, script });

export const fetchInfo = () => admin<AdminInfo>("GET", "/info");
/** mission null: restart into whatever boots today; keepScore: SESSION_PLAN Box B */
export const restartServer = (mission: string | null, keepScore: boolean) =>
  admin<RestartResult>("POST", "/restart", { mission, keep_score: keepScore });
export const clearOverride = () =>
  admin<{ cleared: boolean; mission_env: string }>("POST", "/mission/clear-override");

export const fetchBans = () => admin<BanList>("GET", "/bans");
export const addBan = (key: { name?: string; ip?: string }) =>
  admin<{ kicked: string[] }>("POST", "/bans", key);
export const removeBan = (key: { name?: string; ip?: string }) =>
  admin<{ removed: boolean }>("POST", "/unban", key);
export const clearBans = () => admin<{ unbanned: number }>("POST", "/bans/clear");
/** ip "" lifts every lockout (the three-wrong-codes kind — not bans) */
export const unlock = (ip = "") => admin<{ unlocked: number }>("POST", "/unlock", { ip });
