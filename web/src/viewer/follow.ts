/** Step the follow camera through the roster.
 *
 * Clicking a drone works when you can hit it; during a busy delivery run the
 * projector operator wants to tour the class without aiming at 6-pixel
 * targets. Its own module so the test never has to load Pixi. */

export function nextFollowId(ids: readonly string[],
                             current: string | null): string | null {
  if (ids.length === 0) return null;
  const at = current === null ? -1 : ids.indexOf(current);
  // an unknown current (the drone left) starts the tour over
  return ids[(at + 1) % ids.length];
}
