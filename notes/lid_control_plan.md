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

### Rotation sign convention (revised 2026-10-30)
Author angles **semantically**, not per-screen:
- **`+` = inner (nose-side) corner DOWN**: angry / menacing direction
- **`−` = inner corner UP**: sad / worried / pleading direction

Convert to pi3d Z at draw time: `left z = base + angle`, `right z = base − angle`,
where `base = ROTATE_DEGREES if ROTATE_EYES else 0`. Presets then never need
per-eye signs, and the mount correction is never lost (see "Composition with
ROTATE_EYES" below).

### Expression presets (rotation + weight combos)
These are approximate starting points; all need visual tuning. Rotation columns use
the semantic sign above and give **left-eye** values; the right eye mirrors unless the preset is
listed under the asymmetric table.

**Core set (original)**

| Expression | Upper wt | Lower wt | Upper rot | Lower rot | Notes |
|---|---|---|---|---|---|
| `NEUTRAL` | 0.3 | 0.7 | 0° | 0° | Default resting pose |
| `WIDE_AWAKE` | 0.0 | 1.0 | 0° | 0° | |
| `TIRED` | 0.6 | 0.6 | 0° | 0° | |
| `ANGRY` | 0.5 | 0.55 | +12° | +5° | |
| `SAD` | 0.5 | 0.7 | −10° | 0° | |
| `SUSPICIOUS` | 0.6 | 0.55 | +8° | +4° | |
| `EXCITED` | 0.1 | 0.85 | 0° | 0° | |
| `SQUINT` | 0.65 | 0.45 | +15° | +8° | |

**Extended set (new)**

| Expression | Upper wt | Lower wt | Upper rot | Lower rot | Pupil | Extras |
|---|---|---|---|---|---|---|
| `HAPPY` | 0.35 | 0.45 | −4° | −8° | 0.6 | Lower lid pushed up = "smiling eyes" |
| `SURPRISED` | 0.0 | 1.0 | 0° | 0° | 0.3 | Suppress auto-blink while held |
| `SCARED` | 0.05 | 0.9 | −8° | 0° | 0.2 | Small gaze jitter; faster blink rate |
| `WORRIED` | 0.35 | 0.7 | −14° | 0° | 0.5 | Stronger inner-up than `SAD` |
| `PLEADING` | 0.15 | 0.8 | −12° | 0° | 0.95 | Big pupils, gaze slightly up |
| `SLEEPY` | 0.75 | 0.65 | −3° | 0° | — | Blink rate ×0.5, slow blink duration |
| `BORED` | 0.55 | 0.7 | 0° | 0° | — | Gaze bias down/side |
| `FOCUSED` | 0.45 | 0.55 | +6° | +3° | 0.4 | Steady gaze, reduced saccade range |
| `DISGUSTED` | 0.55 | 0.45 | +6° | −6° | — | Lower inner corner up (sneer) |
| `MISCHIEVOUS` | 0.5 | 0.5 | +6° | −6° | — | Gaze bias to one side |
| `MENACING` | 0.55 | 0.5 | +18° | +6° | 0.1 | Signature dragon look, slit pupil; near the rotation limit |

Pupil = `pupil_scale` (0 = min/slit, 1 = max dilation, same as keyframe JSON). "—" = leave
the current pupil behaviour unchanged.

**Asymmetric presets** (left and right given separately, no mirroring)

| Expression | Left upper wt / rot | Left lower wt / rot | Right upper wt / rot | Right lower wt / rot | Extras |
|---|---|---|---|---|---|
| `CONFUSED` | 0.25 / −8° | 0.7 / 0° | 0.55 / +6° | 0.6 / 0° | |
| `SKEPTICAL` | 0.15 / −6° | 0.7 / 0° | 0.55 / +8° | 0.55 / +3° | One "brow" raised |
| `SMUG` | 0.55 / +4° | 0.6 / 0° | 0.35 / 0° | 0.7 / 0° | Gaze to the side |

Asymmetric presets require the right eye's lids to update independently, so they must force the
`right_independent` path in `update_lid_tracking` (currently `crazy_eyes or not MIRROR_LIDS`).

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

### Composition with ROTATE_EYES
Today `draw_scene()` only calls `lids[side].rotateToZ(z)` when `ROTATE_EYES` is set, and
`rotateToZ` is absolute. Expression rotation must therefore:
1. Always be applied, even when `ROTATE_EYES` is False (base = 0).
2. Add to the mount angle, never replace it: `rotateToZ(base ± upper, base ± lower)`.

Pivot: pi3d rotates around the mesh origin, which for the lids is the eye center. A lid point
at distance `d` from center moves about `d·sin θ`; at the default 128px radius, 12° moves the
corner roughly 25px. This is the main reason for the rotation-limit question below.

---

## Feature 3: Expression Preset Data Model

### Proposed types
```python
@dataclass(frozen=True)
class LidPose:
    upper_wt:  float          # 0 = open, 1 = closed (same as everywhere else)
    lower_wt:  float
    upper_rot: float = 0.0    # degrees, semantic sign (+ = inner corner down)
    lower_rot: float = 0.0

@dataclass(frozen=True)
class Expression:
    left:        LidPose
    right:       LidPose | None = None          # None → mirror left
    pupil_scale: float | None = None            # None → leave pupil alone
    gaze_bias:   tuple[float, float] | None = None
    blink_rate:  float | None = None            # multiplier on auto-blink interval; 0 = suppress
```
- Presets live in a dict keyed by an `Expression` enum name (e.g. in `eye/expressions.py`).
- `right=None` covers the symmetric tables; asymmetric presets fill in `right`.
- Optional fields stay `None`, so an expression only overrides what it authors and
  everything else (saccades, pupil, auto-blink) keeps running normally.

### LidAnimator (answers open question 4)
One object per eye that owns the **current** and **target** `LidPose` plus a duration, and is
eased with `smoothstep`. Weights and angles move together, so they never step on each other.
`update_lid_tracking` reads `animator.current` as a new priority level:

1. MANUAL gamepad override (Y/A held)
2. **Active expression (`LidAnimator`)** ← new
3. `eyelid_tracking=True`
4. Scripted `lid_weight`
5. lid_channels preview / fixed defaults

Expression sits above tracking because a held emotion should not be pulled around by the
eye's vertical position. An expression could set `eyelid_tracking=True` explicitly
if blending the two is wanted later.

### Keyframe JSON integration
```json
{ "destination": [0, 0], "move_duration": 0.8, "hold_duration": 2.0,
  "expression": "MENACING" }
```
- `expression` is **sticky**, like `auto_blink` / `eyelid_tracking`: it persists until a
  later keyframe changes it. `"expression": null` returns to normal lid behaviour.
- The transition uses the keyframe's `move_duration` (via `LidAnimator`), so lids ease
  into the emotion while the eye travels.
- Optional `lid_rotation: [upper, lower]` (or a `{"left": …, "right": …}` dict, mirroring
  `lid_weight`) for one-off angles without a named preset.
- Explicit `lid_weight` / `lid_rotation` on a keyframe override the expression's values
  for that keyframe.
- **Fixes the carry-forward gap:** today `current_lid_weight` returns `None` whenever the
  previous keyframe didn't author `lid_weight` (`eye/sequence.py:201`), so lids freeze.
  Make `lid_weight` sticky too (carry the last authored value forward), so interpolation
  always has a "from" value.
- `editor.html` gains an expression dropdown per keyframe.

### Gamepad (MANUAL mode)
Add a binding to cycle expressions and one to return to `NEUTRAL`. Button assignment is
still to be decided; check `bluetooth/bindings.py` for free combos.

---

## Open Questions / Refinement Needed

1. **Natural mapping tuning** — the FULLY_OPEN / HALF_OPEN weight table above needs
   visual testing; actual values depend on the SVG geometry of the active eye set.
2. **Rotation limits** — what angle range looks good before the lid curve clips or
   looks broken? Likely ±15°–20° maximum; needs testing.
3. **Per-eye asymmetry**: *proposed answer:* yes, first-class asymmetric presets via
   `Expression.right` (see `CONFUSED` / `SKEPTICAL` / `SMUG`). They force independent right-lid updates.
4. **Smooth transition between expressions**: *proposed answer:* one `LidAnimator` per
   eye owning weight + angle targets together (see Feature 3).
5. **Interaction with blink**: `_blend_lid` always applies blink on top of tracking_pos.
   *Proposed:* scale rotation by `(1 − blink_weight)` so the lids flatten as they close and
   meet cleanly. Tilted lids at full closure may leave a gap at the corners; verify visually.
6. **Eye set compatibility** — lid rotation + weight values tuned for the dragon SVG
   will need re-tuning for other eye sets (hypno spiral uses different lid geometry).
   Consider storing per-eye-set defaults in the `EyeSetDef`.
7. **Expression vs. RANDOM mode**: should RANDOM mode occasionally drift into a
   random expression (weighted toward `NEUTRAL`)? That would give the idle animation
   more life without any scripting.
8. **Gaze bias scope**: `gaze_bias` needs a hook into `EyeState.update_position`'s random
   destination picker (offset the unit-circle center). Confirm that's acceptable before
   adding it.
