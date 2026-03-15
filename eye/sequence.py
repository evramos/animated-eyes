import json
from models.point import Point, smoothstep


class Keyframe:
    def __init__(self, destination, move_duration, hold_duration, pupil_scale=None, control=None):
        self.destination = Point(*destination)
        self.move_duration = move_duration
        self.hold_duration = hold_duration
        self.pupil_scale = pupil_scale  # None = don't override
        self.control = Point(*control) if control else None  # Bézier ctrl pt

class SequencePlayer:
    def __init__(self, path):
        self._t = 0.0
        with open(path) as f:
            raw = json.load(f)
        self.keyframes = [Keyframe(**kf) for kf in raw["data"]]
        self._n        = len(self.keyframes)
        self.index     = -1
        self._armed    = True   # ready to push next destination

    # ------------------------------------------------------------------
    def update(self, eye_state, now):
        """Call once per frame instead of eye_state.update_position(now)."""

        self._move(eye_state, now)  # advance first; may set is_moving=False this frame

        # Hold check runs after _move so the frame movement ends counts toward hold.
        # dt=0 on that frame means hold_duration=0.0 advances immediately.
        if not eye_state.is_moving:
            dt = now - eye_state.start_time
            if self._armed or (self._n > 1 and dt >= eye_state.hold_duration):
                self._advance(eye_state, now)
                self._move(eye_state, now)   # begin new movement in same frame


    # ------------------------------------------------------------------
    def _advance(self, eye_state, now):
        """Push the next keyframe's destination into eye_state."""
        self.index = (self.index + 1) % len(self.keyframes)
        kf = self.keyframes[self.index]

        eye_state.start.copy_from(eye_state.current)
        eye_state.destination.set(kf.destination.x, kf.destination.y)
        eye_state.move_duration = kf.move_duration
        eye_state.hold_duration = kf.hold_duration
        eye_state.start_time    = now
        eye_state.is_moving     = True
        self._armed             = False

    # ------------------------------------------------------------------
    def _move(self, eye_state, now):
        """Smooth movement — linear or Bézier depending on keyframe."""
        if not eye_state.is_moving:
            return

        dt = now - eye_state.start_time

        # Arrived — begin hold
        if dt >= eye_state.move_duration:
            eye_state.current.copy_from(eye_state.destination)
            eye_state.start.copy_from(eye_state.destination)
            eye_state.start_time = now
            eye_state.is_moving  = False
            return

        t = dt / eye_state.move_duration
        if eye_state.hold_duration > 0.0:
            t = smoothstep(t)   # decelerates to rest at destination
        # hold=0.0 keeps linear t: constant velocity through the waypoint, no perceived stop
        self._t = t

        kf = self.keyframes[self.index]
        p0 = eye_state.start
        p2 = eye_state.destination

        if kf.control:
            # Quadratic Bézier: P(t) = (1-t)²P0 + 2(1-t)tP1 + t²P2
            p1  = kf.control
            u   = 1.0 - t
            eye_state.current.set(
                u*u*p0.x + 2*u*t*p1.x + t*t*p2.x,
                u*u*p0.y + 2*u*t*p1.y + t*t*p2.y,
                )
        else:
            eye_state.current.set(
                p0.x + (p2.x - p0.x) * t,
                p0.y + (p2.y - p0.y) * t,
            )

    # ------------------------------------------------------------------
    @property
    def current_pupil_scale(self):
        """Interpolated pupil scale — None if not authored in this keyframe."""
        kf   = self.keyframes[self.index]
        prev = self.keyframes[self.index - 1]   # wraps cleanly at 0
        if kf.pupil_scale is None or prev.pupil_scale is None:
            return None
        return prev.pupil_scale + (kf.pupil_scale - prev.pupil_scale) * self._t