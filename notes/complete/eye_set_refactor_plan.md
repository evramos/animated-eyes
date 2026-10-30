# Eye Set Refactor — Dragon as an Eye Set + Lazy Drivers

Status: **Phase 1 implemented 2026-10-29** (smoke-tested on macOS mock; pending Pi verification). Phase 2 not started.

## Current State (baseline)

### How eye sets are created today
`init_scene` (`init.py:269-271`) runs `EyeSetInitializer.all()` → `register()` for every subclass at startup.

| Piece | When created | Where |
|---|---|---|
| **Driver** (`HypnoSpiral()`, `ConcentricRings()`) | **Eagerly at startup**, every registered set | `driver = self._driver_factory()` in `EyeSetInitializer.register()` (`eye_sets/base.py`) |
| **Meshes** (two hemispheres) | **Lazily on first activation** | `_build` closure, invoked by `EyeSetDef.meshes()` |

So every set's numpy grid, first two frames and two GL textures get built at boot, even if the set is never used.
Per-frame updates are lazy: `update_eye_set` only calls `driver.update()` on the active set.

### Problems with dragon ("NORMAL") being special-cased
- `draw_scene` has `if alt: … else: iris/sclera` branches 3× (`pipeline/stages.py` ~479-518).
- `update_iris` hardcodes `if state.eye_set == EyeSet.HYPNO: return` → **bug:** iris still regens every frame while RINGS is active.
- `SceneContext` carries dragon-only data (`iris_z`, `iris_regen_threshold`, `left/right.iris/sclera`).
- `bluetooth/bindings.py` `_switch_eye_set` hardcodes `draw_lids = (eye_set == NORMAL)`.

---

## Decisions made
- **Lids are shared** across all eye sets (scene-level). Later: per-set JSON expressions that fire randomly or on manual trigger
  drive lid weights; the expression system shouldn't care which skin is active.
- **Lazy drivers.** Only the startup set (`EYE_SET` in `constants.py`, already configurable) is pre-built in `init_scene`.

## Open decisions
- ~~Rename `EyeSet.NORMAL` → `EyeSet.DRAGON`~~ — **done**.
- ~~Python version on the Pi~~ — **confirmed 3.13.5** (Trixie, `/opt/pi-eyes-venv`). PEP 695 `type` is used for `Side`.

---

## Plan — Phase 1: Dragon eye set + lazy registry

### 1. `EyeSetDef` becomes a lazy handle (`models/scene_types.py`)
Use `functools.cached_property` instead of a manual `if self._x is None` check.

```python
from functools import cached_property
from typing import Protocol, Literal

type Side = Literal[0, 1]          # 3.12+; on 3.11 use: Side = Literal[0, 1]

class EyeSetRenderer(Protocol):
    driver: object | None
    def update(self, now: float, pupil_scale: float) -> None: ...
    def rotate(self, side: Side, x: float, y: float, z: float | None) -> None: ...
    def draw(self, side: Side) -> None: ...

@dataclass(eq=False)
class EyeSetDef:
    factory:   Callable[[], EyeSetRenderer]
    presets:   list = field(default_factory=list)
    draw_lids: bool = True                 # default lid visibility when this set activates
    # later: expressions_path for per-set expression JSON

    @cached_property
    def renderer(self) -> EyeSetRenderer:
        return self.factory()              # runs once, on first access

    @property
    def built(self) -> bool:
        return "renderer" in self.__dict__
```

Notes:
- `cached_property` stores the result in the instance `__dict__` → after the first access it's a plain attribute lookup (cheaper than a method call per frame).
- Can't combine with `@dataclass(slots=True)` (needs `__dict__`).
- `Protocol` is already used in `pipeline/state.py` — renderers don't need a shared base class.
- `apply_preset` stays, reads `self.renderer.driver`.

### 2. Hemisphere sets (`eye_sets/base.py`)
```python
LEFT, RIGHT = 0, 1

class HemisphereRenderer:
    """HYPNO / RINGS: one textured sphere per eye. Driver created here (lazily)."""
    def __init__(self, ctx, driver_factory):
        self.driver  = driver_factory()
        self._meshes = (_make_eye_mesh(ctx,  ctx.eye_position, self.driver.texture),
                        _make_eye_mesh(ctx, -ctx.eye_position, self.driver.texture_alt))
    def update(self, now, pupil_scale): self.driver.update(now)
    def rotate(self, side, x, y, z):
        m = self._meshes[side]; m.rotateToX(x); m.rotateToY(y)
        if z is not None: m.rotateToZ(z)
    def draw(self, side): self._meshes[side].draw()
```
`EyeSetInitializer.register()` returns
`{eye_set: EyeSetDef(lambda: HemisphereRenderer(ctx, factory), presets, draw_lids=False)}`
— the driver is constructed inside the lambda, so it's lazy.

### 3. New `eye_sets/dragon.py`
- `DragonRenderer`: moves `init.py` ~184-266 here (iris/sclera textures, iris regen threshold, `iris_z`, iris meshes, lathed scleras).
- `update(now, pupil_scale)` = today's `update_iris` (track `_prev_pupil` internally; `FrameState.prev_pupil_scale` goes away).
- `rotate` / `draw` iterate `(iris, sclera)` per side.
- `DragonInitializer(EyeSetInitializer)` overrides `register()` → `EyeSetDef(lambda: DragonRenderer(ctx, svg), draw_lids=True)`.
- Import it in `eye_sets/__init__.py` so `__init_subclass__` registers it.

### 4. `init_scene` keeps only shared pieces
- `scale_points` on all svg lists — **must stay here**: it mutates svg in place and both lids and dragon read it.
  Moving it into the lazy dragon build would leave lids unscaled when the startup set isn't dragon, or double-scale on rebuild.
- Lid meshes (`EyeLidMesh` ×2) + lid regen thresholds.
- Build registry (cheap — factories only), then `eye_sets[EYE_SET].renderer` to pre-warm the startup set.
- `SceneContext` slims to: `lids`, `eye_sets`, `upper_lid_regen_threshold`, `lower_lid_regen_threshold`.

### 5. Pipeline changes
- `draw_scene`: one loop, no `if alt` branches. **Drop the `left_alt` / `right_alt` pair entirely**
  (`left_alt, right_alt = defn.meshes() if defn else (None, None)`, `pipeline/stages.py:477`).
  Today "left" means two things — `ctx.scene.left` (dragon iris/sclera/lids) vs `left_alt` (eye-set hemisphere) —
  and every step branches on which one is live. After the refactor there is a **single left and a single right**:
  the active renderer owns whatever geometry its eyes need, and lids are the only other per-side object.
  ```python
  def draw_scene(ctx, state):
      r    = ctx.scene.eye_sets[state.eye_set].renderer
      lids = ctx.scene.lids                       # (left, right) EyeLidMesh pair
      z    = ROTATE_DEGREES if ROTATE_EYES else None
      right_eye_pos = ctx.eyes.right if state.crazy_eyes else ctx.eyes.left

      for side, eye, convergence in ((LEFT,  ctx.eyes.left,  CONVERGENCE),
                                     (RIGHT, right_eye_pos, -CONVERGENCE)):
          r.rotate(side, eye.current.y, eye.current.x + convergence, z)
          if z is not None:
              lids[side].rotateToZ(z)

      for side in (LEFT, RIGHT):
          if side == LEFT and DEBUG_MOVEMENT:
              ctx.debug_overlay.draw(ctx.eyes.left, ctx.display_ctx)
              continue
          r.draw(side)
          if state.draw_lids:
              lids[side].draw()
  ```
  - No `defn` `None` fallback: every `EyeSet` (dragon included) has a registry entry, so a missing one is a bug and should raise `KeyError`.
  - Keep the `DEBUG_MOVEMENT` overlay replacing the left draw (lids included, matching today's behaviour).
  - `EyeSetDef.meshes()` goes away (replaced by `.renderer`), so `update_eye_set`'s `defn.meshes()` lazy-build trigger (`pipeline/stages.py:360`) becomes `defn.renderer`.
- Delete `update_iris`; `update_eye_set` calls `r.update(now, pupil_scale)` (fixes the RINGS iris-regen bug).
- `bindings._switch_eye_set`: `state.draw_lids = defn.draw_lids`.
- `FrameState.draw_lids` initialized from `eye_sets[EYE_SET].draw_lids` instead of hardcoded `True` (`pipeline/state.py:60`).
- Update docstrings in `pipeline/pipeline.py` header.

---

## Plan — Phase 2 (follow-up): Background pre-build to remove first-switch hitch

With lazy drivers, first switch to HYPNO runs `_build_grid()` + two `_draw()` passes inside one frame → a dropped frame or two on Pi.

Split driver construction:
- **CPU part** (numpy grid, first frames) → worker thread. numpy releases the GIL on large array ops, so this works on regular CPython (no free-threaded build needed).
- **GL part** (`pi3d.Texture`, `pi3d.Sphere`) → render thread only (owns the GL context).

```python
class HypnoSpiral:
    def __init__(self, config=None):   # CPU only — thread-safe
        ...grid, first frames into self._out / self._out_alt...
        self._texture = None
    def upload(self):                  # GL — render thread only
        self._texture     = pi3d.Texture(Image.fromarray(self._out), ...)
        self._texture_alt = pi3d.Texture(Image.fromarray(self._out_alt), ...)
```
- `EyeSetDef.prepare()` submits the CPU part to a shared `ThreadPoolExecutor(max_workers=1)`.
- On switch: keep drawing the current set until the future completes, then upload + mesh build on render thread and swap (~100 ms switch latency instead of a stall).
- Optional: `prepare()` all non-startup sets right after boot → instant switches always.

Do this as a separate change after Phase 1 is verified on the Pi (touches driver constructors + adds threading).

---

## Considered and skipped
- **PEP 649 deferred annotations (3.14)** — would remove `from __future__ import annotations` / `TYPE_CHECKING` quoting. Breaks if Pi < 3.14; no runtime benefit.
- **3.13/3.14 JIT, free-threaded builds** — hot path is numpy + GL, neither benefits; free-threaded ARM wheels for pi3d/numpy are spotty.
