# DragonEyes

Animated dragon eyes for Raspberry Pi using pi3d and SSD1351 OLED displays. Runs on macOS for development via a hardware mock layer.

## Credits

Based on [Adafruit Pi_Eyes](https://github.com/adafruit/Pi_Eyes) by Adafruit Industries. This project uses their pi3d rendering foundation, SVG-driven eye geometry, Snake Eyes Bonnet ADC integration, and eyelid/blink state machine as a starting point, with substantial additions and refactoring on top.

---

## Running the Project

**macOS (development):**
```
venv/bin/python run_dev.py
```
Use `venv/` (arm64, Python 3.14) — not `.venv/` (x86_64) or `.venv_arm64/`. Import order in `run_dev.py` is critical: `mock.hardware` must load before `eyes` so all Pi hardware calls are intercepted.

**Raspberry Pi (production):**
```
python main.py [--radius N]
```
`--radius` overrides the default eye radius (128px; use 240 for IPS screens). Set `ROTATE_EYES = True` in `constants.py` when screens are mounted 180°.

---

## Project Structure

```
DragonEyes/
├── main.py               — Entry point; outer animation loop
├── run_dev.py            — macOS dev launcher (loads mock layer first)
├── frame_pipeline.py     — Per-frame render pipeline
├── init.py               — Hardware and scene initialization chain
├── constants.py          — All behavior flags and configuration
├── gfxutil.py            — SVG path parsing and pi3d geometry helpers
├── debug_overlay.py      — Debug movement visualizer
├── snake_eyes_bonnet.py  — ADC input thread for analog joystick/pupil
│
├── eye/                  — Per-eye animation logic
│   ├── state.py          — EyeState: position, blink state machine, saccades
│   ├── lid.py            — EyeLidMesh, EyeLidState, _LidState
│   ├── sequence.py       — SequencePlayer: JSON keyframe playback
│   └── eyes.py           — Eyes class: coordinates both eye instances
│
├── eye_sets/             — Swappable visual skins (plugin registry)
│   ├── base.py           — EyeSetConfig base class
│   ├── hypnosis.py       — Live-generated hypnotic spiral texture
│   ├── concentric.py     — Live-generated concentric rings texture
│   ├── palettes.py       — Color palette definitions
│   └── constants.py      — Preset configurations for each eye set
│
├── models/               — Shared dataclasses (import via `from models import X`)
│   ├── scene_types.py    — LidPoints, EyeMeshes, SvgPoints, SceneContext
│   ├── system_types.py   — HardwareContext, DisplayContext
│   └── point.py          — Point, smoothstep
│
├── mock/                 — macOS hardware mock layer
│   ├── hardware.py       — Patches OpenGL and injects mock hardware modules
│   ├── keyboardGPIO.py   — SDL2 keyboard → GPIO pin simulation
│   └── bonnet.py         — Mock Snake Eyes Bonnet / ADC
│
├── keyframes/            — JSON keyframe sequence files
│   ├── sample1.json
│   └── ...
│
├── graphics/             — SVG eye geometry and textures
│   ├── dragon-eye-edit.svg
│   ├── dragon-iris-color.png
│   ├── dragon-sclera.png
│   └── lid.png
│
└── notes/                — Design docs and planning notes
```

---

## Configuration (`constants.py`)

All runtime behavior is controlled here — no code changes needed for most use cases.

| Constant | Default | Description |
|---|---|---|
| `CONTROL_MODE` | `RANDOM` | `RANDOM`, `MANUAL`, `SCRIPTED`, or `TRACKING` |
| `EYE_SET` | `NORMAL` | `NORMAL`, `HYPNO`, `RINGS`, or `GLITCH` |
| `EYE_SET_PRESETS` | `False` | Cycle eye set presets via gamepad |
| `SEQUENCE_FILE` | `keyframes/sample1.json` | Active keyframe file for `SCRIPTED` mode |
| `AUTO_BLINK` | `True` | Autonomous random blink timer |
| `CRAZY_EYES` | `False` | Each eye moves independently |
| `EYELID_TRACKING` | `True` | Upper eyelid follows eye's vertical position |
| `MIRROR_LIDS` | `True` | Right lid mirrors left; `False` = independent channels |
| `ROTATE_EYES` | `False` | Set `True` when screens are mounted 180° |
| `PUPIL_IN` | `-1` | ADC channel for pupil (`-1` = auto/fractal) |
| `JOYSTICK_X_IN` / `Y_IN` | `-1` | ADC channels for manual eye position |
| `CONVERGENCE` | `2.0` | Eye convergence (0 = parallel, >1 = over-converged) |
| `DEBUG_MOVEMENT` | `False` | Replaces eye draw with saccade vector overlay |
| `KEYFRAME_STEP` | `False` | Space bar steps one keyframe at a time |
| `TARGET_FPS` | `60` | Frame rate cap |

---

## Features Added Over Pi_Eyes

### Architecture Refactor
- Full package structure: `eye/`, `eye_sets/`, `mock/`, `models/`
- Typed dataclasses for all shared state (`HardwareContext`, `DisplayContext`, `SceneContext`, `SvgPoints`, `EyeMeshes`, `LidPoints`, `Point`)
- Clean initialization chain: `init_gpio()` → `init_adc()` → `init_svg()` → `init_display()` → `init_scene()`
- Separation of frame pipeline (`frame_pipeline.py`) from entry point (`main.py`)

### Control Modes
- **RANDOM** — autonomous saccades with smoothstep easing, randomized hold durations
- **MANUAL** — gamepad joystick drives eye position and lid weight in real time
- **SCRIPTED** — `SequencePlayer` follows JSON keyframe sequences with optional Bézier control points
- **TRACKING** — stub for camera/sensor-driven eye movement (gyro mode in planning)

### Scripted Keyframe Sequences
- `SequencePlayer` in `eye/sequence.py` loads JSON keyframe files
- Per-keyframe fields: `destination`, `move_duration`, `hold_duration`, optional `pupil_scale`, optional `control` (quadratic Bézier)
- `hold_duration: 0.0` = constant-velocity pass-through (no perceived stop)
- Sequences loop; `KEYFRAME_STEP` mode for frame-by-frame debugging
- Keyframe editor: `keyframes/editor.html` (browser-based visual tool)

### Eye Sets — Swappable Visual Skins
- Plugin registry in `eye_sets/` allows runtime eye set switching
- **NORMAL** — original dragon iris texture (SVG-driven pi3d mesh)
- **HYPNO** — live-generated hypnotic spiral, configurable rotation speed and color palette
- **RINGS** — live-generated concentric rings with configurable palette
- **GLITCH** — glitch visual effect
- Presets for each eye set; `EYE_SET_PRESETS = True` enables gamepad cycling

### Gamepad Input
- 8BitDo Micro (or compatible) via macOS `GCController` / PyObjC
- Joystick → eye X/Y position in `MANUAL` mode
- D-pad / buttons → runtime mode switching, lid adjustment, eye set cycling
- Controller bindings configurable in `frame_pipeline.py`

### macOS Development Environment
- `mock/hardware.py` patches `ctypes.util.find_library` to redirect `GLESv2.2` → macOS OpenGL framework
- Injects `KeyboardGPIO` as `RPi.GPIO`; keyboard keys simulate GPIO states
- `mock/bonnet.py` simulates Snake Eyes Bonnet ADC channels
- SDL2 keyboard controls: Space = blink both, L = wink left, R = wink right
- No Raspberry Pi required for development

### Eye Animation Improvements
- `Point` dataclass with `+`, `-`, `*`, `/` operators for clean movement math
- `smoothstep` easing on all saccades
- `CRAZY_EYES` — independent left/right eye destinations
- Eyelid tracking: upper lid follows eye's vertical position
- Mesh regen thresholds (¼-pixel granularity) to avoid unnecessary GPU work
- Convergence control: eyes angle inward by a configurable amount

### Debug Tools
- `DEBUG_MOVEMENT = True` — renders a `DebugOverlay` showing saccade start/end vectors instead of the eye
- `KEYFRAME_STEP` — pause-and-advance mode for scripted sequence inspection

### Deployment
- `deploy.sh` — rsync-based deploy script to Raspberry Pi target

---

## Keyboard Controls (macOS dev)

| Key | GPIO Pin | Function |
|-----|----------|----------|
| Space | 23 | Blink both eyes |
| L | 22 | Wink left eye |
| R | 24 | Wink right eye |
| 5 / 6 | — | Lid preview channels (mock bonnet) |

---

## Graphics

SVG source: `graphics/dragon-eye-edit.svg` — edit named paths here to reshape eye geometry. Named paths: `pupilMin`, `pupilMax`, `iris`, `scleraFront`, `scleraBack`, `upperLid*`, `lowerLid*`.

Sclera is a pi3d `Lathe` (revolution solid) generated from the front/back angle points. Left iris UV is offset 0.5 (180° rotation) so both eyes don't obviously share a texture tile.
