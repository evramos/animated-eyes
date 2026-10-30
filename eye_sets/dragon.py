"""
eye_sets/dragon.py

The original dragon eye: SVG-driven iris mesh (regenerated as the pupil
dilates) over a lathed, textured sclera. Lids are scene-level and shared
with every other eye set, so they are not built here.

Expects svg point lists to already be scaled to eye dimensions — init_scene
runs scale_points before any renderer is built.
"""

from __future__ import annotations

from typing import Final

import pi3d

from constants import EyeSet
from eye_sets.base import EyeSetInitializer
from gfxutil import mesh_init, points_bounds, points_interp, points_mesh, re_axis, zangle
from models import EyeSetDef, Side, SvgPoints

# ── Assets ─────────────────────────────────────────────────────────────────────

IRIS_PATH:       Final = "resources/graphics/dragon-iris-color.png"
SCLERA_PATH:     Final = "resources/graphics/dragon-sclera.png"

# ── Registration ───────────────────────────────────────────────────────────────

class DragonInitializer(EyeSetInitializer):
    def __init__(self):
        super().__init__(EyeSet.DRAGON)

    def register(self, ctx, svg) -> dict:
        return {self._eye_set: EyeSetDef(factory=lambda: DragonRenderer(ctx, svg), draw_lids=True)}


# ── DragonRenderer ─────────────────────────────────────────────────────────────

class DragonRenderer:
    """Iris + sclera meshes for both eyes. No texture driver — the iris animates via mesh regen."""

    driver = None

    def __init__(self, ctx, svg: SvgPoints):
        self._svg        = svg
        self._prev_pupil = -1.0   # forces iris regen on first update

        # Load texture maps --------------------------------------------------------
        iris_map   = pi3d.Texture(IRIS_PATH,   mipmap=False, filter=pi3d.constants.GL_LINEAR)
        sclera_map = pi3d.Texture(SCLERA_PATH, mipmap=False, filter=pi3d.constants.GL_LINEAR, blend=True)

        # U/V map may be useful for debugging texture placement; not normally used
        # uv_map = pi3d.Texture("resources/graphics/uv.png",  mipmap=False, filter=pi3d.constants.GL_LINEAR, blend=False, m_repeat=True)

        # Regenerating the iris during pupil dilation is CPU intensive. Determine a size change threshold below which
        # regeneration will not occur; roughly equal to 1/4 pixel, since 4x4 area sampling is used.
        self._regen_threshold = 0.0
        a, b = points_bounds(svg.pupil_min), points_bounds(svg.pupil_max)  # Bounds of pupil at min size (in pixels) at max size
        max_dist = max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]), abs(a[3] - b[3]))  # Determine distance of max variance around each edge

        # maxDist is motion range in pixels as pupil scales between 0.0 and 1.0.
        # 1.0 / maxDist is one pixel's worth of scale range.  Need 1/4 that...
        if max_dist > 0: self._regen_threshold = 0.25 / max_dist

        # Generate initial iris meshes; vertex elements get replaced in update(), this just sets up textures, etc.
        right_iris = mesh_init((32, 4), (0, 0.5 / iris_map.iy), True, False)
        right_iris.set_textures([iris_map])
        right_iris.set_shader(ctx.shader)
        right_iris.positionX(-ctx.eye_position)

        # Left iris map U value is offset by 0.5; effectively a 180 degree rotation, so it's less obvious that the same texture is in use on both.
        left_iris = mesh_init((32, 4), (0.5, 0.5 / iris_map.iy), True, False)
        left_iris.set_textures([iris_map])
        left_iris.set_shader(ctx.shader)
        left_iris.positionX(ctx.eye_position)

        self._iris_z = zangle(svg.iris, ctx.eye_radius)[0] * 0.99  # Get iris Z depth, for later

        # ----------------------------------------------------------------------------------------------------------------------
        # Generate scleras for each eye...start with a 2D shape for lathing...
        angle1 = zangle(svg.sclera_front, ctx.eye_radius)[1]  # Sclera front angle
        angle2 = zangle(svg.sclera_back, ctx.eye_radius)[1]  # " back angle
        angle_range = 180 - angle1 - angle2
        pts = []

        # ADD EXTRA INITIAL POINT because of some weird behavior with Pi3D and VideoCore VI with the Lathed shapes we make
        # later. This adds a *tiny* ring of extra polygons that simply disappear on screen. It's not necessary on VC4, but
        # not harmful either, so we just do it rather than try to be all clever.
        ca, sa = pi3d.Utility.from_polar((90 - angle1) + angle_range * 0.0001)
        pts.append((ca * ctx.eye_radius, sa * ctx.eye_radius))

        for i in range(24):
            ca, sa = pi3d.Utility.from_polar((90 - angle1) - angle_range * i / 23)
            pts.append((ca * ctx.eye_radius, sa * ctx.eye_radius))

        # Scleras are generated independently (object isn't re-used) so each may have a different image map (heterochromia,
        # corneal scar, or the same image map can be offset on one so the repetition isn't obvious).
        left_sclera = pi3d.Lathe(path=pts, sides=64, x=ctx.eye_position)
        left_sclera.set_textures([sclera_map])
        # left_sclera.set_textures([uv_map]) # debug option
        left_sclera.set_shader(ctx.shader)
        re_axis(left_sclera, 0)

        right_sclera = pi3d.Lathe(path=pts, sides=64, x=-ctx.eye_position)
        right_sclera.set_textures([sclera_map])
        right_sclera.set_shader(ctx.shader)
        re_axis(right_sclera, 0.5)  # Image map offset = 180 degree rotation

        # Indexed by LEFT / RIGHT; iris drawn before sclera (matches original draw order)
        self._meshes = ((left_iris, left_sclera), (right_iris, right_sclera))

    def update(self, now: float, pupil_scale: float) -> None:
        """Regenerate iris mesh if pupil scale has changed by at least one regen threshold.

        Interpolates between pupil_min and pupil_max point lists, builds a 3D mesh,
        and pushes it to both eye iris objects.
        """
        if abs(pupil_scale - self._prev_pupil) >= self._regen_threshold:
            inter_pupil = points_interp(self._svg.pupil_min, self._svg.pupil_max, pupil_scale)
            mesh = points_mesh((None, inter_pupil, self._svg.iris), 4, -self._iris_z, True)
            for iris, _ in self._meshes:
                iris.re_init(pts=mesh)
            self._prev_pupil = pupil_scale

    def rotate(self, side: Side, x: float, y: float, z: float | None) -> None:
        for m in self._meshes[side]:
            m.rotateToX(x)
            m.rotateToY(y)
            if z is not None:
                m.rotateToZ(z)

    def draw(self, side: Side) -> None:
        for m in self._meshes[side]:
            m.draw()
