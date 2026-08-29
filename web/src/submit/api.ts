/** REST helpers for the submit page. Token lives in localStorage. */

import { ApiFailure, request } from "../shared/http";
import { withPrefix } from "../shared/prefix";
import type { Health, JoinInfo, RoomsInfo, StatusInfo } from "../shared/protocol";

export { ApiFailure } from "../shared/http";

export const TOKEN_KEY = "dl_token";
export const STUDENT_KEY = "dl_student";
/** The viewer's key too: one browser used for both pages types it once. */
export const CODE_KEY = "dl_room_code";

function authed<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = localStorage.getItem(TOKEN_KEY);
  return request<T>(method, path, token ? { Authorization: `Bearer ${token}` } : {}, body);
}

export async function join(roomCode: string, name: string): Promise<JoinInfo> {
  const info = await authed<JoinInfo>("POST", "/api/v1/join",
    { room_code: roomCode, name });
  localStorage.setItem(TOKEN_KEY, info.token);
  localStorage.setItem(STUDENT_KEY, JSON.stringify(
    { student_id: info.student_id, name: info.name, sysid: info.sysid }));
  try {
    // a code that worked is worth keeping: sessions expire, and retyping it
    // is the most common reason a student needs the instructor mid-class
    localStorage.setItem(CODE_KEY, roomCode);
  } catch {
    // private mode / quota: prefill is a convenience, never a failure
  }
  return info;
}

export const fetchStatus = () => authed<StatusInfo>("GET", "/api/v1/status");

export const submitCode = (code: string) =>
  authed<{ run_id: string }>("POST", "/api/v1/submit", { code });
export const stopRun = () => authed<{ stopped: boolean }>("POST", "/api/v1/stop");
export const resetMine = () => authed<{ ok: boolean }>("POST", "/api/v1/reset-mine");
/** No variant: the server picks the starter for the mission that is live. */
export const fetchTemplate = async (variant = ""): Promise<string> => {
  const q = variant ? `?variant=${encodeURIComponent(variant)}` : "";
  const res = await fetch(withPrefix(`/api/v1/template${q}`));
  if (!res.ok) throw new ApiFailure(
    { code: "template", msg: `no ${variant} template (${res.status})` }, res.status);
  return res.text();
};

/** The rooms this page can offer (empty unless the server sets ROOMS). */
export const fetchRooms = () => request<RoomsInfo>("GET", "/api/v1/rooms", {});

/** A room's own /healthz, reached through the proxy at its prefix — so this
 * is the one request that must NOT get this page's prefix added. Null when
 * the room is down (stopped for the day, or not proxied): the list says "closed". */
export async function fetchRoomHealth(path: string): Promise<Health | null> {
  try {
    const res = await fetch(`${path}/healthz`);
    if (!res.ok) return null;
    return await res.json() as Health;
  } catch {
    return null;
  }
}
