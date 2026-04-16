"""
eye_sets/concentric.py

Live-generated concentric rings texture for the RINGS eye set.

Computed entirely with numpy using a radial distance grid precomputed once
at init. Each frame the animation offset shifts which ring color maps to each
radius. The resulting uint8 array is pushed to a pi3d.Texture via
update_ndarray() — no GL object re-allocation per frame.

Math overview:
    ring_width  = radius / num_rings
    pattern_len = ring_width * num_colors
    shifted     = (r + offset) % pattern_len          — animated radial position
    band_idx    = floor(shifted / ring_width) % n     — which color band
    pos_in_band = frac(shifted / ring_width) * ring_width — position within band
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
from eye_sets.palettes import RINGS_PALETTES


# ── Registration ───────────────────────────────────────────────────────────────

class ConcentricInitializer(EyeSetInitializer):
    def __init__(self):
        from eye_sets.constants import RINGS_PRESETS  # lazy — avoids circular import at load time
        super().__init__(EyeSet.RINGS, ConcentricRings, RINGS_PRESETS)

# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass
class ConcentricConfig(EyeSetConfig):
    # Shape
    num_rings:    int   = 4          # number of visible rings
    band_colors:  int   = 2          # how many palette colors per pattern cycle (2–5)
    palette:      str   = "neon"     # key into PALETTES
    # Motion
    direction:    str   = "outward"  # "none" | "outward" | "inward" | "pulse"
    speed:        float = 1.2        # rings per second (outward/inward) or pulse rate
    pulse_len:    float = 1.0        # pulse travel in pattern-lengths
    # Right eye pairing
    right_shift:  int   = 1          # palette index offset for right eye
    right_mirror: bool  = False      # reverse animation direction on right eye
    # Effects
    gradient:     bool  = False      # smooth lerp between adjacent bands
    glow:         bool  = False      # brightness boost at band edges
    glow_size:    int   = 3          # glow falloff in pixels
    edge_soft:    float = 0.0        # soft blend width at band boundaries (px)
    color_cycle:  bool  = False      # slowly rotate palette hues over time
    cycle_speed:  float = 0.5        # hue rotation speed (radians/sec)
    bright_pulse: bool  = False      # oscillate overall brightness
    bright_speed: float = 1.0        # brightness oscillation frequency (cycles/sec)
    center_dot:   str   = "none"     # "none" | "black" | "white" | "color"
    dot_size:     int   = 4          # center dot radius in pixels


# ── ConcentricRings ────────────────────────────────────────────────────────────

class ConcentricRings:
    """Generates and updates a live concentric rings texture for the RINGS eye set."""

    def __init__(self, config: ConcentricConfig = None):
        self._config      = config or ConcentricConfig()
        self._offset      = 0.0
        self._pulse_phase = 0.0
        self._cycle_angle = 0.0
        self._bright_phase = 0.0
        self._last_update = 0.0
        self._build_grid()

        np.clip(self._draw(right=False),          0, 255, out=self._out, casting='unsafe')
        np.clip(self._draw(right=True)[:, ::-1], 0, 255, out=self._out_alt, casting='unsafe')
        self._texture     = pi3d.Texture(Image.fromarray(self._out,     "RGB"), mipmap=False, filter=pi3d.constants.GL_LINEAR, blend=True)
        self._texture_alt = pi3d.Texture(Image.fromarray(self._out_alt, "RGB"), mipmap=False, filter=pi3d.constants.GL_LINEAR)

    # ── Grid ──────────────────────────────────────────────────────────────────

    def _build_grid(self):
        """Precompute radial distance grid. Called once at init and on size change."""
        size = self._config.size
        half = size / 2.0
        y_idx, x_idx = np.mgrid[0:size, 0:size].astype(np.float32)
        dx = x_idx - half
        dy = y_idx - half
        self._r            = np.sqrt(dx * dx + dy * dy)
        self._half         = half
        self._circle_mask  = (self._r <= half)[..., np.newaxis]
        self._out          = np.empty((size, size, 3), dtype=np.uint8)
        self._out_alt      = np.empty((size, size, 3), dtype=np.uint8)

    # ── Hue shift ─────────────────────────────────────────────────────────────

    def _hue_shift(self, palette: np.ndarray, angle: float) -> np.ndarray:
        """Rotate palette hues by angle (radians) using the standard RGB rotation matrix."""
        c, s = math.cos(angle), math.sin(angle)
        m = np.array([
            [0.299+0.701*c+0.168*s, 0.587-0.587*c+0.330*s, 0.114-0.114*c-0.497*s],
            [0.299-0.299*c-0.328*s, 0.587+0.413*c+0.035*s, 0.114-0.114*c+0.292*s],
            [0.299-0.300*c+1.250*s, 0.587-0.588*c-1.050*s, 0.114+0.886*c-0.203*s],
        ], dtype=np.float32)
        return np.clip(palette @ m.T, 0, 255)

    # ── Draw ──────────────────────────────────────────────────────────────────

    def _draw(self, right: bool = False) -> np.ndarray:
        """Render one frame into a (size, size, 3) uint8 array."""
        cfg  = self._config
        r    = self._r
        half = self._half

        palette = np.array(RINGS_PALETTES[cfg.palette], dtype=np.float32)
        n_col   = min(cfg.band_colors, len(palette))
        palette = palette[:n_col]

        if cfg.color_cycle:
            palette = self._hue_shift(palette, self._cycle_angle)

        if right and cfg.right_shift > 0:
            palette = np.roll(palette, cfg.right_shift, axis=0)

        ring_width  = half / cfg.num_rings
        pattern_len = ring_width * n_col

        eye_offset = self._offset
        if right and cfg.right_mirror:
            eye_offset = -eye_offset

        # ── Band lookup ───────────────────────────────────────────────────────
        shifted     = ((r + eye_offset) % pattern_len + pattern_len) % pattern_len
        band_pos    = shifted / ring_width
        band_idx    = np.floor(band_pos).astype(np.int32) % n_col
        pos_in_band = (band_pos - np.floor(band_pos)) * ring_width

        # ── Color selection ───────────────────────────────────────────────────
        if cfg.gradient:
            t        = (band_pos - np.floor(band_pos))[..., np.newaxis]
            next_idx = (band_idx + 1) % n_col
            colors   = palette[band_idx] * (1.0 - t) + palette[next_idx] * t

        elif cfg.glow:
            dist_to_edge = np.minimum(pos_in_band, ring_width - pos_in_band)
            colors = palette[band_idx].astype(np.float32)
            glow_px = max(cfg.glow_size, 1e-4)
            glow_t  = np.clip(1.0 - dist_to_edge / glow_px, 0.0, 1.0)[..., np.newaxis]
            colors  = np.clip(colors * (1.0 + glow_t * 1.2), 0, 255)

        elif cfg.edge_soft > 0.0 and ring_width > cfg.edge_soft * 2:
            blend_px  = cfg.edge_soft
            next_idx  = (band_idx + 1) % n_col
            prev_idx  = (band_idx - 1) % n_col
            colors    = palette[band_idx].astype(np.float32)
            # blend near leading edge
            dist_next = ring_width - pos_in_band
            t_next    = np.clip(1.0 - dist_next / blend_px, 0.0, 1.0)[..., np.newaxis] * 0.5
            near_next = (dist_next < blend_px)[..., np.newaxis]
            colors    = np.where(near_next, colors * (1.0 - t_next) + palette[next_idx] * t_next, colors)
            # blend near trailing edge
            t_prev    = np.clip(1.0 - pos_in_band / blend_px, 0.0, 1.0)[..., np.newaxis] * 0.5
            near_prev = (pos_in_band < blend_px)[..., np.newaxis]
            colors    = np.where(near_prev, colors * (1.0 - t_prev) + palette[prev_idx] * t_prev, colors)

        else:
            colors = palette[band_idx].astype(np.float32)

        # ── Brightness pulse ─────────────────────────────────────────────────
        if cfg.bright_pulse:
            brightness = 0.4 + 0.6 * (math.sin(self._bright_phase) * 0.5 + 0.5)
            colors     = colors * brightness

        # ── Circular mask ─────────────────────────────────────────────────────
        frame = colors * self._circle_mask

        # # ── Center dot ───────────────────────────────────────────────────────
        # if cfg.center_dot != "none":
        #     if cfg.center_dot == "black":
        #         dot_color = np.zeros(3, dtype=np.float32)
        #     elif cfg.center_dot == "white":
        #         dot_color = np.full(3, 255.0, dtype=np.float32)
        #     else:
        #         dot_color = palette[0]
        #     dot_mask = (r <= cfg.dot_size)[..., np.newaxis]
        #     frame    = np.where(dot_mask, dot_color, frame)

        return frame

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, now: float) -> bool:
        """Advance animation state and redraw if the update interval has elapsed."""
        cfg = self._config
        if now - self._last_update < 1.0 / cfg.update_hz:
            return False

        dt = now - self._last_update if self._last_update > 0 else 1.0 / cfg.update_hz
        self._last_update = now

        n_col       = min(cfg.band_colors, len(RINGS_PALETTES[cfg.palette]))
        ring_width  = self._half / cfg.num_rings
        pattern_len = ring_width * n_col
        px_per_sec  = cfg.speed * 20.0

        if cfg.direction == "outward":
            self._offset -= px_per_sec * dt
        elif cfg.direction == "inward":
            self._offset += px_per_sec * dt
        elif cfg.direction == "pulse":
            self._pulse_phase += dt * cfg.speed * math.pi * 2.0 * 0.25
            self._offset = math.sin(self._pulse_phase) * pattern_len * cfg.pulse_len

        if cfg.color_cycle:
            self._cycle_angle += dt * cfg.cycle_speed

        if cfg.bright_pulse:
            self._bright_phase += dt * cfg.bright_speed * math.pi * 2.0

        np.clip(self._draw(right=False),          0, 255, out=self._out, casting='unsafe')
        np.clip(self._draw(right=True)[:, ::-1], 0, 255, out=self._out_alt, casting='unsafe')
        self._texture.update_ndarray(self._out)
        self._texture_alt.update_ndarray(self._out_alt)
        return True

    # ── Config swap ───────────────────────────────────────────────────────────

    def set_config(self, config: ConcentricConfig) -> None:
        """Swap to a new preset at runtime. Rebuilds grid and output buffers only if size changed."""
        needs_rebuild = config.size != self._config.size
        self._config = config
        if needs_rebuild:
            self._build_grid()  # also reallocates _out / _out_alt

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def texture(self) -> pi3d.Texture:
        return self._texture

    @property
    def texture_alt(self) -> pi3d.Texture:
        """Color-shifted + horizontally mirrored version — used for the right eye."""
        return self._texture_alt
