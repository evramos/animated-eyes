import glob
import json
import os

from constants import AUTO_BLINK, EYELID_TRACKING, KEYFRAME_STEP
from models.point import Point, smoothstep


class Keyframe:
    def __init__(self, destination, move_duration, hold_duration, pupil_scale=None, control=None,
                 lid_weight=None, auto_blink=None, eyelid_tracking=None):

        self.destination = Point(*destination)
        self.move_duration = move_duration
        self.hold_duration = hold_duration
        self.pupil_scale = pupil_scale  # None = don't override
        self.control = Point(*control) if control else None  # Bézier ctrl pt

        # None = not authored; player tracks sticky state
        self.auto_blink = auto_blink
        self.eyelid_tracking = eyelid_tracking

        # Normalize lid_weight: [u, l] → per-eye dict; None stays None
        if isinstance(lid_weight, list) and len(lid_weight) == 2:
            self.lid_weight = {"left": lid_weight, "right": lid_weight}
        else:
            self.lid_weight = lid_weight # dict with "left"/"right" keys, or None

# noinspection PyAttributeOutsideInit
class SequencePlayer:
    def __init__(self, path):
        self.load(path)
        self._files      = sorted(glob.glob("keyframes/*.json"))
        self._file_index = self._files.index(path) if path in self._files else 0
        print(f"[seq] {len(self._files)} keyframe files: {[os.path.basename(f) for f in self._files]}")
        print(f"[seq] active: {self.current_file or 'none'}")

    @property
    def current_file(self):
        """Basename of the active keyframe file, or None if no files found."""
        return os.path.basename(self._files[self._file_index]) if self._files else None

    def cycle(self, delta):
        """Advance to the next/previous keyframe file by delta steps and reload."""
        if not self._files:
            return
        self._file_index = (self._file_index + delta) % len(self._files)
        self.load(self._files[self._file_index])
        print(f"[seq] → {self.current_file}", flush=True)

    def load(self, path):
        """Replace the active sequence in-place, resetting all playback state."""
        with open(path) as f:
            raw = json.load(f)
        self._t              = 0.0
        self.index           = -1
        self.keyframes       = [Keyframe(**kf) for kf in raw["data"]]

        # Sticky flags — start from global constants, updated when a keyframe authors them
        self.auto_blink      = AUTO_BLINK
        self.eyelid_tracking = EYELID_TRACKING

        self._armed          = True   # ready to push next destination
        self._step_pending   = False  # set by step(); consumed in update()


    # ------------------------------------------------------------------
    def update(self, eye_state, now):
        """Call once per frame instead of eye_state.update_position(now)."""
        self._move(eye_state, now)

        if not eye_state.is_moving:
            dt = now - eye_state.start_time
            can_advance = self._armed or (len(self.keyframes) > 1 and dt >= eye_state.hold_duration)
            if KEYFRAME_STEP:
                can_advance = can_advance and self._step_pending
                self._step_pending = False
            if can_advance:
                self._advance(eye_state, now)
                self._move(eye_state, now)

    def step(self):
        """Request one keyframe advance. Only used when KEYFRAME_STEP is True."""
        self._step_pending = True

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

        if KEYFRAME_STEP:
            print(f"[step] kf {self.index}  dest=({kf.destination.x:.0f},{kf.destination.y:.0f})"
                  f"  auto_blink={self.auto_blink}  tracking={self.eyelid_tracking}")

        if kf.auto_blink is not None:
            self.auto_blink = kf.auto_blink
        if kf.eyelid_tracking is not None:
            self.eyelid_tracking = kf.eyelid_tracking

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

    @property
    def current_lid_weight(self):
        """Interpolated lid weights — None if not authored in both this and previous keyframe.
        Returns:
            dict | None: {"left": (upper, lower), "right": (upper, lower)}, or None.
        """
        kf = self.keyframes[self.index]
        prev = self.keyframes[self.index - 1]
        if kf.lid_weight is None or prev.lid_weight is None:
            return None
        result = {}
        for side in ("left", "right"):
            pu, pl = prev.lid_weight[side]
            ku, kl = kf.lid_weight[side]
            result[side] = (pu + (ku - pu) * self._t, pl + (kl - pl) * self._t)
        return result
