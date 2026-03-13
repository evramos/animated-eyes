# constants.py
# INPUT CONFIG for eye motion ----------------------------------------------
# ANALOG INPUTS REQUIRE SNAKE EYES BONNET
TARGET_FPS      = 60

AUTO_BLINK      = True  # If True, eyes blink autonomously
CRAZY_EYES      = False # If True, each eye moves in different directions
TRACKING        = True  # If True, eyelid tracks pupil

ROTATE_EYES     = False # Set True when running on hardware
ROTATE_DEGREES  = 180   # (screens mounted 180°)
# --------------------------------------------------------------------------
JOYSTICK_X_IN   = -1    # Analog input for eye horizontal position (-1 = auto)
JOYSTICK_Y_IN   = -1    # Analog input for eye vertical position (-1 = auto)
PUPIL_IN        = -1    # Analog input for pupil control (-1 = auto)

# JOYSTICK_X_IN = 1
# JOYSTICK_Y_IN = 2
# PUPIL_IN = 0
# --------------------------------------------------------------------------
PUPIL_SMOOTH    = 16    # If > 0, filter input from PUPIL_IN
WINK_L_PIN      = 22    # GPIO pin for LEFT eye wink button
BLINK_PIN       = 23    # GPIO pin for blink button (BOTH eyes)
WINK_R_PIN      = 24    # GPIO pin for RIGHT eye wink button
# --------------------------------------------------------------------------
RANDOM          = "random"
MANUAL          = "manual"
CONTROL_MODE    = RANDOM

PUPIL_SCALE     = 0.5
PUPIL_MIN       = 0.0   # Lower analog range from PUPIL_IN
PUPIL_MAX       = 1.0   # Upper "

CONVERGENCE     = 2.0

NO_BLINK        = 0
EN_BLINKING     = 1
DE_BLINKING     = 2