# Hypno Spiral Eye Set — Design Notes

## Overview

The spiral is an **eye set** — a full replacement of the iris texture. The sclera and lids
remain unchanged. When active, a numpy array representing the spiral is redrawn each N frames
and pushed into the GL texture that the iris mesh samples from.

Reference: `hypno-spiral.html` (in Downloads) was used to explore the parameter space.

---

## 1. New enum + constants (`constants.py`)

```python
class EyeSet(Enum):
    NORMAL = auto()   # existing iris texture (dragon or any PNG)
    HYPNO  = auto()   # live-generated spiral
    GLITCH = auto()   # glitch effect (future)

EYE_SET = EyeSet.NORMAL
```

---

## 2. New module: `eye/hypno.py`

### `HypnoConfig` — all tunable parameters

```python
@dataclass
class HypnoConfig:
    name:        str   = "classic"
    # Shape
    arms:        int   = 2         # number of spiral arms
    turns:       int   = 5         # how many full rotations the spiral makes
    thickness:   float = 0.15      # arm width as fraction of circle (0–1)
    palette:     str   = "classic" # key into PALETTES dict
    # Motion
    spin_dir:    str   = "cw"      # "none" | "cw" | "ccw" | "rock"
    spin_speed:  float = 0.025
    wave:        str   = "out"     # "none" | "out" | "in" | "pulse" | "standing" | "alternate"
    wave_speed:  float = 0.03
    distort:     float = 0.0       # radial distortion amplitude (0–1)
    # Effects
    trails:      float = 0.0       # frame persistence (0–1)
    color_cycle: float = 0.0       # hue rotation speed (0–1)
    thick_pulse: float = 0.0       # thickness modulation amplitude (0–1)
    glow:        bool  = False     # soft edge falloff instead of hard cutoff
    dashes:      bool  = False     # periodic opacity along arm
    taper:       bool  = False     # arms thin toward center
    mirror:      int   = 0         # rotational mirror folds: 0, 2, 4, 6, 8
    # Render
    size:        int   = 256       # texture resolution (power of 2)
    update_hz:   int   = 30        # texture redraws per second
```

### `HypnoSpiral` — the class

```python
class HypnoSpiral:
    def __init__(self, config: HypnoConfig):
        # Pre-compute static polar grid (done once at init):
        #   r[y,x], theta[y,x] — polar coords for every texel
        #   b = log(max_r + 1) / (turns * 2π)  — log-spiral rate
        # Create initial numpy RGBA array (size × size × 3, uint8)
        # Build pi3d.Texture from PIL Image of that array

    def update(self, now: float) -> bool:
        # Returns True if texture was redrawn this call
        # Rate-limits to config.update_hz
        # Advances self._phase by config.speed
        # Re-runs the numpy draw, pushes to GL via tex.update_ndarray()

    @property
    def texture(self) -> pi3d.Texture: ...
```

### Numpy vectorized draw (core math)

The HTML uses a stroke-based approach; for a GPU texture the polar phase approach is faster
(fully vectorizable with numpy, no Python loops):

```
b = log(max_r + 1) / (num_turns * 2π)

# For each pixel:
theta_spiral = log(max(r, 1)) / b       # where on the spiral this r maps to
phase_raw    = (θ - theta_spiral) * num_arms / (2π) + anim_phase
phase        = phase_raw mod 1.0        # 0→1 per arm cycle

# phase → palette color (linear interpolation between stops)
# distance from nearest arm edge → anti-aliased alpha blend
```

Wave modes:
- `"none"`:      static, no animation
- `"out"`:       `anim_phase += wave_speed` each frame
- `"in"`:        `anim_phase -= wave_speed` each frame
- `"pulse"`:     `anim_phase += sin(now * freq) * wave_speed`
- `"standing"`:  `sin(theta * 2) * sin(anim_phase * 2)`
- `"alternate"`: adjacent arms move in opposite directions

Spin modes:
- `"none"`:  no rotation
- `"cw"`:    `spin_angle += spin_speed`
- `"ccw"`:   `spin_angle -= spin_speed`
- `"rock"`:  `spin_angle = sin(anim_phase * 0.4) * 1.5`

### Palettes

Ported from `hypno-spiral-v3.html` — 8 hex colors each, stored as `(R,G,B)` tuples:

```python
PALETTES = {
    "classic":     [(255,0,0),(0,102,255),(0,204,68),(255,213,0),(255,0,255),(0,255,255),(255,102,0),(170,0,255)],
    "neon":        [(255,0,255),(0,255,170),(255,255,0),(255,51,102),(0,204,255),(255,102,0),(102,255,0),(204,0,255)],
    "fire":        [(255,17,0),(255,102,0),(255,170,0),(255,221,0),(255,51,0),(255,136,0),(255,204,0),(255,68,0)],
    "ice":         [(0,170,255),(0,221,255),(68,238,255),(136,255,255),(0,119,204),(0,187,238),(102,221,255),(170,255,255)],
    "psychedelic": [(255,0,170),(170,0,255),(0,68,255),(0,255,170),(255,255,0),(255,68,0),(0,255,68),(255,0,102)],
    "venom":       [(0,255,0),(51,255,51),(0,221,0),(102,255,102),(0,187,0),(68,255,68),(0,255,68),(34,238,34)],
    "sunset":      [(255,69,0),(255,99,71),(255,127,80),(255,215,0),(255,140,0),(255,20,147),(220,20,60),(255,105,180)],
    "ocean":       [(0,68,170),(0,102,204),(0,136,238),(0,170,255),(34,187,255),(68,204,255),(0,102,153),(0,85,187)],
    "bw":          [(255,255,255),(187,187,187),(255,255,255),(187,187,187),(255,255,255),(187,187,187),(255,255,255),(187,187,187)],
}
```

---

## 3. `FrameState` additions (`frame_pipeline.py`)

```python
eye_set:      EyeSet = EYE_SET        # active skin
prev_eye_set: EyeSet = EYE_SET        # for detecting transitions
```

---

## 4. `SceneContext` addition (`models/scene_types.py`)

```python
@dataclass
class SceneContext:
    ...
    hypno:          HypnoSpiral | None = None
    normal_iris_tex: pi3d.Texture | None = None   # saved ref for switching back to NORMAL
```

`init_scene` always creates the `HypnoSpiral` (cheap — just numpy arrays, no file I/O).
Also save `iris_map` as `scene.normal_iris_tex` so it can be restored on eye set switch.

---

## 5. New pipeline stage: `update_eye_set` (`frame_pipeline.py`)

Called between `update_iris` and `update_blinks` in `frame()`:

```python
def update_eye_set(now, state, scene):
    if state.eye_set == EyeSet.HYPNO:
        if scene.hypno.update(now):
            scene.left.iris.set_textures([scene.hypno.texture])
            scene.right.iris.set_textures([scene.hypno.texture])
    elif state.prev_eye_set == EyeSet.HYPNO:
        # just switched back to NORMAL
        scene.left.iris.set_textures([scene.normal_iris_tex])
        scene.right.iris.set_textures([scene.normal_iris_tex])
    state.prev_eye_set = state.eye_set
```

`update_iris` (pupil scale regen) is skipped when `eye_set == HYPNO` — the iris mesh
shape doesn't change, only its texture does.

---

## 6. Gamepad bindings

All global (no mode gate):

| Combo | Action |
|---|---|
| X + Down | Toggle NORMAL ↔ HYPNO |
| X + Right trigger | Next preset |
| X + Left trigger  | Previous preset |

---

## File Change Summary

| File | Change |
|---|---|
| `constants.py` | Add `EyeSet` enum, `EYE_SET` constant |
| `eye/hypno.py` | **New** — `HypnoConfig`, `HypnoSpiral`, `PALETTES` |
| `eye/__init__.py` | Export `HypnoSpiral`, `HypnoConfig` |
| `models/scene_types.py` | Add `hypno`, `normal_iris_tex` to `SceneContext` |
| `frame_pipeline.py` | Add `eye_set`/`prev_eye_set` to `FrameState`; add `update_eye_set()` |
| `init.py` | Create `HypnoSpiral` in `init_scene`, save `dragon_iris_tex` ref |
| `main.py` | Call `update_eye_set(now, state, scene)` in `frame()` |
| `bluetooth/` | Add toggle binding for `state.eye_set` |

---

## Open Questions (to decide before implementation)

1. **Texture size**: 256×256 hardcoded for now; move to `constants.py` later.
2. **Sclera during hypno mode**: Keep normal sclera; fade via `set_alpha()` on transition.
3. **Lids during hypno mode**: Keep normal blinking; `auto_blink` toggle handles force-open.
4. **Iris mesh shape**: Spiral wraps to existing iris SVG shape for now.
