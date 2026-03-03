# DragonEyes — Project Notes

Animated dragon eyes for Raspberry Pi using pi3d. Runs on macOS for development
via a hardware mock layer.

## Running on macOS

Use `run_dev.py` as the entry point, not `eyes.py` directly.
Import order in `run_dev.py` matters — `mock_hardware` must load before `eyes`.

```
venv/bin/python run_dev.py
```

Use the arm64 venv (`venv/`), not `.venv/` (x86_64) or `.venv_arm64/`.

## File Overview

| File | Purpose |
|------|---------|
| `eyes.py` | Main animation loop and rendering |
| `eye_state.py` | `EyeState` class — all per-eye state and logic |
| `constants.py` | Project-wide configuration constants |
| `gfxutil.py` | SVG path parsing and pi3d geometry helpers |
| `snake_eyes_bonnet.py` | ADC input thread for analog joystick/pupil |
| `mock_hardware.py` | macOS dev bootstrap — patches OpenGL and mocks RPi hardware |
| `KeyboardGPIO.py` | GPIO mock that maps keyboard keys to pin states via SDL2 |
| `run_dev.py` | macOS dev launcher |

## EyeState Class (`eye_state.py`)

Consolidates all per-eye state that was previously scattered globals.

**Fields:** `start_x/y`, `dest_x/y`, `cur_x/y`, `move_duration`, `hold_duration`,
`start_time`, `is_moving`, `blink_state`, `blink_start_time`, `blink_duration`,
`tracking_pos`

**Methods:**
- `update_position(now)` — autonomous saccade movement state machine
- `update_blink(wink_pin, now)` — blink state machine (closing → held → opening)
- `start_blink(now, duration)` — sets EN_BLINKING with given duration

In `eyes.py`, `left_eye` and `right_eye` are the two instances.

## macOS OpenGL Compatibility

pi3d looks for `GLESv2.2` via `ctypes.util.find_library`, which returns `None`
on macOS. `mock_hardware.py` patches `find_library` to redirect that lookup to
the macOS native OpenGL framework so SDL2 and pi3d share the same GL context.

Display is created with `use_sdl2=True` and an explicit size (`w=800, h=256`)
to avoid fullscreen.

## KeyboardGPIO Pin Mapping

Keyboard keys simulate GPIO button presses (held = LOW):

| Key | Pin | Function |
|-----|-----|----------|
| Space | 23 | Blink both eyes |
| L | 22 | Wink left eye |
| R | 24 | Wink right eye |

## Constants (`constants.py`)

Key flags: `AUTO_BLINK`, `CRAZY_EYES`, `TRACKING`, `CONVERGENCE`

Pin assignments: `WINK_L_PIN=22`, `BLINK_PIN=23`, `WINK_R_PIN=24`

Set `CRAZY_EYES = True` to give each eye independent movement.
