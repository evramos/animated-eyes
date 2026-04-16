"""
eye_sets/base.py

Base initializer for eye set modules.

EyeSetInitializer provides a default register() that works for any eye set
whose two eyes are symmetric hemisphere meshes driven by driver.texture /
driver.texture_alt. Override register() only when the geometry differs.

To add a new eye set (e.g. GLITCH):
    class GlitchInitializer(EyeSetInitializer):
        def __init__(self):
            from eye_sets.constants import GLITCH_PRESETS
            super().__init__(EyeSet.GLITCH, GlitchDriver, GLITCH_PRESETS)
"""

import pi3d

from gfxutil import re_axis
from models import EyeSetDef


class EyeSetInitializer:
    """Base initializer for standard symmetric eye sets.

    Subclasses only need to provide __init__ — the default register() builds
    two hemisphere meshes using driver.texture / driver.texture_alt.

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

    def __init__(self, eye_set, driver_factory, presets=None):
        self._eye_set        = eye_set
        self._driver_factory = driver_factory
        self._presets        = presets

    @staticmethod
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

    def register(self, ctx, svg) -> dict:
        """Build and return the EyeSetDef entry for this eye set."""
        driver = self._driver_factory()

        def _build():
            return (self._make_eye_mesh(ctx,  ctx.eye_position, driver.texture),
                    self._make_eye_mesh(ctx, -ctx.eye_position, driver.texture_alt))

        return {self._eye_set: EyeSetDef(build=_build, driver=driver, presets=self._presets)}
