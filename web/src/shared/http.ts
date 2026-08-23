/** Shared REST plumbing: the server's {"error": {...}} envelope as a typed throw. */

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

export async function request<T>(method: string, path: string,
                                 headers: Record<string, string>,
                                 body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", ...headers },
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
