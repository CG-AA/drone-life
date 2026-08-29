#!/bin/sh
# Print the per-room env files for N small rooms plus the big one, by the
# convention in docs/ROOMS.md: room i is HTTP 800i, MAVLink 5760+100i, 20
# seats; `main` is :8000, MAVLink 5760-5823, 64 seats. Writes nothing — pipe
# each block where the runbook says (/etc/drone-life.d/<id>.env), or run
#     sh docs/deploy/rooms/mkrooms.sh 5 | sudo sh   (it emits the tee commands)
set -eu
n=${1:-5}
seats=${SEATS:-20}
big=${BIG_SEATS:-64}
public=${PUBLIC_URL:-https://drones.example.org}

echo "sudo install -d -o root -g dronelife -m 750 /etc/drone-life.d"
echo "sudo tee /etc/drone-life.d/main.env >/dev/null <<EOF"
echo "# the big room: / on the proxy, the 64-seat siege (docs/ROOMS.md)"
echo "PORT=8000"
echo "MAVLINK_BASE_PORT=5760"
echo "MAX_STUDENTS=$big"
echo "STATE_DIR=state/main"
echo "EOF"
i=1
while [ "$i" -le "$n" ]; do
  echo "sudo tee /etc/drone-life.d/r$i.env >/dev/null <<EOF"
  echo "# room $i: /r$i/ on the proxy — HTTP 800$i, MAVLink $((5760 + 100 * i))-$((5760 + 100 * i + seats - 1))"
  echo "PORT=800$i"
  echo "MAVLINK_BASE_PORT=$((5760 + 100 * i))"
  echo "MAX_STUDENTS=$seats"
  echo "STATE_DIR=state/r$i"
  echo "ROOM_LABEL=Room $i"
  echo "# the projector's join card: send this room's tables straight here"
  echo "PUBLIC_URL=$public/r$i"
  echo "EOF"
  i=$((i + 1))
done
echo "sudo chmod 640 /etc/drone-life.d/*.env && sudo chgrp dronelife /etc/drone-life.d/*.env"
