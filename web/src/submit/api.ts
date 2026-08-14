/** REST helpers for the submit page. Token lives in localStorage. */

export const TOKEN_KEY = "dl_token";
export const STUDENT_KEY = "dl_student";

export interface ApiError {
  code: string;
  msg: string;
  line?: number;
  col?: number;
}

export class ApiFailure extends Error {
  constructor(public error: ApiError, public status: number) {
    super(error.msg);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let error: ApiError = { code: "http", msg: `request failed (${res.status})` };
    try {
      error = (await res.json()).error ?? error;
    } catch { /* not JSON */ }
    throw new ApiFailure(error, res.status);
  }
  return res.json() as Promise<T>;
}

export interface JoinInfo {
  token: string;
  student_id: string;
  name: string;
  slot: number;
  sysid: number;
  spawn: { n: number; e: number };
  rejoined: boolean;
}

export async function join(roomCode: string, name: string): Promise<JoinInfo> {
  const info = await request<JoinInfo>("POST", "/api/v1/join",
    { room_code: roomCode, name });
  localStorage.setItem(TOKEN_KEY, info.token);
  localStorage.setItem(STUDENT_KEY, JSON.stringify(
    { student_id: info.student_id, name: info.name, sysid: info.sysid }));
  return info;
}

export const submitCode = (code: string) =>
  request<{ run_id: string }>("POST", "/api/v1/submit", { code });
export const stopRun = () => request<{ stopped: boolean }>("POST", "/api/v1/stop");
export const resetMine = () => request<{ ok: boolean }>("POST", "/api/v1/reset-mine");
export const fetchTemplate = async (): Promise<string> => {
  const res = await fetch("/api/v1/template");
  return res.text();
};
