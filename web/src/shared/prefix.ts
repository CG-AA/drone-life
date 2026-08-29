/** Where this page lives under the proxy.
 *
 * The workshop runs the small missions as several server processes behind one
 * nginx, on `/r1/`, `/r2/`, … (docs/ROOMS.md); the proxy strips the prefix, so
 * the server never sees it and every request the page makes must add it back.
 * The page learns the prefix from its own address — `/r1/submit` is room 1's
 * student page, `/submit` is the big room's — so one build serves every room.
 *
 * Computed on demand, not at import: tests stub `location` without a
 * pathname, and the answer cannot change while a page is open anyway. */

/** `/r1/submit` → `/r1`, `/r1/` → `/r1`, `/submit` → ``, `/` → ``. */
export function derivePrefix(pathname: string | undefined): string {
  if (!pathname) return "";
  return pathname.replace(/\/(submit|admin)\/?$/, "").replace(/\/+$/, "");
}

export function prefix(): string {
  return derivePrefix(typeof location === "undefined" ? undefined : location.pathname);
}

/** A root-absolute server path (`/api/v1/join`, `/ws/student`) as this page must ask for it. */
export function withPrefix(path: string): string {
  return prefix() + path;
}
