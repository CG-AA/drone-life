# TODO

- **Drone data sheet.** Publish the simulated drone's spec the way a real
  airframe ships one — top speed, top acceleration, climb/descent rates,
  ceiling, arena size, RTL altitude, velocity-setpoint timeout — in student
  language (STUDENT_GUIDE + a line or two on the CHEATSHEET). The numbers are
  all in `server/app/sim/params.py` (`V_XY_MAX`, `A_XY_MAX`, `V_UP_MAX`,
  `V_DOWN_MAX`, `ALT_MAX`, `ARENA_HALF`, `RTL_ALT`, `VEL_SP_TIMEOUT`); ideally
  the doc is generated or test-pinned to that file so it cannot drift.
  (Raised during the 2026-08-29 playtest: pilots guess at the limits.)

- **Split server for the small missions.** At 64 pilots freefly and delivery
  are a firehose (pad labels pile up, the feed is unreadable, one crate per
  pilot carpets the floor); siege is the mission that wants the crowd. Run
  the warm-up and teaching blocks as several rooms of ~20 — most simply, N
  server instances (own `ROOM_CODE`, port, MAVLink base port, state dir)
  behind the proxy on `/r1`, `/r2`, …, each with its own projector page —
  and merge into one 64-seat siege for the main event. Needs: a systemd
  template unit (`drone-life@.service`), a per-room env file, `make preflight`
  that knows about room N's ports, and a way to carry the roster (not the
  score) from the small rooms into the big one.
- **Proxy / network pressure test.** Every measurement so far is on the lab
  box's loopback. The real path is 62 student pages + the projector, each
  holding a WebSocket, through the OCI VM's nginx and one autossh reverse
  tunnel. Drive N headless browsers (Playwright) against the *public* URL:
  student WS at 10 Hz, one viewer feed, submit bursts; watch tunnel
  throughput, nginx worker/connection limits, `proxy_read_timeout`, and
  whether the 30/min per-IP join budget (`X-Forwarded-For` must reach
  uvicorn) survives a whole room joining in the same minute. Also the
  in-person case where the room's wifi is one NAT address.
