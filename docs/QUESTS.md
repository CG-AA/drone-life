# Quests — siege's programming challenges

A quest is a small task the game states in `GAME:` text and checks by
watching your drone. There is no coordinate to type and no reflex to win:
every quest is drawn from the live world *for you* — your neighbour's
numbers differ — so only code that reads the lines and works them out
generalises. Say the word to opt in:

```python
drone.say("quest")       # "quests on, first one soon"; drone.say("quest off") to stop
```

Personal quests start at wave 2 and come one at a time, ~20 s apart, while a
wave is on. Solving one pays **+5** to you on the board and coins into the
team pot (one per seat). A **room quest** is broadcast to everyone from wave
3 — id = the wave number — and the first pilot to solve it pays the pot
three coins per seat; if *nobody* solves it before it expires (60 s, or the
next wave), the next wave comes **buffed** (`+1 hp` or `faster`, alternating)
— the room's penalty, announced as `room quest 6 missed, next wave +1 hp`
and `wave 7 buffed: +1 hp`.

Every line matches
`^(room )?quest (\d+)(:| stop (\d+)| solved| expired| off)` — the id follows
`quest`, positions come last as `N <int> E <int>` (so `position_in()` reads
them), and `room ` prefixes a room quest.

## Route — parse a list, sequence gotos, choose an order

```
quest 7: route 3 stops, 42 s              visit in the listed order
quest 7: route back 4 stops, 60 s         in REVERSE of the listed order
quest 7: route at 18 m, 4 stops, 60 s     listed order, at that altitude ±1.5 m
quest 7: route any order 5 stops, 90 s    any order — the listed one is deliberately slow
quest 7 stop 1 at N 20 E -30              one line per stop; collect them all first
quest 7 stop 1 ok, 2 to go                progress; a wrong-order touch is ignored (not reset)
```

A stop counts when you are within **2.5 m** of it (any altitude, unless
`at H m`). Stops are ≥ 20 m apart and above the pad rows. The time limit is
the flight at 6 m/s plus 4 s per stop, clamped to 30–90 s; for `any order`
it is computed from the *best* order, and the listed order is at least 1.5×
longer — five stops is 120 permutations, brute force is fine.

## Predict — model a creep's march

```
quest 7: runner at N 40 E -12, in 15 s?   where will THAT creep be in 15 s?
```

Be within **6 m** of the spot when the clock hits, and **still** (under
1 m/s) for the last **2 s** — a drone chasing the callouts does not count.
The answer is locked when the quest is issued (if the creep dies meanwhile,
the place still counts). What you need to know:

- creeps walk cell-centre to cell-centre on the hex grid toward the Keep at
  (0, 0), at `min(2.5, 1.5 + 0.1 × (wave − 1))` m/s × the kind's multiplier:
  grunt 1.0, runner 1.5, brute 0.65, sapper 1.0 (× 1.2 on a `buffed: faster` wave);
- hexes: `n = 4.5 r`, `e = 5.196 (q + r/2)`, pointy-top axial `(q, r)`,
  cube rounding for world → cell (`server/app/game/hex.py`);
- on an empty map many shortest paths tie; the creep follows exactly the one
  the server's flood field picks (`server/app/game/path.py`: a heap ordered
  by `(cost, q, r)`, neighbours in `DIRECTIONS` order, a parent replaced only
  by a strictly cheaper one) and steps like `server/app/game/units.py`.
  The game only issues creeps whose real path equals the empty-map path, so
  a faithful port of those ~60 lines is the whole answer. A straight-line
  model passes the 8 s tier and gets marginal at 15 s.

## Compute — the answer is an altitude

```
quest 7: alt = dist to N 40 E -12 / 4     Euclidean distance from the Keep (0, 0), divided
quest 7: alt = dist pad to N 40 E -12 / 4 …from YOUR pad: position() before takeoff
quest 7: alt = hexes to N 40 E -12        hex steps from the Keep: (|dq| + |dr| + |dq + dr|) / 2
quest 7: alt = hexes pad to N 40 E -12    …from your pad
quest 7: alt = gates x 10 + wave          count this wave's "wave N at" + "also at" lines
quest 7: alt = creeps this wave           add the counts in those lines (the boss aside)
```

Hover over the Keep (within 3 m) at the answer **± 1 m** for **2 s**. There
is no higher/lower hint. Answers are always between 3 and 55 m.

## Endings

```
quest 7 solved! +5, pool +64     room quest 6 solved! +5, pool +192   (others: room quest 6 solved!)
quest 7 expired                  quest 7 off: crashed
```

Worked answers — one script per family — live in `examples/answers/`
(hand them out at the wrap, not before). Knobs: `server/app/game/quests.py`.
