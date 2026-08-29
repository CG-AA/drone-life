#!/usr/bin/env bash
# pre-workshop.sh — everything the lab box needs before the class, in order,
# stopping at the first thing that is not right. Run as your admin account
# (it sudo's to the service user where it must):
#
#     sudo -v && bash docs/deploy/pre-workshop.sh            # the full run
#     ONLY=deploy bash docs/deploy/pre-workshop.sh           # one step: deploy|build|image|restart|preflight|smoke|checklist
#     BRANCH=main ROOMS_N=0 bash docs/deploy/pre-workshop.sh  # no small rooms
#
# What it does, and what it deliberately does NOT do (the checklist at the
# end): it never edits /etc/drone-life.env, never prints the room's secrets,
# and never touches the gateway VM. Every step is idempotent — run it again
# after fixing what it flagged.
set -euo pipefail

OPT=${OPT:-/opt/drone-life}              # the live checkout (owned by $SVC_USER)
SRC=${SRC:-}                             # a local repo to fetch $BRANCH from instead of origin (dev box)
BRANCH=${BRANCH:-main}
SVC_USER=${SVC_USER:-dronelife}
ROOMS_N=${ROOMS_N:-5}                    # small rooms r1..rN (docs/ROOMS.md); 0 = only main
ONLY=${ONLY:-}
UV=${UV:-"~/.local/bin/uv"}              # as $SVC_USER

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '   \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '   \033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
as_svc() { sudo -iu "$SVC_USER" bash -lc "$*"; }
step() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }

units=(drone-life@main)
for i in $(seq 1 "$ROOMS_N"); do units+=("drone-life@r$i"); done

if step deploy; then
  say "1/7 deploy: $BRANCH into $OPT"
  [ -d "$OPT/.git" ] || die "$OPT is not a checkout — DEPLOY.md 'One-time setup' first"
  if [ -n "$SRC" ]; then
    as_svc "git -C $OPT fetch -q $SRC +$BRANCH:$BRANCH"
  else
    as_svc "git -C $OPT fetch -q origin +$BRANCH:$BRANCH"
  fi
  as_svc "git -C $OPT checkout -q $BRANCH && git -C $OPT log -1 --oneline"
  ok "checked out $(as_svc "git -C $OPT rev-parse --short HEAD")"
fi

if step build; then
  say "2/7 build: server deps + web/dist (as $SVC_USER)"
  as_svc "cd $OPT/server && $UV sync -q"
  as_svc "cd $OPT/web && npm ci --silent --no-audit --no-fund && npm run build 2>&1 | tail -1"
  [ -f "$OPT/web/dist/index.html" ] || die "web/dist missing after the build"
  ok "web/dist built"
fi

if step image; then
  say "3/7 runner image (rootless podman store is per user: build as $SVC_USER)"
  as_svc "cd $OPT && make image 2>&1 | tail -2"
  ok "image built"
fi

if step restart; then
  say "4/7 restart the units: ${units[*]}"
  for u in "${units[@]}"; do
    sudo systemctl restart "$u"
  done
  for u in "${units[@]}"; do
    port=$(sudo systemctl show "$u" -p Environment | tr ' ' '\n' | sed -n 's/^PORT=//p' | tail -1)
    port=${port:-8000}
    for _ in $(seq 1 40); do curl -sf "localhost:$port/healthz" >/dev/null && break; sleep 0.5; done
    curl -sf "localhost:$port/healthz" >/dev/null || die "$u is not answering on :$port — journalctl -u $u -n 50"
    ok "$u up on :$port — $(curl -s "localhost:$port/healthz" | tr -d '\n' | cut -c1-90)…"
  done
fi

if step preflight; then
  say "5/7 preflight (the server's own checks, as $SVC_USER, every room)"
  as_svc "cd $OPT && set -a && . /etc/drone-life.env && set +a && PREFLIGHT_ARGS=--all-rooms make preflight" \
    || die "preflight FAILED — every failure line names its fix (docs/DEPLOY.md 'Workshop-day runbook')"
  ok "preflight passed"
fi

if step smoke; then
  say "6/7 smoke on main: 3 bots move, then a clean reset"
  as_svc "cd $OPT && set -a && . /etc/drone-life.env && set +a && make bots N=3 >/dev/null && sleep 12 \
    && curl -s localhost:8000/healthz | python3 -c 'import json,sys; h=json.load(sys.stdin); assert h[\"drones\"]>=3 and h[\"driver_errors\"]==0, h; print(\"   \", h[\"drones\"], \"drones,\", h[\"overruns\"], \"overruns, mission\", h[\"mission\"])' \
    && make reset >/dev/null"
  ok "bots flew, world reset (score 0, roster kept)"
fi

if step checklist; then
  say "7/7 what only you can do — check each before the doors open"
  cat <<'LIST'
   [ ] /etc/drone-life.env: MISSION=freefly for the warm-up (siege comes at the
       break via the SWITCH box), ROOM_CODE + ADMIN_TOKEN not the placeholders,
       FORWARDED_ALLOW_IPS=127.0.0.1 (the tunnel), PUBLIC_URL=the address on the
       projector card, ROOMS=r1,…,rN (or empty for one room), and NO
       EXTRA_BOT_SCRIPTS (the worked answers stay hidden until the wrap).
   [ ] Room files /etc/drone-life.d/*.env exist for every room above (docs/ROOMS.md;
       `sh docs/deploy/rooms/mkrooms.sh N | sudo sh` writes them).
   [ ] The public address answers from OUTSIDE the lab network: open
       $PUBLIC_URL/ (projector page) and /submit on a phone on mobile data —
       the gateway tunnel (docs/deploy/gateway-tunnel/README.md) and the OCI
       firewall rule are the two things that silently rot.
   [ ] Projector: open $PUBLIC_URL/ , type the room code, stand at the back —
       names readable? The projector machine needs a CJK font if any names are
       (headless screenshots render them as boxes).
   [ ] Print docs/CHEATSHEET.md, one per seat (it is the one-pager; QUESTS.md and
       STUDENT_GUIDE.md are links, not prints). Whiteboard: URL + room code.
   [ ] Instructor laptop: $PUBLIC_URL/admin with the admin token; the SWITCH boxes
       from docs/SESSION_PLAN.md §5 in a terminal tab, rehearsed once (time them).
   [ ] `make load LOAD_BOTS=20` was green on THIS box since the last pull
       (README 'Day −1'), and `server/state/balance/rounds.jsonl` has at least one
       `make balance` round to compare the class against (SESSION_PLAN §9).
   [ ] Between sessions: `make reset` (score to 0, roster kept); a truly fresh
       class = stop the unit, delete server/state/<room>/, start it.
LIST
fi
say "done"
