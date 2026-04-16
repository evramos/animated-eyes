"""
viz_depth_issue.py

Visualizes the two geometry problems with the original hypno/rings Lathe path:
  1. Duplicate pole point
  2. Back-hemisphere vertices causing depth-fighting in compressed orthographic depth

Run with: venv/bin/python viz_depth_issue.py
"""

import math
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch

# ── Constants matching the actual eye ─────────────────────────────────────────
EYE_RADIUS   = 128.0
ANGLE1       = 31.1    # sclera_front angle (degrees from Z axis)
ANGLE2       = 35.2    # sclera_back angle
ANGLE_RANGE  = 180 - ANGLE1 - ANGLE2   # = 113.7°
DEPTH_RANGE  = 10000.0                  # orthographic camera depth range
NDC_SCALE    = 2.0 / DEPTH_RANGE        # M[2,2] from _OrthographicMatrix

def from_polar(deg):
    r = math.radians(deg)
    return math.cos(r), math.sin(r)

def build_path_old():
    """Original formula: sweeps angle1+angle_range = 144.8° past pole."""
    pts = [(0.001, EYE_RADIUS)]  # hardcoded seed (duplicate!)
    for i in range(24):
        angle = 90.0 - (ANGLE1 + ANGLE_RANGE) * i / 23
        ca, sa = from_polar(angle)
        pts.append((max(ca * EYE_RADIUS, 0.001), sa * EYE_RADIUS))
    return pts

def build_path_new():
    """Fixed formula: sweeps exactly 90° → pole to equator."""
    ca0, sa0 = from_polar(90.0 + 0.0001)
    pts = [(max(ca0 * EYE_RADIUS, 0.001), sa0 * EYE_RADIUS)]
    for i in range(24):
        angle = 90.0 - 90.0 * i / 23
        ca, sa = from_polar(angle)
        pts.append((max(ca * EYE_RADIUS, 0.001), sa * EYE_RADIUS))
    return pts

def path_to_reaxis(pts):
    """
    Simulate re_axis: Lathe revolves pts around Y, then re_axis swaps y↔z.
    Result for revolution angle φ=0 (rightmost column of vertices):
      x = r,  y = 0,  z = -h
    We return (r, h, z_after_reaxis) for the cross-section at φ=0.
    """
    result = []
    for r, h in pts:
        z_after = -h   # re_axis: new_z = -old_y = -h
        result.append((r, h, z_after))
    return result

old_pts    = build_path_old()
new_pts    = build_path_new()
old_reaxis = path_to_reaxis(old_pts)
new_reaxis = path_to_reaxis(new_pts)

# ── Figure layout ─────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(16, 10))
fig.suptitle("Hypno/Rings Lathe Path — Geometry Issues Visualized", fontsize=14, fontweight='bold')

gs = fig.add_gridspec(2, 3, hspace=0.45, wspace=0.38)
ax_cross  = fig.add_subplot(gs[0, 0])   # cross-section: r vs h
ax_side   = fig.add_subplot(gs[0, 1])   # side view after re_axis: z vs r
ax_ndc    = fig.add_subplot(gs[0, 2])   # NDC depth compression
ax_dup    = fig.add_subplot(gs[1, 0])   # zoom on duplicate pole point
ax_fight  = fig.add_subplot(gs[1, 1])   # depth-fight zone detail
ax_uv     = fig.add_subplot(gs[1, 2])   # UV coverage comparison

# ── 1. Cross-section: Lathe path (r, h) before re_axis ───────────────────────
old_r = [p[0] for p in old_pts]
old_h = [p[1] for p in old_pts]
new_r = [p[0] for p in new_pts]
new_h = [p[1] for p in new_pts]

ax_cross.set_title("1. Lathe Path Cross-Section\n(before re_axis, revolution profile)", fontsize=9)
ax_cross.plot(old_r, old_h, 'r.-', label='Old (144.8°)', markersize=5)
ax_cross.plot(new_r, new_h, 'g.-', label='New (90°)', markersize=5)

# Mark equator line
ax_cross.axhline(0, color='gray', linestyle='--', linewidth=0.8, alpha=0.7)
ax_cross.text(EYE_RADIUS * 0.02, 3, 'equator (h=0)', fontsize=7, color='gray')

# Mark back hemisphere
ax_cross.axhspan(-EYE_RADIUS, 0, alpha=0.08, color='red')
ax_cross.text(EYE_RADIUS * 0.4, -EYE_RADIUS * 0.5, 'back\nhemisphere', fontsize=7,
              color='red', alpha=0.7, ha='center')

# Highlight duplicate point issue
ax_cross.plot(old_r[0], old_h[0], 'ro', markersize=10, alpha=0.5, label='dup seed')
ax_cross.plot(old_r[1], old_h[1], 'rx', markersize=10, markeredgewidth=2)
ax_cross.annotate('duplicate\n(seed + i=0\nsame point)', xy=(old_r[0], old_h[0]),
                  xytext=(30, 20), textcoords='offset points', fontsize=7,
                  color='red', arrowprops=dict(arrowstyle='->', color='red', lw=0.8))

ax_cross.set_xlabel("r (horizontal radius from axis)", fontsize=8)
ax_cross.set_ylabel("h (height along Y axis)", fontsize=8)
ax_cross.legend(fontsize=7, loc='lower right')
ax_cross.set_xlim(-5, EYE_RADIUS * 1.1)
ax_cross.set_ylim(-EYE_RADIUS * 1.1, EYE_RADIUS * 1.1)
ax_cross.tick_params(labelsize=7)
ax_cross.set_aspect('equal')

# ── 2. After re_axis: z vs r (side view, φ=0 slice) ──────────────────────────
old_rr = [p[0] for p in old_reaxis]
old_z  = [p[2] for p in old_reaxis]
new_rr = [p[0] for p in new_reaxis]
new_z  = [p[2] for p in new_reaxis]

ax_side.set_title("2. After re_axis — Side View\n(z = -h; camera at z = -∞)", fontsize=9)
ax_side.plot(old_rr, old_z, 'r.-', label='Old', markersize=5)
ax_side.plot(new_rr, new_z, 'g.-', label='New', markersize=5)
ax_side.axhline(0, color='gray', linestyle='--', linewidth=0.8, alpha=0.7)
ax_side.text(5, 2, 'z=0 (equator)', fontsize=7, color='gray')

# Shade back hemisphere (z > 0 = behind the front face)
ax_side.axhspan(0, EYE_RADIUS * 1.2, alpha=0.08, color='red')
ax_side.text(EYE_RADIUS * 0.45, EYE_RADIUS * 0.6, 'z > 0\n(behind camera)', fontsize=7,
              color='red', alpha=0.8, ha='center')

# Camera direction
ax_side.annotate('', xy=(EYE_RADIUS * 0.5, -EYE_RADIUS * 1.0),
                 xytext=(EYE_RADIUS * 0.5, -EYE_RADIUS * 0.6),
                 arrowprops=dict(arrowstyle='->', color='blue', lw=1.5))
ax_side.text(EYE_RADIUS * 0.52, -EYE_RADIUS * 0.78, 'camera\ndirection', fontsize=7, color='blue')

ax_side.set_xlabel("r (projected radius in XY plane)", fontsize=8)
ax_side.set_ylabel("z after re_axis (−h)", fontsize=8)
ax_side.legend(fontsize=7)
ax_side.set_xlim(-5, EYE_RADIUS * 1.1)
ax_side.set_ylim(-EYE_RADIUS * 1.1, EYE_RADIUS * 1.2)
ax_side.tick_params(labelsize=7)

# ── 3. NDC depth compression ───────────────────────────────────────────────────
z_vals_old = np.array([p[2] for p in old_reaxis])
z_vals_new = np.array([p[2] for p in new_reaxis])

# NDC_z = z * (2/10000) - 1   (orthographic: M[2,2]=2/10000, M[3,2]=-1)
ndc_old = z_vals_old * NDC_SCALE - 1.0
ndc_new = z_vals_new * NDC_SCALE - 1.0

ax_ndc.set_title("3. Orthographic NDC Depth\n(M[2,2]=2/10000 compresses entire range)", fontsize=9)
ax_ndc.scatter(range(len(ndc_old)), ndc_old, c='red', s=15, label='Old', zorder=3)
ax_ndc.scatter(range(len(ndc_new)), ndc_new, c='green', s=15, label='New', zorder=3)

# Highlight the z-fighting zone: where old back-hemisphere points overlap
# with front-hemisphere points
back_mask = np.array([p[2] > 0 for p in old_reaxis])
if back_mask.any():
    back_indices = np.where(back_mask)[0]
    ax_ndc.scatter(back_indices, ndc_old[back_indices], c='darkred', s=40,
                   marker='x', linewidths=2, label=f'back-hemi ({back_mask.sum()} pts)', zorder=4)

# Show actual NDC range of the fighting zone
z_front_equator = 0.0   # equator, front face z=0
z_back_max = max([p[2] for p in old_reaxis if p[2] > 0], default=0)
ndc_front = z_front_equator * NDC_SCALE - 1.0
ndc_back  = z_back_max * NDC_SCALE - 1.0

ax_ndc.axhspan(ndc_front - 0.001, ndc_back + 0.001, alpha=0.15, color='red')
ax_ndc.text(len(ndc_old) * 0.5,
            (ndc_front + ndc_back) / 2,
            f'fight zone\n~{abs(ndc_back - ndc_front):.4f} NDC\n(GPU precision: ~0.0001)',
            fontsize=7, color='darkred', ha='center', va='center')

ax_ndc.set_xlabel("path point index", fontsize=8)
ax_ndc.set_ylabel("NDC depth value", fontsize=8)
ax_ndc.legend(fontsize=7)
ax_ndc.tick_params(labelsize=7)

# ── 4. Zoom: duplicate pole point ─────────────────────────────────────────────
ax_dup.set_title("4. Duplicate Pole Point (zoom)\nSeed + i=0 produce same (r,h)", fontsize=9)
zoom_pts = old_pts[:4]
zoom_r = [p[0] for p in zoom_pts]
zoom_h = [p[1] for p in zoom_pts]

ax_dup.plot(zoom_r, zoom_h, 'r.-', markersize=8)
for idx, (r, h) in enumerate(zoom_pts):
    label = f'seed\n(0.001, {h:.0f})' if idx == 0 else f'i={idx-1}\n({r:.1f}, {h:.1f})'
    offset = (8, -18) if idx < 2 else (8, 8)
    ax_dup.annotate(label, xy=(r, h), xytext=offset, textcoords='offset points',
                    fontsize=7, color='red' if idx < 2 else 'black',
                    arrowprops=dict(arrowstyle='->', color='gray', lw=0.6))

ax_dup.set_xlim(-2, 20)
ax_dup.set_ylim(EYE_RADIUS * 0.85, EYE_RADIUS * 1.05)
ax_dup.set_xlabel("r", fontsize=8)
ax_dup.set_ylabel("h", fontsize=8)
ax_dup.tick_params(labelsize=7)

# Highlight overlap
ax_dup.annotate('', xy=(zoom_r[1], zoom_h[1]), xytext=(zoom_r[0], zoom_h[0]),
                arrowprops=dict(arrowstyle='<->', color='red', lw=1.5))
ax_dup.text(2, EYE_RADIUS * 0.875, '← same point\n   zero-area ring', fontsize=7, color='red')

# ── 5. Depth-fight zone detail ────────────────────────────────────────────────
ax_fight.set_title("5. Depth-Fighting at Equator\n(front vs back hemisphere, z scale exaggerated)", fontsize=9)

# Show a small slice of front hemisphere near equator and back hemisphere
r_range = np.linspace(80, 128, 40)  # pixels, approaching equator

# Front hemisphere: z goes from some negative value toward 0
z_front = -np.sqrt(np.maximum(EYE_RADIUS**2 - r_range**2, 0))
# Back hemisphere (old path): mirrored, z goes from 0 to positive
z_back  =  np.sqrt(np.maximum(EYE_RADIUS**2 - r_range**2, 0))

ndc_f = z_front * NDC_SCALE
ndc_b = z_back  * NDC_SCALE

ax_fight.plot(r_range, ndc_f * 1000, 'b-', linewidth=2, label='front hemisphere')
ax_fight.plot(r_range, ndc_b * 1000, 'r-', linewidth=2, label='back hemisphere (old)')
ax_fight.fill_between(r_range, ndc_f * 1000, ndc_b * 1000, alpha=0.15, color='red',
                      label='z-fight zone')

# GPU depth precision line
gpu_prec = 0.0001 * 1000
ax_fight.axhspan(-gpu_prec, gpu_prec, alpha=0.3, color='yellow', label=f'GPU depth precision (~0.0001 NDC)')

ax_fight.set_xlabel("projected radius r (pixels)", fontsize=8)
ax_fight.set_ylabel("NDC z × 1000 (near equator)", fontsize=8)
ax_fight.legend(fontsize=6.5, loc='upper left')
ax_fight.tick_params(labelsize=7)
ax_fight.set_xlim(80, 130)

ax_fight.annotate('Front and back\noverlap here →\nundefined draw order',
                  xy=(127, 0), xytext=(100, 0.04 * 1000),
                  fontsize=7, color='darkred',
                  arrowprops=dict(arrowstyle='->', color='darkred', lw=0.8))

# ── 6. UV coverage ────────────────────────────────────────────────────────────
ax_uv.set_title("6. UV Coverage\n(planar front-projection: U=x/(2R)+0.5)", fontsize=9)

theta = np.linspace(0, 2 * math.pi, 200)
# Full circle boundary (equator, r=R)
ax_uv.plot(np.cos(theta) * 0.5 + 0.5, np.sin(theta) * 0.5 + 0.5,
           'k-', linewidth=1.5, label='equator (r=R)')

# Old path: last point is at r=cos(-54.8°)*R ≈ 73.8 (relative 0.577)
old_final_r = old_pts[-1][0] / EYE_RADIUS  # normalized
ax_uv.plot(np.cos(theta) * old_final_r * 0.5 + 0.5,
           np.sin(theta) * old_final_r * 0.5 + 0.5,
           'r--', linewidth=1, label=f'old final ring (r≈{old_pts[-1][0]:.0f}px)')

# Mark UV center
ax_uv.plot(0.5, 0.5, 'k+', markersize=12, markeredgewidth=2)
ax_uv.text(0.52, 0.52, 'pole\n(0.5,0.5)', fontsize=7)

# Shade the back-hemisphere UV region (where old path goes past equator)
# these UV coords are inside the equator circle — they overlap front coverage
back_circle = plt.Circle((0.5, 0.5), old_final_r * 0.5, color='red', alpha=0.12, label='back-hemi UV (overlaps front)')
ax_uv.add_patch(back_circle)

ax_uv.set_xlim(0, 1)
ax_uv.set_ylim(0, 1)
ax_uv.set_xlabel("U", fontsize=8)
ax_uv.set_ylabel("V", fontsize=8)
ax_uv.set_aspect('equal')
ax_uv.legend(fontsize=7, loc='lower right')
ax_uv.tick_params(labelsize=7)

# ── Show ──────────────────────────────────────────────────────────────────────
plt.savefig("/tmp/depth_issue_viz.png", dpi=130, bbox_inches='tight')
print("Saved to /tmp/depth_issue_viz.png")
plt.show()
