# Before the workshop — the whole list, in order

Everything the siege enrichment stack needs from a person before the class.
The mechanical half is one script; the rest is here so nothing is in
somebody's head. Tick them top to bottom.

## 1. Land the code (GitHub, ~10 minutes)

The stack is eight branches, each on the previous, on GitHub as stacked
PRs #16–#23 (`siege/1-say-economy` … `siege/8-balance`). Merge them **in order**,
each into the one before it (or squash the whole stack into `main` at once
— it is one linear history), then confirm CI is green on `main`.

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
step). It never edits `/etc/drone-life.env` and never prints secrets.

## 3. Hand checks the script prints (do them at the box, then from outside)

- [ ] `/etc/drone-life.env`: `MISSION=freefly` (siege comes at the break via
      SESSION_PLAN §5's SWITCH box), real `ROOM_CODE` and `ADMIN_TOKEN`,
      `FORWARDED_ALLOW_IPS=127.0.0.1`, `PUBLIC_URL=` the address on the
      projector card, `ROOMS=r1,…` (or empty), and **no** `EXTRA_BOT_SCRIPTS`
      (the worked answers must stay hidden until the wrap).
- [ ] `/etc/drone-life.d/*.env` for every room (docs/ROOMS.md;
      `sh docs/deploy/rooms/mkrooms.sh N | sudo sh`).
- [ ] From a phone on mobile data: `PUBLIC_URL/` (projector), `/submit`,
      `/r1/submit`. The gateway tunnel and the OCI firewall rule are the two
      things that rot silently (docs/deploy/gateway-tunnel/README.md).
- [ ] Projector machine: open `PUBLIC_URL/`, type the room code, read names
      from the back row; install a CJK font if any names need one.
- [ ] Print `docs/CHEATSHEET.md` one per seat (it is the one-pager; the siege
      block now covers coins, the shop, quests and the buildings). Whiteboard:
      URL + room code.
- [ ] Instructor laptop: `PUBLIC_URL/admin` + token; the SWITCH boxes
      (SESSION_PLAN §5) rehearsed once and timed; `make bots N=2
      SCRIPT=bot_siege|bot_tower|bot_repair|bot_scout` ready for a lull.
- [ ] `make load LOAD_BOTS=20` green on the lab box since the last pull
      (passed 2026-08-29 with the full stack: 0 driver errors).
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
does not sudo into anything it was not told to.
