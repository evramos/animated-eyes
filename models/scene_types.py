# scene_types.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Any

import pi3d

if TYPE_CHECKING:
    from eye.lid   import EyeLidMesh


@dataclass
class EyeSetDef:
    """Bundles a mesh factory, optional per-frame driver, and cached meshes for one EyeSet.

    build:  called once on first activation → returns (left_Shape, right_Shape)
    driver: optional object with update(now) and set_config(cfg) — e.g. HypnoSpiral
    """
    build:   Callable[[], tuple[pi3d.Shape, pi3d.Shape]]
    driver:  Any  = None
    presets: list = field(default_factory=list)
    _left:   pi3d.Shape = field(default=None, init=False, repr=False)
    _right:  pi3d.Shape = field(default=None, init=False, repr=False)

    def meshes(self) -> tuple:
        """Return (left, right) meshes, building them on first call."""
        if self._left is None:
            self._left, self._right = self.build()
        return self._left, self._right

    def apply_preset(self, index: int) -> None:
        """Apply presets[index % len] to the driver if the preset has changed."""
        if self.presets and self.driver:
            p = self.presets[index % len(self.presets)]
            if p.name != self.driver._config.name:
                self.driver.set_config(p)


@dataclass
class LidPoints:
    closed: list
    open: list
    edge: list

@dataclass
class EyeMeshes:
    iris:   pi3d.Shape
    sclera: pi3d.Shape
    lids:   EyeLidMesh   # type checker sees this, runtime never evaluates it

@dataclass
class SvgPoints:
    view_box: tuple
    pupil_min: list
    pupil_max: list
    iris: list
    sclera_front: list
    sclera_back: list
    upper_lid: LidPoints
    lower_lid: LidPoints

@dataclass
class SceneContext:
    left:  EyeMeshes
    right: EyeMeshes
    iris_z: float
    iris_regen_threshold: float
    upper_lid_regen_threshold: float
    lower_lid_regen_threshold: float

    # Each EyeSetDef holds a build factory and optional per-frame driver.
    # Meshes are built lazily on first activation via EyeSetDef.meshes().
    eye_set_registry: dict = field(default_factory=dict)  # EyeSet → EyeSetDef
