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

## Siege enrichment (decided 2026-08-29; balance session last)

Ground truth from the 64-seat playtest: a room this size trivialises siege
(`WAVE_MAX = 20`; 52 kills, 0 leaks, Keep untouched by wave 3), forty zappers
stack on one creep because every pilot is told the same nearest target, and
the quarry is infinite so towers cost only ferry time. Everything below is
in `server/app/game/missions/siege.py` unless noted.

- **Reward rule (write it down first).** A puzzle or advanced play pays in
  *team* currency — an unlock for everyone (a building, a lane, a buff for a
  wave) or a multiplier on the wave bonus — never in personal points that
  make the rest of the room decorative. The per-pilot board stays for
  bragging; the round score is what the class beats. *(proposed)*
- **Roles.** Give each role a callout stream, a stat, and a house bot:
  ferry (quarry → site, `tile_carried`), builder (walls/towers at ghosts),
  zapper (lane assignment), repair (rebuild chewed cells — the ghost for a
  chewed wall already exists), scout/spotter (an event-driven pilot that
  relays creep kinds to the room). A role with no bot has no demo on the
  projector and no "beat the house" benchmark — `examples/bot_*.py` grows
  with the role list (SESSION_PLAN §7).
- **Buildings.** The 4-high stack is legal and currently means nothing:
  4 steel = long-range tower (or a different weapon); clay in siege as cheap
  chew-fodder vs steel that only sappers eat fast; a repairable gate at a
  lane; a beacon/lure tile that pulls creeps into a kill zone. Each is a
  `Blueprint` (`server/app/game/building.py`) plus a viewer sprite.
- **Playstyles / economy.** The quarry is `TileSource(remaining=None)`:
  make stock finite per wave (a real ferry economy), pay bounty into a team
  pool that buys unlocks, and let squishing (currently free, any hp) cost
  the tile. Zapping vs building vs ferrying should each be a viable round.
- **Upgrades.** Team-bought, not personal: tower range/cooldown tiers,
  Keep armour, a wave-skip "call the next wave early for +bonus" (the classic
  TD risk knob), a one-time wall repair. Spend from the team pool above.
- **Puzzles for the "this is boring" crowd.** In-game, co-op, rewarding
  without carrying: a sealed gate that opens only when 3 drones hold a
  formation over it (rewards the *lane*, not the trio); a chokepoint
  problem — walls that force the flow field into one kill zone
  (`server/app/game/path.py` is Dijkstra with chew costs, the graph is real);
  an event-driven interceptor that must beat the house zapper's lead model;
  a sapper alarm that only a listener catches. Each ships with a worked
  answer hidden until the wrap (SESSION_PLAN §6 pattern).
- **Anti-blob targeting.** Per-pilot lane/gate assignment in the
  `creep at …` callouts (`TARGET_EVERY` hint) instead of everyone's nearest,
  and diminishing bounty when N drones hover the same creep. *(proposed)*
- **Instrumentation before balance.** `SiegeStats` per round → append a
  JSONL line at reset (pilots, waves, kills by verb, leaks, towers, steel
  ferried, time-to-first-tower); `make balance` runs N headless bot-only
  rounds with fixed `SIM_SEED`s so the balance session works from numbers.
  *(proposed)*
- **Projector at scale.** Hide pad-row labels past ~20 seats, throttle
  per-kind feed rows at 60 pilots, keep the PILOTS board as the readable
  surface. *(proposed)*
- **Balance session — last.** Scale `WAVE_MAX` with pilots (60 pilots met
  the cap on wave 1), then tune bounties/tower stats/quarry stock against
  the JSONL, with the reward rule as the constraint. Not before the content
  above exists, or it gets tuned twice.
