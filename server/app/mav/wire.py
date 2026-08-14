"""One MAVLink parser/packer per TCP connection.

mavutil is blocking and thread-oriented, so server-side we use only the
generated dialect class on raw asyncio streams. Parser state (buffer, seq) is
per-link — never share a MAVLink instance between connections.
"""

from __future__ import annotations

import asyncio

from pymavlink.dialects.v20 import ardupilotmega as mav2

SEV_INFO = mav2.MAV_SEVERITY_INFO
SEV_WARNING = mav2.MAV_SEVERITY_WARNING


class Link:
    def __init__(self, writer: asyncio.StreamWriter, sysid: int) -> None:
        self.writer = writer
        # MAVLink() calls .write() on the object passed as `file` when sending
        self.mav = mav2.MAVLink(self, srcSystem=sysid, srcComponent=1)
        self.mav.robust_parsing = True
        self.warned: set[str] = set()  # once-per-connection notices
        self.last_sp_warn = -1e9  # rate limit setpoint warnings (no ACK exists for them)

    def write(self, data: bytes) -> None:
        if not self.writer.is_closing():
            self.writer.write(data)

    def parse(self, data: bytes) -> list:
        msgs = self.mav.parse_buffer(data) or []
        return [m for m in msgs if m.get_type() != "BAD_DATA"]

    def statustext(self, text: str, severity: int = SEV_INFO) -> None:
        self.mav.statustext_send(severity, text[:50].encode())

    def warn_once(self, key: str, text: str) -> None:
        if key not in self.warned:
            self.warned.add(key)
            self.statustext(text, SEV_WARNING)

    @property
    def buffered(self) -> int:
        try:
            return self.writer.transport.get_write_buffer_size()
        except Exception:
            return 0
