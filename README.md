# Drone Life 🛸

A multiplayer co-op drone programming game for educational workshops. Students write Python scripts in an in-browser IDE to control simulated drones inside a shared 200×200m arena, rendered live on a central projector view.

The platform uses pymavlink communication protocols against ArduPilot GUIDED-mode conventions over network loopback. Code written in the browser sandbox directly transfers to real autonomous drone hardware.

---

## Architecture Flow

```mermaid
graph LR
    Browser["Students' Browsers"] ──> Submit["Submit Page"]
    Submit ──> Sandbox["Podman Sandbox (0.5 CPU, 256MB RAM)"]
    Sandbox ──> MAVLink["MAVLink / TCP"]
    MAVLink ──> Sim["20 Hz Kinematic Sim Engine"]
    Sim ──> Engine["Game Engine & Missions"]
    Engine ──> FastAPI["FastAPI Backend"]
    FastAPI ──> WS["WebSocket Feed"]
    WS ──> Projector["Projector Scoreboard & Viewer"]
```

---

## Integrated Development Environment (IDE)

The student interface requires zero local installation and provides:
* Web Code Editor: Built-in editor featuring syntax highlighting and API autocompletion.
* Live Telemetry: Real-time feedback tracking vehicle status (`mode`, `armed/disarmed`, `N/E/Alt` coordinates).
* Execution Management: Immediate container life-cycle control via `Run`, `Stop`, and `Reset Drone` interface commands.

---

## API Reference (`import dronelife`)

```python
import dronelife

drone.takeoff(alt)               # Commands the drone to climb to the target altitude (meters)
drone.goto(north, east, alt)     # Navigates to absolute coordinates (Arena coordinates range from -100 to 100)
drone.move(vn, ve, vup, secs)    # Direct velocity control vectors (m/s) for a set duration
drone.position()                 # Returns the current telemetry data tuple: (north, east, altitude)
drone.events()                   # Fetches sequential game engine event strings
drone.land()                     # Triggers an immediate landing at the current coordinate position
drone.rtl()                      # Return-to-Launch: Forces the drone to fly back to its starting base
```
*Note: Use `position_in(msg)` to parse string event notifications into raw numeric coordinates.*

---

## Game Modes & Starter Templates

Change the game mode using the `MISSION=<name>` environment variable. Students can select templates from the dropdown menu.

### 1. Freefly Mode (`MISSION=freefly`)
* Objective: A warm-up sandbox to test basic code, flight loops, and ensure safe takeoff and navigation. No crucial objectives.

### 2. Delivery Mode (`MISSION=delivery`)
* Objective: Pick up cargo crates and return them to the central drop pad at `(0, 0)`.

### 3. Siege Mode (`MISSION=siege`)
* Objective: A tower defense event where enemy creeps march toward your central base, the Keep at `(0, 0)`. Game ends when Keep's health hits zero.

### Alternative Game Modes

* `canyon`: Obstacle course. Drones must navigate around pre-placed steel walls in the sky without crashing into them.
* `rampart`: Wall building. Fly to the target, grab steel blocks, and carry them over to stack up a defensive straight wall.
* `forge`: Assembly practice. Drones must gather 6 clay blocks and arrange them into a closed ring to turn on the central furnace.

---

## How to Self-Host

You can host a workshop on a single Ubuntu 24.04 machine. Students only need a web browser and Wi-Fi.

## How It Works

[Student Browser] ──> [FastAPI Server] ──> [Podman Container] ──> [MAVLink/TCP] ──> [20Hz Sim Engine] ──> [WebSocket] ──> [Projector Viewer]

1. Write & Run: Students write and execute Python code in the browser IDE.
2. Sandbox Execution: The backend runs scripts safely inside isolated Podman sandbox containers.
3. Real Protocols: Scripts use `pymavlink` to transmit flight packets locally.
4. Live Stream: Physics and visuals are streamed back via WebSockets.

### 1. Install Dependencies
Run the setup command for Podman, Node.js, and Python tools:
```bash
sudo apt update && sudo apt install -y git make curl openssl podman uidmap slirp4netns && curl -LsSf https://astral.sh | sh && . ~/.local/bin/env && curl -fsSL https://nodesource.com | sudo -E bash - && sudo apt install -y nodejs
```

### 2. Clone and Build
Download the repository and prepare the backend and frontend:
```bash
git clone https://github.com && cd drone-life
cd server && uv sync && cd ..
cd web && npm ci && npm run build && cd ..
```

<<<<<<< HEAD
### 3. Configure and Launch
Set your variables and start the server:
=======
In a second terminal: `cd drone-life && make bots N=5 ADMIN_TOKEN=change-me` —
five demo drones patrol on the viewer.

- `http://localhost:8000/` — the projector view; room code `classroom`
- `http://localhost:8000/submit` — what students see: editor, Run, live log
- `http://127.0.0.1:8121/admin` — instructor console; token `change-me`. The
  console lives on its own loopback port (`ADMIN_PORT`) and is 404 on :8000

Those placeholder secrets only boot because `make dev-server` passes
`ALLOW_DEFAULT_SECRETS=1`; any other launch refuses to start until you set
real ones (`ROOM_CODE`, `ADMIN_TOKEN`).

Now the path a student's script really takes — a rootless podman container:

>>>>>>> 3397612fed372d52672ed0d3f680387f8ff1654b
```bash
make image
export ROOM_CODE="classroom101"
export ADMIN_TOKEN="instructor-secret-key"
export MISSION="freefly"
make preflight
make run
```

### 4. Connect to the Game
* Projector View: `http://<your-server-ip>:8000/` (`ROOM_CODE`)
* Student IDE: `http://<your-server-ip>:8000/submit`
* Instructor Console: `http://<your-server-ip>:8000/admin` (`ADMIN_TOKEN`)

Pulls and Issues are welcome.
