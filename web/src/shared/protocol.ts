/** Mirrors the server's WS envelope (app/api/ws.py + service.world_message). */

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
  yaw: number;
  mode: string;
  armed: boolean;
  on_ground: boolean;
  crashed: boolean;
  connected: boolean;
  carrying: string | null;
}

export interface EntityState {
  id: string;
  kind: string; // "crate" | "dropoff" | future kinds
  n: number;
  e: number;
  alt: number;
  data: Record<string, unknown>;
}

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
  arena: { half: number; alt_max: number };
  mission: string;
  epoch: number;
}

export interface LogLine {
  ts: number;
  stream: "stdout" | "stderr" | "system";
  line: string;
}

export interface RunState {
  run_id: string;
  state: "starting" | "running" | "exited";
  exit_code: number | null;
}

export function parseEnvelope(raw: string): Envelope | null {
  try {
    const msg = JSON.parse(raw) as Envelope;
    return typeof msg === "object" && msg !== null && msg.v === 1 ? msg : null;
  } catch {
    return null;
  }
}
