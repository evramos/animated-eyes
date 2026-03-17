# debug_overlay.py
import math

import pi3d

from models import DisplayContext

class DebugOverlay:

    def __init__(self, ctx: DisplayContext):
        # builds _dot_shader, _left_outline, _dots
        self._eye_radius = ctx.eye_radius
        self._eye_position = ctx.eye_position

        # Debug outline: white square border around each eye, drawn in front of all geometry (z=-200)
        self._dot_shader = pi3d.Shader("mat_flat")

        _travel_r = math.sin(math.radians(33)) * ctx.eye_radius  # projected ±30° travel range
        self._left_outline = self._make_eye_outline(ctx.eye_position, r=_travel_r)

        self._dots = {"s": self._make_dot((1, 0, 0)), "d": self._make_dot((0, 1, 0)), "c": self._make_dot((1, 1, 0))}

    def _make_eye_outline(self, x_center, width=2.0, color=(1, 1, 1), alpha=0.35, r=None):
        if r is None:
            r = self._eye_radius
        vertices = [
            (x_center - r, r, -200),
            (x_center + r, r, -200),
            (x_center + r, -r, -200),
            (x_center - r, -r, -200),
        ]
        outline = pi3d.Lines(vertices=vertices, closed=True, line_width=width)
        outline.set_shader(self._dot_shader)
        outline.set_material(color)
        outline.set_alpha(alpha)
        return outline

    def _make_dot(self, color):
        d = pi3d.Disk(radius=5, sides=20, rx=90, z=1)
        d.set_shader(self._dot_shader)
        d.set_material(color)
        return d

    def _project(self, angle_x, angle_y, eye_x_center):
        """Map eye rotation angles (degrees) to 2D screen pixel position."""
        x = eye_x_center - math.sin(math.radians(angle_x)) * self._eye_radius
        y = math.sin(math.radians(angle_y)) * self._eye_radius
        return x, y

    def draw(self, eye, ctx):
        self._left_outline.draw()

        if eye.is_moving:
            pi3d.opengles.glDisable(pi3d.constants.GL_DEPTH_TEST)
            for attr, key in (("start", "s"), ("destination", "d"), ("current", "c")):
                pt = getattr(eye, attr)
                x, y = self._project(pt.x, pt.y, ctx.eye_position)
                self._dots[key].position(x, y, 1)
                self._dots[key].draw()
            pi3d.opengles.glEnable(pi3d.constants.GL_DEPTH_TEST)