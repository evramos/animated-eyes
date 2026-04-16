"""
eye_sets/hypnosis.py

(꩜﹏꩜)
Live-generated hypnotic spiral texture for the HYPNO eye set.

The spiral is computed entirely with numpy using a polar coordinate grid
precomputed once at init. Each frame, per-pixel arm distance is calculated
and mapped to palette colors. The resulting uint8 array is pushed to a
pi3d.Texture via update_ndarray() — no GL object re-allocation per frame.

Math overview:
    b             = log(max_r + 1) / (turns * 2π)   — log-spiral growth rate
    theta_spiral  = log(r) / b                        — spiral angle at radius r
    phase_raw     = (θ - spin - theta_spiral) * arms / 2π + anim_phase
    arm_dist      = min(phase % 1, 1 - phase % 1)    — 0 at arm center, 0.5 between arms
    on_arm        = arm_dist < half_thickness
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from eye_sets.config import EyeSetConfig

import numpy as np
import pi3d
from PIL import Image

from constants import EyeSet
from eye_sets.base import EyeSetInitializer
from eye_sets.palettes import HYPNO_PALETTES


# ── Registration ───────────────────────────────────────────────────────────────

class HypnoInitializer(EyeSetInitializer):
    def __init__(self):
        from eye_sets.constants import HYPNO_PRESETS  # lazy — avoids circular import at load time
        super().__init__(EyeSet.HYPNO, HypnoSpiral, HYPNO_PRESETS)


# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass
class HypnoConfig(EyeSetConfig):
    # Shape
    arms:        int   = 2          # number of spiral arms (1–8)
    turns:       int   = 3          # full rotations the spiral makes (1–16)
    thickness:   float = 0.45       # arm half-width as fraction of arm period (0–1)
    palette:     str   = "neon"     # key into PALETTES
    # Motion
    spin_dir:    str   = "ccw"      # "none" | "cw" | "ccw" | "rock"
    spin_speed:  float = 0.025      # radians per frame added to spin angle
    wave:        str   = "none"     # "none" | "out" | "in" | "pulse" | "standing" | "alternate"
    wave_speed:  float = 0.03       # phase units per frame
    distort:     float = 0.0        # radial warp amplitude (0–1)
    # Effects
    trails:      float = 0.0        # previous-frame blend (0 = off, 1 = fully frozen)
    color_cycle: float = 0.0        # palette hue rotation rate — TODO: implement
    thick_pulse: float = 0.0        # thickness oscillation amplitude (0–1)
    glow:        bool  = False      # soft Gaussian edge falloff instead of hard cutoff
    dashes:      bool  = False      # periodic opacity gaps along each arm
    taper:       bool  = False      # arms thin toward the center
    mirror:      int   = 0          # rotational mirror folds: 0, 2, or 4


# ── HypnoSpiral ────────────────────────────────────────────────────────────────

class HypnoSpiral:
    """Generates and updates a live spiral texture for the HYPNO eye set.

    Usage:
        spiral = HypnoSpiral()                        # default config
        spiral = HypnoSpiral(PRESETS[2])              # specific preset
        spiral.set_config(PRESETS[1])                 # swap preset at runtime
        redrew = spiral.update(now)                   # call each frame
        mesh.set_textures([spiral.texture])           # on first switch to HYPNO
    """

    def __init__(self, config: HypnoConfig = None):
        self._config       = config or HypnoConfig()
        self._phase        = 0.0   # wave animation phase
        self._spin         = 0.0   # current spin angle (radians)
        self._last_update  = 0.0
        self._prev_frame:  np.ndarray | None = None
        self._build_grid()

        np.clip(self._draw(arm_offset=0),          0, 255, out=self._out, casting='unsafe')
        np.clip(self._draw(arm_offset=1)[:, ::-1], 0, 255, out=self._out_alt, casting='unsafe')
        self._texture     = pi3d.Texture(Image.fromarray(self._out,     "RGB"), mipmap=False, filter=pi3d.constants.GL_LINEAR)
        self._texture_alt = pi3d.Texture(Image.fromarray(self._out_alt, "RGB"), mipmap=False, filter=pi3d.constants.GL_LINEAR)

    # ── Grid ──────────────────────────────────────────────────────────────────

    def _build_grid(self):
        """Precompute static polar arrays. Called once at init and on size/turns change."""
        cfg  = self._config
        size = cfg.size
        half = size / 2.0

        y_idx, x_idx = np.mgrid[0:size, 0:size].astype(np.float32)
        dx = x_idx - half
        dy = y_idx - half

        self._r     = np.sqrt(dx * dx + dy * dy)           # radius per pixel
        self._theta = np.arctan2(dy, dx)                    # angle per pixel [-π, π]
        self._max_r = half

        b = math.log(half + 1.0) / (cfg.turns * 2.0 * math.pi)
        self._b            = b
        self._theta_spiral = np.log(np.maximum(self._r, 1.0)) / b  # static spiral angle per pixel
        self._circle_mask  = (self._r <= half)[..., np.newaxis]     # circular clip mask
        self._prev_frame   = None
        self._out          = np.empty((size, size, 3), dtype=np.uint8)
        self._out_alt      = np.empty((size, size, 3), dtype=np.uint8)

    # ── Draw ──────────────────────────────────────────────────────────────────

    def _draw(self, arm_offset: int = 0) -> np.ndarray:
        """Render one frame into a (size, size, 3) uint8 array."""
        cfg   = self._config
        r     = self._r
        arms  = cfg.arms
        phase = self._phase
        spin  = self._spin

        palette = np.array(HYPNO_PALETTES[cfg.palette], dtype=np.float32)   # (N, 3)
        n_col   = len(palette)

        # ── Phase field ───────────────────────────────────────────────────────
        # Raw angular position of each pixel within the spiral arm cycle.
        theta_offset = self._theta - spin - self._theta_spiral

        if cfg.wave == "standing":
            # Standing wave: no net travel, amplitude oscillates in place
            phase_raw = np.sin(theta_offset * 2.0) * math.sin(phase * 2.0)
        elif cfg.wave == "alternate":
            # Odd/even arms travel in opposite directions
            arm_parity = np.floor(theta_offset * arms / (2.0 * math.pi)).astype(np.int32) % 2
            direction  = np.where(arm_parity == 0, 1.0, -1.0).astype(np.float32)
            phase_raw  = direction * (theta_offset * arms / (2.0 * math.pi)) + phase
        else:
            phase_raw = theta_offset * arms / (2.0 * math.pi) + phase

        arm_phase = phase_raw % 1.0   # 0→1 within one arm period

        # ── Distortion ───────────────────────────────────────────────────────
        if cfg.distort > 0.0:
            warp = cfg.distort * np.sin(phase_raw * 4.0 + self._theta * 3.0) * (r * 0.08 / self._max_r)
            arm_phase = (arm_phase + warp) % 1.0

        # ── Arm distance & thickness ─────────────────────────────────────────
        # arm_dist is 0 at the arm center, 0.5 at the midpoint between arms.
        arm_dist   = np.minimum(arm_phase, 1.0 - arm_phase)
        half_thick = cfg.thickness / 2.0

        if cfg.taper:
            half_thick = half_thick * (0.2 + 0.8 * (r / self._max_r))
        if cfg.thick_pulse > 0.0:
            half_thick = half_thick * (1.0 + cfg.thick_pulse * math.sin(phase * 3.0))

        # ── Arm color lookup ─────────────────────────────────────────────────
        # phase_raw - phase = theta_offset * arms/2π, which correctly tracks
        # arm identity as spin advances (each pixel shows the color of whatever
        # arm is passing over it). The +0.5 shifts the floor discontinuity from
        # arm_phase=0 (arm center) to arm_phase=0.5 (black gap between arms),
        # so no single arm is split across two palette entries.
        arm_idx = (np.floor(phase_raw - phase + 0.5).astype(np.int32) + arm_offset) % arms
        colors  = palette[arm_idx % n_col]     # (size, size, 3) float32

        # ── Pixel shading ─────────────────────────────────────────────────────
        bg = np.zeros((cfg.size, cfg.size, 3), dtype=np.float32)

        if cfg.glow:
            # Gaussian soft edge: full brightness at arm center, fades outward
            sigma = np.maximum(half_thick, 1e-4)
            alpha = np.exp(-(arm_dist ** 2) / (2.0 * sigma ** 2))[..., np.newaxis]
            frame = alpha * colors + (1.0 - alpha) * bg
        else:
            on_arm = (arm_dist < half_thick)[..., np.newaxis]
            frame  = np.where(on_arm, colors, bg).astype(np.float32)

        # ── Dashes ────────────────────────────────────────────────────────────
        if cfg.dashes:
            dash = (np.sin(self._theta_spiral * 0.5 + phase * 20.0) > 0.0)[..., np.newaxis]
            frame = frame * dash

        # ── Circular mask ─────────────────────────────────────────────────────
        frame = frame * self._circle_mask

        # ── Mirror ────────────────────────────────────────────────────────────
        if cfg.mirror == 2:
            frame = (frame + frame[::-1, ::-1]) / 2.0
        elif cfg.mirror == 4:
            frame = (frame + np.rot90(frame, 1) + np.rot90(frame, 2) + np.rot90(frame, 3)) / 4.0

        # ── Trails ────────────────────────────────────────────────────────────
        if cfg.trails > 0.0 and self._prev_frame is not None:
            frame = cfg.trails * self._prev_frame + (1.0 - cfg.trails) * frame

        self._prev_frame = frame
        return frame

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, now: float) -> bool:
        """Advance animation state and redraw if the update interval has elapsed.

        Returns True if the texture was redrawn this call (caller may then call
        set_textures on the iris meshes if needed, though the same Texture object
        is reused so the GL binding stays valid).
        """
        cfg = self._config
        if now - self._last_update < 1.0 / cfg.update_hz:
            return False

        self._last_update = now

        # Advance wave phase
        if cfg.wave == "in":
            self._phase -= cfg.wave_speed
        elif cfg.wave == "pulse":
            self._phase += math.sin(now * 2.0) * cfg.wave_speed
        elif cfg.wave != "none":
            self._phase += cfg.wave_speed

        # Advance spin
        if cfg.spin_dir == "cw":
            self._spin += cfg.spin_speed
        elif cfg.spin_dir == "ccw":
            self._spin -= cfg.spin_speed
        elif cfg.spin_dir == "rock":
            self._spin = math.sin(self._phase * 0.4) * 1.5

        np.clip(self._draw(arm_offset=0),          0, 255, out=self._out, casting='unsafe')
        np.clip(self._draw(arm_offset=1)[:, ::-1], 0, 255, out=self._out_alt, casting='unsafe')
        self._texture.update_ndarray(self._out)
        self._texture_alt.update_ndarray(self._out_alt)
        return True

    # ── Config swap ───────────────────────────────────────────────────────────

    def set_config(self, config: HypnoConfig):
        """Swap to a new preset at runtime. Rebuilds polar grid and output buffers only if size or turns changed."""
        needs_rebuild = (config.size != self._config.size or
                         config.turns != self._config.turns)
        self._config = config
        if needs_rebuild:
            self._build_grid()  # also reallocates _out / _out_alt

    # ── Property ──────────────────────────────────────────────────────────────

    @property
    def texture(self) -> pi3d.Texture:
        return self._texture

    @property
    def texture_alt(self) -> pi3d.Texture:
        """Color-shifted version of the spiral (arm colors offset by 1) — used for the right eye."""
        return self._texture_alt
