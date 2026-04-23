"""
pipeline/state.py

Mutable state dataclasses for the DragonEyes frame pipeline.

These are pure data containers with no hardware or pi3d dependencies so they
can be imported anywhere without pulling in the full rendering stack.
"""

import time
from dataclasses import dataclass, field
from typing import Protocol

from constants import AUTO_BLINK, CRAZY_EYES, CONTROL_MODE, ControlMode, EyeSet, EYE_SET, PUPIL_SCALE


@dataclass
class InputState:
    """Raw button/axis signals written by the gamepad thread."""
    wink_left:     bool = False
    wink_right:    bool = False
    dpad_left:     bool = False
    dpad_right:    bool = False
    dpad_up:       bool = False
    dpad_down:     bool = False
    button_a_held: bool = False
    button_y_held: bool = False
    trigger_left:  bool = False
    trigger_right: bool = False
    step_key_held: bool = False  # edge detection for KEYFRAME_STEP space press


@dataclass
class AHRSState:
    """Mutable state for the AHRS (BNO055) head-tracking path."""
    neutral_yaw:   float = 0.0   # yaw reference for delta calculation
    neutral_pitch: float = 0.0   # pitch reference
    neutral_roll:  float = 0.0   # roll reference (reserved for future use)
    still_since:   float = 0.0   # monotonic time when stillness began (0 = not still)
    prev_time:     float = 0.0   # last frame time for dt computation


@dataclass
class FrameState:
    """Mutable per-frame counters and timers, replacing loose globals in eyes.py."""
    frames:             int         = 0
    beginning_time:     float       = field(default_factory=time.monotonic)
    prev_pupil_scale:   float       = -1.0   # forces iris regen on first frame
    time_of_last_blink: float       = 0.0
    time_to_next_blink: float       = 1.0
    control_mode:       ControlMode = CONTROL_MODE
    controller_input:   InputState  = field(default_factory=InputState)
    manual_x:           float       = 0.0   # current eye angle in MANUAL mode
    manual_y:           float       = 0.0
    manual_last_time:   float       = 0.0
    current_pupil:      float       = PUPIL_SCALE
    manual_pupil:       float       = PUPIL_SCALE
    auto_blink:         bool        = AUTO_BLINK
    crazy_eyes:         bool        = CRAZY_EYES
    eye_set:            EyeSet      = EYE_SET
    prev_eye_set:       EyeSet      = EYE_SET
    preset_index:       int         = 0        # cycles through the active EyeSet's presets
    hypno_transition:   float       = 0.0      # 0.0 = NORMAL, 1.0 = fully in HYPNO
    ahrs:               AHRSState   = field(default_factory=AHRSState)


# ── Lid preview channels ───────────────────────────────────────────────────────

class _HasValue(Protocol):
    @property
    def value(self) -> float: ...


@dataclass
class LidChannels:
    """Holds the four keyboard-driven ADC channels used during lid preview (macOS dev only).
    Pass None on hardware where mock.bonnet is unavailable.
    """
    left_upper:  _HasValue
    left_lower:  _HasValue
    right_upper: _HasValue
    right_lower: _HasValue
