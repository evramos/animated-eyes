from enum import Enum, auto
from typing import Final

# Defines all constants and configuration options for the eye control system.
DEBUG_MOVEMENT:  Final = False
KEYFRAME_STEP:   Final = False  # Space bar steps one keyframe at a time (SCRIPTED mode only)

# ── Eye Motion Configuration ──────────────────────────────────────────────────────────────────────────────────────────
TARGET_FPS:      Final = 60
AUTO_BLINK:      Final = True  # Eyes blink autonomously
CRAZY_EYES:      Final = False # Each eye moves in different directions
MIRROR_LIDS:     Final = True  # Right eyelid controls mirror left; False = independent (channels 3 & 4)
EYELID_TRACKING: Final = True  # Eyelid tracks pupil
ROTATE_EYES:     Final = False # Set True when running on hardware
ROTATE_DEGREES:  Final = 180   # Screen rotation in degrees

# ── Analog Input Configuration (Requires Snake Eyes Bonnet) ───────────────────────────────────────────────────────────
PUPIL_IN:        Final = -1    # Pupil control (-1 = auto)
JOYSTICK_X_IN:   Final = -1    # Eye horizontal position (-1 = auto)
JOYSTICK_Y_IN:   Final = -1    # Eye vertical position (-1 = auto)
PUPIL_SMOOTH:    Final = 16    # Filter input from PUPIL_IN if > 0

# ── GPIO Pin Assignments ──────────────────────────────────────────────────────────────────────────────────────────────
WINK_L_PIN:      Final = 22    # Left eye wink button
BLINK_PIN:       Final = 23    # Blink button (both eyes)
WINK_R_PIN:      Final = 24    # Right eye wink button

# ── Control Modes ─────────────────────────────────────────────────────────────────────────────────────────────────────
class ControlMode(Enum):
    RANDOM   = auto() # Eyes will look around randomly
    MANUAL   = auto() # Eyes are controlled manually via gamepad
    SCRIPTED = auto() # Eyes follow keyframe sequence from SEQUENCE_FILE
    TRACKING = auto() # Eyes will be controlled by tracking input (e.g. eye tracking or external sensors)

CONTROL_MODE:   Final = ControlMode.RANDOM

# ── Eye Sets ──────────────────────────────────────────────────────────────────────────────────────────────────────────
class EyeSet(Enum):
    NORMAL   = auto()   # existing dragon iris texture
    HYPNO    = auto()   # live-generated spiral texture
    RINGS    = auto()   # live-generated concentric texture
    GLITCH   = auto()   # glitch effect

EYE_SET:         Final = EyeSet.NORMAL
EYE_SET_PRESETS: Final = False # True → cycle presets via gamepad; False → use default config

# ── Expression Sequence File ──────────────────────────────────────────────────────────────────────────────────────────
# TODO - There will be more expressions later that would be selected by end-user
SEQUENCE_FILE:   Final = "keyframes/sample1.json"

# ── Tracking Mode ─────────────────────────────────────────────────────────────────────────────────────────────────────
class TrackingMode(Enum):
    EYES   = auto()  # Use tracking eyes data for eye movement
    GYRO   = auto()  # Use AHRS/IMU (BNO055 IMU FUSION) data for eye movement
    BOTH   = auto()  # Use both tracking data sources (not implemented yet)

TRACKING_MODE:   Final = TrackingMode.GYRO

# ── GYRO Mode (BNO055 IMU FUSION) ─────────────────────────────────────────────────────────────────────────────────────
SENSITIVITY_X:   Final = 1.0   # head-turn degrees → eye units (±30 range)
SENSITIVITY_Y:   Final = 0.8   # pitch tends to feel over-reactive; tune lower
STILL_THRESHOLD: Final = 5.0   # °/s below which = "still" (triggers neutral recalibration)
RECAL_DELAY:     Final = 0.25  # seconds still before neutral reference updates
RETURN_SPEED:    Final = 5.0   # leap factor (units/sec) for eye tracking response

# ── Pupil & Convergence Settings ──────────────────────────────────────────────────────────────────────────────────────
PUPIL_SCALE:     Final = 0.5
PUPIL_MIN:       Final = 0.0   # Lower analog range from PUPIL_IN
PUPIL_MAX:       Final = 1.0   # Upper "
CONVERGENCE:     Final = 2.0  # 0.0 = no convergence, 1.0 = full, >1.0 = over-convergence

# ── Blink States ──────────────────────────────────────────────────────────────────────────────────────────────────────
NO_BLINK:        Final = 0
EN_BLINKING:     Final = 1
DE_BLINKING:     Final = 2

# TODO: Replace with cleaner Blink IntEnum if needed
# class Blink(IntEnum):
#     NO          = auto() # 1
#     ENABLE      = auto() # 2
#     DISABLE     = auto() # 3
#     SET         = auto() # 4

# ── Graphics Assets ───────────────────────────────────────────────────────────────────────────────────────────────────
SVG_PATH:        Final = "graphics/dragon-eye-edit.svg"
IRIS_PATH:       Final = "graphics/dragon-iris-color.png"
SCLERA_PATH:     Final = "graphics/dragon-sclera.png"
EYE_LID:         Final = "graphics/lid.png"
UV_MAP:          Final = "graphics/uv.png"
