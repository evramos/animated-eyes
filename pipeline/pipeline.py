"""
pipeline/pipeline.py

FramePipeline — owns all stable rendering context and wraps each pipeline stage
as a method. Constructed once at startup; FrameState is the only thing that
changes frame to frame.

Stage order (called by main.py each frame):
    update_eye_positions  → advance eye position for this frame
    update_iris           → regen iris mesh if pupil scale changed (skipped in HYPNO)
    update_eye_set        → advance hypno spiral texture + sclera fade transition
    update_blinks         → advance blink state machines + auto-blink timer
    update_lid_tracking   → resolve lid tracking positions for both eyes
    update_lids           → blend blink weight into lid weights + regen lid meshes
    draw_scene            → rotate all meshes to current positions and draw
"""

from constants import DEBUG_MOVEMENT, SEQUENCE_FILE
from diagnostics.debug_overlay import DebugOverlay
from eye import SequencePlayer, Eyes
from init import init_gpio, init_adc, init_svg, init_display, init_scene, init_ahrs_sensor
from models import SvgPoints, DisplayContext
from pipeline.stages import (_StageCtx, update_eye_positions, update_iris, update_eye_set, update_blinks,
                             update_lid_tracking, update_lids, draw_scene)
from pipeline.state import FrameState, LidChannels
from sensor import SensorReader


class FramePipeline:
    """Owns all stable rendering context and wraps each pipeline stage as a method.

    Constructed once at startup. FrameState is passed per-call — it is the only
    thing that changes frame to frame; everything else lives here.

    Exposed attributes (needed by main.py / start_gamepad):
        eyes, hw, seq, sensor
    """

    def __init__(self, radius: int | None = None):

        init_gpio()
        self._svg:     SvgPoints       = init_svg()
        self._ctx:     DisplayContext  = init_display(radius)
        self.eyes:     Eyes            = Eyes(self._svg)
        self.seq:      SequencePlayer  = SequencePlayer(SEQUENCE_FILE)
        self.sensor:   SensorReader    = init_ahrs_sensor()

        try:
            from mock.bonnet import Channel as _Channel, Bonnet as _MockBonnet
            _lid_channels = LidChannels(
                left_upper  = _Channel(**_MockBonnet._CHANNEL_KEYS[5]),
                left_lower  = _Channel(**_MockBonnet._CHANNEL_KEYS[6]),
                right_upper = _Channel(**_MockBonnet._CHANNEL_KEYS[3]),
                right_lower = _Channel(**_MockBonnet._CHANNEL_KEYS[4]),
            )
        except ImportError:
            _lid_channels = None

        self._c = _StageCtx(
            eyes           = self.eyes,
            hw             = init_adc(),
            scene          = init_scene(self._svg, self._ctx),
            svg            = self._svg,
            seq            = self.seq,
            sensor         = self.sensor,
            lid_channels   = _lid_channels,
            debug_overlay  = DebugOverlay(self._ctx) if DEBUG_MOVEMENT else None,
            display_ctx    = self._ctx,
        )


    # ── Display lifecycle ─────────────────────────────────────────────────────

    def loop_display_running(self) -> None:
        """Advance the pi3d display loop. Call once per frame before any drawing."""
        self._ctx.display.loop_running()

    def display_stop(self) -> None:
        """Shut down the pi3d display cleanly."""
        self._ctx.display.stop()

    # ── Pipeline stages ───────────────────────────────────────────────────────

    def update_eye_positions(self, now: float, state: FrameState) -> None:
        update_eye_positions(self._c, now, state)

    def update_iris(self, pupil_scale: float, state: FrameState) -> None:
        update_iris(self._c, pupil_scale, state)

    def update_eye_set(self, now: float, state: FrameState) -> None:
        update_eye_set(self._c, now, state)

    def update_blinks(self, now: float, state: FrameState) -> None:
        update_blinks(self._c, now, state)

    def update_lid_tracking(self, state: FrameState) -> None:
        update_lid_tracking(self._c, state)

    def update_lids(self, now: float) -> None:
        update_lids(self._c, now)

    def draw_scene(self, state: FrameState) -> None:
        draw_scene(self._c, state)
