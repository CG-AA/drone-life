# Before the workshop — the whole list, in order

Everything the siege enrichment stack needs from a person before the class.
The mechanical half is one script; the rest is here so nothing is in
somebody's head. Tick them top to bottom.

## 1. Land the code (GitHub, ~10 minutes)

The stack is eight branches, each on the previous, on GitHub as stacked
PRs #16–#23 (`siege/1-say-economy` … `siege/8-balance`); every PR's base is
the previous branch. Two ways to land it — pick one:

- **one merge**: retarget #23 to `main` (Edit → base) and merge it; it is one
  linear history, so `main` gets all eight commits. Close #16–#22.
- **in order**: merge #16 into `main` and delete its branch — GitHub then
  retargets #17 to `main` — and repeat down to #23.

Then confirm CI is green on `main`. Until that is done, the deploy script
needs `BRANCH=siege/8-balance` (it deploys `origin/main` by default).

- [ ] #16 `siege/1-say-economy` → `main` (say() channel, pot → wallets, finite quarry)
- [ ] #17 `siege/2-upgrades` (the shop) — after 1
- [ ] #18 `siege/3-quests` (route / predict / compute, room quests, answers) — after 2
- [ ] #19 `siege/4-buildings` (clay pit, ring tower, beacon, bell) — after 3
- [ ] #20 `siege/5-roles` (repair + scout, the tally, bot_repair / bot_scout) — after 4
- [ ] #21 `siege/6-puzzles` (gate S, bot_chokepoint) — after 5
- [ ] #22 `siege/7-instrumentation` (rounds.jsonl, make balance, feed fold) — after 6
- [ ] #23 `siege/8-balance` (wave cap, pre-workshop script) — after 7
- [ ] `git -C /space/drone-life checkout main && git pull` on the lab box

## 2. Deploy and check the lab box (one command, ~5 minutes)

```bash
cd /space/drone-life && sudo -v && bash docs/deploy/pre-workshop.sh
```

It deploys `main` into `/opt/drone-life`, builds server + web, builds the
runner image as the service user, restarts `drone-life@main` and every
`drone-life@rN`, runs `make preflight --all-rooms`, flies three bots, resets,
and prints the checklist below. It stops at the first failure and says why;
fix and re-run (`ONLY=preflight bash docs/deploy/pre-workshop.sh` reruns one
step; by hand it is `PREFLIGHT_ARGS=--all-rooms make preflight`). It never
edits `/etc/drone-life.env` and never prints secrets. **For a new class add
`FRESH=1`**: the box still holds the 2026-08-29 playtest roster and score in
`server/state/main/`, and the smoke would otherwise pass on ghost seats.

## 3. Hand checks the script prints (do them at the box, then from outside)

- [ ] `/etc/drone-life.env`, by hand — preflight only warns when a value is
      *unset*, a wrong one passes: `MISSION=freefly` (the box is on `siege`
      from the playtest; siege comes back at the break via SESSION_PLAN §5's
      SWITCH box), real `ROOM_CODE` and `ADMIN_TOKEN`, `PUBLIC_URL=` the
      address on the projector card, `ROOMS=r1,…` for the small missions and
      empty for the big siege, and **no** `EXTRA_BOT_SCRIPTS` (the worked
      answers must stay hidden until the wrap).
- [ ] The join limiter matches how students reach the box. Joins are limited
      per client IP (`JOIN_RATE_LIMIT_PER_MINUTE`, default 30). **Direct
      `:8000` through the SSH tunnel (this box, 2026-08-29):** every student
      arrives as `127.0.0.1` and there is no header with their real address,
      so the whole room shares one budget — set
      `JOIN_RATE_LIMIT_PER_MINUTE=300` (or more than the class size) and leave
      `FORWARDED_ALLOW_IPS` alone. **Behind nginx:** keep the default and set
      `FORWARDED_ALLOW_IPS=127.0.0.1` so the `X-Forwarded-For` header is
      trusted from the tunnel.
- [ ] `/etc/drone-life.d/*.env` for every room (docs/ROOMS.md;
      `sh docs/deploy/rooms/mkrooms.sh N | sudo sh`), plus the proxy's
      `location /rN/` blocks and `TUNNEL_ROOM_FORWARDS` on the gateway
      (ROOMS.md) — rooms are a proxy change too.
- [ ] After the deploy, **reload** the projector, `/admin` and any `/submit`
      tab left open from the last class: an old tab runs the old bundle (no
      pot, no quest strip, buildings as grey dots).
- [ ] From a phone on mobile data: `PUBLIC_URL/` (projector), `/submit`,
      `/r1/submit`. The gateway tunnel and the OCI firewall rule are the two
      things that rot silently (docs/deploy/gateway-tunnel/README.md).
- [ ] Projector machine: open `PUBLIC_URL/`, type the room code, read names
      from the back row; install a CJK font if any names need one.
- [ ] Print `docs/CHEATSHEET.md` one per seat — check the print preview: the
      siege block grew (coins, shop, quests, buildings, roles), so it is one
      A4 at 9 pt / landscape, or two pages. Whiteboard: URL + room code.
- [ ] Instructor laptop: `PUBLIC_URL/admin` + token; the SWITCH boxes
      (SESSION_PLAN §5) rehearsed once and timed; `make bots N=2
      SCRIPT=bot_siege|bot_tower|bot_repair|bot_scout` ready for a lull.
- [ ] `make e2e` once (one real container submit end to end), and
      `make load LOAD_BOTS=20` green on the lab box since the last pull
      (passed 2026-08-29 with the full stack: 0 driver errors). Both take
      real minutes; the script only reminds.
- [ ] One `make balance ROUNDS=1 SECONDS=240` on the lab box so
      `server/state/balance/rounds.jsonl` exists to compare the class against
      (SESSION_PLAN §9 has the 2026-08-29 numbers).

## 4. The day itself

SESSION_PLAN.md §3–§5 as before, plus what is new:

- Siege intro: "say wallet / say shop / say quest" go on the screen with zap,
  squish and towers; the printed cheat sheet has them.
- Round 2 (coordinate): name the roles the game now scores — ferry, builder,
  repair, scout — and point at the PILOTS board's tally column.
- Round 3 (record): engineers get §6 (quests, gate S, the chokepoint); hand
  out `examples/answers/` only at the wrap.
- A lull: `bot_repair` / `bot_scout` demo the roles and stay beatable.
- After each round: the reset writes `rounds.jsonl`; read it at the wrap.

## 5. Not automated, on purpose

Merging PRs, editing `/etc/drone-life.env`, anything on the gateway VM, and
prod restarts outside the script are deliberate human steps — the script
does not sudo into anything it was not told to. The script itself needs
`sudo` (the service user owns `/opt/drone-life` and the runner image), so it
is yours to run, not an agent's.

## 6. Known open balance questions (need a human room)

Shop prices, the value of a ring tower / beacon / bell against their ferry
cost, whether 60 s is right for a room quest, and the `WAVE_MAX_PER_PILOT`
slope past wave 8 — bots never buy or build rings. After round 1, look at
`rounds.jsonl` and SESSION_PLAN §9's 2026-08-29 baseline; the knobs are all
named there.
