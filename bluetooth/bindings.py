"""
bindings.py — Gamepad button bindings for DragonEyes.

Organizes bindings into a global section (active in every mode) and three
mode-specific sections (RANDOM, SCRIPTED, MANUAL). Mode-specific callbacks are
wrapped with _when() so they silently no-op when the active mode doesn't match.

Call setup_bindings() after constructing the listener, before start().
"""
from bluetooth.constants import *
from constants import ControlMode


def start_gamepad(quit_event, state, eyes, sequence_player):
    """Create, bind, and start a GamepadListener. Returns the listener."""
    from bluetooth.gamepad import GamepadListener
    listener = GamepadListener(quit_event)
    setup_bindings(listener, quit_event, state, eyes, sequence_player)
    listener.start()
    return listener


def setup_bindings(listener, quit_event, state, eyes, sequence_player):
    """Register all gamepad button bindings on listener.

    Args:
        listener        (GamepadListener):  The listener to register callbacks on.
        quit_event      (threading.Event):  Set to signal a clean exit.
        state           (FrameState):       Shared per-frame mutable state.
        eyes            (Eyes):             Left/right eye objects (for MANUAL seed position).
        sequence_player (SequencePlayer):   Cycled via .cycle() and queried via .current_file.
    """
    def _when(mode, fn):
        """Return a callback that only fires when state.control_mode == mode."""
        return lambda: fn() if state.control_mode == mode else None

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _switch_mode(mode):
        if mode == ControlMode.MANUAL:
            state.manual_x         = eyes.left.current.x
            state.manual_y         = eyes.left.current.y
            state.manual_last_time = 0.0
            state.manual_pupil     = state.current_pupil
        state.control_mode = mode
        if mode == ControlMode.SCRIPTED and sequence_player.current_file:
            print(f"[mode] → {mode.name}  ({sequence_player.current_file})")
        else:
            print(f"[mode] → {mode.name}")

    # ── Global — active in every mode ────────────────────────────────────────
    listener.add_combo(GAMEPAD_QUIT_COMBO, lambda: (
        print(f"[gamepad] {" + ".join(sorted(GAMEPAD_QUIT_COMBO))} → exiting"),
        quit_event.set(),
    ))

    listener.add_combo({BUTTON_B, DPAD_LEFT},  lambda: _switch_mode(ControlMode.RANDOM))
    listener.add_combo({BUTTON_B, DPAD_UP},    lambda: _switch_mode(ControlMode.MANUAL))
    listener.add_combo({BUTTON_B, DPAD_RIGHT}, lambda: _switch_mode(ControlMode.SCRIPTED))

    listener.add_on_press  ("leftShoulder",  lambda: setattr(state, "wink_left",  True))
    listener.add_on_release("leftShoulder",  lambda: setattr(state, "wink_left",  False))
    listener.add_on_press  ("rightShoulder", lambda: setattr(state, "wink_right", True))
    listener.add_on_release("rightShoulder", lambda: setattr(state, "wink_right", False))

    listener.add_on_press(BUTTON_OPTIONS, lambda: (
        setattr(state, "auto_blink", not state.auto_blink),
        print(f"[toggle] auto_blink → {state.auto_blink}"),
    ))

    # ── RANDOM — crazy eyes toggle ────────────────────────────────────────────
    def _toggle_crazy_eyes():
        state.crazy_eyes = not state.crazy_eyes
        print(f"[toggle] crazy_eyes → {state.crazy_eyes}")

    listener.add_on_press(BUTTON_MENU, _when(ControlMode.RANDOM, _toggle_crazy_eyes))

    # ── SCRIPTED — sequence cycling ───────────────────────────────────────────
    listener.add_on_press(BUTTON_Y, _when(ControlMode.SCRIPTED, lambda: sequence_player.cycle(-1)))
    listener.add_on_press(BUTTON_A, _when(ControlMode.SCRIPTED, lambda: sequence_player.cycle(+1)))

    # ── MANUAL — lid adjustment modifier (Y = right eye, A = left eye) ────────
    listener.add_on_press  (BUTTON_Y, _when(ControlMode.MANUAL, lambda: setattr(state, "button_y_held", True)))
    listener.add_on_release(BUTTON_Y,                           lambda: setattr(state, "button_y_held", False))
    listener.add_on_press  (BUTTON_A, _when(ControlMode.MANUAL, lambda: setattr(state, "button_a_held", True)))
    listener.add_on_release(BUTTON_A,                           lambda: setattr(state, "button_a_held", False))

    listener.add_on_press  (DPAD_LEFT,  _when(ControlMode.MANUAL, lambda: setattr(state, "dpad_left",  True)))
    listener.add_on_release(DPAD_LEFT,                            lambda: setattr(state, "dpad_left",  False))
    listener.add_on_press  (DPAD_RIGHT, _when(ControlMode.MANUAL, lambda: setattr(state, "dpad_right", True)))
    listener.add_on_release(DPAD_RIGHT,                           lambda: setattr(state, "dpad_right", False))
    listener.add_on_press  (DPAD_UP,    _when(ControlMode.MANUAL, lambda: setattr(state, "dpad_up",    True)))
    listener.add_on_release(DPAD_UP,                              lambda: setattr(state, "dpad_up",    False))
    listener.add_on_press  (DPAD_DOWN,  _when(ControlMode.MANUAL, lambda: setattr(state, "dpad_down",  True)))
    listener.add_on_release(DPAD_DOWN,                            lambda: setattr(state, "dpad_down",  False))

    listener.add_on_press  ("leftTrigger",  _when(ControlMode.MANUAL, lambda: setattr(state, "trigger_left",  True)))
    listener.add_on_release("leftTrigger",                             lambda: setattr(state, "trigger_left",  False))
    listener.add_on_press  ("rightTrigger", _when(ControlMode.MANUAL, lambda: setattr(state, "trigger_right", True)))
    listener.add_on_release("rightTrigger",                            lambda: setattr(state, "trigger_right", False))
