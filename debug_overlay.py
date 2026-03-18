# debug_overlay.py
import cmath
import math

import pi3d

from constants import ROTATE_DEGREES, ROTATE_EYES
from models import DisplayContext

_sin_deg = lambda a: math.sin(math.radians(a))


class DebugOverlay:

    def __init__(self, ctx: DisplayContext):
        # builds _dot_shader, _left_outline, _dots
        self._eye_radius = ctx.eye_radius
        self._eye_position = ctx.eye_position
        self._rotation = cmath.rect(1, math.radians(ROTATE_DEGREES)) if ROTATE_EYES else None

        # Debug outline: white square border around each eye, drawn in front of all geometry (z=-200)
        self._dot_shader = pi3d.Shader("mat_flat")

        _travel_r = math.sin(math.radians(33)) * ctx.eye_radius  # projected ±30° travel range
        self._left_outline = self._make_eye_outline(ctx.eye_position, r=_travel_r)

        self._dots = {"s": self._make_dot((1, 0, 0)), "d": self._make_dot((0, 1, 0)), "c": self._make_dot((1, 1, 0))}

    def _make_eye_outline(self, x_center, width=2.0, color=(1, 1, 1), alpha=0.35, r=None):
        if r is None:
            r = self._eye_radius
        vertices = [(-r, r, 0), (r, r, 0), (r, -r, 0), (-r, -r, 0)]
        outline = pi3d.Lines(vertices=vertices, closed=True, line_width=width)
        outline.set_shader(self._dot_shader)
        outline.set_material(color)
        outline.set_alpha(alpha)
        outline.position(x_center, 0, -200)
        if ROTATE_EYES:
            outline.rotateToZ(ROTATE_DEGREES)
        return outline

    def _make_dot(self, color):
        d = pi3d.Disk(radius=5, sides=20, rx=90, z=1)
        d.set_shader(self._dot_shader)
        d.set_material(color)
        return d

    def _project(self, angle_x, angle_y, eye_x_center):
        """Map eye rotation angles (degrees) to 2D screen pixel position."""
        offset = complex(-_sin_deg(angle_x), _sin_deg(angle_y)) * self._eye_radius
        if self._rotation:
            offset *= self._rotation
        return eye_x_center + offset.real, offset.imag

    def draw(self, eye, ctx):
        self._left_outline.draw()

        if eye.is_moving:
            pi3d.opengles.glDisable(pi3d.constants.GL_DEPTH_TEST)
            for attr, key in (("start", "s"), ("destination", "d"), ("current", "c")):
                pt = getattr(eye, attr)
                x, y = self._project(pt.x, pt.y, ctx.eye_position)
                self._dots[key].position(x, y, 1)
                if ROTATE_EYES:
                    self._dots[key].rotateToZ(ROTATE_DEGREES)
                self._dots[key].draw()
            pi3d.opengles.glEnable(pi3d.constants.GL_DEPTH_TEST)