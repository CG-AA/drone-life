# TODO

- **Drone data sheet.** Publish the simulated drone's spec the way a real
  airframe ships one — top speed, top acceleration, climb/descent rates,
  ceiling, arena size, RTL altitude, velocity-setpoint timeout — in student
  language (STUDENT_GUIDE + a line or two on the CHEATSHEET). The numbers are
  all in `server/app/sim/params.py` (`V_XY_MAX`, `A_XY_MAX`, `V_UP_MAX`,
  `V_DOWN_MAX`, `ALT_MAX`, `ARENA_HALF`, `RTL_ALT`, `VEL_SP_TIMEOUT`); ideally
  the doc is generated or test-pinned to that file so it cannot drift.
  (Raised during the 2026-08-29 playtest: pilots guess at the limits.)
