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
            if self._armed or (len(self.keyframes) > 1 and dt >= eye_state.hold_duration):
                self._advance(eye_state, now)
                self._move(eye_state, now)   # begin new movement in same frame


    # ------------------------------------------------------------------
    def _advance(self, eye_state, now):
        """
        Advances to the next keyframe and sets up the eye state for the subsequent movement.

        This method increments the keyframe index (wrapping around to the start if necessary), retrieves the next
        keyframe, and configures the eye_state with the new destination, movement duration, hold duration, and start
        time. It also marks the eye as moving and disarms the sequence player to prevent immediate re-advancement.

        Args:
            eye_state: The eye state object to configure with the next keyframe's parameters.
            now (float): The current timestamp to set as the start time for the new movement.

        Returns:
            None: Modifies eye_state and self in place.

        Notes:
            - The index wraps around using modulo, allowing seamless looping through keyframes.
            - Sets self._armed False to ensure hold durations are respected before advancing again.
        """
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
        """
        Moves the eye state smoothly towards the destination using linear interpolation or quadratic Bézier curve.

        This method updates the eye_state's current position based on the elapsed time since the movement started.
        If a control point is defined in the keyframe, it uses quadratic Bézier interpolation for smooth curves;
        otherwise, it uses linear interpolation. The movement can be eased with smoothstep if hold_duration > 0.

        Args:
            eye_state: The eye state object containing start, destination, current positions, and timing info.
            now (float): The current timestamp for calculating elapsed time.

        Returns:
            None: Modifies eye_state in place.

        Notes:
            - If movement duration is exceeded, sets is_moving to False and prepares for hold phase.
            - Updates self._t with the normalized time parameter for use in pupil scaling.
        """
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