import math
import platform
from xml.dom.minidom import parse

import RPi.GPIO as GPIO
import pi3d

from constants import (WINK_L_PIN, BLINK_PIN, WINK_R_PIN, JOYSTICK_X_IN, JOYSTICK_Y_IN, PUPIL_IN,
                       TRACKING_MODE, CONTROL_MODE, SVG_PATH, IRIS_PATH, SCLERA_PATH, EYE_LID, UV_MAP)
from eye import EyeLidMesh
from eye_sets.base import EyeSetInitializer
from gfxutil import get_view_box, get_points, re_axis, zangle, scale_points, points_bounds, mesh_init
from models import LidPoints, EyeMeshes, SvgPoints, SceneContext, HardwareContext, DisplayContext
from sensor import SensorReader
from snake_eyes_bonnet import SnakeEyesBonnet


def init_ahrs_sensor() -> SensorReader:
    """Initialize Attitude & Heading Reference System (BNO055 AHRS reader).

    Selection order:
      1. On macOS / mock: use SERIAL_PORT if set, else auto-detect via WHO probe
      2. On hardware → SensorReader (I²C, direct BNO055).

    Resumes immediately if TRACKING_MODE is GYRO; otherwise starts suspended
    until the mode is switched at runtime.
    """
    if platform.system() == "Darwin": # True on macOS dev machine; False on Raspberry Pi
        from mock.bno055_reader import SerialSensorReader
        selected_sensor = SerialSensorReader()
    else:
        from sensor import BNO055SensorReader
        selected_sensor = BNO055SensorReader()

    selected_sensor.start()

    if CONTROL_MODE == CONTROL_MODE.TRACKING and TRACKING_MODE == TRACKING_MODE.GYRO:
        selected_sensor.resume()

    return selected_sensor


def init_gpio():
    """
    GPIO initialization
    :return:
    """
    GPIO.setmode(GPIO.BCM)
    if WINK_L_PIN >= 0: GPIO.setup(WINK_L_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    if BLINK_PIN >= 0: GPIO.setup(BLINK_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    if WINK_R_PIN >= 0: GPIO.setup(WINK_R_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def init_adc() -> HardwareContext:
    """
    ADC channels are read and stored in a separate thread to avoid slowdown from blocking operations. The animation loop can read at its leisure.

    :return:
    """
    bonnet = None

    if JOYSTICK_X_IN >= 0 or JOYSTICK_Y_IN >= 0 or PUPIL_IN >= 0:
        bonnet = SnakeEyesBonnet(daemon=True)
        bonnet.setup_channel(JOYSTICK_X_IN, reverse=False)
        bonnet.setup_channel(JOYSTICK_Y_IN, reverse=False)
        bonnet.setup_channel(PUPIL_IN, reverse=False)
        bonnet.start()

    return HardwareContext(bonnet=bonnet)


def init_display(radius: int | None) -> DisplayContext:

    # Set up display and initialize pi3d ---------------------------------------
    if platform.system() == "Darwin": # True on macOS dev machine; False on Raspberry Pi
        display = pi3d.Display.create(w=800, h=256, samples=4, use_sdl2=True)
    else:  # Raspberry Pi / Linux
        display = pi3d.Display.create(samples=4)

    display.set_background(0, 0, 0, 1)  # r,g,b,alpha

    # eyeRadius is the size, in pixels, at which the whole eye will be rendered onscreen. eyePosition, also pixels, is the
    # offset (left or right) from the center point of the screen to the center of each eye. This geometry is explained more in-depth in fbx2.c.
    eye_position = display.width / 4
    eye_radius = radius if radius is not None else 128 # Default; use 240 for IPS screens

    # A 2D camera is used, mostly to allow for pixel-accurate eye placement, but also because perspective isn't really helpful or needed here, and
    # also this allows eyelids to be handled somewhat easily as 2D planes. Line of sight is down Z axis, allowing conventional X/Y cartesion
    # coords for 2D positions.

    return DisplayContext(
        display=display, eye_radius=eye_radius, eye_position=eye_position,
        cam=pi3d.Camera(is_3d=False, at=(0, 0, 0), eye=(0, 0, -1000)),
        shader=pi3d.Shader("uv_light"),
        light=pi3d.Light(lightpos=(0, -500, -500), lightamb=(0.2, 0.2, 0.2))
    )


def init_svg() -> SvgPoints:
    # Load SVG file, extract paths & convert to point lists --------------------
    dom = parse(SVG_PATH)

    return SvgPoints(
        view_box=get_view_box(dom),
        pupil_min=get_points(    dom, "pupilMin",       32, True,  True),
        pupil_max=get_points(    dom, "pupilMax",       32, True,  True),
        iris=get_points(         dom, "iris",           32, True,  True),
        sclera_front=get_points( dom, "scleraFront",     0, False, False),
        sclera_back=get_points(  dom, "scleraBack",      0, False, False),
        upper_lid=LidPoints(
            closed=get_points(   dom, "upperLidClosed", 33, False, True),
            open=get_points(     dom, "upperLidOpen",   33, False, True),
            edge=get_points(     dom, "upperLidEdge",   33, False, False)
        ),
        lower_lid=LidPoints(
            closed=get_points(   dom, "lowerLidClosed", 33, False, False),
            open=get_points(     dom, "lowerLidOpen",   33, False, False),
            edge=get_points(     dom, "lowerLidEdge",   33, False, False)
        )
    )

def _lid_regen_threshold(open_pts, closed_pts):
    """
    Calculate the eyelid geometry regeneration threshold based on point displacement.

    Determines the minimum change in eyelid weight (interpolation parameter) required to trigger
    a mesh geometry regeneration. This threshold is derived from the Euclidean distance between
    the middle points of the open and closed eyelid paths. A smaller distance results in a
    larger threshold value, reducing unnecessary regenerations for minor adjustments.

    Args:
        open_pts: A sequence of point tuples representing the eyelid path in the open position.
                 Each point is expected to be a tuple of (x, y) coordinates.
        closed_pts: A sequence of point tuples representing the eyelid path in the closed position.
                   Each point is expected to be a tuple of (x, y) coordinates.

    Returns:
        float: The regeneration threshold value. Represents 1/4 pixel of motion range normalized
               by the distance between open and closed positions. Returns 0.0 if the distance is zero.

    Notes:
        - Uses the middle point of each path (at index len(pts) // 2) to estimate the path displacement.
        - The 0.25 factor corresponds to 1/4 pixel, which aligns with the 4x4 area sampling used
          in the rendering pipeline.
        - This approach differs from iris threshold calculation, which uses bounding box analysis.

    Example:
        >>> open_path = [(0, 10), (5, 15), (10, 10)]
        >>> closed_path = [(0, 5), (5, 5), (10, 5)]
        >>> threshold = _lid_regen_threshold(open_path, closed_path)
        # threshold is approximately 0.05 (0.25 / 5.0 distance)
    """
    # Extract middle points from each path to represent overall displacement
    mid_open = open_pts[len(open_pts) // 2]
    mid_closed = closed_pts[len(closed_pts) // 2]

    # Calculate Euclidean distance between the middle points
    distance = math.hypot(mid_closed[0] - mid_open[0], mid_closed[1] - mid_open[1])

    # Return threshold scaled by 1/4 pixel, or 0.0 if distance is negligible
    return 0.25 / distance if distance > 0 else 0.0

def init_scene(svg: SvgPoints, ctx: DisplayContext) -> SceneContext:

    # Load texture maps --------------------------------------------------------
    iris_map   = pi3d.Texture(IRIS_PATH,   mipmap=False, filter=pi3d.constants.GL_LINEAR)
    sclera_map = pi3d.Texture(SCLERA_PATH, mipmap=False, filter=pi3d.constants.GL_LINEAR, blend=True)
    lid_map    = pi3d.Texture(EYE_LID,     mipmap=False, filter=pi3d.constants.GL_LINEAR, blend=True)

    # U/V map may be useful for debugging texture placement; not normally used
    uv_map     = pi3d.Texture(UV_MAP,      mipmap=False, filter=pi3d.constants.GL_LINEAR, blend=False, m_repeat=True)

    # Initialize static geometry -----------------------------------------------

    # Transform point lists to eye dimensions
    points_list = [
        svg.pupil_min, svg.pupil_max, svg.iris, svg.sclera_front, svg.sclera_back,
        svg.upper_lid.closed, svg.upper_lid.open, svg.upper_lid.edge,
        svg.lower_lid.closed, svg.lower_lid.open, svg.lower_lid.edge
    ]
    for points in points_list:
        scale_points(points, svg.view_box, ctx.eye_radius)

    # Regenerating flexible object geometry (such as eyelids during blinks, or iris during pupil dilation) is CPU intensive, can noticeably slow things
    # down, especially on single-core boards.  To reduce this load somewhat, determine a size change threshold below which regeneration will not occur;
    # roughly equal to 1/4 pixel, since 4x4 area sampling is used.

    # Determine change in pupil size to trigger iris geometry regen
    iris_regen_threshold = 0.0
    a, b = points_bounds(svg.pupil_min), points_bounds(svg.pupil_max)  # Bounds of pupil at min size (in pixels) at max size
    max_dist = max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]), abs(a[3] - b[3]))  # Determine distance of max variance around each edge

    # maxDist is motion range in pixels as pupil scales between 0.0 and 1.0.
    # 1.0 / maxDist is one pixel's worth of scale range.  Need 1/4 that...
    if max_dist > 0: iris_regen_threshold = 0.25 / max_dist

    upper_lid_regen_threshold = _lid_regen_threshold(svg.upper_lid.open, svg.upper_lid.closed)
    lower_lid_regen_threshold = _lid_regen_threshold(svg.lower_lid.open, svg.lower_lid.closed)

    # Generate initial iris meshes; vertex elements will get replaced on a per-frame basis in the main loop, this just sets up textures, etc.
    right_iris = mesh_init((32, 4), (0, 0.5 / iris_map.iy), True, False)
    right_iris.set_textures([iris_map])
    right_iris.set_shader(ctx.shader)
    right_iris.positionX(-ctx.eye_position)

    # Left iris map U value is offset by 0.5; effectively a 180 degree rotation, so it's less obvious that the same texture is in use on both.
    left_iris = mesh_init((32, 4), (0.5, 0.5 / iris_map.iy), True, False)
    left_iris.set_textures([iris_map])
    left_iris.set_shader(ctx.shader)
    left_iris.positionX(ctx.eye_position)

    iris_z_angle = zangle(svg.iris, ctx.eye_radius)[0] * 0.99  # Get iris Z depth, for later

    # ----------------------------------------------------------------------------------------------------------------------
    # Eyelid meshes are likewise temporary; texture coordinates are assigned here but geometry is dynamically regenerated in main loop.
    left_lids = EyeLidMesh(lid_map, ctx.shader, ctx.eye_position, ctx.eye_radius)
    right_lids = EyeLidMesh(lid_map, ctx.shader, -ctx.eye_position, ctx.eye_radius)

    # ----------------------------------------------------------------------------------------------------------------------
    # Generate scleras for each eye...start with a 2D shape for lathing...
    angle1 = zangle(svg.sclera_front, ctx.eye_radius)[1]  # Sclera front angle
    angle2 = zangle(svg.sclera_back, ctx.eye_radius)[1]  # " back angle
    angle_range = 180 - angle1 - angle2
    pts = []

    # ADD EXTRA INITIAL POINT because of some weird behavior with Pi3D and VideoCore VI with the Lathed shapes we make
    # later. This adds a *tiny* ring of extra polygons that simply disappear on screen. It's not necessary on VC4, but
    # not harmful either, so we just do it rather than try to be all clever.
    ca, sa = pi3d.Utility.from_polar((90 - angle1) + angle_range * 0.0001)
    pts.append((ca * ctx.eye_radius, sa * ctx.eye_radius))

    for i in range(24):
        ca, sa = pi3d.Utility.from_polar((90 - angle1) - angle_range * i / 23)
        pts.append((ca * ctx.eye_radius, sa * ctx.eye_radius))

    # Scleras are generated independently (object isn't re-used) so each may have a different image map (heterochromia,
    # corneal scar, or the same image map can be offset on one so the repetition isn't obvious).
    left_sclera = pi3d.Lathe(path=pts, sides=64, x=ctx.eye_position)
    left_sclera.set_textures([sclera_map])
    # left_sclera.set_textures([uv_map]) # debug option
    left_sclera.set_shader(ctx.shader)
    re_axis(left_sclera, 0)

    right_sclera = pi3d.Lathe(path=pts, sides=64, x=-ctx.eye_position)
    right_sclera.set_textures([sclera_map])
    right_sclera.set_shader(ctx.shader)
    re_axis(right_sclera, 0.5)  # Image map offset = 180 degree rotation

    # ── EyeSet registry — each initializer owns its own mesh factory and driver ──
    eye_set_registry = {}
    for _init in EyeSetInitializer.all():
        eye_set_registry.update(_init.register(ctx, svg))

    return SceneContext(
        left=EyeMeshes(iris=left_iris, sclera=left_sclera, lids=left_lids),
        right=EyeMeshes(iris=right_iris, sclera=right_sclera, lids=right_lids),
        iris_z=iris_z_angle, iris_regen_threshold=iris_regen_threshold,
        upper_lid_regen_threshold=upper_lid_regen_threshold, lower_lid_regen_threshold=lower_lid_regen_threshold,
        eye_set_registry=eye_set_registry,
    )
