/** Mirrors the server's wire shapes: the WS envelope (app/api/ws.py +
 * app/api/messages.py) and the REST payloads (routes_public/routes_admin).
 *
 * Ordering quirk: the per-socket sender drains the latest-wins world slot
 * before the hello/tiles queue, so the FIRST frame a fresh client receives is
 * usually `world`, ahead of `hello`. Pages must tolerate a world frame with
 * arena defaults still in place. */

export interface Envelope<T = unknown> {
  v: number;
  type: string;
  t: number;
  data: T;
}

export interface DroneState {
  id: string;
  student_id: string;
  name: string;
  sysid: number;
  n: number;
  e: number;
  alt: number;
  vn: number;
  ve: number;
  valt: number;
  yaw: number;
  mode: string;
  armed: boolean;
  on_ground: boolean;
  crashed: boolean;
  connected: boolean;
  carrying: string | null;
}

/** Every kind the missions emit today; the viewer renders unknown kinds with a
 * neutral fallback marker, so this list is documentation, not a gate. */
export const KNOWN_KINDS = [
  "crate", "dropoff",                                  // delivery
  "tile_source", "tile_carried", "ghost_tile",         // building missions
  "furnace",                                           // forge
  "keep", "troop", "tower", "beam",                    // siege
] as const;

export interface EntityState {
  id: string;
  kind: string; // one of KNOWN_KINDS, or a future kind (fallback-rendered)
  n: number;
  e: number;
  alt: number;
  /** per-kind payload — see the …Data shapes below; `carried_by` is special:
   * the server derives DroneState.carrying from it (app/api/messages.py) */
  data: Record<string, unknown>;
}

// Per-kind `data` shapes, as the missions emit them. Renderers coerce field
// by field (a missing field degrades, not crashes), so these are the
// documented contract rather than enforced parses.
export interface CrateData { carried_by?: string }
export interface TileSourceData { material: string; remaining: number | null }
export interface TileCarriedData { carried_by: string; material: string }
export interface GhostTileData { material: string; need: number; have: number; size: number }
export interface TroopData { dir: number; chewing: boolean }
export interface KeepData { hp: number; max: number }
export interface TowerData { range: number }
export interface BeamData { tn: number; te: number; talt: number }

export interface PadState {
  slot: number;
  n: number;
  e: number;
  name: string;
}

export interface WorldData {
  epoch: number;
  t: number;
  score: number;
  drones: DroneState[];
  entities: EntityState[];
  pads: PadState[];
}

export interface EventData {
  kind: string;
  msg: string;
  student_id: string | null;
  data: Record<string, unknown>;
  t: number;
}

export interface HelloData {
  proto: number;
  /** hex_size: the lattice pads and landmarks snap to (m, center-to-corner) */
  arena: { half: number; alt_max: number; hex_size: number };
  mission: string;
  epoch: number;
}

/** One hex cell's stack, bottom-up. Mirrors TileMap.to_wire(). */
export interface TileCell {
  q: number;
  r: number;
  stack: string[]; // material names
}

export interface TilesData {
  geometry: { size: number; tile_height: number };
  cells: TileCell[];
}

export interface LogLine {
  ts: number;
  stream: "stdout" | "stderr" | "system";
  line: string;
}

/** Why a run ended (app/runner/manager.py END_REASONS); null until it has. */
export type RunEndReason =
  | "done" | "error" | "timeout" | "stopped" | "replaced"
  | "start_failed" | "runner_failed";

export interface RunState {
  run_id: string;
  state: "starting" | "running" | "exited";
  exit_code: number | null;
  reason: RunEndReason | null;
}

// ---------------- REST payloads (routes_public.py / routes_admin.py) --------

export interface JoinInfo {
  token: string;
  student_id: string;
  name: string;
  slot: number;
  sysid: number;
  spawn: { n: number; e: number };
  rejoined: boolean;
}

/** GET /api/v1/status — what a returning page needs to catch up before its
 * socket opens. `drone` is deliberately loose: the world frame refreshes the
 * strip a moment later, and this view carries a subset of DroneState. */
export interface StatusInfo {
  student_id: string;
  run: RunState | null;
  drone: unknown;
  log_tail: LogLine[];
}

export interface RosterStudent {
  student_id: string;
  name: string;
  slot: number;
  sysid: number;
  run: RunState | null;
  connected: boolean;
  crashed: boolean;
}

export interface Roster {
  students: RosterStudent[];
  score: number;
  mission: string;
  epoch: number;
}

/** GET /healthz (service.health()) — unauthenticated, no podman probes in it. */
export interface Health {
  ok: boolean;
  drones: number;
  ticks: number;
  overruns: number;
  score: number;
  mission: string;
  students: number;
  uptime_s: number;
  driver_alive: boolean;
  last_tick_age_s: number;
  driver_errors: number;
}

export interface BotsResult {
  started: string[]; // student ids
  room_full: boolean;
}

export function parseEnvelope(raw: string, onSkew?: () => void): Envelope | null {
  try {
    const msg = JSON.parse(raw) as Envelope;
    if (typeof msg !== "object" || msg === null) return null;
    if (msg.v !== 1) {
      // a redeployed server speaking a newer protocol: tell the page instead
      // of silently dropping everything (which looks like a hung UI)
      onSkew?.();
      return null;
    }
    return msg;
  } catch {
    return null;
  }
}
