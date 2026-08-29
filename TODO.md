# TODO

- **Drone data sheet.** Publish the simulated drone's spec the way a real
  airframe ships one — top speed, top acceleration, climb/descent rates,
  ceiling, arena size, RTL altitude, velocity-setpoint timeout — in student
  language (STUDENT_GUIDE + a line or two on the CHEATSHEET). The numbers are
  all in `server/app/sim/params.py` (`V_XY_MAX`, `A_XY_MAX`, `V_UP_MAX`,
  `V_DOWN_MAX`, `ALT_MAX`, `ARENA_HALF`, `RTL_ALT`, `VEL_SP_TIMEOUT`); ideally
  the doc is generated or test-pinned to that file so it cannot drift.
  (Raised during the 2026-08-29 playtest: pilots guess at the limits.)

- **Proxy / network pressure test.** Every measurement so far is on the lab
  box's loopback. The real path is 62 student pages + the projector, each
  holding a WebSocket, through the OCI VM's nginx and one autossh reverse
  tunnel. Drive N headless browsers (Playwright) against the *public* URL:
  student WS at 10 Hz, one viewer feed, submit bursts; watch tunnel
  throughput, the proxy's worker/connection limits if one is in the path,
  and the join budget: on the direct `:8000` tunnel the whole room is one IP
  to the limiter (`JOIN_RATE_LIMIT_PER_MINUTE` must exceed the class size);
  behind nginx `X-Forwarded-For` must reach uvicorn (`FORWARDED_ALLOW_IPS`).
  Also the in-person case where the room's wifi is one NAT address.

## Siege enrichment — shipped 2026-08-29 (PRs #16–#23)

The 64-seat playtest trivialised siege (a flat cap of 20 creeps, an
infinite quarry, forty zappers on one creep). What landed, in the order it
stacks: the `say()` channel with a team pot paid per pilot per kill and
wallets on every wave clear, a finite quarry; the shop (personal zap /
speed / tower tiers, colour and outline); quests — opt-in route / predict /
compute challenges drawn per pilot, one room quest a wave whose miss buffs
the next wave, worked answers in `examples/answers/`; the clay pit, ring
tower, beacon and bell; repair and scout roles with a per-pilot tally on the
board and two house bots; the sealed gate S formation puzzle and the
chokepoint answer; `rounds.jsonl` at every reset and `make balance`; the
wave cap scaling with the room. Where it is written down: the siege block
of `docs/CHEATSHEET.md`, `docs/QUESTS.md`, `docs/STUDENT_GUIDE.md`,
`docs/SESSION_PLAN.md` §6–§9, `docs/MISSIONS.md`, and the before-class
list in `docs/PRE_WORKSHOP.md`.

Decisions that are settled, so nobody re-litigates them: the pot is the
team's, the spending is personal (no team-bought upgrades); a quest or
puzzle pays the pot plus a small named bonus; **the blob stays** — forty
zappers on one creep is the unedited starter doing what it says, the fix is
a ten-line student edit, never a server-side lane assignment; the projector
keeps its chaos (pad labels and the feed untouched, except that repeated
pickup rows fold).

Still open:

- **Balance with a human room.** Bots never buy, ring a tower, light a
  beacon or ring the bell, so shop prices (`SHOP`), the value of a ring
  tower / beacon / bell against their ferry cost, `PLACE`/`REPAIR` points,
  whether 60 s is right for a room quest, and the `WAVE_MAX_PER_PILOT` slope
  past wave 8 are judged from the first real class: read `rounds.jsonl` at
  the wrap against SESSION_PLAN §9's 2026-08-29 baseline; every knob is
  named there.
- **A depot for a true ferry / builder split.** Today one pilot carries and
  places, so `ferried ≈ placed + crashes`; a hand-off cell (a `TileSource`
  that placements refill) would make ferrying its own role. Balance-session
  material.
- **Predict quests and the map.** A wall raised after a predict is issued
  can make the locked answer wrong; the eligibility filter (empty-map and
  real-map marches must agree) makes it rare, not impossible. Watch
  `quests_missed` vs solved in the class's `rounds.jsonl`.
