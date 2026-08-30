#!/usr/bin/env bash
# pre-workshop.sh — everything the lab box needs before the class, in order,
# stopping at the first thing that is not right. Run as your admin account
# (it sudo's to the service user where it must):
#
#     sudo -v && bash docs/deploy/pre-workshop.sh             # the full run
#     ONLY=preflight bash docs/deploy/pre-workshop.sh          # one step: deploy|build|image|preflight|start|smoke|checklist
#     BRANCH=siege/8-balance bash docs/deploy/pre-workshop.sh  # before the stack is merged
#     FRESH=1 bash docs/deploy/pre-workshop.sh                 # a new class: forget the old roster and score
#
# Rooms come from ROOMS= in /etc/drone-life.env (override: ROOMS_LIST="r1 r2").
# Steps: deploy → build → image → (units stopped) preflight → start → smoke →
# the checklist of what only a person can do. Idempotent: run it again after
# fixing what it flagged. It never edits /etc/drone-life.env, never prints a
# secret, and never touches the gateway VM.
set -euo pipefail

OPT=${OPT:-/opt/drone-life}              # the live checkout (owned by $SVC_USER)
SRC=${SRC:-}                             # a local repo to fetch $BRANCH from instead of origin
BRANCH=${BRANCH:-main}
SVC_USER=${SVC_USER:-dronelife}
ENV_FILE=${ENV_FILE:-/etc/drone-life.env}
ROOMS_DIR=${ROOMS_DIR:-/etc/drone-life.d}
ONLY=${ONLY:-}
FRESH=${FRESH:-0}

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '   \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '   \033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
# every service-user command: login shell (uv/npm on PATH), fail on any pipe
as_svc() { sudo -iu "$SVC_USER" bash -lc "set -euo pipefail; export PATH=\$HOME/.local/bin:\$PATH; cd $OPT; $*"; }
step() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }
envval() { sudo sed -n "s/^$2=//p" "$1" 2>/dev/null | tail -1 | tr -d '"'"'"; }  # KEY from an env file, never printed
room_port() { local p; p=$(envval "$ROOMS_DIR/$1.env" PORT); echo "${p:-8000}"; }

[ -r "$ENV_FILE" ] || sudo test -r "$ENV_FILE" || die "$ENV_FILE missing — DEPLOY.md 'One-time setup'"
if [ -n "${ROOMS_LIST:-}" ]; then rooms=$ROOMS_LIST; else rooms=$(envval "$ENV_FILE" ROOMS | tr ',' ' '); fi
units=(drone-life@main)
for r in $rooms; do units+=("drone-life@$r"); done

if step deploy; then
  say "1/7 deploy: $BRANCH into $OPT"
  [ -d "$OPT/.git" ] || die "$OPT is not a checkout — DEPLOY.md 'One-time setup' first"
  if [ -n "$SRC" ]; then
    as_svc "git fetch -q $SRC $BRANCH && git checkout -q -B $BRANCH FETCH_HEAD"
  else
    as_svc "git fetch -q origin && git checkout -q -B $BRANCH origin/$BRANCH"
  fi
  ok "checked out $(as_svc "git log -1 --oneline")"
fi

if step build; then
  say "2/7 build: server deps + web/dist (as $SVC_USER)"
  as_svc "cd server && uv sync -q"
  as_svc "cd web && npm ci --silent --no-audit --no-fund && npm run build > /dev/null"
  as_svc "test -f web/dist/index.html && test web/dist/index.html -nt .git/HEAD" \
    || die "web/dist is missing or older than the checkout — the build did not run"
  ok "web/dist built"
fi

if step image; then
  say "3/7 runner image (the rootless podman store is per user: build as $SVC_USER)"
  as_svc "make image > /dev/null"
  as_svc "podman image exists \$(sed -n 's/^runner_image: str = \"\\(.*\\)\"/\\1/p' server/app/config.py | head -1) || podman images --format '{{.Repository}}:{{.Tag}}' | grep -q drone-life-runner" \
    || die "the runner image is not in $SVC_USER's podman store"
  ok "image present"
fi

if step preflight; then
  say "4/7 preflight with the units stopped (so the port checks are real)"
  for u in "${units[@]}"; do sudo systemctl stop "$u" 2>/dev/null || true; done
  if [ "$FRESH" = "1" ]; then
    for r in main $rooms; do sudo rm -rf "$OPT/server/state/$r"; done
    ok "state wiped: a new class (roster, score, tokens gone)"
  fi
  as_svc "set -a && . $ENV_FILE && set +a && PREFLIGHT_ARGS=--all-rooms make preflight" \
    || die "preflight FAILED — every failure line names its fix (docs/DEPLOY.md 'Workshop-day runbook')"
  ok "preflight passed"
fi

if step start; then
  say "5/7 start the units: ${units[*]}"
  for u in "${units[@]}"; do sudo systemctl start "$u"; done
  for u in "${units[@]}"; do
    r=${u#drone-life@}; port=$(room_port "$r")
    for _ in $(seq 1 40); do curl -sf "localhost:$port/healthz" >/dev/null && break; sleep 0.5; done
    curl -sf "localhost:$port/healthz" >/dev/null || die "$u is not answering on :$port — journalctl -u $u -n 50"
    ok "$u up on :$port — $(curl -s "localhost:$port/healthz" | tr -d '\n' | cut -c1-90)…"
  done
fi

if step smoke; then
  say "6/7 smoke on main: three bots take off, then a reset (bots gone, score 0)"
  port=$(room_port main)
  token=$(envval "$ENV_FILE" ADMIN_TOKEN)
  [ -n "$token" ] || die "no ADMIN_TOKEN in $ENV_FILE"
  started=$(curl -s -X POST "http://127.0.0.1:$port/api/v1/admin/bots" -H "X-Admin-Token: $token" \
    -H 'Content-Type: application/json' -d '{"count":3,"script":"bot_patrol","mode":"local"}' \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("started", [])))' 2>/dev/null || echo 0)
  sleep 12
  h=$(curl -s "localhost:$port/healthz")
  curl -s -X POST "http://127.0.0.1:$port/api/v1/admin/reset" -H "X-Admin-Token: $token" >/dev/null || true  # always
  [ "$started" = "3" ] || die "only $started/3 bots started (room full of ghosts? FRESH=1 wipes the old roster)"
  echo "$h" | python3 -c 'import json,sys; h=json.load(sys.stdin); assert h["driver_errors"]==0, h; print("   ", h["drones"], "drones seated,", h["overruns"], "overruns, mission", h["mission"])'
  ok "bots flew, world reset (score 0; the roster stays — FRESH=1 for a new class)"
fi

if step checklist; then
  say "7/7 what only you can do — check each before the doors open"
  cat <<'LIST'
   [ ] $ENV_FILE: MISSION=freefly for the warm-up (siege comes at the break via
       the SWITCH box); ROOM_CODE / ADMIN_TOKEN not the placeholders; PUBLIC_URL
       = the address on the projector card; ROOMS=r1,… for the small missions
       and EMPTY for the big siege; NO EXTRA_BOT_SCRIPTS (the worked answers
       stay hidden until the wrap). Preflight only warns when a value is UNSET.
   [ ] The join limiter (JOIN_RATE_LIMIT_PER_MINUTE, per client IP, default 30):
       :8000 straight through the SSH tunnel = the whole room is one IP, so set
       it above the class size (300); behind nginx keep the default and set
       FORWARDED_ALLOW_IPS=127.0.0.1 instead.
   [ ] /etc/drone-life.d/<room>.env for every room in ROOMS (docs/ROOMS.md;
       `sh docs/deploy/rooms/mkrooms.sh N | sudo sh`), and the proxy's /rN/
       locations + TUNNEL_ROOM_FORWARDS on the gateway (ROOMS.md) if rooms are used.
   [ ] The public address answers from OUTSIDE the lab network: PUBLIC_URL/
       (projector), /submit, /r1/submit on a phone on mobile data — the gateway
       tunnel and the OCI firewall rule rot silently (docs/deploy/gateway-tunnel/).
   [ ] After this deploy, RELOAD the projector, /admin and any /submit tab left
       open from the last class — an old tab runs the old bundle.
   [ ] Projector: open PUBLIC_URL/, type the room code, read names from the back
       row; the projector machine needs a CJK font if any names need one.
   [ ] Print docs/CHEATSHEET.md, one per seat (the one-pager). Whiteboard: URL + code.
   [ ] Instructor laptop: PUBLIC_URL/admin + token; the SWITCH boxes
       (SESSION_PLAN §5) rehearsed once and timed.
   [ ] `make e2e` once (one real container submit), `make load LOAD_BOTS=20`
       green on THIS box since the last pull, and one `make balance ROUNDS=1
       SECONDS=240` so rounds.jsonl has a baseline — each takes real minutes.
   [ ] Between sessions: `make reset` (score 0, roster kept); a truly new class:
       FRESH=1 with this script (or stop the unit, delete server/state/<room>/).
LIST
fi
say "done"
