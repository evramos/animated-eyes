# Ripple Eye Skin — Implementation Plan

## Concept
A new eye skin featuring concentric rippling rings emanating outward from the pupil,
alternating between two colors with rough/jagged edges. Selectable at runtime via
a mobile webpage over Bluetooth. Uses the same lid logic as the dragon eye.

---

## What Stays the Same
- All lid logic (`EyeLidState`, `EyeLidMesh`, lid weights, blink, tracking)
- Eye position and rotation (`EyeState`, saccade system)
- `init_display`, `init_gpio`, `init_adc`

---

## New Components

### 1. GLSL Ripple Shader — `shaders/ripple_iris.glsl`
The ring pattern is computed entirely on the GPU.
- Compute UV distance from center: `r = length(uv - 0.5)`
- Add noise to `r` for rough edges: `noise = sin(uv.x * 40.0) * sin(uv.y * 40.0) * roughness`
- Drive ring color from: `step(0.0, sin((r + noise) * freq - time * speed))`
- Mix between `color_a` and `color_b` based on ring value
- Mask center as solid dark circle using `pupil_radius` uniform

```glsl
float r = length(uv - 0.5);
float noise = sin(uv.x * 40.0) * sin(uv.y * 40.0) * roughness;
float ring = step(0.0, sin((r + noise) * freq - time * speed));
gl_FragColor = mix(color_a, color_b, ring);
```

Uniforms:
| Name           | Type  | Description                        |
|----------------|-------|------------------------------------|
| `color_a`      | vec3  | First ring color (RGB)             |
| `color_b`      | vec3  | Second ring color (RGB)            |
| `freq`         | float | Ring spacing / density             |
| `speed`        | float | Outward drift rate                 |
| `roughness`    | float | Edge jaggedness amount             |
| `time`         | float | Current time in seconds (animated) |
| `pupil_radius` | float | Solid dark center radius (0–0.5)   |

### 2. Skin Init — `eye_skins/ripple.py`
- `init_ripple_scene(svg, ctx) → SceneContext`
- Reuses existing SVG iris mesh geometry
- Binds the ripple shader instead of the dragon texture
- Sclera stays dark/black for contrast
- Returns the same `SceneContext` shape `eyes.py` expects — swapping skins
  is just swapping which init function was called

### 3. Live Parameters — `eye_skins/ripple_params.py`
- `RippleParams` dataclass holding all live shader uniforms
- Bluetooth/web controller writes to this object
- Frame loop reads from it and pushes to shader via `set_uniform(...)` each frame

```python
@dataclass
class RippleParams:
    color_a:      tuple = (1.0, 0.0, 0.0)   # red
    color_b:      tuple = (0.0, 0.0, 0.0)   # black
    freq:         float = 20.0
    speed:        float = 1.5
    roughness:    float = 0.02
    pupil_radius: float = 0.15
```

### 4. Mobile Webpage / Bluetooth Bridge (future)
- Small Flask or FastAPI server running on the Pi
- Exposes REST endpoints for each parameter
- Mobile page (Web Bluetooth API or local network URL) hits the endpoints
- Server writes received values into `RippleParams` instance
- Render loop picks up changes next frame automatically
- Self-contained — does not touch the render loop

---

## File Structure

```
eye_skins/
    __init__.py
    ripple.py           ← init_ripple_scene() → SceneContext
    ripple_params.py    ← RippleParams dataclass (live uniforms)
shaders/
    ripple_iris.glsl    ← fragment shader (the visual effect)
```

---

## Implementation Order
1. `shaders/ripple_iris.glsl` — get the visual effect right first
2. `eye_skins/ripple_params.py` — parameter dataclass
3. `eye_skins/ripple.py` — skin init wiring it together
4. Test in `run_dev.py` by temporarily swapping `init_scene` → `init_ripple_scene`
5. Add skin selection logic to `eyes.py` (e.g. `EYE_SKIN` constant or runtime flag)
6. Flask/FastAPI control server (separate task)
7. Mobile webpage UI (separate task)

---

## Notes
- Ring math on the GPU means the CPU only pushes a few float uniforms per frame —
  the animation itself costs nothing in Python (important on Pi at 60fps)
- `roughness` noise uses sin-based noise (no texture lookup needed) for simplicity;
  can be upgraded to a hash-based noise function for more organic edges later
- The `time` uniform increments each frame: `time += 1.0 / TARGET_FPS`
