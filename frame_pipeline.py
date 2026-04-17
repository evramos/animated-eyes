"""
frame_pipeline.py

Per-frame rendering pipeline for DragonEyes.
Each function handles one stage of the frame; eyes.py calls them in order.

Stage order:
    update_eye_positions  → advance eye position for this frame
    update_iris           → regen iris mesh if pupil scale changed (skipped in HYPNO)
    update_eye_set        → advance hypno spiral texture + sclera fade transition
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

from bluetooth.constants import AXIS_SPEED, AXIS_SPRING
from constants import *
from eye import SequencePlayer, Eyes, Eye
from gfxutil import points_interp, points_mesh
from models import HardwareContext, SceneContext


@dataclass
class InputState:
    """Raw button/axis signals written by the gamepad thread."""
    wink_left:     bool = False
    wink_right:    bool = False
    dpad_left:     bool = False
    dpad_right:    bool = False
    dpad_up:       bool = False
    dpad_down:     bool = False
    button_a_held: bool = False
    button_y_held: bool = False
    trigger_left:  bool = False
    trigger_right: bool = False
    step_key_held: bool = False # edge detection for KEYFRAME_STEP space press


# ── Shared frame state ─────────────────────────────────────────────────────────

@dataclass
class FrameState:
    """Mutable per-frame counters and timers, replacing loose globals in eyes.py."""
    frames:             int         = 0
    beginning_time:     float       = field(default_factory=time.monotonic)
    prev_pupil_scale:   float       = -1.0   # forces iris regen on first frame
    time_of_last_blink: float       = 0.0
    time_to_next_blink: float       = 1.0
    control_mode:       ControlMode = CONTROL_MODE
    controller_input:   InputState  = field(default_factory=InputState)
    manual_x:           float       = 0.0   # current eye angle in MANUAL mode
    manual_y:           float       = 0.0
    manual_last_time:   float       = 0.0
    current_pupil:      float       = PUPIL_SCALE
    manual_pupil:       float       = PUPIL_SCALE
    auto_blink:         bool        = AUTO_BLINK
    crazy_eyes:         bool        = CRAZY_EYES
    eye_set:            EyeSet      = EYE_SET
    prev_eye_set:       EyeSet      = EYE_SET
    preset_index:       int         = 0        # cycles through the active EyeSet's presets
    hypno_transition:   float       = 0.0      # 0.0 = NORMAL, 1.0 = fully in HYPNO


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

# ── Helpers ────────────────────────────────────────────────────────────────────

def _blend_lid(t, n): # blend tracking pos with blink weight
    return t + n * (1.0 - t)


def _adc_to_angle(ch):
    return -30.0 + ch.value * 60.0


def _adjust_lid_tracking(eye: Eye, pad_input: InputState, step: float) -> None:
    if pad_input.dpad_up:
        eye.upper_tracking_pos = max(0.0, eye.upper_tracking_pos - step)
    elif pad_input.dpad_down:
        eye.upper_tracking_pos = min(1.0, eye.upper_tracking_pos + step)
    if pad_input.dpad_left:
        eye.lower_tracking_pos = max(0.0, eye.lower_tracking_pos - step)
    elif pad_input.dpad_right:
        eye.lower_tracking_pos = min(1.0, eye.lower_tracking_pos + step)


def _apply_axis(value: float, neg_held, pos_held, lid_mod, dt) -> float:
    if not lid_mod and neg_held:
        return max(-30.0, value - AXIS_SPEED * dt)
    elif not lid_mod and pos_held:
        return min( 30.0, value + AXIS_SPEED * dt)
    elif value > 0:
        return max(0.0, value - AXIS_SPRING * dt)
    elif value < 0:
        return min(0.0, value + AXIS_SPRING * dt)
    return value

# ── Pipeline stages ────────────────────────────────────────────────────────────

def update_eye_positions(now: float, eyes: Eyes, hw: HardwareContext, state: FrameState,
                         sequence_player: SequencePlayer=None):
    """Advance left (and optionally right) eye position for this frame.

    The active CONTROL_MODE determines the source:
        MANUAL   — ADC joystick channels from the bonnet
        SCRIPTED — SequencePlayer keyframe playback
        RANDOM   — autonomous saccade state machine

    Args:
        now             (float):           Current timestamp in seconds.
        eyes            (Eyes):            Left & Right eye instance.
        hw              (HardwareContext): Bonnet ADC accessor.
        state           (FrameState):      Holds manual joystick state; updated in MANUAL mode.
        sequence_player (SequencePlayer):  Required when CONTROL_MODE is SCRIPTED.
    """
    match state.control_mode:
        case ControlMode.MANUAL:
            if JOYSTICK_X_IN >= 0 and JOYSTICK_Y_IN >= 0:
                eyes.left.current.x = _adc_to_angle(hw.bonnet.channel[JOYSTICK_X_IN])
                eyes.left.current.y = _adc_to_angle(hw.bonnet.channel[JOYSTICK_Y_IN])
            else:
                dt = min(now - state.manual_last_time, 0.05) if state.manual_last_time else 0.0
                state.manual_last_time = now

                _input = state.controller_input
                _lid_mod = _input.button_a_held or _input.button_y_held

                state.manual_x = _apply_axis(state.manual_x, _input.dpad_left, _input.dpad_right, _lid_mod, dt)
                state.manual_y = _apply_axis(state.manual_y, _input.dpad_down, _input.dpad_up, _lid_mod, dt)

                eyes.left.current.x = state.manual_x
                eyes.left.current.y = state.manual_y

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

    if state.crazy_eyes:
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
    if state.eye_set == EyeSet.HYPNO:
        return  # hypno texture owns the iris mesh; skip SVG-based regen
    if abs(pupil_scale - state.prev_pupil_scale) >= scene.iris_regen_threshold:
        inter_pupil = points_interp(svg.pupil_min, svg.pupil_max, pupil_scale)
        mesh = points_mesh((None, inter_pupil, svg.iris), 4, -scene.iris_z, True)
        scene.left.iris.re_init(pts=mesh)
        scene.right.iris.re_init(pts=mesh)
        state.prev_pupil_scale = pupil_scale


def update_eye_set(now: float, state: FrameState, scene: SceneContext) -> None:
    """Advance the hypno spiral texture and apply preset changes.

    draw_scene handles which meshes are drawn based on state.eye_set.
    Texture objects are bound at init and updated in-place — no set_textures needed here.

    Args:
        now   (float):        Current timestamp in seconds.
        state (FrameState):   Reads eye_set; updates prev_eye_set.
        scene (SceneContext): hypno spiral instance.
    """
    eye_set = state.eye_set
    defn = scene.eye_set_registry.get(eye_set)
    if defn:
        defn.meshes()  # trigger lazy build on first activation
        if defn.driver:
            if EYE_SET_PRESETS:
                defn.apply_preset(state.preset_index)
            defn.driver.update(now)

    state.prev_eye_set = eye_set


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
    auto_blink = state.auto_blink

    if auto_blink and (now - state.time_of_last_blink) >= state.time_to_next_blink:
        state.time_of_last_blink = now
        duration = random.uniform(0.035, 0.06)
        if eyes.left.blink_state  == NO_BLINK: eyes.left.start_blink(now, duration)
        if eyes.right.blink_state == NO_BLINK: eyes.right.start_blink(now, duration)
        state.time_to_next_blink = duration * 3 + random.uniform(0.0, 4.0)

    eyes.left.update_blink(WINK_L_PIN,  now, wink_held=state.controller_input.wink_left)
    eyes.right.update_blink(WINK_R_PIN, now, wink_held=state.controller_input.wink_right)

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
    # MANUAL lid override — Y/A + dpad adjusts right/left lid tracking directly.
    # If EYELID_TRACKING is False, return early so positions stay in place after release.
    # If EYELID_TRACKING is True, fall through so tracking resumes when buttons are released.
    if state.control_mode == ControlMode.MANUAL:
        _STEP = 0.5 / TARGET_FPS
        con_inp = state.controller_input
        if con_inp.button_y_held:
            _adjust_lid_tracking(eyes.right, con_inp, _STEP)
        if con_inp.button_a_held:
            _adjust_lid_tracking(eyes.left, con_inp, _STEP)
        if (con_inp.button_y_held or con_inp.button_a_held) or not EYELID_TRACKING:
            return

    right_independent = state.crazy_eyes or not MIRROR_LIDS

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


def draw_scene(eyes, scene, ctx, debug_overlay, state):
    """Rotate all meshes to current eye positions and draw the frame.

    Applies X/Y rotation from eye position, optional Z rotation when ROTATE_EYES
    is set, then draws or delegates to the debug overlay.

    Args:
        eyes         (Eyes):           Left & Right eye instance.
        scene         (SceneContext):  All pi3d mesh objects.
        ctx           (DisplayContext): Display and shader context.
        debug_overlay (DebugOverlay|None): Drawn instead of the scene when DEBUG_MOVEMENT is True.
    """
    right_eye_pos = eyes.right if state.crazy_eyes else eyes.left

    eye_set = state.eye_set
    defn    = scene.eye_set_registry.get(eye_set)
    left_alt, right_alt = defn.meshes() if defn else (None, None)

    for eye, meshes, alt, convergence in (
        (eyes.left,     scene.left,  left_alt,  CONVERGENCE),
        (right_eye_pos, scene.right, right_alt, -CONVERGENCE),
    ):
        if alt:
            alt.rotateToX(eye.current.y)
            alt.rotateToY(eye.current.x + convergence)
        else:
            meshes.iris.rotateToX(eye.current.y)
            meshes.iris.rotateToY(eye.current.x + convergence)
            meshes.sclera.rotateToX(eye.current.y)
            meshes.sclera.rotateToY(eye.current.x + convergence)

    if ROTATE_EYES:
        for meshes, alt in ((scene.left, left_alt), (scene.right, right_alt)):
            if alt:
                alt.rotateToZ(ROTATE_DEGREES)
            else:
                meshes.iris.rotateToZ(ROTATE_DEGREES)
                meshes.sclera.rotateToZ(ROTATE_DEGREES)
            meshes.lids.rotateToZ(ROTATE_DEGREES)

    if DEBUG_MOVEMENT:
        debug_overlay.draw(eyes.left, ctx)
    else:
        if left_alt:
            left_alt.draw()
        else:
            scene.left.iris.draw()
            scene.left.sclera.draw()
        scene.left.lids.draw()

    if right_alt:
        right_alt.draw()
    else:
        scene.right.iris.draw()
        scene.right.sclera.draw()
    scene.right.lids.draw()
