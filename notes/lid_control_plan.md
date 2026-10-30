# Lid Position Control & Rotation — Brainstorm

## Current System (baseline to build on)

### Weight convention — confirmed
- `weight 0.0` = **fully open** (maps to `open_pts` in SVG)
- `weight 1.0` = **fully closed** (maps to `closed_pts` in SVG)
- Driven by `points_interp(open_pts, closed_pts, weight)` — `weight` is the blend fraction
  toward the *closed* points, so 0 = open, 1 = closed.

### Default resting positions
| Lid | Default weight | What it looks like |
|---|---|---|
| Upper | 0.3 | Slightly drooped — not pinned wide open |
| Lower | 0.7 | Raised 70% toward closed — gives the eye a natural "shelf" |

These are asymmetric on purpose: the lids travel different distances in the SVG geometry.
Equal weights (e.g. both 0.5) will *not* look like a natural half-open eye.

### Blend formula
`_blend_lid(tracking_pos, blink_weight)` = `t + n * (1 - t)`
Blink weight is a multiplying override that always pushes toward 1.0.
At blink_weight=1.0 any tracking_pos collapses to fully closed.

---

## Feature 1: Explicit Lid Position Control

### What we need
A clean way to drive lid positions to a target value (for expressions, mode switching, etc.)
independently of the tracking/blink system.

### Single vs. two-value API
- **Single value given for an eye** → drive both upper and lower together using a
  *natural mapping* (not equal weights — see below).
- **Two values given** → set upper and lower independently.

### "Natural" combined openness mapping
Because upper and lower have different resting points and travel ranges, a single
"openness" knob should map to natural lid weights rather than equal values.
Proposed: define a `LidPreset` (or just a tuple) that encodes paired upper/lower weights
for common positions.

| Openness label | Upper weight | Lower weight | Notes |
|---|---|---|---|
| `FULLY_OPEN` | 0.0 | 1.0 | Upper pinned up, lower pushed down out of view |
| `NATURAL_OPEN` | 0.3 | 0.7 | Default resting — looks normal and awake |
| `HALF_OPEN` | 0.5 | 0.6 | Halfway — sleepy-ish |
| `MOSTLY_CLOSED` | 0.8 | 0.5 | Almost a squint |
| `FULLY_CLOSED` | 1.0 | 1.0 | Both lids meet — forced shut |

The table above is a starting point; actual values need visual tuning.

### Direct value vs. "perfect" normalized value — recommendation
**Keep 0–1 direct weights** rather than inverting to a 0=closed / 1=open convention.
Reason: the existing weight system, `points_interp`, `_LidState`, `current_lid_weight`,
and all keyframe JSON all speak in the same 0=open / 1=closed direction.
Introducing a flipped convention for the new API buys nothing and creates a translation
tax every time you cross the boundary.

Document the convention clearly in the API signature name and docstring:
```python
def set_lid_weight(eye, weight: float)              # 0=open, 1=closed; applies to both lids
def set_lid_weights(eye, upper: float, lower: float) # independent control
```

### Smooth vs. snap-to-target
- **Snap**: write directly to `upper_tracking_pos` / `lower_tracking_pos` each frame —
  already how `update_lid_tracking` works in the SCRIPTED path.
- **Smooth/animated**: lerp toward the target weight over time (like the existing eye
  position smoothing). Add a target + speed to `EyeState` or a new `LidController` object.
  This would be useful for expression transitions.

Recommended path: support both. `set_lid_weights(eye, u, l)` snaps (direct assignment).
`animate_lid_weights(eye, u, l, duration)` smooths over N seconds using the same
`smoothstep` already used for eye position.

### Where this connects
The expression mode (roadmap item 2) will need this as its primary lid API.
`SAD`, `EXCITED`, etc. would just be named presets that call `animate_lid_weights`.

---

## Feature 2: Lid Rotation for Expressions

### Current state
`EyeLidMesh.rotateToZ(angle)` rotates **both** upper and lower lids to the same angle.
Already called in `draw_scene()` when `ROTATE_EYES=True`.
Individual lids are accessible: `lids.upper.rotateToZ(angle)` and `lids.lower.rotateToZ(angle)`
are already valid pi3d calls — the infrastructure is there.

### What independent upper/lower rotation expresses
Rotation tilts the lid curve along its Z axis. Since the lids are horizontal arcs,
Z-rotation effectively "tilts" the eyebrow shape without changing the weight/openness.

| What rotates | Direction | Visual effect |
|---|---|---|
| Upper lid inward (nose-corner down) | Left eye: +Z, Right eye: −Z | Angry / menacing |
| Upper lid outward (nose-corner up) | Left eye: −Z, Right eye: +Z | Sad / worried |
| Both lids same positive angle | Canted tilt | Curious / head-tilt |
| Upper inward + lower inward | Both corners fold in | Aggressive squint |
| Upper out + lower in | Opposite tilt | Confused / wry |
| Asymmetric left vs. right eye | One eye only | Smug / suspicious |

### Expression presets (rotation + weight combos)
These are approximate starting points; all need visual tuning.

| Expression | Upper wt | Lower wt | Upper rot (left/right) | Lower rot (left/right) |
|---|---|---|---|---|
| `NEUTRAL` | 0.3 | 0.7 | 0° / 0° | 0° / 0° |
| `WIDE_AWAKE` | 0.0 | 1.0 | 0° / 0° | 0° / 0° |
| `TIRED` | 0.6 | 0.6 | 0° / 0° | 0° / 0° |
| `ANGRY` | 0.5 | 0.55 | +12° / −12° | +5° / −5° |
| `SAD` | 0.5 | 0.7 | −10° / +10° | 0° / 0° |
| `SUSPICIOUS` | 0.6 | 0.55 | +8° / −8° | +4° / −4° |
| `EXCITED` | 0.1 | 0.85 | 0° / 0° | 0° / 0° |
| `SQUINT` | 0.65 | 0.45 | +15° / −15° | +8° / −8° |

Positive rotation = clockwise when viewed from the front.
For mirrored eyes (left/right) the sign flips to keep the expression symmetric.

### API options for per-lid rotation

**Option A — extend `EyeLidMesh.rotateToZ`**
```python
def rotateToZ(self, upper_angle: float, lower_angle: float | None = None):
    self.upper.rotateToZ(upper_angle)
    self.lower.rotateToZ(upper_angle if lower_angle is None else lower_angle)
```
Minimal change; backward-compatible (existing callers pass one value, lower defaults to same).

**Option B — expose upper/lower directly**
Leave `rotateToZ` as-is; call `lids.upper.rotateToZ(a)` and `lids.lower.rotateToZ(b)` 
from the expression driver. Simpler but callers need to know the internals.

**Option C — `LidRotation` dataclass on `EyeMeshes` / expression preset**
Add a `(upper_angle, lower_angle)` field to the expression system and drive it in
`draw_scene()`. Cleanest if expressions become first-class presets.

Recommendation: start with **Option A** (minimal, backward-compatible) and move to C
once the expression preset system is fleshed out.

---

## Open Questions / Refinement Needed

1. **Natural mapping tuning** — the FULLY_OPEN / HALF_OPEN weight table above needs
   visual testing; actual values depend on the SVG geometry of the active eye set.
2. **Rotation limits** — what angle range looks good before the lid curve clips or
   looks broken? Likely ±15°–20° maximum; needs testing.
3. **Per-eye asymmetry** — should expressions always be symmetric (left mirrors right)
   or do we want first-class asymmetric presets (e.g. smug left eye only)?
4. **Smooth transition between expressions** — `animate_lid_weights` + `animate_lid_rotation`
   both need to run concurrently without stepping on each other or the blink system.
   A small `LidAnimator` class that owns both weight and angle targets + speeds may be
   cleaner than two separate animation variables on `EyeState`.
5. **Interaction with blink** — `_blend_lid` always applies blink on top of tracking_pos.
   Rotation does not currently interact with blink; confirm this is the right behaviour
   (do we want the rotation to zero out when the eye is fully blinked closed?).
6. **Eye set compatibility** — lid rotation + weight values tuned for the dragon SVG
   will need re-tuning for other eye sets (hypno spiral uses different lid geometry).
   Consider storing per-eye-set defaults in the `EyeSetDef`.
