"""
bindings.py — Gamepad button bindings for DragonEyes.

Organizes bindings into a global section (active in every mode) and three
mode-specific sections (RANDOM, SCRIPTED, MANUAL). Mode-specific callbacks are
wrapped with _when() so they silently no-op when the active mode doesn't match.

Call setup_bindings() after constructing the listener, before start().
"""
from collections.abc import Callable

from bluetooth import GamepadListener
from bluetooth.constants import *
from constants import ControlMode, EyeSet
from pipeline import FrameState, FramePipeline


def start_gamepad(state: FrameState, pipeline: FramePipeline) -> GamepadListener:
    """Create, bind, and start a GamepadListener. Returns the listener."""
    listener = GamepadListener()
    setup_bindings(listener, state, pipeline)
    listener.start()
    return listener

def setup_bindings(listener: GamepadListener, state: FrameState, pipeline: FramePipeline):
    """Register all gamepad button bindings on listener.

    Args:
        listener    (GamepadListener):  The listener to register callbacks on.
        state       (FrameState):       Shared per-frame mutable state.
        pipeline    (FramePipeline):    Provides access to stable contexts needed by callbacks.
    """
    # ── Helpers ───────────────────────────────────────────────────────────────
    def _switch_mode(mode: ControlMode):

        if pipeline.sensor is not None:
            pipeline.sensor.resume() if mode == ControlMode.TRACKING else pipeline.sensor.suspend()

        if mode == ControlMode.MANUAL:
            state.manual_x         = pipeline.eyes.left.current.x
            state.manual_y         = pipeline.eyes.left.current.y
            state.manual_last_time = 0.0
            state.manual_pupil     = state.current_pupil
        state.control_mode = mode
        if mode == ControlMode.SCRIPTED and pipeline.seq.current_file:
            print(f"[mode] → {mode.name}  ({pipeline.seq.current_file})")
        else:
            print(f"[mode] → {mode.name}")

    def _when(mode: ControlMode, fn: Callable[[], None]) -> Callable[[], None]:
        """Return a callback that only fires when state.control_mode == mode."""
        return lambda: fn() if state.control_mode == mode else None

    def bind_held(button, attr, mode=None):
        _input = state.controller_input
        press = _when(mode, lambda: setattr(_input, attr, True)) if mode else lambda: setattr(_input, attr, True)
        listener.add_on_press  (button, press)
        listener.add_on_release(button, lambda: setattr(_input, attr, False))

    # ── Global — active in every mode ────────────────────────────────────────
    def _toggle_auto_blink():
        state.auto_blink = not state.auto_blink
        print(f"[toggle] auto_blink → {state.auto_blink}")

    def _quit():
        print(f"[gamepad] {" + ".join(sorted(GAMEPAD_QUIT_COMBO))} → exiting")
        listener.request_quit()

    listener.add_combo(GAMEPAD_QUIT_COMBO, _quit)
    listener.add_combo({BUTTON_B, DPAD_LEFT},  lambda: _switch_mode(ControlMode.RANDOM))
    listener.add_combo({BUTTON_B, DPAD_UP},    lambda: _switch_mode(ControlMode.MANUAL))
    listener.add_combo({BUTTON_B, DPAD_RIGHT}, lambda: _switch_mode(ControlMode.SCRIPTED))
    listener.add_combo({BUTTON_B, DPAD_DOWN},  lambda: _switch_mode(ControlMode.TRACKING))
    listener.add_on_press(BUTTON_OPTIONS, _toggle_auto_blink)
    bind_held(LEFT_SHOULDER,  "wink_left")
    bind_held(RIGHT_SHOULDER, "wink_right")
    bind_held(BUTTON_X, "button_x_held")
    bind_held(BUTTON_B, "button_b_held")

    # ── Eye set — active in every mode ───────────────────────────────────────

    def _preset_count() -> int:
        defn = pipeline._c.scene.eye_set_registry.get(state.eye_set)
        return len(defn.presets) if defn and defn.presets else 1

    def _switch_eye_set(eye_set):
        state.eye_set = eye_set
        state.preset_index = 0
        if eye_set == EyeSet.NORMAL:
            state.draw_lids = True
        else:
            state.draw_lids = False

        print(f"[eye_set] → {state.eye_set.name}")

    listener.add_combo({BUTTON_X, DPAD_UP},    lambda: _switch_eye_set(EyeSet.NORMAL))
    listener.add_combo({BUTTON_X, DPAD_LEFT},  lambda: _switch_eye_set(EyeSet.HYPNO))
    listener.add_combo({BUTTON_X, DPAD_RIGHT}, lambda: _switch_eye_set(EyeSet.RINGS))

    def _next_preset():
        n = _preset_count()
        state.preset_index = (state.preset_index + 1) % n
        print(f"[preset] → {state.preset_index}")

    def _prev_preset():
        n = _preset_count()
        state.preset_index = (state.preset_index - 1) % n
        print(f"[preset] → {state.preset_index}")

    listener.add_combo({BUTTON_X, RIGHT_TRIGGER},  _next_preset)
    listener.add_combo({BUTTON_X, LEFT_TRIGGER},   _prev_preset)

    # ── RANDOM — crazy eyes toggle ────────────────────────────────────────────
    def _toggle_crazy_eyes():
        state.crazy_eyes = not state.crazy_eyes
        print(f"[toggle] crazy_eyes → {state.crazy_eyes}")

    def _toggle_draw_lids():
        state.draw_lids = not state.draw_lids
        print(f"[toggle] draw_lids → {state.draw_lids}")

    def _on_menu():
        if state.eye_set in (EyeSet.HYPNO, EyeSet.RINGS):
            _toggle_draw_lids()
        elif state.control_mode == ControlMode.RANDOM:
            _toggle_crazy_eyes()

    listener.add_on_press(BUTTON_MENU, _on_menu)

    # ── SCRIPTED — sequence cycling ───────────────────────────────────────────
    listener.add_on_press(BUTTON_Y, _when(ControlMode.SCRIPTED, lambda: pipeline.seq.cycle(-1)))
    listener.add_on_press(BUTTON_A, _when(ControlMode.SCRIPTED, lambda: pipeline.seq.cycle(+1)))

    # ── MANUAL — lid adjustment modifier (Y = right eye, A = left eye) ────────
    bind_held(BUTTON_Y, "button_y_held", ControlMode.MANUAL)
    bind_held(BUTTON_A, "button_a_held", ControlMode.MANUAL)

    bind_held(DPAD_LEFT,  "dpad_left",  ControlMode.MANUAL)
    bind_held(DPAD_RIGHT, "dpad_right", ControlMode.MANUAL)
    bind_held(DPAD_UP,    "dpad_up",    ControlMode.MANUAL)
    bind_held(DPAD_DOWN,  "dpad_down",  ControlMode.MANUAL)

    bind_held(LEFT_TRIGGER,  "trigger_left",  ControlMode.MANUAL)
    bind_held(RIGHT_TRIGGER, "trigger_right", ControlMode.MANUAL)
