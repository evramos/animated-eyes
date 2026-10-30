"""
eye_sets/base.py

Base initializer for eye set modules.

EyeSetInitializer provides a default register() that works for any eye set
whose two eyes are symmetric hemisphere meshes driven by driver.texture /
driver.texture_alt. Override register() only when the geometry differs
(see eye_sets/dragon.py).

To add a new eye set (e.g. GLITCH):
    class GlitchInitializer(EyeSetInitializer):
        def __init__(self):
            from eye_sets.constants import GLITCH_PRESETS
            super().__init__(EyeSet.GLITCH, GlitchDriver, GLITCH_PRESETS)
"""

import pi3d

from gfxutil import re_axis
from models import EyeSetDef, Side


def _make_eye_mesh(ctx, x: float, texture) -> pi3d.Sphere:
    """Build a hemisphere mesh with planar front-projection UV.

    UV: U = x/(2R)+0.5, V = y/(2R)+0.5 — texture center maps to eye center.
    """
    shape = pi3d.Sphere(radius=ctx.eye_radius, slices=24, sides=64, x=x)
    shape.set_textures([texture])
    shape.set_shader(ctx.shader)
    re_axis(shape, 0.0)
    _inv = 1.0 / (2.0 * ctx.eye_radius)
    ab = shape.buf[0].array_buffer
    ab[:, 6:8] = ab[:, 0:2] * _inv + 0.5
    return shape


class HemisphereRenderer:
    """One textured hemisphere per eye (HYPNO / RINGS). Driver is created here, so it's lazy."""

    def __init__(self, ctx, driver_factory):
        self.driver  = driver_factory()
        self._meshes = (_make_eye_mesh(ctx,  ctx.eye_position, self.driver.texture),
                        _make_eye_mesh(ctx, -ctx.eye_position, self.driver.texture_alt))

    def update(self, now: float, pupil_scale: float) -> None:
        self.driver.update(now)

    def rotate(self, side: Side, x: float, y: float, z: float | None) -> None:
        m = self._meshes[side]
        m.rotateToX(x)
        m.rotateToY(y)
        if z is not None:
            m.rotateToZ(z)

    def draw(self, side: Side) -> None:
        self._meshes[side].draw()


class EyeSetInitializer:
    """Base initializer for standard symmetric eye sets.

    Subclasses only need to provide __init__ — the default register() wraps
    a HemisphereRenderer factory in an EyeSetDef. Nothing is built until the
    set's .renderer is first accessed.

    Subclasses are auto-registered at class-definition time via __init_subclass__.
    Call EyeSetInitializer.all() to get one instance of every registered subclass.
    """

    _registry: list[type] = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        EyeSetInitializer._registry.append(cls)

    @classmethod
    def all(cls) -> list['EyeSetInitializer']:
        """Instantiate and return one of each registered subclass."""
        return [c() for c in cls._registry]

    def __init__(self, eye_set, driver_factory=None, presets=None):
        self._eye_set        = eye_set
        self._driver_factory = driver_factory
        self._presets        = presets or []

    def register(self, ctx, svg) -> dict:
        """Return the (unbuilt) EyeSetDef entry for this eye set."""
        return {self._eye_set: EyeSetDef(factory=lambda: HemisphereRenderer(ctx, self._driver_factory),
                                         presets=self._presets, draw_lids=False)}
