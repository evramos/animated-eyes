# AHRS Eye Position Modes

Three implementations of eye position driving from IMU head orientation, all living in
`pipeline/stages.py`. Each is a drop-in for the other — same signature:

```python
def _update_ahrs_position_*(now, eyes, snap, ahrs, dt)
```

---

## `_update_ahrs_position_binary` (line 117)

**How it works:**
- Computes `q_delta = q_current ∘ q_neutral⁻¹` — relative rotation since neutral.
- Drives eye position at full strength while angular velocity exceeds `STILL_THRESHOLD_BINARY`.
- When velocity drops below threshold, the eye target is NOT zeroed — it just stops updating.
  The lerp continues driving toward the last computed target.
- Neutral recalibrates after `RECAL_DELAY_BINARY` seconds of continuous stillness.

**Problem:** The threshold crossing causes **jitter** — gyro noise oscillates the velocity
signal around the threshold, making the eye stutter on/off during slow movement or return.

---

## `_update_ahrs_position_blended` (line 151)

**How it works:**
- Same relative quaternion delta approach as binary.
- `follow_blend = min(1.0, velocity / STILL_THRESHOLD_BLENDED)` — a continuous 0→1 weight.
- Eye target = `rotation * follow_blend`, so deflection scales linearly with angular velocity.
- **180° guard:** if `abs(q_delta.w) < 0.15` (>~162° from neutral), snaps neutral forward
  to prevent the `atan2` sign flip that would cause the eye to jump to the opposite extreme.
- **Deadband:** `follow_blend < 0.15` → target snaps to `(0, 0)` instead of the noisy
  near-zero rotation value. Eliminates jitter at the return-to-center transition.
- Neutral recalibrates after `RECAL_DELAY_BLENDED` seconds of stillness.
- Uses `tanh` soft-clamp instead of hard ±30° clamp for smoother edge behavior.

**Advantages over binary:** No threshold-crossing jitter; smooth fade on deceleration;
sustained head tilt absorbed by recalibration without visible pop.

---

## `_update_ahrs_position_worldframe` (planned — not yet implemented)

**Concept:**
Rather than computing a relative delta from a neutral reference, use the sensor's
**absolute world-frame rotation vector** directly. The BNO08x (and BNO055 in NDOF mode)
outputs orientation relative to a fixed world frame (gravity = −Z, magnetic north = +X).

**How it would work:**
- Extract absolute yaw and pitch directly from `q_current` in world frame.
- Map yaw/pitch offsets from a fixed forward direction to eye X/Y.
- No neutral tracking, no recalibration delay, no drift accumulation.
- Eyes always point toward a fixed point in the room regardless of where the head started.

**Trade-offs:**
- Requires the sensor to be fully calibrated (magnetometer must lock onto north).
  On the BNO08x this is the `ROTATION_VECTOR` report (game rotation vector skips mag).
- Absolute yaw from magnetometer is sensitive to nearby magnetic interference (motors, cables).
- No "neutral absorb" means a sustained head tilt keeps the eyes deflected permanently,
  which may feel unnatural for a wearable or prop.
- Would suit a **fixed-mount** scenario better than head-worn (e.g. animatronic head on a stand).

**Possible implementation sketch:**
```python
# Extract world-frame yaw and pitch from absolute quaternion
# (forward vector = (1,0,0) in sensor frame)
gx, gy, gz = _quat_apply(q_current, (1.0, 0.0, 0.0))
yaw_abs   = -math.degrees(math.atan2(gy, gx))
pitch_abs =  math.degrees(math.atan2(gz, math.sqrt(gx*gx + gy*gy)))

# Map to eye range — subtract a fixed "forward" reference captured at startup
target_x = max(-30.0, min(30.0, (yaw_abs   - ahrs.forward_yaw)   * SENSITIVITY_X))
target_y = max(-30.0, min(30.0, (pitch_abs - ahrs.forward_pitch) * SENSITIVITY_Y))
```

---

## Comparison

| Feature                  | binary         | blended         | worldframe (planned) |
|--------------------------|----------------|-----------------|----------------------|
| Jitter on deceleration   | Yes            | No (deadband)   | Depends on mag noise |
| Neutral recalibration    | Yes            | Yes             | No                   |
| Sustained tilt absorbed  | Yes            | Yes             | No                   |
| Requires mag calibration | No             | No              | Yes                  |
| 180° guard needed        | No             | Yes             | No                   |
| Best use case            | Simple test    | Head-worn prop  | Fixed-mount animatronic |
