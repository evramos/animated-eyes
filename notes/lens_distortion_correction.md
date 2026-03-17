# Lens Distortion Correction

## Physical Lens Specs
- Outer Diameter: 40mm
- Inner Diameter: 37.5mm (clear aperture — nearly perfect match for the 38mm diagonal SSD1351 OLED)
- Height: 16mm
- Focal Length: 22mm

Screen sits inside the focal length (16mm < 22mm), so the lens acts as a magnifier producing
a virtual image that appears larger and slightly behind the lens surface — with barrel distortion at the edges.

---

## Why Distortion Is Fine for an Eye

A real cornea is a convex dome that naturally produces barrel distortion and makes the iris
appear to curve away at the edges. The lens physically replicates this effect, adding perceived
depth and realism. Leave it uncorrected for the eye display.

---

## Correcting Distortion for a Game / Flat Content

The lens causes **barrel distortion** (straight lines bow outward).
The fix is to pre-warp the rendered image with the inverse — **pincushion distortion** —
so the lens straightens it back out.

This is the same technique used by VR headsets (Oculus, Meta, etc.).

### The Math (Brown-Conrady Model)

```
r_corrected = r * (1 + k1·r² + k2·r⁴)
```

- `r` = pixel distance from screen center, normalized to [-1, 1]
- `k1` — primary coefficient; positive value pushes pixels outward (pincushion)
- `k2` — secondary coefficient; fine-tunes the outer edges
- Starting range for this lens: `k1 ≈ 0.1–0.3`, `k2 ≈ 0.05`

### GLSL Fragment Shader

Save as `shaders/distortion_correct.glsl` (fragment stage):

```glsl
uniform sampler2D tex0;
varying vec2 uv;

uniform float k1;
uniform float k2;

void main(void) {
    vec2 c = uv * 2.0 - 1.0;           // remap [0,1] → [-1,1] centered
    float r2 = dot(c, c);               // r²
    float warp = 1.0 + k1*r2 + k2*r2*r2;
    vec2 warped = c * warp;             // push pixels outward
    vec2 src = (warped + 1.0) * 0.5;   // back to [0,1]

    if (src.x < 0.0 || src.x > 1.0 || src.y < 0.0 || src.y > 1.0)
        gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0);  // black border outside
    else
        gl_FragColor = texture2D(tex0, src);
}
```

### pi3d Integration (two-pass render)

```python
post = pi3d.PostProcess(shader=pi3d.Shader("distortion_correct"))
post.set_uniform("k1", 0.15)   # tune against your lens
post.set_uniform("k2", 0.05)

# in your game loop:
post.start_capture()
    draw_game_scene()
post.end_capture()
post.draw()
```

### Tuning k1 / k2

1. Render a grid of straight lines on screen
2. Increase `k1` until the grid looks flat through the lens
3. Adjust `k2` only if the edges still bow after k1 is set

### Notes
- The black border at screen edges after correction is unavoidable —
  it's where the lens stretched pixel data in from outside the screen boundary
- VR headsets with ~40mm focal length typically use k1≈0.2, k2≈0.05
- This lens has a shorter focal length (22mm) → stronger distortion → start k1 higher (~0.2–0.3)
