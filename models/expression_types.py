# expression_types.py
from __future__ import annotations
from dataclasses import dataclass

from models.scene_types import Side, LEFT


@dataclass(frozen=True)
class LidPose:
    """Upper + lower lid pose for one eye.

    Weights:   0.0 = open, 1.0 = closed (same convention as _LidState / keyframe lid_weight).
    Rotations: degrees, semantic sign — + = inner (nose-side) corner down, − = inner corner up.
               Converted to pi3d Z per side at draw time, never stored per-screen.
    """
    upper_wt:  float = 0.3
    lower_wt:  float = 0.7
    upper_rot: float = 0.0
    lower_rot: float = 0.0

    def lerp(self, other: LidPose, t: float) -> LidPose:
        """Blend toward other by t (0 = self, 1 = other); weights and angles together."""
        return LidPose(self.upper_wt  + (other.upper_wt  - self.upper_wt)  * t,
                       self.lower_wt  + (other.lower_wt  - self.lower_wt)  * t,
                       self.upper_rot + (other.upper_rot - self.upper_rot) * t,
                       self.lower_rot + (other.lower_rot - self.lower_rot) * t)


@dataclass(frozen=True)
class Expression:
    """Named lid preset loaded from resources/expressions/*.json.

    left:        lid pose for the left eye
    right:       None → mirror left (symmetric); set for asymmetric presets (SMUG, CONFUSED)
    pupil_scale: 0 = min/slit, 1 = max dilation; None → leave pupil alone
    gaze_bias:   (x, y) offset for RANDOM-mode destinations; None → no bias
    blink_rate:  multiplier on auto-blink interval, 0 = suppress; None → unchanged
    """
    name:        str
    left:        LidPose
    right:       LidPose | None = None
    pupil_scale: float | None = None
    gaze_bias:   tuple[float, float] | None = None
    blink_rate:  float | None = None

    @property
    def symmetric(self) -> bool:
        return self.right is None

    def pose(self, side: Side) -> LidPose:
        """Lid pose for one eye. Mirroring is semantic, so the left pose is reused as-is."""
        return self.left if side == LEFT or self.right is None else self.right
