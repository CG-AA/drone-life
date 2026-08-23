/** REST helpers for the submit page. Token lives in localStorage. */

import { ApiFailure, request } from "../shared/http";
import type { JoinInfo } from "../shared/protocol";

export { ApiFailure } from "../shared/http";

export const TOKEN_KEY = "dl_token";
export const STUDENT_KEY = "dl_student";

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
  return info;
}

export const submitCode = (code: string) =>
  authed<{ run_id: string }>("POST", "/api/v1/submit", { code });
export const stopRun = () => authed<{ stopped: boolean }>("POST", "/api/v1/stop");
export const resetMine = () => authed<{ ok: boolean }>("POST", "/api/v1/reset-mine");
export const fetchTemplate = async (variant = "beginner"): Promise<string> => {
  const res = await fetch(`/api/v1/template?variant=${encodeURIComponent(variant)}`);
  if (!res.ok) throw new ApiFailure(
    { code: "template", msg: `no ${variant} template (${res.status})` }, res.status);
  return res.text();
};
