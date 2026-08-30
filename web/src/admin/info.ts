/** The console's wording for what the server is and what a restart will do —
 * pure, so the sentences the instructor acts on are testable without a DOM. */

import type { AdminInfo, BanList, RestartResult } from "../shared/protocol";

/** "1h02", "12m", "45s" — coarse on purpose; this is a glance, not a clock. */
export function uptime(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h${String(m % 60).padStart(2, "0")}`;
}

/** The room line under the health line: which process this is, which mission
 * it runs and why, and whether a restart would come back on its own. */
export function describeRoom(info: AdminInfo): string {
  const parts = [info.label ? `${info.room} · ${info.label}` : info.room];
  if (info.mission_override !== null) {
    const env = info.mission_env === info.mission ? "same as MISSION=" : `MISSION=${info.mission_env} ignored`;
    parts.push(`mission ${info.mission} (override; ${env})`);
  } else {
    parts.push(`mission ${info.mission} (MISSION=)`);
  }
  parts.push(info.admin_port ? `console :${info.admin_port}` : "console on the public port");
  parts.push(`up ${uptime(info.uptime_s)}`);
  parts.push(info.supervised ? "restart: systemd brings it back" : "restart: by hand");
  return parts.join(" · ");
}

/** The banner after a restart was accepted. Whether the box brings the server
 * back is the one thing the instructor must know before walking away. */
export function restartNotice(r: RestartResult, switching: boolean): string {
  const what = switching ? `restarting into ${r.mission}` : "restarting";
  return r.supervised
    ? `${what} — systemd brings the room back in a few seconds; pages reconnect on their own`
    : `${what} — nobody will bring it back: start the server again by hand ` +
      "(make dev-server / systemctl start), then reload this page";
}

export interface BanRow {
  kind: "name" | "ip" | "lockout";
  key: string;
  label: string;
}

/** The keep-out table, bans first (the instructor's doing), then the automatic
 * lockouts with their time left. */
export function banRows(bans: BanList): BanRow[] {
  const rows: BanRow[] = [];
  for (const name of bans.names) rows.push({ kind: "name", key: name, label: name });
  for (const ip of bans.ips) rows.push({ kind: "ip", key: ip, label: ip });
  for (const lock of bans.lockouts) {
    const left = lock.remaining_s === null ? "until restart"
      : `${Math.max(1, Math.ceil(lock.remaining_s / 60))} min left`;
    rows.push({ kind: "lockout", key: lock.ip, label: `${lock.ip} · ${left}` });
  }
  return rows;
}

/** Loose: enough to catch a name typed into the address box, not a validator. */
export function looksLikeAddress(s: string): boolean {
  return /^[0-9a-f.:]+$/i.test(s) && /[.:]/.test(s);
}
