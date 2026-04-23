"""
pipeline/stages.py

Free pipeline-stage functions and their private helpers.

Each function advances one aspect of the frame: eye positions, iris mesh,
eye-set texture, blinks, lid tracking, lid meshes. All stable context is
bundled into _StageCtx so callers pass one object instead of many args.
"""

import random
from dataclasses import dataclass

import RPi.GPIO as GPIO

from bluetooth.constants import AXIS_SPEED, AXIS_SPRING
from constants import *
from debug_overlay import DebugOverlay
from eye import SequencePlayer, Eye, Eyes
from gfxutil import points_interp, points_mesh
from models import DisplayContext, EyeMeshes, HardwareContext, SceneContext, SvgPoints
from pipeline.state import AHRSState, FrameState, LidChannels
from sensor import SensorReader


# ── Stable context bundle ─────────────────────────────────────────────────────

@dataclass(slots=True)
class _StageCtx:
    """All stable pipeline references bundled into one object.

    Built once in FramePipeline.__init__ and passed to every stage function.
    Only FrameState (mutable, per-frame) and now/pupil_scale (scalars) are
    passed separately.
    """
    eyes:           Eyes
    hw:             HardwareContext
    scene:          SceneContext
    svg:            SvgPoints
    seq:            SequencePlayer
    sensor:         SensorReader
    lid_channels:   LidChannels | None
    debug_overlay:  DebugOverlay | None
    display_ctx:    DisplayContext


# ── Private helpers ───────────────────────────────────────────────────────────

def _blend_lid(t, n):
    """Blend tracking position with blink weight."""
    return t + n * (1.0 - t)


def _adc_to_angle(ch):
    return -30.0 + ch.value * 60.0


def _adjust_lid_tracking(eye: Eye, pad_input, step: float):
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
        return min(30.0, value + AXIS_SPEED * dt)
    elif value > 0:
        return max(0.0, value - AXIS_SPRING * dt)
    elif value < 0:
        return min(0.0, value + AXIS_SPRING * dt)
    return value


def _update_ahrs_position(now: float, eyes: Eyes, sensor: SensorReader, ahrs: AHRSState, dt: float):
    """Drive eye position from BNO055 head orientation.

    Computes delta from a recalibrating neutral reference so sustained head tilt
    is handled naturally. Neutral updates after RECAL_DELAY seconds of stillness
    (angular velocity below STILL_THRESHOLD).
    """
    yaw, pitch, _ = sensor.euler
    velocity = sensor.angular_velocity

    if velocity < STILL_THRESHOLD:
        if ahrs.still_since == 0.0:
            ahrs.still_since = now
        elif (now - ahrs.still_since) >= RECAL_DELAY:
            ahrs.neutral_yaw   = yaw
            ahrs.neutral_pitch = pitch
    else:
        ahrs.still_since = 0.0

    yaw_delta   = ((yaw   - ahrs.neutral_yaw)   + 180.0) % 360.0 - 180.0
    pitch_delta = ((pitch - ahrs.neutral_pitch) +  90.0) % 180.0 -  90.0

    target_x = max(-30.0, min(30.0, yaw_delta   * SENSITIVITY_X))
    target_y = max(-30.0, min(30.0, pitch_delta * SENSITIVITY_Y))

    t = min(1.0, RETURN_SPEED * dt)
    eyes.left.current.x += (target_x - eyes.left.current.x) * t
    eyes.left.current.y += (target_y - eyes.left.current.y) * t


def _update_lid(now: float, eye: Eye, eye_meshes: EyeMeshes, svg: SvgPoints, scene: SceneContext, flip: bool):
    """Blend blink weight with tracking position and regenerate lid meshes for one eye.

    Args:
        now        (float):        Current timestamp in seconds.
        eye        (Eye):          Eye instance (provides tracking_pos and blink_weight).
        eye_meshes (EyeMeshes):    pi3d mesh objects for this eye (scene.left or scene.right).
        svg        (SvgPoints):    Lid point lists.
        scene      (SceneContext): Provides regen thresholds.
        flip       (bool):         True for right eye (mirrors UV orientation).
    """
    n = eye.blink_weight(now)
    eye.lids.upper.update(eye_meshes.lids.upper, svg.upper_lid, _blend_lid(eye.upper_tracking_pos, n), scene.upper_lid_regen_threshold, flip)
    eye.lids.lower.update(eye_meshes.lids.lower, svg.lower_lid, _blend_lid(eye.lower_tracking_pos, n), scene.lower_lid_regen_threshold, flip)


# ── Pipeline stages ───────────────────────────────────────────────────────────

def update_eye_positions(ctx: _StageCtx, now: float, state: FrameState):
    """Advance left (and optionally right) eye position for this frame.

    The active CONTROL_MODE determines the source:
        MANUAL   — ADC joystick channels from the bonnet
        SCRIPTED — SequencePlayer keyframe playback
        RANDOM   — autonomous saccade state machine
        TRACKING — external sensor tracking input
    """
    match state.control_mode:
        case ControlMode.MANUAL:
            if JOYSTICK_X_IN >= 0 and JOYSTICK_Y_IN >= 0:
                ctx.eyes.left.current.x = _adc_to_angle(ctx.hw.bonnet.channel[JOYSTICK_X_IN])
                ctx.eyes.left.current.y = _adc_to_angle(ctx.hw.bonnet.channel[JOYSTICK_Y_IN])
            else:
                dt = min(now - state.manual_last_time, 0.05) if state.manual_last_time else 0.0
                state.manual_last_time = now

                _input = state.controller_input
                _lid_mod = _input.button_a_held or _input.button_y_held

                state.manual_x = _apply_axis(state.manual_x, _input.dpad_left, _input.dpad_right, _lid_mod, dt)
                state.manual_y = _apply_axis(state.manual_y, _input.dpad_down, _input.dpad_up, _lid_mod, dt)

                ctx.eyes.left.current.x = state.manual_x
                ctx.eyes.left.current.y = state.manual_y

        case ControlMode.SCRIPTED:
            if ctx.seq:
                if KEYFRAME_STEP:
                    pressed = GPIO.input(BLINK_PIN) == GPIO.LOW
                    if pressed and not state.controller_input.step_key_held:
                        ctx.seq.step()
                    state.controller_input.step_key_held = pressed
                ctx.seq.update(ctx.eyes.left, now)

        case ControlMode.RANDOM:
            ctx.eyes.left.update_position(now)

        case ControlMode.TRACKING:
            if TRACKING_MODE == TrackingMode.GYRO and ctx.sensor is not None:
                dt = min(now - state.ahrs.prev_time, 0.05) if state.ahrs.prev_time else 1.0 / TARGET_FPS
                state.ahrs.prev_time = now
                _update_ahrs_position(now, ctx.eyes, ctx.sensor, state.ahrs, dt)

    if state.crazy_eyes:
        ctx.eyes.right.update_position(now)


def update_iris(ctx: _StageCtx, pupil_scale: float, state: FrameState):
    """Regenerate iris mesh if pupil scale has changed by at least one regen threshold.

    Interpolates between pupil_min and pupil_max point lists, builds a 3D mesh,
    and pushes it to both eye iris objects. Skipped if the change is below the
    scene's iris_regen_threshold (¼-pixel granularity).
    """
    if state.eye_set == EyeSet.HYPNO:
        return  # hypno texture owns the iris mesh; skip SVG-based regen
    if abs(pupil_scale - state.prev_pupil_scale) >= ctx.scene.iris_regen_threshold:
        inter_pupil = points_interp(ctx.svg.pupil_min, ctx.svg.pupil_max, pupil_scale)
        mesh = points_mesh((None, inter_pupil, ctx.svg.iris), 4, -ctx.scene.iris_z, True)
        ctx.scene.left.iris.re_init(pts=mesh)
        ctx.scene.right.iris.re_init(pts=mesh)
        state.prev_pupil_scale = pupil_scale


def update_eye_set(ctx: _StageCtx, now: float, state: FrameState):
    """Advance the hypno spiral texture and apply preset changes.

    draw_scene handles which meshes are drawn based on state.eye_set.
    Texture objects are bound at init and updated in-place — no set_textures needed here.
    """
    eye_set = state.eye_set
    defn = ctx.scene.eye_set_registry.get(eye_set)
    if defn:
        defn.meshes()  # trigger lazy build on first activation
        if defn.driver:
            if EYE_SET_PRESETS:
                defn.apply_preset(state.preset_index)
            defn.driver.update(now)

    state.prev_eye_set = eye_set


def update_blinks(ctx: _StageCtx, now: float, state: FrameState):
    """Advance blink state machines and fire the auto-blink timer.

    Handles three blink sources:
        - Auto-blink timer (AUTO_BLINK constant), or per-keyframe override
        - BLINK_PIN GPIO (blinks both eyes while held)
        - Per-eye wink pins (WINK_L_PIN / WINK_R_PIN)
    """
    if state.auto_blink and (now - state.time_of_last_blink) >= state.time_to_next_blink:
        state.time_of_last_blink = now
        duration = random.uniform(0.035, 0.06)
        if ctx.eyes.left.blink_state  == NO_BLINK: ctx.eyes.left.start_blink(now, duration)
        if ctx.eyes.right.blink_state == NO_BLINK: ctx.eyes.right.start_blink(now, duration)
        state.time_to_next_blink = duration * 3 + random.uniform(0.0, 4.0)

    ctx.eyes.left.update_blink(WINK_L_PIN,  now, wink_held=state.controller_input.wink_left)
    ctx.eyes.right.update_blink(WINK_R_PIN, now, wink_held=state.controller_input.wink_right)

    if BLINK_PIN >= 0 and not KEYFRAME_STEP and GPIO.input(BLINK_PIN) == GPIO.LOW:
        duration = random.uniform(0.035, 0.06)
        if ctx.eyes.left.blink_state  == NO_BLINK: ctx.eyes.left.start_blink(now, duration)
        if ctx.eyes.right.blink_state == NO_BLINK: ctx.eyes.right.start_blink(now, duration)


def update_lid_tracking(ctx: _StageCtx, state: FrameState):
    """Resolve lid tracking positions for both eyes.

    Priority (highest → lowest):
        1. eyelid_tracking=True  — dynamic tracking from eye position
        2. lid_weight authored   — interpolated scripted weights
        3. lid_channels preview  — macOS dev keyboard channels
        4. Fixed defaults        — 0.4 upper / 0.6 lower

    eyelid_tracking overrides lid_weight when both are set on a keyframe.
    """
    # MANUAL lid override — Y/A + dpad adjusts right/left lid tracking directly.
    # If EYELID_TRACKING is False, return early so positions stay in place after release.
    # If EYELID_TRACKING is True, fall through so tracking resumes when buttons are released.
    if state.control_mode == ControlMode.MANUAL:
        _STEP = 0.5 / TARGET_FPS
        con_inp = state.controller_input
        if con_inp.button_y_held:
            _adjust_lid_tracking(ctx.eyes.right, con_inp, _STEP)
        if con_inp.button_a_held:
            _adjust_lid_tracking(ctx.eyes.left, con_inp, _STEP)
        if (con_inp.button_y_held or con_inp.button_a_held) or not EYELID_TRACKING:
            return

    right_independent = state.crazy_eyes or not MIRROR_LIDS

    lid_weight  = ctx.seq.current_lid_weight if ctx.seq else None
    do_tracking = ctx.seq.eyelid_tracking    if ctx.seq else EYELID_TRACKING

    if do_tracking:
        if ctx.lid_channels:
            left_upper_bias  = ctx.lid_channels.left_upper.value
            left_lower_bias  = ctx.lid_channels.left_lower.value
            right_upper_bias = ctx.lid_channels.right_upper.value if not MIRROR_LIDS else left_upper_bias
            right_lower_bias = ctx.lid_channels.right_lower.value if not MIRROR_LIDS else left_lower_bias
        else:
            left_upper_bias = right_upper_bias = 0.4
            left_lower_bias = right_lower_bias = 0.6

        ctx.eyes.left.update_tracking(left_upper_bias, left_lower_bias)
        if right_independent:
            ctx.eyes.right.update_tracking(right_upper_bias, right_lower_bias)

    elif lid_weight is not None:
        # Scripted weights — assign directly, no smoothing
        lu, ll = lid_weight["left"]
        ru, rl = lid_weight["right"]
        ctx.eyes.left.upper_tracking_pos = lu
        ctx.eyes.left.lower_tracking_pos = ll
        if right_independent:
            ctx.eyes.right.upper_tracking_pos = ru
            ctx.eyes.right.lower_tracking_pos = rl
    else:
        if ctx.lid_channels:
            ctx.eyes.left.upper_tracking_pos  = ctx.lid_channels.left_upper.value
            ctx.eyes.left.lower_tracking_pos  = ctx.lid_channels.left_lower.value
            ctx.eyes.right.upper_tracking_pos = ctx.lid_channels.left_upper.value if MIRROR_LIDS else ctx.lid_channels.right_upper.value
            ctx.eyes.right.lower_tracking_pos = ctx.lid_channels.left_lower.value if MIRROR_LIDS else ctx.lid_channels.right_lower.value

    if not right_independent:
        ctx.eyes.right.upper_tracking_pos = ctx.eyes.left.upper_tracking_pos
        ctx.eyes.right.lower_tracking_pos = ctx.eyes.left.lower_tracking_pos


def update_lids(ctx: _StageCtx, now: float):
    """Blend blink weight into lid weights and regenerate lid meshes for both eyes."""
    _update_lid(now, ctx.eyes.left,  ctx.scene.left,  ctx.svg, ctx.scene, False)
    _update_lid(now, ctx.eyes.right, ctx.scene.right, ctx.svg, ctx.scene, True)


def draw_scene(ctx: _StageCtx, state: FrameState):
    """Rotate all meshes to current eye positions and draw the frame.

    Applies X/Y rotation from eye position, optional Z rotation when ROTATE_EYES
    is set, then draws or delegates to the debug overlay.
    """
    right_eye_pos = ctx.eyes.right if state.crazy_eyes else ctx.eyes.left

    eye_set = state.eye_set
    defn    = ctx.scene.eye_set_registry.get(eye_set)
    left_alt, right_alt = defn.meshes() if defn else (None, None)

    for eye, meshes, alt, convergence in (
        (ctx.eyes.left, ctx.scene.left,  left_alt,   CONVERGENCE),
        (right_eye_pos, ctx.scene.right, right_alt, -CONVERGENCE),
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
        for meshes, alt in ((ctx.scene.left, left_alt), (ctx.scene.right, right_alt)):
            if alt:
                alt.rotateToZ(ROTATE_DEGREES)
            else:
                meshes.iris.rotateToZ(ROTATE_DEGREES)
                meshes.sclera.rotateToZ(ROTATE_DEGREES)
            meshes.lids.rotateToZ(ROTATE_DEGREES)

    if DEBUG_MOVEMENT:
        ctx.debug_overlay.draw(ctx.eyes.left, ctx.display_ctx)
    else:
        if left_alt:
            left_alt.draw()
        else:
            ctx.scene.left.iris.draw()
            ctx.scene.left.sclera.draw()
        ctx.scene.left.lids.draw()

    if right_alt:
        right_alt.draw()
    else:
        ctx.scene.right.iris.draw()
        ctx.scene.right.sclera.draw()
    ctx.scene.right.lids.draw()
