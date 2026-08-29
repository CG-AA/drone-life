# drone-life — workshop co-op drone game
# Dev quickstart:  make dev-server   (terminal 1)
#                  make dev-web      (terminal 2, hot-reload frontend on :5173)
# Production:      make image build run

ROOM_CODE ?= classroom
ADMIN_TOKEN ?= change-me
MISSION ?= delivery
# PORT follows a sourced room env file (docs/ROOMS.md): `. /etc/drone-life.d/r2.env`
# then `make reset` talks to room 2. ROOM= scopes preflight and kill-prod the same way.
PORT ?= 8000
HOST ?= 127.0.0.1:$(PORT)
ROOM ?=
N ?= 5
MODE ?= local
SCRIPT ?= bot_patrol
LOAD_BOTS ?= 10
# balance rounds (make balance): headless bot-only siege rounds on fixed seeds
ROUNDS ?= 3
BOTS ?= 6:bot_siege 2:bot_tower
SECONDS ?= 300

.PHONY: dev-server dev-web build typecheck image run kill-dev kill-prod test test-server test-web e2e load balance lint lint-fix preflight bots reset clean

# ALLOW_DEFAULT_SECRETS: dev boots on the placeholder room code/admin token above.
# `make run` deliberately does not set it — production refuses the defaults.
dev-server:
	cd server && ROOM_CODE=$(ROOM_CODE) ADMIN_TOKEN=$(ADMIN_TOKEN) MISSION=$(MISSION) \
		ALLOW_DEFAULT_SECRETS=1 uv run uvicorn app.main:app --reload --port 8000

dev-web:
	cd web && npm run dev

build:
	cd web && npm run build

image:
	podman build -f runner/Containerfile -t drone-life-runner:latest .

run:
	cd server && ROOM_CODE=$(ROOM_CODE) ADMIN_TOKEN=$(ADMIN_TOKEN) MISSION=$(MISSION) \
		uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers

# kill every dev instance: uvicorn --reload servers and vite dev servers
kill-dev:
	-pkill -f 'uvicorn app.main:app --reload' || true
	-pkill -f 'vite' || true

# kill every prod instance: uvicorn servers (non-reload) plus any bot containers.
# make kill-prod ROOM=r2 takes only room 2's containers (its server is systemd's to stop).
kill-prod:
ifeq ($(ROOM),)
	-pkill -f 'uvicorn app.main:app --host'
	-podman ps -aq --filter label=drone-life=1 | xargs -r podman rm -f -t 0
else
	-podman ps -aq --filter label=drone-life-room=$(ROOM) | xargs -r podman rm -f -t 0
endif

test: test-server test-web

test-server:
	cd server && uv run pytest -q

test-web:
	cd web && npm test

typecheck:
	cd web && npm run typecheck
	cd server && uv run mypy app

e2e:
	cd server && uv run pytest -q -m e2e

# rehearse the real class size on the real hardware: make load LOAD_BOTS=20
load:
	cd server && LOAD_BOTS=$(LOAD_BOTS) uv run pytest -q -m load

# balance from numbers: N bot-only siege rounds -> server/state/balance/rounds.jsonl + a table
# e.g. make balance ROUNDS=2 BOTS="6:bot_siege 2:bot_tower 1:bot_repair" SECONDS=180
balance:
	cd server && uv run python -m tools.balance --rounds $(ROUNDS) --bots "$(BOTS)" --seconds $(SECONDS)

lint:
	cd server && uv run ruff check app tests tools
	cd web && npm run lint

lint-fix:
	cd server && uv run ruff check --fix app tests tools

# workshop morning: can this box actually run a class? (--no-smoke skips the test container)
# make preflight ROOM=r2 checks room 2 as its unit sees it (docs/ROOMS.md)
preflight:
	cd server && uv run python -m app.preflight $(if $(ROOM),--room $(ROOM)) $(PREFLIGHT_ARGS)

# spawn demo bots: make bots N=10 MODE=container SCRIPT=bot_courier
bots:
	curl -s -X POST http://$(HOST)/api/v1/admin/bots \
		-H "X-Admin-Token: $(ADMIN_TOKEN)" -H 'Content-Type: application/json' \
		-d '{"count":$(N),"script":"$(SCRIPT)","mode":"$(MODE)"}'

reset:
	curl -s -X POST http://$(HOST)/api/v1/admin/reset -H "X-Admin-Token: $(ADMIN_TOKEN)"

clean:
	rm -rf server/state web/dist
