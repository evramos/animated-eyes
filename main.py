#!/usr/bin/python

# Animated dragon eyes for Raspberry Pi using pi3d.
# Per-eye state (position, blink, tracking) is managed by EyeState in eye/state.py.
# Frame pipeline lives in the pipeline/ package.
# Constants are in constants.py. Hardware is mocked for macOS dev via mock/hardware.py.

import argparse
import random
import time

import pi3d

from bluetooth import start_gamepad
from constants import TARGET_FPS, PUPIL_MIN, PUPIL_MAX, PUPIL_SMOOTH, PUPIL_IN, ControlMode
from pipeline import FramePipeline, FrameState

# ── Init ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--radius", type=int)
args, _ = parser.parse_known_args()

pipeline  = FramePipeline(radius=args.radius)
state     = FrameState()
listener  = start_gamepad(state, pipeline)
mykeys    = pi3d.Keyboard()

# ── Frame ──────────────────────────────────────────────────────────────────────
def frame(pupil_scale: float):

    if listener.quit_requested:
        return False

    pipeline.loop_display_running()
    now = time.monotonic()

    state.frames += 1
    if state.frames % TARGET_FPS == 0:
        state.beginning_time = now

    pipeline.update_eye_positions(now, state)
    pipeline.update_iris(pupil_scale, state)
    pipeline.update_eye_set(now, state)
    pipeline.update_blinks(now, state)
    pipeline.update_lid_tracking(state)
    pipeline.update_lids(now)
    pipeline.draw_scene(state)
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
            pupil_scale_value = max(PUPIL_MIN, min(start_value + dv * dt / duration, PUPIL_MAX))
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
                pupil_value = pipeline.hw.bonnet.channel[PUPIL_IN].value
                pupil_value = max(PUPIL_MIN, min(pupil_value, PUPIL_MAX))
                pupil_value = (pupil_value - PUPIL_MIN) / (PUPIL_MAX - PUPIL_MIN)
                if PUPIL_SMOOTH > 0:
                    pupil_value = (state.current_pupil * (PUPIL_SMOOTH - 1) + pupil_value) / PUPIL_SMOOTH

            frame(pupil_value)
            _frame_sleep(frame_start)

        state.current_pupil = pupil_value

        k = mykeys.read()
        if k == 27 or listener.quit_requested:
            mykeys.close()
            pipeline.display_stop()
            exit(0)


if __name__ == "__main__":
    main()
