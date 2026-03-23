"""
frame_pipeline.py

Per-frame rendering pipeline for DragonEyes.
Each function handles one stage of the frame; eyes.py calls them in order.

Stage order:
    update_eye_positions  → advance eye position for this frame
    update_iris           → regen iris mesh if pupil scale changed
    update_blinks         → advance blink state machines + auto-blink timer
    update_lid_tracking   → resolve lid tracking positions for both eyes
    update_lids           → blend blink weight into lid weights + regen lid meshes (per eye)
    draw_scene            → rotate all meshes to current positions and draw
"""

import random
import time
from dataclasses import dataclass, field
from typing import Protocol

import RPi.GPIO as GPIO

from constants import *
from gfxutil import points_interp, points_mesh

_blend_lid = lambda t, n: t + n * (1.0 - t)   # blend tracking pos with blink weight
_adc_to_angle = lambda ch: -30.0 + ch.value * 60.0

# ── Shared frame state ─────────────────────────────────────────────────────────

@dataclass
class FrameState:
    """Mutable per-frame counters and timers, replacing loose globals in eyes.py."""
    frames:             int         = 0
    beginning_time:     float       = field(default_factory=time.monotonic)
    prev_pupil_scale:   float       = -1.0   # forces iris regen on first frame
    time_of_last_blink: float       = 0.0
    time_to_next_blink: float       = 1.0
    step_key_held:      bool        = False  # edge detection for KEYFRAME_STEP space press
    control_mode:       ControlMode = CONTROL_MODE
    wink_left:          bool        = False
    wink_right:         bool        = False


# ── Lid preview channels ───────────────────────────────────────────────────────

class _HasValue(Protocol):
    @property
    def value(self) -> float: ...


@dataclass
class LidChannels:
    """Holds the four keyboard-driven ADC channels used during lid preview (macOS dev only).
    Pass None on hardware where mock.bonnet is unavailable.
    """
    left_upper:  _HasValue
    left_lower:  _HasValue
    right_upper: _HasValue
    right_lower: _HasValue


# ── Pipeline stages ────────────────────────────────────────────────────────────

def update_eye_positions(now, eyes, hw, state, sequence_player=None):
    """Advance left (and optionally right) eye position for this frame.

    The active CONTROL_MODE determines the source:
        MANUAL   — ADC joystick channels from the bonnet
        SCRIPTED — SequencePlayer keyframe playback
        RANDOM   — autonomous saccade state machine

    Args:
        now             (float):         Current timestamp in seconds.
        eyes            (Eyes):           Left & Right eye instance.
        hw              (HardwareContext): Bonnet ADC accessor.
        sequence_player (SequencePlayer): Required when CONTROL_MODE is SCRIPTED.
    """
    match state.control_mode:
        case ControlMode.MANUAL:
            if JOYSTICK_X_IN >= 0 and JOYSTICK_Y_IN >= 0:
                eyes.left.current.x = _adc_to_angle(hw.bonnet.channel[JOYSTICK_X_IN])
                eyes.left.current.y = _adc_to_angle(hw.bonnet.channel[JOYSTICK_Y_IN])

        case ControlMode.SCRIPTED:
            if sequence_player:
                if KEYFRAME_STEP:
                    pressed = GPIO.input(BLINK_PIN) == GPIO.LOW
                    if pressed and not state.step_key_held:
                        sequence_player.step()
                    state.step_key_held = pressed
                sequence_player.update(eyes.left, now)

        case ControlMode.RANDOM:
            eyes.left.update_position(now)

    if CRAZY_EYES:
        eyes.right.update_position(now)


def update_iris(pupil_scale, state, scene, svg):
    """Regenerate iris mesh if pupil scale has changed by at least one regen threshold.

    Interpolates between pupil_min and pupil_max point lists, builds a 3D mesh,
    and pushes it to both eye iris objects. Skipped if the change is below the
    scene's iris_regen_threshold (¼-pixel granularity).

    Args:
        pupil_scale (float):      Current pupil scale (0.0–1.0).
        state       (FrameState): Holds prev_pupil_scale; updated on regen.
        scene       (SceneContext): pi3d mesh objects and regen thresholds.
        svg         (SvgPoints):   Pupil and iris point lists.
    """
    if abs(pupil_scale - state.prev_pupil_scale) >= scene.iris_regen_threshold:
        inter_pupil = points_interp(svg.pupil_min, svg.pupil_max, pupil_scale)
        mesh = points_mesh((None, inter_pupil, svg.iris), 4, -scene.iris_z, True)
        scene.left.iris.re_init(pts=mesh)
        scene.right.iris.re_init(pts=mesh)
        state.prev_pupil_scale = pupil_scale


def update_blinks(now, eyes, state, sequence_player=None):
    """Advance blink state machines and fire the auto-blink timer.

    Handles three blink sources:
        - Auto-blink timer (AUTO_BLINK constant), or per-keyframe override
        - BLINK_PIN GPIO (blinks both eyes while held)
        - Per-eye wink pins (WINK_L_PIN / WINK_R_PIN)

    Args:
        now             (float):               Current timestamp in seconds.
        eyes            (Eyes):                Left & Right eye instance.
        state           (FrameState):          Holds blink timer state; updated on auto-blink.
        sequence_player (SequencePlayer|None): When provided, reads auto_blink from the
                                               active keyframe instead of the constant.
    """
    auto_blink = sequence_player.auto_blink if sequence_player else AUTO_BLINK

    if auto_blink and (now - state.time_of_last_blink) >= state.time_to_next_blink:
        state.time_of_last_blink = now
        duration = random.uniform(0.035, 0.06)
        if eyes.left.blink_state  == NO_BLINK: eyes.left.start_blink(now, duration)
        if eyes.right.blink_state == NO_BLINK: eyes.right.start_blink(now, duration)
        state.time_to_next_blink = duration * 3 + random.uniform(0.0, 4.0)

    eyes.left.update_blink(WINK_L_PIN,  now, wink_held=state.wink_left)
    eyes.right.update_blink(WINK_R_PIN, now, wink_held=state.wink_right)

    if BLINK_PIN >= 0 and not KEYFRAME_STEP and GPIO.input(BLINK_PIN) == GPIO.LOW:
        duration = random.uniform(0.035, 0.06)
        if eyes.left.blink_state  == NO_BLINK: eyes.left.start_blink(now, duration)
        if eyes.right.blink_state == NO_BLINK: eyes.right.start_blink(now, duration)


def update_lid_tracking(eyes, lid_channels, state, sequence_player=None):
    """Resolve lid tracking positions for both eyes.

    Priority (highest → lowest):
        1. eyelid_tracking=True  — dynamic tracking from eye position
        2. lid_weight authored   — interpolated scripted weights
        3. lid_channels preview  — macOS dev keyboard channels
        4. Fixed defaults        — 0.4 upper / 0.6 lower

    eyelid_tracking overrides lid_weight when both are set on a keyframe.

    Args:
        eyes            (Eyes):                Left & Right eye instance.
        lid_channels    (LidChannels|None):    Preview channels, or None on hardware.
        state           (FrameState):          Used for the per-second debug print.
        sequence_player (SequencePlayer|None): When provided, reads lid_weight and
                                               eyelid_tracking from the active keyframe.
    """
    right_independent = CRAZY_EYES or not MIRROR_LIDS

    lid_weight = sequence_player.current_lid_weight if sequence_player else None
    do_tracking = sequence_player.eyelid_tracking if sequence_player else EYELID_TRACKING

    if sequence_player and state.frames % TARGET_FPS == 0:
        lw = lid_weight
        lw_str = (f"L({lw['left'][0]:.2f},{lw['left'][1]:.2f}) R({lw['right'][0]:.2f},{lw['right'][1]:.2f})"
                  if lw else "none")
        # print(f"[seq] kf={sequence_player.index}  auto_blink={sequence_player.auto_blink}  "
        #       f"tracking={do_tracking}  lid_weight={lw_str}")

    if do_tracking:
        if lid_channels:
            left_upper_bias  = lid_channels.left_upper.value
            left_lower_bias  = lid_channels.left_lower.value
            right_upper_bias = lid_channels.right_upper.value if not MIRROR_LIDS else left_upper_bias
            right_lower_bias = lid_channels.right_lower.value if not MIRROR_LIDS else left_lower_bias
        else:
            left_upper_bias = right_upper_bias = 0.4
            left_lower_bias = right_lower_bias = 0.6

        eyes.left.update_tracking(left_upper_bias, left_lower_bias)
        if right_independent:
            eyes.right.update_tracking(right_upper_bias, right_lower_bias)

        # if lid_channels and state.frames % TARGET_FPS == 0:
        #     print(f"L upper: {left_upper_bias:.2f}, L lower: {left_lower_bias:.2f} | "
        #           f"R upper: {right_upper_bias:.2f}, R lower: {right_lower_bias:.2f}")
    elif lid_weight is not None:
        # Scripted weights — assign directly, no smoothing
        lu, ll = lid_weight["left"]
        ru, rl = lid_weight["right"]
        eyes.left.upper_tracking_pos = lu
        eyes.left.lower_tracking_pos = ll
        if right_independent:
            eyes.right.upper_tracking_pos = ru
            eyes.right.lower_tracking_pos = rl
    else:
        if lid_channels:
            eyes.left.upper_tracking_pos  = lid_channels.left_upper.value
            eyes.left.lower_tracking_pos  = lid_channels.left_lower.value
            eyes.right.upper_tracking_pos = lid_channels.left_upper.value if MIRROR_LIDS else lid_channels.right_upper.value
            eyes.right.lower_tracking_pos = lid_channels.left_lower.value if MIRROR_LIDS else lid_channels.right_lower.value

    if not right_independent:
        eyes.right.upper_tracking_pos = eyes.left.upper_tracking_pos
        eyes.right.lower_tracking_pos = eyes.left.lower_tracking_pos


def update_lids(now, eye, eye_meshes, svg, scene, flip):
    """Blend blink weight with tracking position and regenerate lid meshes for one eye.

    Args:
        now        (float):     Current timestamp in seconds.
        eye        (Eye):       Eye instance (provides tracking_pos and blink_weight).
        eye_meshes (EyeMeshes): pi3d mesh objects for this eye (scene.left or scene.right).
        svg        (SvgPoints): Lid point lists.
        scene      (SceneContext): Provides regen thresholds.
        flip       (bool):      True for right eye (mirrors UV orientation).
    """
    n = eye.blink_weight(now)
    eye.lids.upper.update(eye_meshes.lids.upper, svg.upper_lid, _blend_lid(eye.upper_tracking_pos, n), scene.upper_lid_regen_threshold, flip)
    eye.lids.lower.update(eye_meshes.lids.lower, svg.lower_lid, _blend_lid(eye.lower_tracking_pos, n), scene.lower_lid_regen_threshold, flip)


def draw_scene(eyes, scene, ctx, debug_overlay):
    """Rotate all meshes to current eye positions and draw the frame.

    Applies X/Y rotation from eye position, optional Z rotation when ROTATE_EYES
    is set, then draws or delegates to the debug overlay.

    Args:
        eyes         (Eyes):           Left & Right eye instance.
        scene         (SceneContext):  All pi3d mesh objects.
        ctx           (DisplayContext): Display and shader context.
        debug_overlay (DebugOverlay|None): Drawn instead of the scene when DEBUG_MOVEMENT is True.
    """
    right_eye_pos = eyes.right if CRAZY_EYES else eyes.left

    # Rotate iris and sclera to current eye angles
    for eye, meshes, convergence in (
        (eyes.left,     scene.left,   CONVERGENCE),
        (right_eye_pos, scene.right, -CONVERGENCE),
    ):
        meshes.iris.rotateToX(eye.current.y)
        meshes.iris.rotateToY(eye.current.x + convergence)
        meshes.sclera.rotateToX(eye.current.y)
        meshes.sclera.rotateToY(eye.current.x + convergence)

    if ROTATE_EYES:
        for meshes in (scene.left, scene.right):
            meshes.iris.rotateToZ(ROTATE_DEGREES)
            meshes.sclera.rotateToZ(ROTATE_DEGREES)
            meshes.lids.rotateToZ(ROTATE_DEGREES)

    if DEBUG_MOVEMENT:
        debug_overlay.draw(eyes.left, ctx)
    else:
        scene.left.iris.draw()
        scene.left.sclera.draw()
        scene.left.lids.draw()

    scene.right.iris.draw()
    scene.right.sclera.draw()
    scene.right.lids.draw()
