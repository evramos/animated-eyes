"""
eye_sets/constants.py

Preset lists for all live-generated eye sets.
Import via: from eye_sets.constants import HYPNO_PRESETS, RINGS_PRESETS
"""

from eye_sets.hypnosis import HypnoConfig
from eye_sets.concentric import ConcentricConfig

# ── Hypno presets ──────────────────────────────────────────────────────────────

HYPNO_PRESETS: list[HypnoConfig] = [
    HypnoConfig(name="neon",         arms=2, turns=5,  palette="neon",        wave="out",       spin_dir="cw"),
    HypnoConfig(name="fire-spin",    arms=3, turns=4,  palette="fire",        wave="out",       spin_dir="cw",   spin_speed=0.04,  glow=True),
    HypnoConfig(name="psychedelic",  arms=4, turns=6,  palette="psychedelic", wave="pulse",     spin_dir="rock", thick_pulse=0.3,  glow=True),
    HypnoConfig(name="ice-in",       arms=2, turns=5,  palette="ice",         wave="in",        spin_dir="ccw"),
    HypnoConfig(name="venom-taper",  arms=3, turns=4,  palette="venom",       wave="out",       spin_dir="cw",   taper=True),
    HypnoConfig(name="neon-dash",    arms=4, turns=5,  palette="neon",        wave="out",       spin_dir="cw",   dashes=True,     glow=True),
    HypnoConfig(name="bw-mirror",    arms=2, turns=6,  palette="bw",          wave="out",       spin_dir="cw",   mirror=4),
    HypnoConfig(name="sunset-rock",  arms=3, turns=5,  palette="sunset",      wave="alternate", spin_dir="rock", trails=0.3),
    HypnoConfig(name="ocean-stand",  arms=2, turns=8,  palette="ocean",       wave="standing",  spin_dir="none"),
]

# ── Rings Presets ──────────────────────────────────────────────────────────────

RINGS_PRESETS: list[ConcentricConfig] = [
    ConcentricConfig(name="fire-out",      palette="fire",      direction="outward", num_rings=2,  band_colors=2),
    ConcentricConfig(name="dragon-pulse",  palette="dragon",    direction="pulse",   num_rings=6,  band_colors=3, pulse_len=1.2, glow=True),
    ConcentricConfig(name="void-in",       palette="void",      direction="inward",  num_rings=10, band_colors=2, edge_soft=3.0),
    ConcentricConfig(name="neon-gradient", palette="neon",      direction="outward", num_rings=8,  band_colors=4, gradient=True),
    ConcentricConfig(name="lava-bright",   palette="lava",      direction="outward", num_rings=6,  band_colors=2, bright_pulse=True, glow=True),
    ConcentricConfig(name="cyber-cycle",   palette="cyber",     direction="outward", num_rings=8,  band_colors=3, color_cycle=True, cycle_speed=0.4),
    ConcentricConfig(name="witch-pulse",   palette="witch",     direction="pulse",   num_rings=5,  band_colors=2, pulse_len=0.8, bright_pulse=True),
    ConcentricConfig(name="rainbow-soft",  palette="rainbow",   direction="outward", num_rings=10, band_colors=5, gradient=True, center_dot="black", dot_size=6),
    ConcentricConfig(name="red-static",    palette="red-black", direction="none",    num_rings=8,  band_colors=2),
]
