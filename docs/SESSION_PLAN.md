# Workshop session plan — freefly → delivery → siege

The minute-by-minute run of a ~4 hour session for a mixed room (students +
working engineers), up to 20 pilots. Freefly proves everyone can fly, delivery
teaches the GAME-message loop, and **siege is the main event**, played in
rounds. Companion docs: operational commands in `DEPLOY.md` (runbook),
student-facing rules in `STUDENT_GUIDE.md`, the printed one-pager in
`CHEATSHEET.md`.

## 1. The arc at a glance

| block | mission | why |
|---|---|---|
| warmup | `freefly` | the unedited template is a visible win; no way to fail |
| teach | `delivery` | introduces `drone.events()`, goto loops, co-op scoring |
| main | `siege` ×3 rounds | spends every skill under pressure; rounds give a "beat our record" ladder |

Missions are boot-time (`MISSION=` env var): every arrow above is an env edit
plus a restart — see the transition boxes in §5. Rehearse both boxes before
the day; the failure modes (ghost bots, carried-over score) are surprising the
first time.

## 2. Timing (T = 240 min; scaling notes at the end)

Warmup 45′ (welcome, first flight, freefly) · delivery 50′ · break 15′ ·
**siege 115′** (intro + three rounds) · wrap 15′. Two of the transitions ride
on natural seams (the break, the wrap); only freefly → delivery costs live
minutes. Every SWITCH block budgets 5′ — rehearsed, the restart itself is
under one minute; the rest is students pressing Run again.

## 3. Before doors open (T−20)

- `systemctl status drone-life@main` green; `MISSION=freefly` in `/etc/drone-life.env`.
  Pulled new code since the last class? `make image` too — cheap, and the
  sandbox then matches the server (the live `dronelife.py` is mounted into
  every run regardless, so a stale image cannot break imports).
- Projector on `/` with the room code entered; admin console (`/admin`) open
  on the instructor laptop.
- Smoke: `make bots N=3 HOST=localhost:8000 ADMIN_TOKEN=...` → three drones
  move on the projector → `make reset HOST=... ADMIN_TOKEN=...`.
- A printed `CHEATSHEET.md` on every seat; STUDENT_GUIDE link visible.

## 4. Minute-by-minute

| clock | block | instructor | projector | students |
|---|---|---|---|---|
| −0:20 | boot + smoke | §3 checklist; end on `make reset` | arena + room code | trickle in, join |
| 0:00 | welcome (10′) | the pitch: real pymavlink, one shared sky; join walkthrough on screen | join feed | join at `/submit` |
| 0:10 | first flight (15′) | run the unedited template live; then "everyone press Run" | 20 drones climb and move | run template, unedited |
| 0:25 | freefly play (20′) | tour `goto` / `move` / `position` / `events` from the cheat sheet; invite crashes — arena walls are soft | drones everywhere | change the numbers, break things safely |
| 0:45 | SWITCH → delivery (5′) | **Box A** (§5) | restart, then crates appear | wait, then press Run again |
| 0:50 | delivery I (25′) | narrate the first pickup and delivery; read the GAME hints aloud as they land in someone's log | score climbing, feed names | write the courier loop |
| 1:15 | lull check | if the feed stalls: `make bots N=2 SCRIPT=bot_courier` as pace-setters; kick them from `/admin` once humans overtake | bots demonstrate the loop | copy what the bots do |
| 1:20 | delivery II (15′) | call out names from the feed ("Alice delivered!"); tease the optimizations (nearest crate, `wait=False`) | milestones | optimize |
| 1:35 | break (15′) | write the delivery total on the whiteboard; run **Box A** with `MISSION=siege` during the break | restart banner → keep + quarry | break |
| 1:50 | siege intro (15′) | rules on screen: creeps → Keep, zap / squish / towers; "45 s grace — get a tower up"; assign nothing yet | keep, gates, quarry | read the siege block of the cheat sheet |
| 2:05 | siege round 1 — learn (30′) | let it be chaos; narrate the first tower, first zap, first chewed wall; end round: `make reset`, record score + wave on the whiteboard | waves, towers, keep hp | fight however they like |
| 2:35 | siege round 2 — coordinate (35′) | before Run: assign roles out loud — quarry ferries, tower builders, zappers; mid-round, point at the gate that's leaking | fewer leaks, higher waves | play a role |
| 3:10 | siege round 3 — the record (35′) | "beat round 2." Engineers: hand out the §6 challenges; everyone else defends | record attempt | defend / automate |
| 3:45 | wrap (15′) | scores ladder on the whiteboard; the pymavlink reveal (STUDENT_GUIDE table); "this exact code flies a real drone" | final feed | — |

## 5. Transition procedures

**Box A — fresh start** (used at every switch in the default plan):

1. Edit the mission and restart. Prod:
   `sudo sed -i 's/^MISSION=.*/MISSION=<name>/' /etc/drone-life.env && sudo systemctl restart drone-life@main`.
   Dev: Ctrl-C the server, `MISSION=<name> make dev-server`.
2. The restart restores roster **and score** from the snapshot — including any
   `Bot-*` entries, which come back as ghost drones parked on pads (their
   scripts died with the server).
3. `make reset HOST=... ADMIN_TOKEN=...` — kills scripts, removes every
   `Bot-*`, respawns drones, **zeroes the score**, fresh mission state.
4. Announce: "press Run again" (the restart severed every script's MAVLink
   connection; nothing resumes by itself).

**Box B — carry the score across a switch** (alternative, for a cumulative
day-total narrative):

1. While still on the old mission, kick every `Bot-*` from `/admin` (a kick
   snapshots immediately; bots left in the roster would ghost through).
2. Env edit + restart as in Box A. Score carries over via the snapshot;
   mission state does not (siege boots into its 45 s grace — correct).
3. Do **not** `make reset`. Students press Run again.

The default plan uses Box A everywhere and keeps the day's narrative on the
whiteboard (per-block scores stay comparable). Use Box B only if you want one
growing number all day.

## 6. The engineers' strand (round 3, "for working engineers only")

Hand these to anyone who finished the courier loop in one sitting. Each has a
worked answer in the repo — don't reveal that until the wrap.

1. **Drop the training wheels.** Re-write your flight in raw pymavlink — pick
   *pymavlink* from the templates menu (`examples/template_pymavlink.py`).
   Everything `dronelife` does is ~150 lines you can read.
2. **Beat the house bot.** `examples/bot_siege.py` parses
   `creep at N .. E ..` and leads the target 6 m toward the Keep, because the
   callout is where the creep *was*. Write a zapper that out-kills it
   (better lead model? intercept geometry? camp the gate?).
3. **Tower placement as a graph problem.** Creeps walk a Dijkstra flow field
   and *chew through* walls when blocked (`server/app/game/path.py`). Where do
   3-steel towers actually pay off? Build the chokepoint, not the wall.
4. **Event-driven flying.** Replace blocking `goto` with
   `goto(..., wait=False)` + a `position()` / `events()` polling loop — a
   drone that re-targets mid-flight when a fresher callout arrives.

## 7. Pace-setter bots

- Delivery lull: `make bots N=2 SCRIPT=bot_courier` — two bots quietly show
  the full loop on the projector. Kick them from `/admin` once real deliveries
  resume (they hold roster slots, and the cap is `MAX_STUDENTS`).
- Siege lull: `make bots N=2 SCRIPT=bot_siege` for zappers, and
  `make bots N=1 SCRIPT=bot_tower` to demo building — it ferries steel to
  the game's own `build a tower at …` suggestion and stacks three, so the
  room sees a tower rise and start shooting. (`bot_builder` is rampart's:
  it waits for `wall gap` lines siege never sends and hovers forever.)
- Never leave bots in during a "record" round — the record should be human.

## 8. Contingencies

- **Server dies mid-block**: systemd restarts it; snapshot is ≤ 30 s stale;
  everyone presses Run again (that's the whole recovery).
- **Mission misbehaving** (`mission bug in …` on the feed): fall back to
  `MISSION=delivery` via Box A — it's the best-rehearsed content.
- **`sim error — check server logs` on the feed**: *not* a mission bug —
  switching missions will not help. The failure is below the mission (sim,
  gateway, or the socket fan-out); the sim keeps ticking. Restart when there
  is a natural break; the journal names the file.
- **Projector feed stuck**: refresh the tab; the viewer replays state on
  connect.
- **Every submit 503s**: the runner image is missing/broken — preflight
  problem (see DEPLOY runbook), not a gameplay fix. Bots in `MODE=local`
  still work for demos while it's fixed.
- **A griefer**: `/admin` kill script, then kick if it continues.
- **Whole class stalling in siege**: let the Keep fall once — it's −25 and it
  rebuilds; narrate it as drama, then point at the leaking gate.
- **Room joins slower than planned**: stretch freefly, shrink delivery II;
  never shrink the siege intro — round 1 absorbs confusion, the intro doesn't.

## 9. Balance knobs (numbers from the pre-workshop rehearsal)

Delivery (all in `server/app/game/missions/delivery.py`): crate supply is
roster-scaled — one crate per `PILOTS_PER_CRATE` (1) connected pilot,
clamped to [`CRATE_COUNT` 3, `CRATE_MAX` 64], one top-up per
`SPAWN_STAGGER_S` (2 s); value `POINTS` (10).

Measured (20 × `bot_courier`, local mode, 7.8 min): **12.5 deliveries/min**,
median crate wait **12.7 s** (a long tail to ~90 s when a crate spawns far
from the pack — it spreads the room, leave it), score climbs linearly
(no starvation flattening), 7 crates live for 20 pilots, tick overruns
0.05 %. Twenty optimal bots are the *ceiling* — expect a human class at
roughly a third of that rate, which sits mid-band. **Verdict: ship the
defaults.** If a fast class ever floods it, raise `PILOTS_PER_CRATE` 1→2;
if a slow one starves, lower `CRATE_MAX` won't help — lower
`PILOTS_PER_CRATE` 3→2 instead.

Siege (all in `server/app/game/missions/siege.py`): `GRACE_S` (45 — raise to
60 for a first-timer room, or when the intro runs long), `BUILD_S` (20,
between waves), `SPAWN_GAP` (1.5 s/creep), wave size
`min(20, 4 + 2·(wave−1) + pilots//4)` (roster-scaled: 20 pilots meet the
cap at wave 6, one rehearsal drone still sees 4), base speed
`min(2.5, 1.5 + 0.1·(wave−1))` × the kind's multiplier. Scoring: bounty per
kind (grunt/runner 2, sapper 3, brute 5, champion 20), `WAVE_BONUS` 10 for
a clean wave / `WAVE_BONUS_LEAKY` 5, `TOWER_POINTS` 15, `KEEP_HIT_POINTS`
−1 per leak, `KEEP_FALL_POINTS` −25 (the falling hit charges only that).

The roster (`KINDS` / `SHARES`): grunts 1 hp from wave 1; runners (1.5×
speed) from 3; brutes (3 hp, 0.65× speed, chew 2×) from 5; sappers (2 hp,
chew 3×) from 7; a champion (8 hp, 0.6×, three Keep hits) behind every 5th
wave (`BOSS_EVERY`). Gates: one lane through wave 3, two from 4, all three
from 8 (`_gates_for`). Between waves the game announces a tower site four
cells before the Keep beside the last lane (`BUILD_SITE_STEPS`, 8 ≈ 40 m out —
past where gate-camping zappers already emptied it); towers reach 16 m and
fire every 2 s; a drone zaps one creep per 1.5 s (`ZAP_DWELL`), never a clump.

Measured before the kinds landed (8 × `bot_siege` + 2 × `bot_builder`,
~3.5 min): grace and the wave machine ran exactly on the documented clocks
— waves 1–3 in ~50 s per cycle, all cleared by zaps alone, keep never hit;
eight optimal zappers trivialized early waves. That is why the first
waves stayed grunts-only teaching waves and the pressure (hp, speed, two
gates, the boss) now arrives from wave 3–5 instead of at the old size cap.
Re-measure with `make bots N=6 SCRIPT=bot_siege` + `N=2 SCRIPT=bot_tower`
before the day and watch the round summary on reset.

## Scaling the plan to other lengths

- **3 h**: drop delivery II and siege round 1's last 10 minutes; two siege
  rounds instead of three.
- **2 h**: 15′ warmup, 35′ delivery, one 40′ siege round, 10′ wrap — siege
  stops being "the main event" and becomes the finale; consider `GRACE_S=60`.

## Day −1 checklist (cannot be verified off the lab server)

- [ ] `set -a && . /etc/drone-life.env && set +a && make preflight` (the env
      file is not read by `make` on its own) / podman path: `make image`,
      `make e2e`, one container-mode submit end-to-end from a real browser.
- [ ] `make load LOAD_BOTS=20` on the lab hardware; overruns < 1% on
      `/healthz`.
- [ ] Both transition boxes on the real box (`/etc/drone-life.env` edit +
      `systemctl restart` — time them; they're the 5′ SWITCH blocks).
- [ ] Projector readability from 5 m; printed CHEATSHEET legible at desk.
- [ ] Full dry run of §4 with 3 bots + one real phone/laptop as a fake
      student.
