from typing import Final

BUTTON_A:       Final = "buttonA"
BUTTON_B:       Final = "buttonB"
BUTTON_X:       Final = "buttonX"
BUTTON_Y:       Final = "buttonY"
BUTTON_OPTIONS: Final = "buttonOptions"
BUTTON_MENU:    Final = "buttonMenu"
BUTTON_HOME:    Final = "buttonHome"
# BUTTON_SHARE:   Final = "buttonShare" # Nintendo Switch Pro Controller "Share" button
DPAD_UP:        Final = "dpad_up"
DPAD_DOWN:      Final = "dpad_down"
DPAD_LEFT:      Final = "dpad_left"
DPAD_RIGHT:     Final = "dpad_right"
LEFT_SHOULDER:  Final = "leftShoulder"
RIGHT_SHOULDER: Final = "rightShoulder"
LEFT_TRIGGER:   Final = "leftTrigger"
RIGHT_TRIGGER:  Final = "rightTrigger"

GAMEPAD_QUIT_COMBO = {BUTTON_OPTIONS, BUTTON_MENU}  # Select (−) + Start (+)

# macOS physicalInputProfile key → internal button name
PROFILE_TO_GC : Final = {
    "Button A":               BUTTON_A,
    "Button B":               BUTTON_B,
    "Button X":               BUTTON_X,
    "Button Y":               BUTTON_Y,
    "Button Options":         BUTTON_OPTIONS,
    "Button Menu":            BUTTON_MENU,
    "Button Home":            BUTTON_HOME,
    # "Button Share":           BUTTON_SHARE, # Functional only with Pro Controller
    "Left Shoulder":          LEFT_SHOULDER,
    "Right Shoulder":         RIGHT_SHOULDER,
    "Left Trigger":           LEFT_TRIGGER,
    "Right Trigger":          RIGHT_TRIGGER,
    "Direction Pad Up":       DPAD_UP,
    "Direction Pad Down":     DPAD_DOWN,
    "Direction Pad Left":     DPAD_LEFT,
    "Direction Pad Right":    DPAD_RIGHT,
}

# evdev keycode name → internal button name (same convention as above)
EVDEV_TO_GC : Final = {
    "BTN_SOUTH":      BUTTON_A,
    "BTN_EAST":       BUTTON_B,
    "BTN_NORTH":      BUTTON_X,
    "BTN_WEST":       BUTTON_Y,
    "BTN_SELECT":     BUTTON_OPTIONS,
    "BTN_START":      BUTTON_MENU,
    "BTN_MODE":       BUTTON_HOME,
    "BTN_TL":         LEFT_SHOULDER,
    "BTN_TR":         RIGHT_SHOULDER,
    "BTN_TL2":        LEFT_TRIGGER,
    "BTN_TR2":        RIGHT_TRIGGER,
    # "BTN_DPAD_UP":    DPAD_UP,
    # "BTN_DPAD_DOWN":  DPAD_DOWN,
    # "BTN_DPAD_LEFT":  DPAD_LEFT,
    # "BTN_DPAD_RIGHT": DPAD_RIGHT,
}

# ABS_HAT axis value → dpad button name
DPAD_X : Final = {-1: DPAD_LEFT, 1: DPAD_RIGHT}
DPAD_Y : Final = {-1: DPAD_UP,   1: DPAD_DOWN}
