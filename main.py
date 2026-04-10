#!/usr/bin/python

# Animated dragon eyes for Raspberry Pi using pi3d.
# Per-eye state (position, blink, tracking) is managed by EyeState in eye/state.py.
# Frame pipeline stages live in frame_pipeline.py.
# Constants are in constants.py. Hardware is mocked for macOS dev via mock/hardware.py.

import argparse
import platform
import random
import threading
import time

import pi3d

if platform.system() == "Darwin":
    try:
        import Foundation as _Foundation
        _ns_date = _Foundation.NSDate.dateWithTimeIntervalSinceNow_
        _main_rl = _Foundation.NSRunLoop.mainRunLoop()
        def _pump_runloop():
            _main_rl.runUntilDate_(_ns_date(0))
    except ImportError:
        def _pump_runloop(): pass
else:
    def _pump_runloop(): pass

from constants import (
    DEBUG_MOVEMENT, TARGET_FPS, SEQUENCE_FILE, PUPIL_MIN, PUPIL_MAX, PUPIL_SMOOTH, PUPIL_IN, ControlMode)
from debug_overlay import DebugOverlay
from bluetooth import start_gamepad
from eye import Eyes, SequencePlayer
from frame_pipeline import (FrameState, LidChannels, draw_scene, update_eye_positions,
                            update_iris, update_blinks, update_lid_tracking, update_lids)
from init import init_gpio, init_adc, init_svg, init_display, init_scene

# ── Init ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--radius", type=int)
args, _ = parser.parse_known_args()

init_gpio()
hw    = init_adc()
svg   = init_svg("graphics/dragon-eye-edit.svg")
ctx   = init_display(args.radius)
scene = init_scene(svg, ctx)

debug_overlay   = DebugOverlay(ctx) if DEBUG_MOVEMENT else None
sequence_player = SequencePlayer(SEQUENCE_FILE)

mykeys = pi3d.Keyboard()
eyes   = Eyes(svg)
state  = FrameState()

quit_event = threading.Event()
_listener  = start_gamepad(quit_event, state, eyes, sequence_player)

# Lid preview — keyboard-driven channels for visual tuning (macOS dev only)
try:
    from mock.bonnet import Channel as _Channel, Bonnet as _MockBonnet
    lid_channels = LidChannels(
        left_upper  = _Channel(**_MockBonnet._CHANNEL_KEYS[5]),
        left_lower  = _Channel(**_MockBonnet._CHANNEL_KEYS[6]),
        right_upper = _Channel(**_MockBonnet._CHANNEL_KEYS[3]),
        right_lower = _Channel(**_MockBonnet._CHANNEL_KEYS[4]),
    )
except ImportError:
    lid_channels = None

# ── Frame ──────────────────────────────────────────────────────────────────────
def frame(pupil_scale):

    if quit_event.is_set():
        return False

    ctx.display.loop_running()
    now = time.monotonic()
    left, right = eyes.left, eyes.right

    state.frames += 1
    if state.frames % TARGET_FPS == 0:
        elapsed = now - state.beginning_time
        # if elapsed > 0:
        #     print("FPS: {:.2f}".format(TARGET_FPS / elapsed))
        state.beginning_time = now

    _pump_runloop()
    update_eye_positions(now, eyes, hw, state, sequence_player)
    update_iris(pupil_scale, state, scene, svg)
    update_blinks(now, eyes, state, sequence_player)
    update_lid_tracking(eyes, lid_channels, state, sequence_player)
    update_lids(now, left,  scene.left,  svg, scene, False)
    update_lids(now, right, scene.right, svg, scene, True)
    draw_scene(eyes, scene, ctx, debug_overlay, state)

    return True

def _frame_sleep(frame_start):
    """Hybrid sleep: yield CPU for most of the frame budget, busy-wait the last 1ms."""
    deadline  = frame_start + (1.0 / TARGET_FPS)
    remaining = deadline - time.monotonic()
    if remaining > 0.001:
        time.sleep(remaining - 0.001)
    while time.monotonic() < deadline:
        pass

# ── Split Pupil ────────────────────────────────────────────────────────────────
def split_pupil(start_value, end_value, duration, variance):
    """Recursive simulated pupil response when no analog sensor is present.

    Subdivides the transition between start_value and end_value into smaller
    random segments until the range drops below 0.125, then animates the pupil
    scale linearly over the remaining duration.

    Args:
        start_value (float): Pupil scale starting value (0.0–1.0).
        end_value   (float): Pupil scale ending value (0.0–1.0).
        duration    (float): Start-to-end time in seconds.
        variance    (float): Maximum +/- random pupil scale deviation at midpoint.
    """
    start_time = time.time()
    if variance >= 0.125:
        duration  *= 0.5
        variance  *= 0.5
        mid_value  = ((start_value + end_value - variance) * 0.5 + random.uniform(0.0, variance))
        split_pupil(start_value, mid_value, duration, variance)
        split_pupil(mid_value,   end_value, duration, variance)
    else:
        dv = end_value - start_value
        while True:
            frame_start = time.monotonic()
            dt = time.time() - start_time
            if dt >= duration: break

            pupil_scale_value = start_value + dv * dt / duration
            pupil_scale_value = max(PUPIL_MIN, min(pupil_scale_value, PUPIL_MAX))
            if not frame(pupil_scale_value):
                return
            _frame_sleep(frame_start)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():

    while True:
        if PUPIL_IN < 0 and state.control_mode != ControlMode.MANUAL:
            pupil_value = random.random()
            split_pupil(state.current_pupil, pupil_value, 4.0, 1.0)
        else:
            frame_start = time.monotonic()

            if state.control_mode == ControlMode.MANUAL:
                if state.controller_input.trigger_right:
                    state.manual_pupil = max(PUPIL_MIN, state.manual_pupil - 1.0 / TARGET_FPS)
                elif state.controller_input.trigger_left:
                    state.manual_pupil = min(PUPIL_MAX, state.manual_pupil + 1.0 / TARGET_FPS)
                pupil_value = state.manual_pupil
            else:
                pupil_value = hw.bonnet.channel[PUPIL_IN].value
                pupil_value = max(PUPIL_MIN, min(pupil_value, PUPIL_MAX))
                pupil_value = (pupil_value - PUPIL_MIN) / (PUPIL_MAX - PUPIL_MIN)
                if PUPIL_SMOOTH > 0:
                    pupil_value = ((state.current_pupil * (PUPIL_SMOOTH - 1) + pupil_value) / PUPIL_SMOOTH)

            frame(pupil_value)
            _frame_sleep(frame_start)

        state.current_pupil = pupil_value

        k = mykeys.read()
        if k == 27 or quit_event.is_set():
            mykeys.close()
            ctx.display.stop()
            exit(0)

if __name__ == "__main__":
    main()
