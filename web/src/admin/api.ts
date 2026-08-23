/** REST helpers for the instructor page. Admin token lives in sessionStorage —
 * deliberately not localStorage, since instructor machines are often shared. */

import { request } from "../shared/http";

export { ApiFailure } from "../shared/http";

const TOKEN_KEY = "dl_admin_token";

export const getToken = (): string => sessionStorage.getItem(TOKEN_KEY) ?? "";
export const setToken = (t: string): void => sessionStorage.setItem(TOKEN_KEY, t);
export const clearToken = (): void => sessionStorage.removeItem(TOKEN_KEY);

function admin<T>(method: string, path: string, body?: unknown): Promise<T> {
  return request<T>(method, `/api/v1/admin${path}`, { "X-Admin-Token": getToken() }, body);
}

export interface RosterStudent {
  student_id: string;
  name: string;
  slot: number;
  sysid: number;
  run: { run_id: string; state: string; exit_code: number | null } | null;
  connected: boolean;
  crashed: boolean;
}

export interface Roster {
  students: RosterStudent[];
  score: number;
  mission: string;
  epoch: number;
}

export const fetchRoster = () => admin<Roster>("GET", "/students");
export const killScript = (studentId: string) =>
  admin<{ stopped: boolean }>("POST", "/kill", { student_id: studentId });
export const kickStudent = (studentId: string) =>
  admin<{ ok: boolean }>("POST", "/kick", { student_id: studentId });
export const resetWorld = () => admin<{ ok: boolean; epoch: number }>("POST", "/reset");
export const spawnBots = (count: number, mode: string, script: string) =>
  admin<{ started: string[]; room_full: boolean }>("POST", "/bots", { count, mode, script });
