#!/usr/bin/python

# Animated dragon eyes for Raspberry Pi using pi3d.
# Per-eye state (position, blink, tracking) is managed by EyeState in eye/state.py.
# Frame pipeline stages live in frame_pipeline.py.
# Constants are in constants.py. Hardware is mocked for macOS dev via mock/hardware.py.

import argparse
import random
import time
import json
import pi3d

from debug_overlay  import DebugOverlay
from init           import init_gpio, init_adc, init_svg, init_display, init_scene
from eye            import Eyes, SequencePlayer
from frame_pipeline import (FrameState, LidChannels,
                             update_eye_positions, update_iris,
                             update_blinks, update_lid_tracking,
                             update_lids, draw_scene)
from constants import *

# ── Init ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument("--radius", type=int)
args, _ = parser.parse_known_args()

init_gpio()
hw    = init_adc()
svg   = init_svg("graphics/dragon-eye-edit.svg")
ctx   = init_display(args.radius)
scene = init_scene(svg, ctx)

debug_overlay = DebugOverlay(ctx) if DEBUG_MOVEMENT else None

mykeys    = pi3d.Keyboard()
eyes = Eyes(svg)

sequence_player = SequencePlayer(SEQUENCE_FILE) if CONTROL_MODE == ControlMode.SCRIPTED else None

state = FrameState()

scene.left.sclera.positionX(ctx.eye_position)
scene.left.iris.positionX(ctx.eye_position)
scene.right.sclera.positionX(-ctx.eye_position)
scene.right.iris.positionX(-ctx.eye_position)

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

    ctx.display.loop_running()
    now = time.monotonic()

    state.frames += 1
    if state.frames % TARGET_FPS == 0:
        if now > state.beginning_time:
            print("FPS: {:.2f}".format(state.frames / (now - state.beginning_time)))
        print(json.dumps({"eye": eyes.left.to_dict()}))

    update_eye_positions(now, eyes, hw, sequence_player)
    update_iris(pupil_scale, state, scene, svg)
    update_blinks(now, eyes, state)
    update_lid_tracking(eyes, lid_channels, state)
    update_lids(now, eyes.left,  scene.left,  svg, scene, False)
    update_lids(now, eyes.right, scene.right, svg, scene, True)
    draw_scene(eyes, scene, ctx, debug_overlay)

    return True

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
            frame(pupil_scale_value)
            elapsed    = time.monotonic() - frame_start
            sleep_time = (1.0 / TARGET_FPS) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():

    current_pupil_scale = PUPIL_SCALE

    while True:
        if PUPIL_IN < 0:
            pupil_value = random.random()
            split_pupil(current_pupil_scale, pupil_value, 4.0, 1.0)
        else:
            frame_start = time.monotonic()

            pupil_value = hw.bonnet.channel[PUPIL_IN].value
            pupil_value = max(PUPIL_MIN, min(pupil_value, PUPIL_MAX))
            pupil_value = (pupil_value - PUPIL_MIN) / (PUPIL_MAX - PUPIL_MIN)

            if PUPIL_SMOOTH > 0:
                pupil_value = ((current_pupil_scale * (PUPIL_SMOOTH - 1) + pupil_value) / PUPIL_SMOOTH)

            frame(pupil_value)

            elapsed    = time.monotonic() - frame_start
            sleep_time = (1.0 / TARGET_FPS) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            elif sleep_time < 0:
                print(f"Frame overrun: {-sleep_time * 1000:.1f}ms late")

        current_pupil_scale = pupil_value

        k = mykeys.read()
        if k == 27:
            mykeys.close()
            ctx.display.stop()
            exit(0)

if __name__ == "__main__":
    main()
