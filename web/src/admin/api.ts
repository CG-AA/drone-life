/** REST helpers for the instructor page. Admin token lives in sessionStorage —
 * deliberately not localStorage, since instructor machines are often shared. */

import { request } from "../shared/http";
import type { BotsResult, Health, Roster } from "../shared/protocol";

export { ApiFailure } from "../shared/http";

const TOKEN_KEY = "dl_admin_token";

export const getToken = (): string => sessionStorage.getItem(TOKEN_KEY) ?? "";
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
export const resetWorld = () => admin<{ ok: boolean; epoch: number }>("POST", "/reset");
export const spawnBots = (count: number, mode: string, script: string) =>
  admin<BotsResult>("POST", "/bots", { count, mode, script });
