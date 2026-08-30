"""Who is kept out: banned names and banned addresses, kept across restarts.

A ban is the instructor's doing and has no expiry — unlike the strike guard's
lockouts (api/auth.py), which are automatic and time out. Names are matched
the way the roster matches them (case- and whitespace-insensitive); addresses
are whatever the join saw (`Student.ip`), so behind a shared wifi one address
is everyone behind it.
"""

from __future__ import annotations

import re


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()


class BanList:
    def __init__(self) -> None:
        self.names: set[str] = set()  # normalized
        self.ips: set[str] = set()

    # ---------------------------------------------------------------- names

    def name_banned(self, name: str) -> bool:
        return _norm(name) in self.names

    def ban_name(self, name: str) -> bool:
        """True if the name was not already banned. Empty names are ignored."""
        key = _norm(name)
        if not key or key in self.names:
            return False
        self.names.add(key)
        return True

    def unban_name(self, name: str) -> bool:
        key = _norm(name)
        if key not in self.names:
            return False
        self.names.discard(key)
        return True

    # ------------------------------------------------------------ addresses

    def ip_banned(self, ip: str) -> bool:
        return bool(ip) and ip in self.ips

    def ban_ip(self, ip: str) -> bool:
        """True if the address was not already banned. A bot has no address:
        nothing to ban, and an empty key must never match every empty ip."""
        ip = ip.strip()
        if not ip or ip in self.ips:
            return False
        self.ips.add(ip)
        return True

    def unban_ip(self, ip: str) -> bool:
        ip = ip.strip()
        if ip not in self.ips:
            return False
        self.ips.discard(ip)
        return True

    # -------------------------------------------------------------- the lot

    def clear(self) -> int:
        n = len(self.names) + len(self.ips)
        self.names.clear()
        self.ips.clear()
        return n

    def to_dict(self) -> dict:
        return {"names": sorted(self.names), "ips": sorted(self.ips)}

    def restore(self, data: dict | None) -> None:
        if not data:
            return
        self.names.update(str(n) for n in data.get("names", []) if str(n))
        self.ips.update(str(ip) for ip in data.get("ips", []) if str(ip))
