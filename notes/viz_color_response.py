"""
notes/viz_color_response.py

Visualizes the color response mismatch between macOS sRGB and the SSD1351 OLED.

Shows:
  - macOS sRGB: how OpenGL encodes and displays color (gamma ~2.2)
  - OLED raw:   what the display actually outputs given raw pixel values (no correction)
  - OLED LUT:   the SSD1351 B8h gamma table response (applied on top of raw input)
  - Corrected:  the proposed software LUT pre-correction baked in before RGB565 pack
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# ── SSD1351 B8h gamma table (from fbx2.c initOLED) ───────────────────────────
# 64 entries mapping grayscale input level → drive value (0x00–0xB3)
B8_LUT = np.array([
    0x00, 0x08, 0x0D, 0x12, 0x17, 0x1B, 0x1F, 0x22,
    0x26, 0x2A, 0x2D, 0x30, 0x34, 0x37, 0x3A, 0x3D,
    0x40, 0x43, 0x46, 0x49, 0x4C, 0x4F, 0x51, 0x54,
    0x57, 0x59, 0x5C, 0x5F, 0x61, 0x64, 0x67, 0x69,
    0x6C, 0x6E, 0x71, 0x73, 0x76, 0x78, 0x7B, 0x7D,
    0x7F, 0x82, 0x84, 0x86, 0x89, 0x8B, 0x8D, 0x90,
    0x92, 0x94, 0x97, 0x99, 0x9B, 0x9D, 0x9F, 0xA2,
    0xA4, 0xA6, 0xA8, 0xAA, 0xAD, 0xAF, 0xB1, 0xB3,
], dtype=np.float32)

x8 = np.arange(256)   # 8-bit input values (0–255)
xn = x8 / 255.0       # normalized 0–1

# ── macOS sRGB response ───────────────────────────────────────────────────────
# sRGB encodes with gamma ~2.2. The monitor linearizes on display.
# From the pi3d renderer's perspective: what you see on macOS IS the reference.
srgb_display = xn  # macOS shows what you give it — this IS the reference line

# ── OLED raw path (no correction) ────────────────────────────────────────────
# fbx2 just truncates: 8-bit → 5/6-bit. No gamma applied in software.
# Green channel (6-bit): input >> 2 → 64 levels
green_6bit  = (x8 >> 2).astype(int)
oled_raw_g  = B8_LUT[green_6bit] / 0xB3   # normalize to 0–1

# Red/Blue channel (5-bit): input >> 3 → 32 levels, use every 2nd LUT entry
red_5bit    = (x8 >> 3).astype(int)
oled_raw_rb = B8_LUT[red_5bit * 2] / 0xB3

# ── Hardware contrast mismatch — green is attenuated by C1 register ──────────
# C1: R=0xFF, G=0xA3 (163), B=0xFF → green is at 163/255 = 63.9% of R/B
GREEN_CONTRAST = 163 / 255
oled_raw_g_contrasted = oled_raw_g * GREEN_CONTRAST

# ── Proposed corrected path ───────────────────────────────────────────────────
# Apply software gamma LUT before packing: (v)^1.47 compensates for sRGB vs OLED
GAMMA_EXP = 1.47
corrected_rb = np.power(np.clip(oled_raw_rb, 0, 1), 1.0 / GAMMA_EXP)
corrected_g  = np.power(np.clip(oled_raw_g_contrasted, 0, 1), 1.0 / GAMMA_EXP)

# ── Plot ──────────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(14, 9), facecolor="#111")
gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.38, wspace=0.32)

AX_STYLE = dict(facecolor="#1a1a1a")
GRID     = dict(color="#333", linewidth=0.5)

def styled_ax(ax, title):
    ax.set_facecolor("#1a1a1a")
    ax.set_title(title, color="#ccc", fontsize=10, pad=8)
    ax.tick_params(colors="#777")
    ax.spines[:].set_color("#444")
    ax.set_xlabel("Input value (0–255)", color="#888", fontsize=8)
    ax.set_ylabel("Perceived brightness", color="#888", fontsize=8)
    ax.set_xlim(0, 255); ax.set_ylim(0, 1)
    ax.grid(**GRID)

# ── 1. Response curves overlay ────────────────────────────────────────────────
ax1 = fig.add_subplot(gs[0, :])
styled_ax(ax1, "Color Response: macOS sRGB  vs  SSD1351 OLED (current, no correction)")
ax1.plot(x8, srgb_display,           color="#4af",  lw=2,   label="macOS sRGB (reference)")
ax1.plot(x8, oled_raw_rb,            color="#f44",  lw=1.5, label="OLED R/B channel (5-bit, no correction)")
ax1.plot(x8, oled_raw_g,             color="#4f4",  lw=1.5, label="OLED G channel (6-bit, no correction)")
ax1.plot(x8, oled_raw_g_contrasted,  color="#4f4",  lw=1.5, ls="--", label="OLED G with C1 contrast (×0.64)")
ax1.fill_between(x8, srgb_display, oled_raw_rb, alpha=0.08, color="#f44")
ax1.legend(facecolor="#222", edgecolor="#555", labelcolor="#ccc", fontsize=8)

# ── 2. R/B mismatch detail ────────────────────────────────────────────────────
ax2 = fig.add_subplot(gs[1, 0])
styled_ax(ax2, "R/B Channel: sRGB vs OLED (current vs corrected)")
ax2.plot(x8, srgb_display, color="#4af", lw=2,   label="macOS reference")
ax2.plot(x8, oled_raw_rb,  color="#f44", lw=1.5, label="OLED current")
ax2.plot(x8, corrected_rb, color="#fa4", lw=1.5, ls="--", label=f"After γ={GAMMA_EXP} LUT")
ax2.legend(facecolor="#222", edgecolor="#555", labelcolor="#ccc", fontsize=8)

# ── 3. G mismatch detail ─────────────────────────────────────────────────────
ax3 = fig.add_subplot(gs[1, 1])
styled_ax(ax3, "G Channel: sRGB vs OLED (C1 attenuation + corrected)")
ax3.plot(x8, srgb_display,            color="#4af", lw=2,   label="macOS reference")
ax3.plot(x8, oled_raw_g_contrasted,   color="#4f4", lw=1.5, label="OLED current (C1 attenuated)")
ax3.plot(x8, corrected_g,             color="#af4", lw=1.5, ls="--", label=f"After γ={GAMMA_EXP} + contrast boost")
ax3.legend(facecolor="#222", edgecolor="#555", labelcolor="#ccc", fontsize=8)

fig.suptitle("SSD1351 OLED vs macOS sRGB — Color Response Mismatch",
             color="#eee", fontsize=12, y=0.98)

plt.savefig("notes/viz_color_response.png", dpi=150, bbox_inches="tight",
            facecolor=fig.get_facecolor())
print("Saved → notes/viz_color_response.png")
plt.show()
