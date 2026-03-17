"""
Visualization of complex-number rotation as used in debug_overlay._project().

Run with:  venv/bin/python viz_complex_rotation.py
"""

import cmath
import math
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

# ── Parameters matching debug_overlay ─────────────────────────────────────────
EYE_RADIUS     = 128
ROTATE_DEGREES = 180
angle_x        = 20   # eye looking 20° right
angle_y        = 10   # eye looking 10° up

# ── Step 1: raw offset (before rotation) ──────────────────────────────────────
dx_raw = -math.sin(math.radians(angle_x)) * EYE_RADIUS
dy_raw =  math.sin(math.radians(angle_y)) * EYE_RADIUS

# ── Step 2: rotation factor ────────────────────────────────────────────────────
rotation = cmath.rect(1, math.radians(ROTATE_DEGREES))

# ── Step 3: rotate ─────────────────────────────────────────────────────────────
offset_before = complex(dx_raw, dy_raw)
offset_after  = offset_before * rotation

# ── Plot ───────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(15, 5))
fig.suptitle("debug_overlay._project()  —  complex rotation step by step", fontsize=13, fontweight="bold")

R = EYE_RADIUS * 1.4  # axis limit

def draw_axes(ax, lim):
    ax.axhline(0, color="#555", linewidth=0.8, zorder=0)
    ax.axvline(0, color="#555", linewidth=0.8, zorder=0)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=8)
    ax.set_xlabel("real  (dx)", fontsize=9)
    ax.set_ylabel("imag  (dy)", fontsize=9)

def arrow(ax, x, y, color, label, lw=2):
    ax.annotate("", xy=(x, y), xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw))
    ax.plot(x, y, "o", color=color, markersize=6)
    ax.text(x + 4, y + 4, label, color=color, fontsize=9, fontweight="bold")

# ── Panel 1: the raw offset vector ────────────────────────────────────────────
ax = axes[0]
draw_axes(ax, R)
ax.set_title(f"① Raw offset\n"
             f"complex(-sin({angle_x}°), sin({angle_y}°)) × {EYE_RADIUS}", fontsize=9)

circle = plt.Circle((0, 0), EYE_RADIUS, color="#3399ff", fill=False, linestyle="--", linewidth=1, alpha=0.4)
ax.add_patch(circle)
ax.text(EYE_RADIUS + 4, 4, f"r={EYE_RADIUS}", color="#3399ff", fontsize=7, alpha=0.7)

arrow(ax, dx_raw, dy_raw, "#e74c3c", f"({dx_raw:.1f}, {dy_raw:.1f})")
ax.text(-R * 0.95, -R * 0.85,
        f"dx = −sin({angle_x}°)·{EYE_RADIUS} = {dx_raw:.1f}\n"
        f"dy =  sin({angle_y}°)·{EYE_RADIUS} = {dy_raw:.1f}",
        fontsize=8, color="#333",
        bbox=dict(boxstyle="round,pad=0.3", fc="#f8f8f8", ec="#ccc"))

# ── Panel 2: the rotation factor on the unit circle ───────────────────────────
ax = axes[1]
draw_axes(ax, 1.5)
ax.set_title(f"② Rotation factor\n"
             f"cmath.rect(1, {ROTATE_DEGREES}°)  =  {rotation.real:.0f} + {rotation.imag:.0f}i", fontsize=9)

theta_vals = np.linspace(0, math.radians(ROTATE_DEGREES), 200)
ax.plot(np.cos(theta_vals), np.sin(theta_vals), color="#27ae60", linewidth=1.5, alpha=0.6)
unit_circle = plt.Circle((0, 0), 1.0, color="#27ae60", fill=False, linestyle="--", linewidth=1, alpha=0.3)
ax.add_patch(unit_circle)

# angle arc label
mid_theta = math.radians(ROTATE_DEGREES / 2)
ax.annotate(f"{ROTATE_DEGREES}°", xy=(math.cos(mid_theta) * 0.6, math.sin(mid_theta) * 0.6),
            fontsize=10, color="#27ae60", ha="center")

arrow(ax, rotation.real, rotation.imag, "#27ae60",
      f"({rotation.real:.0f}, {rotation.imag:.0f})", lw=2.5)

# show e^(iθ) formula
ax.text(-1.4, -1.35,
        f"e^(i·π) = cos(180°) + i·sin(180°)\n"
        f"        = −1 + 0i",
        fontsize=8, color="#333",
        bbox=dict(boxstyle="round,pad=0.3", fc="#f8f8f8", ec="#ccc"))

# ── Panel 3: before & after multiplication ────────────────────────────────────
ax = axes[2]
draw_axes(ax, R)
ax.set_title(f"③ Result:  offset × rotation_factor\n"
             f"= ({dx_raw:.1f}+{dy_raw:.1f}i) × ({rotation.real:.0f}+{rotation.imag:.0f}i)", fontsize=9)

circle = plt.Circle((0, 0), EYE_RADIUS, color="#3399ff", fill=False, linestyle="--", linewidth=1, alpha=0.4)
ax.add_patch(circle)

# faded original
ax.annotate("", xy=(offset_before.real, offset_before.imag), xytext=(0, 0),
            arrowprops=dict(arrowstyle="-|>", color="#e74c3c", lw=1.5, alpha=0.3))
ax.text(offset_before.real + 4, offset_before.imag + 4, "before", color="#e74c3c", fontsize=8, alpha=0.4)

# rotation arc between before and after
a_start = math.atan2(offset_before.imag, offset_before.real)
a_end   = math.atan2(offset_after.imag,  offset_after.real)
arc_r   = EYE_RADIUS * 0.55
arc_ts  = np.linspace(a_start, a_start + math.radians(ROTATE_DEGREES), 60)
ax.plot(arc_r * np.cos(arc_ts), arc_r * np.sin(arc_ts),
        color="#f39c12", linewidth=2, linestyle=":")
arc_mid = arc_ts[len(arc_ts) // 2]
ax.text(arc_r * math.cos(arc_mid) * 1.15,
        arc_r * math.sin(arc_mid) * 1.15,
        f"×{ROTATE_DEGREES}°", color="#f39c12", fontsize=9, ha="center")

# result
arrow(ax, offset_after.real, offset_after.imag, "#8e44ad",
      f"({offset_after.real:.1f}, {offset_after.imag:.1f})", lw=2.5)

ax.text(-R * 0.95, -R * 0.85,
        f"new dx = {offset_after.real:.1f}  (offset.real)\n"
        f"new dy = {offset_after.imag:.1f}  (offset.imag)",
        fontsize=8, color="#333",
        bbox=dict(boxstyle="round,pad=0.3", fc="#f8f8f8", ec="#ccc"))

plt.tight_layout()
plt.savefig("viz_complex_rotation.png", dpi=150, bbox_inches="tight")
print("Saved: viz_complex_rotation.png")
plt.show()
