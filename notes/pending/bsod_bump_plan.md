# BSOD Bump Effect — Design Notes

## Overview

When the device housing is physically bumped or knocked, the BNO055 accelerometer detects
the impact and triggers a "Blue Screen of Death" eye animation for a few seconds before
returning to normal operation.

Reuses the `GyroReader` built for GYRO mode — bump detection is a free add-on once the
sensor thread exists.

## Sensor — bump detection

The BNO055 has two detection paths:

### Option A: Software polling (default — use this)
Poll `gyro.linear_accel_magnitude` each frame (gravity-subtracted by the BNO055 fusion chip,
so resting = 0 regardless of orientation). Trigger if magnitude exceeds threshold. ~20ms
latency at 60 FPS — perfectly adequate for a bump reaction.

Use `linear_acceleration` output (not raw accelerometer) — gravity is already subtracted.

### Option B: HIGH_G hardware interrupt (verify INT pin first)
> **Note:** The INT pin on the Adafruit BNO055 breakout (#2472) may be tied to GND on some
> board revisions rather than being a usable output. Verify with a multimeter before wiring.
> If it is functional, configure the BNO055's HIGH_G interrupt registers (threshold ~800mg,
> duration 5ms) and wire INT to a spare GPIO. Sub-frame latency. If not available, use Option A.

## Wiring

```
BNO055 breakout:
  VIN → 3.3V
  GND → GND
  SDA → GPIO 2   (shared I²C bus with bonnet)
  SCL → GPIO 3   (shared I²C bus with bonnet)
  INT → verify pin before use — may be GND on this breakout revision
  RST → GPIO 16  (soft reset for I²C lockup recovery — see power management notes)
```

## New constants (constants.py)

```python
# ── Bump / BSOD Effect ────────────────────────────────────────────────────────
BUMP_DETECT_PIN:    Final = -1    # -1 = software polling (default); set to GPIO pin if INT is wired
BUMP_THRESHOLD_MG:  Final = 800   # mg acceleration to trigger (tune on hardware)
BUMP_DEBOUNCE:      Final = 0.3   # seconds — ignore re-triggers during BSOD
BUMP_BSOD_DURATION: Final = 3.5  # seconds — how long BSOD plays before restoring
```

## New FrameState fields

```python
bump_active:     bool        = False
bump_end_time:   float       = 0.0
bump_saved_set:  EyeSet      = EyeSet.NORMAL   # restored after BSOD ends
bump_saved_mode: ControlMode = ControlMode.RANDOM
```

## Pipeline stage — check_bump()

Runs at the top of the frame loop, before `update_eye_positions`:

```python
def check_bump(now, eyes, state):
    if state.bump_active:
        if now >= state.bump_end_time:          # BSOD expired — restore
            state.bump_active  = False
            state.eye_set      = state.bump_saved_set
            state.control_mode = state.bump_saved_mode
            state.auto_blink   = True
        return                                   # no other updates while active

    triggered = (BUMP_DETECT_PIN >= 0 and GPIO.input(BUMP_DETECT_PIN) == GPIO.LOW)

    if triggered:
        state.bump_saved_set  = state.eye_set
        state.bump_saved_mode = state.control_mode
        state.bump_active     = True
        state.bump_end_time   = now + BUMP_BSOD_DURATION
        state.eye_set         = EyeSet.GLITCH
        state.control_mode    = ControlMode.MANUAL   # freeze eye position
        state.auto_blink      = False
        eyes.left.current.set(0.0, -5.0)            # wide open, staring forward
        eyes.right.current.set(0.0, -5.0)
```

## GlitchDriver — BSOD texture (eye_sets/glitch.py)

Follows the same pattern as `HypnoSpiral` — a `(256×256)` RGBA numpy array updated each
frame and pushed into a `pi3d.Texture`.

| Time | Visual |
|---|---|
| 0.0–0.1s | Flash white (shock frame) |
| 0.1s+ | Solid #0000AA (classic BSOD blue) |
| Every frame | 2–4 random horizontal scanline bands of pixel noise |
| Every ~0.5s | Brief full-screen static flash |
| Final 0.3s | Fade to black before state is restored |

## EyeSet.GLITCH hook

`EyeSet.GLITCH` is already defined in `constants.py`. `eye_sets/base.py` documents the
pattern for adding it. Steps:
1. Create `eye_sets/glitch.py` with `GlitchDriver` + `GlitchInitializer`
2. Add `GLITCH_PRESETS` to `eye_sets/constants.py`
3. Import `GlitchInitializer` in `eye_sets/__init__.py`

## macOS dev mock

Add keyboard key `B` to `mock/gyro.py` (or `mock/hardware.py`) to simulate a bump hit —
fires the same `check_bump()` path so the BSOD effect can be tested without hardware.

## Implementation order

1. `gyro/reader.py` — add `.linear_accel_magnitude`; add HIGH_G interrupt config only if INT pin is confirmed usable
2. `eye_sets/glitch.py` — `GlitchDriver` BSOD texture
3. `eye_sets/constants.py` — `GLITCH_PRESETS`
4. `eye_sets/__init__.py` — import `GlitchInitializer`
5. `frame_pipeline.py` — `check_bump()` + `FrameState` fields
6. `constants.py` — bump constants
7. `mock/gyro.py` or `mock/hardware.py` — `B` key triggers bump

## Power management

The BNO055 draws ~12.3mA in normal fusion mode. For power saving, **software suspend is
preferred over RST** — it drops to ~40µA (300× less), wakes in milliseconds, and retains
calibration. RST kills power entirely but wipes calibration and needs ~650ms + recalibration
to recover.

### Suspend / resume via I²C register

The `adafruit_bno055` library doesn't expose power mode directly, but it's a single register
write. Add these to `GyroReader`:

```python
def suspend(self):
    self._bno.mode = 0x00                     # CONFIG_MODE first (required)
    self._bno._write_register(0x3E, 0x02)     # suspend — ~40µA

def resume(self):
    self._bno._write_register(0x3E, 0x00)     # normal power
    self._bno.mode = adafruit_bno055.NDOF_MODE
```

Call `suspend()` when leaving GYRO mode / disabling bump detection; `resume()` when
re-entering. Calibration is retained across suspend/resume cycles.

### RST GPIO — wire it anyway (for lockup recovery, not power saving)

The BNO055 occasionally hangs and stops responding on I²C if the bus gets corrupted.
A hardware reset via GPIO recovers it without a full Pi reboot. Wire RST to a GPIO
(e.g. GPIO 16, active LOW) and pulse it LOW briefly in `GyroReader.reset()`:

```python
def reset(self):
    GPIO.output(BNO_RST_PIN, GPIO.LOW)
    time.sleep(0.01)
    GPIO.output(BNO_RST_PIN, GPIO.HIGH)
    time.sleep(0.65)    # BNO055 boot time
    # re-init sensor after reset
```

| Use case | Method |
|---|---|
| Switching GYRO/bump on and off during a session | Software suspend/resume |
| Sensor hung / I²C lockup | RST GPIO pulse |
| Device idle for hours (battery power) | RST GPIO held LOW |

Add to `constants.py`:
```python
BNO_RST_PIN: Final = 16   # GPIO wired to BNO055 RST; -1 if not wired
```

## Notes

- `BUMP_DEBOUNCE` prevents the BSOD from re-triggering while it's already playing — a hard
  knock may produce multiple spikes above threshold across several frames
- The INT pin on the Adafruit BNO055 breakout (#2472) may be tied to GND — verify with a
  multimeter before assuming the hardware interrupt path is available; software polling is
  the safe default (`BUMP_DETECT_PIN = -1`)
- The BSOD effect intentionally suppresses `auto_blink` — dead, glassy stare is the point
- `ControlMode.MANUAL` during BSOD freezes the eyes at (0, -5) without any control loop
  fighting the fixed position
- See `gyro_mode_plan.md` — the `GyroReader` serves both features
