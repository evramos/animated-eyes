from enum import Enum, auto

DEBUG_MOVEMENT  = False

# Eye motion configuration
TARGET_FPS      = 60
AUTO_BLINK      = True  # Eyes blink autonomously
CRAZY_EYES      = False # Each eye moves in different directions
TRACKING        = True  # Eyelid tracks pupil
ROTATE_EYES     = False # Set True when running on hardware
ROTATE_DEGREES  = 180   # Screen rotation in degrees

# Analog input configuration (requires Snake Eyes Bonnet)
JOYSTICK_X_IN   = 1     # Eye horizontal position (-1 = auto)
JOYSTICK_Y_IN   = 2     # Eye vertical position (-1 = auto)
PUPIL_IN        = 0     # Pupil control (-1 = auto)
PUPIL_SMOOTH    = 16    # Filter input from PUPIL_IN if > 0

# GPIO pin assignments
WINK_L_PIN      = 22    # Left eye wink button
BLINK_PIN       = 23    # Blink button (both eyes)
WINK_R_PIN      = 24    # Right eye wink button

# Control modes
class ControlMode(Enum):
    RANDOM     = auto() # 1
    MANUAL     = auto() # 2
    SCRIPTED   = auto() # 3

CONTROL_MODE = ControlMode.SCRIPTED

# TODO - There will be more expressions later that would be selected by end-user
# Expression sequence file
SEQUENCE_FILE = "keyframes/sample4.json"

# Pupil and convergence settings
PUPIL_SCALE     = 0.5
PUPIL_MIN       = 0.0   # Lower analog range from PUPIL_IN
PUPIL_MAX       = 1.0   # Upper "
CONVERGENCE     = 2.0  # 0.0 = no convergence, 1.0 = full, >1.0 = over-convergence

# Blink states
NO_BLINK        = 0
EN_BLINKING     = 1
DE_BLINKING     = 2

# TODO: Replace with cleaner Blink IntEnum if needed
# class Blink(IntEnum):
#     NO          = auto() # 1
#     ENABLE      = auto() # 2
#     DISABLE     = auto() # 3
#     SET         = auto() # 4
