#!/usr/bin/python

# Animated dragon eyes for Raspberry Pi using pi3d.
# Per-eye state (position, blink, tracking) is managed by EyeState in eye_state.py.
# Constants are in constants.py. Hardware is mocked for macOS dev via mock_hardware.py.

import argparse
import random
import time
import RPi.GPIO as GPIO
from xml.dom.minidom import parse
from gfxutil import *
from snake_eyes_bonnet import SnakeEyesBonnet
from eye_state import EyeState
from constants import *


# GPIO initialization ------------------------------------------------------

GPIO.setmode(GPIO.BCM)
if WINK_L_PIN >= 0: GPIO.setup(WINK_L_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
if BLINK_PIN  >= 0: GPIO.setup(BLINK_PIN , GPIO.IN, pull_up_down=GPIO.PUD_UP)
if WINK_R_PIN >= 0: GPIO.setup(WINK_R_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)


# ADC stuff ----------------------------------------------------------------

# ADC channels are read and stored in a separate thread to avoid slowdown
# from blocking operations. The animation loop can read at its leisure.

if JOYSTICK_X_IN >= 0 or JOYSTICK_Y_IN >= 0 or PUPIL_IN >= 0:
    bonnet = SnakeEyesBonnet(daemon=True)
    bonnet.setup_channel(JOYSTICK_X_IN, reverse=JOYSTICK_X_FLIP)
    bonnet.setup_channel(JOYSTICK_Y_IN, reverse=JOYSTICK_Y_FLIP)
    bonnet.setup_channel(PUPIL_IN, reverse=PUPIL_IN_FLIP)
    bonnet.start()


# Load SVG file, extract paths & convert to point lists --------------------

dom               = parse("graphics/dragon-eye.svg")
view_box          = get_view_box(dom)
pupilMinPts       = get_points(dom, "pupilMin"      , 32, True , True )
pupilMaxPts       = get_points(dom, "pupilMax"      , 32, True , True )
irisPts           = get_points(dom, "iris"          , 32, True , True )
scleraFrontPts    = get_points(dom, "scleraFront"   ,  0, False, False)
scleraBackPts     = get_points(dom, "scleraBack"    ,  0, False, False)
upperLidClosedPts = get_points(dom, "upperLidClosed", 33, False, True )
upperLidOpenPts   = get_points(dom, "upperLidOpen"  , 33, False, True )
upperLidEdgePts   = get_points(dom, "upperLidEdge"  , 33, False, False)
lowerLidClosedPts = get_points(dom, "lowerLidClosed", 33, False, False)
lowerLidOpenPts   = get_points(dom, "lowerLidOpen"  , 33, False, False)
lowerLidEdgePts   = get_points(dom, "lowerLidEdge"  , 33, False, False)


# Set up display and initialize pi3d ---------------------------------------

# DISPLAY = pi3d.Display.create(samples=4)
DISPLAY = pi3d.Display.create(w=800, h=256, samples=4, use_sdl2=True)
DISPLAY.set_background(0, 0, 0, 1) # r,g,b,alpha

# eyeRadius is the size, in pixels, at which the whole eye will be rendered onscreen. eyePosition, also pixels, is the
# offset (left or right) from the center point of the screen to the center of each eye. This geometry is explained more in-depth in fbx2.c.
eyePosition = DISPLAY.width / 4
eyeRadius = 128  # Default; use 240 for IPS screens

parser = argparse.ArgumentParser()
parser.add_argument("--radius", type=int)
args, _ = parser.parse_known_args()
if args.radius:
    eyeRadius = args.radius


# A 2D camera is used, mostly to allow for pixel-accurate eye placement, but also because perspective isn't really helpful or needed here, and
# also this allows eyelids to be handled somewhat easily as 2D planes. Line of sight is down Z axis, allowing conventional X/Y cartesion
# coords for 2D positions.
cam    = pi3d.Camera(is_3d=False, at=(0,0,0), eye=(0,0,-1000))
shader = pi3d.Shader("uv_light")
light  = pi3d.Light(lightpos=(0, -500, -500), lightamb=(0.2, 0.2, 0.2))

# Load texture maps --------------------------------------------------------

irisMap   = pi3d.Texture("graphics/dragon-iris-color.png", mipmap=False, filter=pi3d.constants.GL_LINEAR)
scleraMap = pi3d.Texture("graphics/dragon-sclera.png", mipmap=False, filter=pi3d.constants.GL_LINEAR, blend=True)
lidMap    = pi3d.Texture("graphics/lid.png", mipmap=False, filter=pi3d.constants.GL_LINEAR, blend=True)

# U/V map may be useful for debugging texture placement; not normally used
uvMap     = pi3d.Texture("graphics/uv.png", mipmap=False, filter=pi3d.constants.GL_LINEAR, blend=False, m_repeat=True)

# Initialize static geometry -----------------------------------------------

# Transform point lists to eye dimensions
points_list = [
    pupilMinPts, pupilMaxPts, irisPts, scleraFrontPts, scleraBackPts,
    upperLidClosedPts, upperLidOpenPts, upperLidEdgePts,
    lowerLidClosedPts, lowerLidOpenPts, lowerLidEdgePts
]
for points in points_list:
    scale_points(points, view_box, eyeRadius)

# Regenerating flexible object geometry (such as eyelids during blinks, or iris during pupil dilation) is CPU intensive, can noticeably slow things
# down, especially on single-core boards.  To reduce this load somewhat, determine a size change threshold below which regeneration will not occur;
# roughly equal to 1/4 pixel, since 4x4 area sampling is used.

# Determine change in pupil size to trigger iris geometry regen
irisRegenThreshold = 0.0
a = points_bounds(pupilMinPts) # Bounds of pupil at min size (in pixels)
b = points_bounds(pupilMaxPts) # " at max size

maxDist = max(abs(a[0] - b[0]), abs(a[1] - b[1]), # Determine distance of max
              abs(a[2] - b[2]), abs(a[3] - b[3])) # variance around each edge
# maxDist is motion range in pixels as pupil scales between 0.0 and 1.0.
# 1.0 / maxDist is one pixel's worth of scale range.  Need 1/4 that...
if maxDist > 0: irisRegenThreshold = 0.25 / maxDist


def lid_regen_threshold(open_pts, closed_pts):
    """
    Determine change in eyelid values needed to trigger geometry regen.
    This is done a little differently than the pupils...instead of bounds, the distance between the middle points of the open
    and closed eyelid paths is evaluated, then similar 1/4 pixel threshold is determined.
    """
    mid_open = open_pts[len(open_pts) // 2]
    mid_closed = closed_pts[len(closed_pts) // 2]
    delta_x = mid_closed[0] - mid_open[0]
    delta_y = mid_closed[1] - mid_open[1]
    sq_dist = delta_x * delta_x + delta_y * delta_y
    return 0.25 / math.sqrt(sq_dist) if sq_dist > 0 else 0.0

upperLidRegenThreshold = lid_regen_threshold(upperLidOpenPts, upperLidClosedPts)
lowerLidRegenThreshold = lid_regen_threshold(lowerLidOpenPts, lowerLidClosedPts)

# Generate initial iris meshes; vertex elements will get replaced on a per-frame basis in the main loop, this just sets up textures, etc.
rightIris = mesh_init((32, 4), (0, 0.5 / irisMap.iy), True, False)
rightIris.set_textures([irisMap])
rightIris.set_shader(shader)

# Left iris map U value is offset by 0.5; effectively a 180 degree rotation, so it's less obvious that the same texture is in use on both.
leftIris = mesh_init((32, 4), (0.5, 0.5 / irisMap.iy), True, False)
leftIris.set_textures([irisMap])
leftIris.set_shader(shader)
irisZ = zangle(irisPts, eyeRadius)[0] * 0.99 # Get iris Z depth, for later

# ----------------------------------------------------------------------------------------------------------------------
# Eyelid meshes are likewise temporary; texture coordinates are assigned here but geometry is dynamically regenerated in main loop.
leftUpperEyelid = mesh_init((33, 5), (0, 0.5 / lidMap.iy), False, True)
leftUpperEyelid.set_textures([lidMap])
leftUpperEyelid.set_shader(shader)

leftLowerEyelid = mesh_init((33, 5), (0, 0.5 / lidMap.iy), False, True)
leftLowerEyelid.set_textures([lidMap])
leftLowerEyelid.set_shader(shader)

rightUpperEyelid = mesh_init((33, 5), (0, 0.5 / lidMap.iy), False, True)
rightUpperEyelid.set_textures([lidMap])
rightUpperEyelid.set_shader(shader)

rightLowerEyelid = mesh_init((33, 5), (0, 0.5 / lidMap.iy), False, True)
rightLowerEyelid.set_textures([lidMap])
rightLowerEyelid.set_shader(shader)
# ----------------------------------------------------------------------------------------------------------------------
# Generate scleras for each eye...start with a 2D shape for lathing...
angle1 = zangle(scleraFrontPts, eyeRadius)[1] # Sclera front angle
angle2 = zangle(scleraBackPts , eyeRadius)[1] # " back angle
aRange = 180 - angle1 - angle2
pts    = []

# ADD EXTRA INITIAL POINT because of some weird behavior with Pi3D and
# VideoCore VI with the Lathed shapes we make later. This adds a *tiny*
# ring of extra polygons that simply disappear on screen. It's not
# necessary on VC4, but not harmful either, so we just do it rather
# than try to be all clever.
ca, sa = pi3d.Utility.from_polar((90 - angle1) + aRange * 0.0001)
pts.append((ca * eyeRadius, sa * eyeRadius))

for i in range(24):
    ca, sa = pi3d.Utility.from_polar((90 - angle1) - aRange * i / 23)
    pts.append((ca * eyeRadius, sa * eyeRadius))

# Scleras are generated independently (object isn't re-used) so each
# may have a different image map (heterochromia, corneal scar, or the
# same image map can be offset on one so the repetition isn't obvious).
leftEye = pi3d.Lathe(path=pts, sides=64)
leftEye.set_textures([uvMap])
leftEye.set_shader(shader)
re_axis(leftEye, 0)

rightEye = pi3d.Lathe(path=pts, sides=64)
rightEye.set_textures([scleraMap])
rightEye.set_shader(shader)
re_axis(rightEye, 0.5) # Image map offset = 180 degree rotation


# Init global stuff --------------------------------------------------------

mykeys = pi3d.Keyboard() # For capturing key presses
left_eye, right_eye = (EyeState(), EyeState())

frames = 0
beginningTime = time.time()

rightEye.positionX(-eyePosition)
rightIris.positionX(-eyePosition)
rightUpperEyelid.positionX(-eyePosition)
rightUpperEyelid.positionZ(-eyeRadius - 42)
rightLowerEyelid.positionX(-eyePosition)
rightLowerEyelid.positionZ(-eyeRadius - 42)

leftEye.positionX(eyePosition)
leftIris.positionX(eyePosition)
leftUpperEyelid.positionX(eyePosition)
leftUpperEyelid.positionZ(-eyeRadius - 42)
leftLowerEyelid.positionX(eyePosition)
leftLowerEyelid.positionZ(-eyeRadius - 42)

prevPupilScale          = -1.0 # Force regen on first frame
prevLeftUpperLidWeight, prevLeftLowerLidWeight = (0.5, 0.5)
prevRightUpperLidWeight, prevRightLowerLidWeight = (0.5, 0.5)
prevLeftUpperLidPts  = points_interp(upperLidOpenPts, upperLidClosedPts, 0.5)
prevLeftLowerLidPts  = points_interp(lowerLidOpenPts, lowerLidClosedPts, 0.5)
prevRightUpperLidPts = points_interp(upperLidOpenPts, upperLidClosedPts, 0.5)
prevRightLowerLidPts = points_interp(lowerLidOpenPts, lowerLidClosedPts, 0.5)

luRegen, llRegen, ruRegen, rlRegen = (True, True, True, True)
timeOfLastBlink, timeToNextBlink = (0.0, 1.0)


# ----------------------------------------------------------------------------------------------------------------------
# Frame -- Generate one frame of imagery
# ----------------------------------------------------------------------------------------------------------------------
def frame(p):
    global frames
    global prevPupilScale
    global prevLeftUpperLidPts, prevLeftLowerLidPts, prevRightUpperLidPts, prevRightLowerLidPts
    global prevLeftUpperLidWeight, prevLeftLowerLidWeight, prevRightUpperLidWeight, prevRightLowerLidWeight
    global luRegen, llRegen, ruRegen, rlRegen
    global timeOfLastBlink, timeToNextBlink

    DISPLAY.loop_running()
    now = time.time()
    frames += 1

    # if(now > beginningTime):
    # 	print("now > beginningTime: ", frames/(now-beginningTime))

    if JOYSTICK_X_IN >= 0 and JOYSTICK_Y_IN >= 0:
        # Eye position from analog inputs
        left_eye.current.x = -30.0 + bonnet.channel[JOYSTICK_X_IN].value * 60.0
        left_eye.current.y = -30.0 + bonnet.channel[JOYSTICK_Y_IN].value * 60.0
    else : # Autonomous eye position
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
    if abs(p - prevPupilScale) >= irisRegenThreshold:
        # Interpolate points between min and max pupil sizes
        interPupil = points_interp(pupilMinPts, pupilMaxPts, p)
        # Generate mesh between interpolated pupil and iris bounds
        mesh = points_mesh((None, interPupil, irisPts), 4, -irisZ, True)
        # Assign to both eyes
        leftIris.re_init(pts=mesh)
        rightIris.re_init(pts=mesh)
        prevPupilScale = p

# ----------------------------------------------------------------------------------------------------------------------
    # Eyelid WIP
    """
    Auto-blink timer — if enough time has passed since the last blink, trigger both eyes to close and schedule the next blink randomly.
    """
    if AUTO_BLINK and (now - timeOfLastBlink) >= timeToNextBlink:
        timeOfLastBlink = now
        duration = random.uniform(0.035, 0.06) # duration = random.uniform(0.035, 1.00)

        if left_eye.blink_state != EN_BLINKING: left_eye.start_blink(now , duration)
        if right_eye.blink_state != EN_BLINKING: right_eye.start_blink(now , duration)

        timeToNextBlink = duration * 3 + random.uniform(0.0, 4.0) # timeToNextBlink = duration * 3 + random.uniform(0.0, 5.0)

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
    newLeftUpperLidWeight = left_eye.tracking_pos + (n * (1.0 - left_eye.tracking_pos))
    newLeftLowerLidWeight = (1.0 - left_eye.tracking_pos) + (n * left_eye.tracking_pos)

    n = right_eye.blink_weight(now)
    if CRAZY_EYES:
        newRightUpperLidWeight = right_eye.tracking_pos + (n * (1.0 - right_eye.tracking_pos))
        newRightLowerLidWeight = (1.0 - right_eye.tracking_pos) + (n * right_eye.tracking_pos)
    else:
        newRightUpperLidWeight = left_eye.tracking_pos + (n * (1.0 - left_eye.tracking_pos))
        newRightLowerLidWeight = (1.0 - left_eye.tracking_pos) + (n * left_eye.tracking_pos)

# ----------------------------------------------------------------------------------------------------------------------
    def update_lid(mesh, open_pts, closed_pts, edge_pts, new_weight, prev_weight, prev_pts, regen, threshold, flip):
        if regen or abs(new_weight - prev_weight) >= threshold:
            new_pts = points_interp(open_pts, closed_pts, new_weight)
            if new_weight > prev_weight:
                mesh.re_init(pts=points_mesh((edge_pts, prev_pts, new_pts), 5, 0, flip))
            else:
                mesh.re_init(pts=points_mesh((edge_pts, new_pts, prev_pts), 5, 0, flip))
            return new_pts, new_weight, True
        return prev_pts, prev_weight, False

    prevLeftUpperLidPts, prevLeftUpperLidWeight, luRegen = update_lid(
        leftUpperEyelid, upperLidOpenPts, upperLidClosedPts, upperLidEdgePts, newLeftUpperLidWeight,
        prevLeftUpperLidWeight, prevLeftUpperLidPts, luRegen, upperLidRegenThreshold, False
    )
    prevLeftLowerLidPts, prevLeftLowerLidWeight, llRegen = update_lid(
        leftLowerEyelid, lowerLidOpenPts, lowerLidClosedPts, lowerLidEdgePts, newLeftLowerLidWeight,
        prevLeftLowerLidWeight, prevLeftLowerLidPts, llRegen, lowerLidRegenThreshold, False
    )

    prevRightUpperLidPts, prevRightUpperLidWeight, ruRegen = update_lid(
        rightUpperEyelid, upperLidOpenPts, upperLidClosedPts, upperLidEdgePts, newRightUpperLidWeight,
        prevRightUpperLidWeight, prevRightUpperLidPts, ruRegen, upperLidRegenThreshold, True
    )
    prevRightLowerLidPts, prevRightLowerLidWeight, rlRegen = update_lid(
        rightLowerEyelid, lowerLidOpenPts, lowerLidClosedPts, lowerLidEdgePts, newRightLowerLidWeight,
        prevRightLowerLidWeight, prevRightLowerLidPts, rlRegen, lowerLidRegenThreshold, True
    )

# ----------------------------------------------------------------------------------------------------------------------
    # Left eye (on screen right)
    leftIris.rotateToX(left_eye.current.y)
    leftIris.rotateToY(left_eye.current.x + CONVERGENCE)
    leftEye.rotateToX(left_eye.current.y)
    leftEye.rotateToY(left_eye.current.x + CONVERGENCE)

    # Right eye (on screen left)
    if CRAZY_EYES:
        rightIris.rotateToX(right_eye.current.y)
        rightIris.rotateToY(right_eye.current.x - CONVERGENCE)
        rightEye.rotateToX(right_eye.current.y)
        rightEye.rotateToY(right_eye.current.x - CONVERGENCE)
    else:
        rightIris.rotateToX(left_eye.current.y)
        rightIris.rotateToY(left_eye.current.x - CONVERGENCE)
        rightEye.rotateToX(left_eye.current.y)
        rightEye.rotateToY(left_eye.current.x - CONVERGENCE)

    # Flip Eyes Horizontally
    if FLIP_EYES:
        leftIris.rotateToZ(180)
        leftEye.rotateToZ(180)
        leftUpperEyelid.rotateToZ(180)
        leftLowerEyelid.rotateToZ(180)

        rightIris.rotateToZ(180)
        rightEye.rotateToZ(180)
        rightUpperEyelid.rotateToZ(180)
        rightLowerEyelid.rotateToZ(180)

    leftIris.draw()
    leftEye.draw()
    leftUpperEyelid.draw()
    leftLowerEyelid.draw()

    rightIris.draw()
    rightEye.draw()
    rightUpperEyelid.draw()
    rightLowerEyelid.draw()

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
            dt = time.time() - start_time
            if dt >= duration: break
            pupil_scale_value = start_value + dv * dt / duration
            pupil_scale_value = max(PUPIL_MIN, min(pupil_scale_value, PUPIL_MAX))
            frame(pupil_scale_value) # Draw frame w/interim pupil scale value

# ----------------------------------------------------------------------------------------------------------------------
# MAIN LOOP -- runs continuously
# ----------------------------------------------------------------------------------------------------------------------
def main():

    current_pupil_scale = PUPIL_SCALE

    while True:
        if PUPIL_IN < 0:  # Fractal auto pupil scale
            pupil_value = random.random()
            split_pupil(current_pupil_scale, pupil_value, 4.0, 1.0)

        else:  # Pupil scale from sensor
            pupil_value = bonnet.channel[PUPIL_IN].value
            # If you need to calibrate PUPIL_MIN and MAX, add a 'print v' here for testing.

            pupil_value = max(PUPIL_MIN, min(pupil_value, PUPIL_MAX))
            pupil_value = (pupil_value - PUPIL_MIN) / (PUPIL_MAX - PUPIL_MIN)  # Scale to 0.0 to 1.0:

            if PUPIL_SMOOTH > 0:
                pupil_value = ((current_pupil_scale * (PUPIL_SMOOTH - 1) + pupil_value) / PUPIL_SMOOTH)

            frame(pupil_value)

        current_pupil_scale = pupil_value

        k = mykeys.read()
        if k == 27:
            mykeys.close()
            DISPLAY.stop()
            exit(0)
