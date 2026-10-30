# GYRO Mode — Design Notes

## Overview

Use an **Adafruit BNO055 9-DOF IMU** (product #2472, $34.95) to drive eye position from
head orientation. When the user turns their head, the eyes follow. When the head returns to
neutral, the eyes spring back to centre.

The BNO055 has an onboard ARM Cortex-M0 that performs sensor fusion internally, outputting
clean Euler angles (yaw/pitch/roll) and quaternions at 100 Hz over I²C — no fusion math
needed in Python.

## Sensor

- **Interface:** I²C, address 0x28 or 0x29
- **Outputs used:** Absolute Euler angles (yaw/pitch/roll in degrees), gyro angular velocity (°/s)
- **Library:** `adafruit-circuitpython-bno055`
- **Wiring:** Shares the existing I²C bus (SDA GPIO 2, SCL GPIO 3) with the Snake Eyes Bonnet; RST → GPIO 16 for lockup recovery

## Existing hook

`ControlMode.TRACKING` and `TrackingMode.GYRO` are already defined in `constants.py`.
The pipeline just needs a new case added to `update_eye_positions()` in `frame_pipeline.py`.

## Algorithm — dynamic neutral reference

Rather than using raw angular velocity (which snaps back the moment motion stops), use
**absolute Euler angle deltas from a recalibrating neutral reference**. This handles sustained
head tilt naturally.

```
head_delta_x = current_yaw   - neutral_yaw
head_delta_y = current_pitch - neutral_pitch

eye_x = clamp(head_delta_x * GYRO_SENSITIVITY_X, -30, 30)
eye_y = clamp(head_delta_y * GYRO_SENSITIVITY_Y, -30, 30)
```

The neutral recalibrates when angular velocity drops below `GYRO_STILL_THRESHOLD` for
`GYRO_RECAL_DELAY` seconds. Eyes spring back to (0, 0) with lerp easing — not a snap.

## New constants (constants.py)

```python
# ── Gyro Mode (BNO055) ────────────────────────────────────────────────────────
GYRO_SENSITIVITY_X:   Final = 1.0   # head-turn degrees → eye units (±30 range)
GYRO_SENSITIVITY_Y:   Final = 0.8   # pitch is usually over-sensitive; tune lower
GYRO_STILL_THRESHOLD: Final = 2.0   # °/s below which = "still"
GYRO_RECAL_DELAY:     Final = 1.5   # seconds still before neutral recalibrates
GYRO_RETURN_SPEED:    Final = 8.0   # units/sec spring-back speed at neutral
```

## New files

| File | Purpose |
|---|---|
| `gyro/reader.py` | Background thread; reads BNO055 at ~50 Hz; exposes `.euler`, `.angular_velocity`, `.calibrated` |
| `gyro/__init__.py` | Exports `GyroReader` |
| `mock/gyro.py` | macOS stub; returns (0,0,0) by default; arrow keys simulate head tilt |

## Changes to existing files

- **`init.py`** — add `init_gyro() -> GyroReader`; on Pi uses `adafruit_bno055`; on macOS imports `mock.gyro`
- **`frame_pipeline.py`** — add `ControlMode.TRACKING` case in `update_eye_positions()`; add `gyro_neutral_yaw`, `gyro_neutral_pitch`, `gyro_still_since` to `FrameState`
- **`main.py`** — call `init_gyro()` alongside `init_adc()`; pass `GyroReader` into `frame()`

## `_update_gyro_position` sketch

```python
def _update_gyro_position(now, eyes, gyro, state, dt):
    yaw, pitch, _ = gyro.euler
    vel = gyro.angular_velocity  # °/s magnitude

    if vel < GYRO_STILL_THRESHOLD:
        if state.gyro_still_since == 0.0:
            state.gyro_still_since = now
        elif (now - state.gyro_still_since) >= GYRO_RECAL_DELAY:
            state.gyro_neutral_yaw   = yaw
            state.gyro_neutral_pitch = pitch
    else:
        state.gyro_still_since = 0.0

    dx = (yaw   - state.gyro_neutral_yaw)   * GYRO_SENSITIVITY_X
    dy = (pitch  - state.gyro_neutral_pitch) * GYRO_SENSITIVITY_Y

    target_x = max(-30.0, min(30.0, dx))
    target_y = max(-30.0, min(30.0, dy))

    eyes.left.current.x += (target_x - eyes.left.current.x) * min(1.0, GYRO_RETURN_SPEED * dt)
    eyes.left.current.y += (target_y - eyes.left.current.y) * min(1.0, GYRO_RETURN_SPEED * dt)
```

## Implementation order

1. `gyro/reader.py` + `mock/gyro.py`
2. `init.py` — `init_gyro()`
3. `frame_pipeline.py` — `FrameState` fields + `_update_gyro_position`
4. `constants.py` — gyro constants
5. `main.py` — wire up

## Power management

**Do not use RST for power saving** — it wipes calibration and needs ~650ms + recalibration
on every wake. Use software suspend instead (~40µA, retains calibration, wakes in ms).

Wire RST to a GPIO anyway (e.g. GPIO 16) as a lockup recovery mechanism — the BNO055
occasionally hangs on I²C bus corruption and a GPIO reset recovers it without rebooting
the Pi. See `bsod_bump_plan.md` for the full suspend/resume/reset implementation in
`GyroReader`.

Add to `constants.py`:
```python
BNO_RST_PIN: Final = 16   # GPIO wired to BNO055 RST; -1 if not wired
```

## Notes

- The `GyroReader` built here doubles as the bump detection sensor (see `bsod_bump_plan.md`)
- Tune `GYRO_SENSITIVITY_Y` lower than X — pitch (nodding) tends to feel over-reactive
- BNO055 needs ~2 seconds of movement to reach full calibration after power-on; expose
  `.calibrated` property so the UI can optionally wait before activating GYRO mode
