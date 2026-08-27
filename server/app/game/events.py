"""Canonical registry of feed event kinds.

Every kind emitted through WorldAPI.emit_event or the engine/service bus must
be listed here. Two guards keep it honest: the mission test harness
(tests/support/harness.py) asserts membership on every emit, and the web HUD's
severity table is checked against this file by web/src/viewer/hud.test.ts,
which parses the block between the BEGIN/END markers — keep the
one-kind-per-line quoted format.
"""

# BEGIN-EVENT-KINDS
EVENT_KINDS: frozenset[str] = frozenset({
    # engine / service lifecycle
    "joined",
    "kicked",
    "crashed",
    "respawned",
    "orphan_rtl",
    "script_exit",
    "reset",
    "reset_mine",
    "score",
    "milestone",
    "mission_error",
    # delivery
    "crate_spawn",
    "crate_lost",
    "pickup",
    "delivery",
    # building (rampart / forge)
    "tile_lost",
    "tile_placed",
    "wall_complete",
    "furnace_lit",
    # siege
    "wave_start",
    "wave_clear",
    "keep_hit",
    "keep_fell",
    "tower_up",
    "tower_down",
})
# END-EVENT-KINDS
