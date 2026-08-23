# Sprite atlas

Drop `game.json` + `game.png` here (a Pixi-compatible spritesheet: TexturePacker
"JSON (Hash)" or Aseprite `--sheet --data --format json-hash`). The viewer loads
`/sprites/game.json` on start; when it is missing or malformed it falls back to
procedurally drawn placeholder art with the same keys, so nothing breaks while
the art is in progress. `/?placeholder=1` forces the placeholders; `/?atlas=URL`
loads another sheet.

## Frame keys

```
kind/variant/dir{d}[/f{k}]      e.g.  drone/base/dir3/f0   crate/dir0   dropoff/base/dir0/f5
```

- `kind` — `drone`, `crate`, `dropoff`, `prop` (props: `prop/tree/dir0` …). Mission
  entities are looked up by their `kind`, with `data.variant` selecting the variant.
- `variant` — `base` is the default and the fallback for missing variants. Drones use
  `base` for students, `bot` for `Bot-*` names, `crashed` when crashed (falls back to
  `base` + red tint + an X).
- `dir{d}` — direction frames. The number of directions is inferred from the highest
  `dir` present (+1); 1, 8 and 16 are the sensible values. Missing directions fall
  back to `dir0`.
- `f{k}` — optional animation frames (rotor spin, pulse), played at the kind's fps
  (`drone` 12, `dropoff` 6). Absent = a single still frame.

## Directions are screen-space (artist-friendly)

`dir0` faces **screen-up**; directions increase **clockwise**. For 8 directions:

| dir | faces        | world heading |
|----:|--------------|---------------|
| 0   | up           | NE            |
| 1   | up-right     | E             |
| 2   | right        | SE            |
| 3   | down-right   | S             |
| 4   | down         | SW            |
| 5   | down-left    | W             |
| 6   | left         | NW            |
| 7   | up-left      | N             |

16 directions interleave these (dir1 = between up and up-right, …). The world is
2:1 isometric with north up-left and east up-right, so "up-right" (E) runs along
the diamond edge at 26.6°, not 45° — draw the diagonal frames along the iso edges,
exactly like any 2:1 iso game. (`FRAME0_YAW` in `heading.ts` is the single knob if
your sheet starts elsewhere.)

## Sizes and anchors

Art pixels are world pixels at zoom 1 (8 px = 1 m on the default arena). The
viewer renders icon sprites at integer device scales, never smaller than native.
Reference sizes: drone 28×28, crate 18×18, dropoff decal 80×44, tree 24×36.

Anchors: put a `pivot`/`anchor` per frame in the JSON if you can (Pixi reads
`anchor`); otherwise defaults apply — drone (0.5, 0.5), crate (0.5, 0.78),
dropoff (0.5, 0.5), prop (0.5, 1).

Add `"tintable": true` to `meta` if the drone art is white/grey and should be
tinted per pilot slot colour (the placeholders are).
