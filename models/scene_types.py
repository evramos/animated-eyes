# scene_types.py
from __future__ import annotations
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Callable, Literal, Protocol

if TYPE_CHECKING:
    from eye.lid   import EyeLidMesh

type Side = Literal[0, 1]
LEFT:  Side = 0
RIGHT: Side = 1


class EyeSetRenderer(Protocol):
    """Owns all per-eye geometry for one eye set (lids excluded — those are scene-level)."""
    driver: object | None
    def update(self, now: float, pupil_scale: float) -> None: ...
    def rotate(self, side: Side, x: float, y: float, z: float | None) -> None: ...
    def draw(self, side: Side) -> None: ...


@dataclass(eq=False)
class EyeSetDef:
    """Lazy handle for one EyeSet.

    factory:   called once on first access of .renderer → builds driver + meshes
    presets:   driver configs cycled via gamepad (empty for sets without a driver)
    draw_lids: default lid visibility when this set activates
    """
    factory:   Callable[[], EyeSetRenderer]
    presets:   list = field(default_factory=list)
    draw_lids: bool = True

    @cached_property
    def renderer(self) -> EyeSetRenderer:
        return self.factory()  # runs once; afterwards a plain __dict__ lookup

    def build(self) -> EyeSetRenderer:
        """Build the renderer now (idempotent). Use to pre-warm instead of waiting for first frame."""
        return self.renderer

    @property
    def built(self) -> bool:
        return "renderer" in self.__dict__

    def apply_preset(self, index: int) -> None:
        """Apply presets[index % len] to the driver if the preset has changed."""
        driver = self.renderer.driver
        if self.presets and driver:
            p = self.presets[index % len(self.presets)]
            if p.name != driver._config.name:
                driver.set_config(p)


@dataclass
class LidPoints:
    closed: list
    open: list
    edge: list

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
    lids: tuple[EyeLidMesh, EyeLidMesh]   # indexed by LEFT / RIGHT; shared across all eye sets
    upper_lid_regen_threshold: float
    lower_lid_regen_threshold: float

    # EyeSet → EyeSetDef. Renderers are built lazily on first access of .renderer;
    # only the startup EYE_SET is pre-warmed in init_scene.
    eye_sets: dict = field(default_factory=dict)
