#!/usr/bin/python

# Animated dragon eyes for Raspberry Pi using pi3d.
# Per-eye state (position, blink, tracking) is managed by EyeState in state.py.
# Constants are in constants.py. Hardware is mocked for macOS dev via hardware.py.

import argparse
import random
import time
import json
import RPi.GPIO as GPIO
import pi3d

from debug_overlay import DebugOverlay
from gfxutil import points_interp, points_mesh
from init import init_gpio, init_adc, init_svg, init_display, init_scene
from eye import EyeLidState, EyeState, SequencePlayer
from constants import *

parser = argparse.ArgumentParser()
parser.add_argument("--radius", type=int)
args, _ = parser.parse_known_args()

init_gpio()
hw    = init_adc()
svg   = init_svg("graphics/dragon-eye-edit.svg")
ctx   = init_display(args.radius)
scene = init_scene(svg, ctx)

debug_overlay = DebugOverlay(ctx) if DEBUG_MOVEMENT else None

# Init global stuff --------------------------------------------------------

mykeys = pi3d.Keyboard() # For capturing key presses
left_eye, right_eye = (EyeState(), EyeState())

if CONTROL_MODE == ControlMode.SCRIPTED:
    sequence_player = SequencePlayer(SEQUENCE_FILE)

frames = 0
beginningTime = time.time()

scene.left.sclera.positionX(ctx.eye_position)
scene.left.iris.positionX(ctx.eye_position)
scene.right.sclera.positionX(-ctx.eye_position)
scene.right.iris.positionX(-ctx.eye_position)

prev_pupil_scale = -1.0 # Force regen on first frame
left_eye_lids = EyeLidState(svg.upper_lid.open, svg.upper_lid.closed, svg.lower_lid.open, svg.lower_lid.closed)
right_eye_lids = EyeLidState(svg.upper_lid.open, svg.upper_lid.closed, svg.lower_lid.open, svg.lower_lid.closed)
timeOfLastBlink, timeToNextBlink = (0.0, 1.0)

# ----------------------------------------------------------------------------------------------------------------------
# Frame -- Generate one frame of imagery
# ----------------------------------------------------------------------------------------------------------------------
def frame(pupil_scale):

    global frames
    global prev_pupil_scale
    global timeOfLastBlink, timeToNextBlink

    ctx.display.loop_running()
    now = time.time()

    frames += 1
    if frames % TARGET_FPS == 0 and now > beginningTime:
        print("FPS: {:.2f}".format(frames / (now - beginningTime)))

    if frames % TARGET_FPS == 0:
        print(json.dumps({"eye": left_eye.to_dict()}))

    match CONTROL_MODE:
        case ControlMode.MANUAL:
            if JOYSTICK_X_IN >= 0 and JOYSTICK_Y_IN >= 0:
                left_eye.current.x = -30.0 + hw.bonnet.channel[JOYSTICK_X_IN].value * 60.0
                left_eye.current.y = -30.0 + hw.bonnet.channel[JOYSTICK_Y_IN].value * 60.0

        case ControlMode.SCRIPTED:
            sequence_player.update(left_eye, now)

        case ControlMode.RANDOM:
            left_eye.update_position(now)

    if CRAZY_EYES: # repeat for other eye if CRAZY_EYES
        right_eye.update_position(now)
# ----------------------------------------------------------------------------------------------------------------------
    """
    # Regenerate iris geometry only if size changed by >= 1/4 pixel
    
    p is the current pupil scale (0.0–1.0). Every frame it checks if the pupil has changed enough to be worth redrawing (at
    least 1/4 pixel worth of change). If so, it interpolates between the minimum and maximum pupil point shapes, generates a
    3D mesh connecting the pupil ring to the iris ring, and pushes that mesh to both eyes. prevPupilScale is saved so next
    frame knows where it left off.
    """
    if abs(pupil_scale - prev_pupil_scale) >= scene.iris_regen_threshold:
        # Interpolate points between min and max pupil sizes
        inter_pupil = points_interp(svg.pupil_min, svg.pupil_max, pupil_scale)
        # Generate mesh between interpolated pupil and iris bounds
        mesh = points_mesh((None, inter_pupil, svg.iris), 4, -scene.iris_z, True)
        # Assign to both eyes
        scene.left.iris.re_init(pts=mesh)
        scene.right.iris.re_init(pts=mesh)
        prev_pupil_scale = pupil_scale

# ----------------------------------------------------------------------------------------------------------------------
    # Eyelid WIP
    """
    Auto-blink timer — if enough time has passed since the last blink, trigger both eyes to close and schedule the next blink randomly.
    """
    if AUTO_BLINK and (now - timeOfLastBlink) >= timeToNextBlink:
        timeOfLastBlink = now
        duration = random.uniform(0.035, 0.06) # duration

        if left_eye.blink_state == NO_BLINK: left_eye.start_blink(now , duration)
        if right_eye.blink_state == NO_BLINK: right_eye.start_blink(now , duration)

        timeToNextBlink = duration * 3 + random.uniform(0.0, 4.0)

    """
    update_blink — advances each eye's blink state machine: closing → held closed (if button held) → opening → done.
    """
    left_eye.update_blink(WINK_L_PIN, now)
    right_eye.update_blink(WINK_R_PIN, now)

    if BLINK_PIN >= 0 and GPIO.input(BLINK_PIN) == GPIO.LOW:
        duration = random.uniform(0.035, 0.06)

        if left_eye.blink_state == NO_BLINK: left_eye.start_blink(now , duration)
        if right_eye.blink_state == NO_BLINK: right_eye.start_blink(now , duration)
# ----------------------------------------------------------------------------------------------------------------------
    # TODO - Need an explanation on what this section does between the comment dashes '# ----'
    """
    Keeps the upper eyelid in sync with the eye. I think
    """

    if TRACKING:
        n = 0.4 - left_eye.current.y / 60.0
        n = max(0.0, min(n, 1.0))
        left_eye.tracking_pos = (left_eye.tracking_pos * 3.0 + n) * 0.25

        if CRAZY_EYES:
            n = 0.4 - right_eye.current.y / 60.0
            n = max(0.0, min(n, 1.0))
            right_eye.tracking_pos = (right_eye.tracking_pos * 3.0 + n) * 0.25

# ----------------------------------------------------------------------------------------------------------------------
    n = left_eye.blink_weight(now)
    new_left_upper_lid_weight = left_eye.tracking_pos + (n * (1.0 - left_eye.tracking_pos))
    new_left_lower_lid_weight = (1.0 - left_eye.tracking_pos) + (n * left_eye.tracking_pos)

    n = right_eye.blink_weight(now)
    if CRAZY_EYES:
        new_right_upper_lid_weight = right_eye.tracking_pos + (n * (1.0 - right_eye.tracking_pos))
        new_right_lower_lid_weight = (1.0 - right_eye.tracking_pos) + (n * right_eye.tracking_pos)
    else:
        new_right_upper_lid_weight = left_eye.tracking_pos + (n * (1.0 - left_eye.tracking_pos))
        new_right_lower_lid_weight = (1.0 - left_eye.tracking_pos) + (n * left_eye.tracking_pos)

    left_eye_lids.upper.update(scene.left.lids.upper, svg.upper_lid, new_left_upper_lid_weight, scene.upper_lid_regen_threshold, False)
    left_eye_lids.lower.update(scene.left.lids.lower, svg.lower_lid, new_left_lower_lid_weight, scene.lower_lid_regen_threshold, False)

    right_eye_lids.upper.update(scene.right.lids.upper, svg.upper_lid, new_right_upper_lid_weight, scene.upper_lid_regen_threshold, True)
    right_eye_lids.lower.update(scene.right.lids.lower, svg.lower_lid, new_right_lower_lid_weight, scene.lower_lid_regen_threshold, True)

# ----------------------------------------------------------------------------------------------------------------------
    # Left eye (on screen right)
    scene.left.iris.rotateToX(left_eye.current.y)
    scene.left.iris.rotateToY(left_eye.current.x + CONVERGENCE)
    scene.left.sclera.rotateToX(left_eye.current.y)
    scene.left.sclera.rotateToY(left_eye.current.x + CONVERGENCE)

    # Right eye (on screen left)
    if CRAZY_EYES:
        scene.right.iris.rotateToX(right_eye.current.y)
        scene.right.iris.rotateToY(right_eye.current.x - CONVERGENCE)
        scene.right.sclera.rotateToX(right_eye.current.y)
        scene.right.sclera.rotateToY(right_eye.current.x - CONVERGENCE)
    else:
        scene.right.iris.rotateToX(left_eye.current.y)
        scene.right.iris.rotateToY(left_eye.current.x - CONVERGENCE)
        scene.right.sclera.rotateToX(left_eye.current.y)
        scene.right.sclera.rotateToY(left_eye.current.x - CONVERGENCE)

    # Flip Eyes Horizontally
    if ROTATE_EYES:
        scene.left.iris.rotateToZ(ROTATE_DEGREES)
        scene.left.sclera.rotateToZ(ROTATE_DEGREES)
        scene.left.lids.rotateToZ(ROTATE_DEGREES)

        scene.right.iris.rotateToZ(ROTATE_DEGREES)
        scene.right.sclera.rotateToZ(ROTATE_DEGREES)
        scene.right.lids.rotateToZ(ROTATE_DEGREES)

    if DEBUG_MOVEMENT:
        debug_overlay.draw(left_eye, ctx)
    else:
        scene.left.iris.draw()
        scene.left.sclera.draw()
        scene.left.lids.draw()

    scene.right.iris.draw()
    scene.right.sclera.draw()
    scene.right.lids.draw()

    return True

# ----------------------------------------------------------------------------------------------------------------------
# Split Pupil -- Recursive simulated pupil response
# ----------------------------------------------------------------------------------------------------------------------
def split_pupil(start_value, end_value, duration, variance):
    """
    Recursive simulated pupil response when no analog sensor is present. Subdivides the transition between startValue and endValue
    into smaller random segments until the range drops below 0.125, then animates the pupil scale linearly over the remaining duration.

    Args:
      start_value (float): Pupil scale starting value (0.0 to 1.0).
      end_value (float): Pupil scale ending value (0.0 to 1.0).
      duration (float): Start-to-end time in floating-point seconds.
      variance (float): Maximum +/- random pupil scale deviation at midpoint.
    """
    start_time = time.time()
    if variance >= 0.125: # Limit sub-dvision count, because recursion
        duration *= 0.5 # Split time & range in half for subdivision,
        variance *= 0.5 # then pick random center point within variance range:
        mid_value = ((start_value + end_value - variance) * 0.5 + random.uniform(0.0, variance))

        split_pupil(start_value, mid_value, duration, variance)
        split_pupil(mid_value, end_value, duration, variance)

    else: # No more subdivisions, do iris motion...
        dv = end_value - start_value

        while True:
            frame_start = time.monotonic()
            dt = time.time() - start_time
            if dt >= duration: break
            pupil_scale_value = start_value + dv * dt / duration
            pupil_scale_value = max(PUPIL_MIN, min(pupil_scale_value, PUPIL_MAX))
            frame(pupil_scale_value) # Draw frame w/interim pupil scale value

            elapsed = time.monotonic() - frame_start
            sleep_time = (1.0 / TARGET_FPS) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

# ----------------------------------------------------------------------------------------------------------------------
# MAIN LOOP -- runs continuously
# ----------------------------------------------------------------------------------------------------------------------
def main():

    current_pupil_scale = PUPIL_SCALE

    while True:

        if PUPIL_IN < 0:  # Fractal auto pupil scale — split_pupil handles its own frame timing
            pupil_value = random.random()
            split_pupil(current_pupil_scale, pupil_value, 4.0, 1.0)

        else:  # Pupil scale from sensor
            frame_start = time.monotonic()

            pupil_value = hw.bonnet.channel[PUPIL_IN].value
            # If you need to calibrate PUPIL_MIN and MAX, add a 'print v' here for testing.

            pupil_value = max(PUPIL_MIN, min(pupil_value, PUPIL_MAX))
            pupil_value = (pupil_value - PUPIL_MIN) / (PUPIL_MAX - PUPIL_MIN)  # Scale to 0.0 to 1.0:

            if PUPIL_SMOOTH > 0:
                pupil_value = ((current_pupil_scale * (PUPIL_SMOOTH - 1) + pupil_value) / PUPIL_SMOOTH)

            frame(pupil_value)

            elapsed = time.monotonic() - frame_start
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