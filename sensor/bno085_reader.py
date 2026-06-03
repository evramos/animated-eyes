"""
sensor/bno085_reader.py

Background thread that reads the Adafruit BNO085 9-DOF IMU at ~50 Hz over I²C.
Uses GAME_ROTATION_VECTOR (gyro + accel, no magnetometer) for immediate
relative-orientation tracking — equivalent to IMUPLUS_MODE on the BNO055.

Key differences from BNO055SensorReader:
  - Reports must be enabled explicitly before reading.
  - game_quaternion returns (i, j, k, real) — reordered to (w, x, y, z) internally.
  - Gyroscope values are in rad/s — converted to °/s for pipeline consistency.
  - No hardware suspend via CircuitPython; suspend() pauses polling only (~6mA idle).

Wiring (shares existing I²C bus with Snake Eyes Bonnet):
  VIN → 3.3V
  GND → GND
  SDA → GPIO 2
  SCL → GPIO 3
"""

import math
import time
import threading

import board
import busio
from adafruit_bno08x import (
    BNO_REPORT_GAME_ROTATION_VECTOR,
    BNO_REPORT_GYROSCOPE,
    BNO_REPORT_LINEAR_ACCELERATION,
)
from adafruit_bno08x.i2c import BNO08X_I2C

from constants import DEBUG_SENSOR
from sensor.base import SensorReader, SensorSnapshot

_RAD_TO_DEG = 180.0 / math.pi


class BNO085SensorReader(SensorReader):
    """Reads BNO085 IMU sensor in the background over I²C.

    Instantiate, then call start() once from init. The thread begins suspended — call resume() when GYRO mode
    is selected, suspend() when leaving those modes.
    """

    _PERIOD = 1.0 / 50.0  # 50 Hz poll rate

    def __init__(self):
        super().__init__(daemon=True, name="BNO085SensorReader")

        self._lock   = threading.Lock()
        self._active = threading.Event()  # set = polling; clear = suspended

        # Cached sensor readings, updated under _lock
        self._quaternion:             tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
        self._angular_velocity:       float = 0.0
        self._linear_accel_magnitude: float = 0.0
        self._fully_calibrated:       bool  = False

        # Set up I²C and sensor
        # Default address is 0x4A; bridge the ADR pad on the breakout for 0x4B
        self._i2c = busio.I2C(board.SCL, board.SDA)
        self._bno = BNO08X_I2C(self._i2c, address=0x4A)
        self._enable_reports()

        self._debug_tick: int = 0

        # Park in suspend immediately — thread blocks until resume() is called
        # Note: BNO085 has no software suspend register; sensor stays powered (~6mA)

    # ── Public properties ──────────────────────────────────────────────────────

    def snapshot(self) -> SensorSnapshot:
        """Capture quaternion, angular_velocity, and bump_detected in a single lock acquire."""
        with self._lock:
            # TODO - Update bump_detected when implementing bump detection based on linear_accel_magnitude threshold.
            return SensorSnapshot(
                angular_velocity=self._angular_velocity,
                bump_detected=False,
                fully_calibrated=self._fully_calibrated,
                quaternion=self._quaternion,
            )

    @property
    def linear_accel_magnitude(self) -> float:
        """Gravity-subtracted linear acceleration magnitude in m/s². Used for bump detection."""
        with self._lock:
            return self._linear_accel_magnitude

    @property
    def fully_calibrated(self) -> bool:
        """True once the gyro bias has been learned (gyr accuracy ≥ 2 on the 0–3 scale)."""
        with self._lock:
            return self._fully_calibrated

    # ── Power management ───────────────────────────────────────────────────────

    def suspend(self):
        """Pause polling. The BNO085 has no software suspend register; sensor stays powered.

        Calibration data is retained. resume() resumes polling immediately with no
        recalibration needed.
        """
        self._active.clear()

    def resume(self):
        """Start polling. Safe to call from the main thread at any time."""
        self._active.set()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _enable_reports(self):
        self._bno.enable_feature(BNO_REPORT_GAME_ROTATION_VECTOR)
        self._bno.enable_feature(BNO_REPORT_GYROSCOPE)
        self._bno.enable_feature(BNO_REPORT_LINEAR_ACCELERATION)

    def _poll(self):
        """Read one sample from the sensor and update cached values."""
        try:
            # Gyro angular velocity (rad/s → °/s); compute scalar magnitude
            gyro = self._bno.gyro
            gx, gy, gz = gyro if gyro and None not in gyro else (0.0, 0.0, 0.0)
            gx_deg, gy_deg, gz_deg = gx * _RAD_TO_DEG, gy * _RAD_TO_DEG, gz * _RAD_TO_DEG
            av = math.sqrt(gx_deg * gx_deg + gy_deg * gy_deg + gz_deg * gz_deg)

            # Gravity-subtracted linear acceleration (m/s²); scalar magnitude for bump detection
            la = self._bno.linear_acceleration
            lax, lay, laz = la if la and None not in la else (0.0, 0.0, 0.0)
            lam = math.sqrt(lax * lax + lay * lay + laz * laz)

            # BNO085 returns (i, j, k, real) — reorder to pipeline convention (w, x, y, z)
            raw_q = self._bno.game_quaternion
            if raw_q and None not in raw_q:
                qi, qj, qk, qreal = raw_q
                qw, qx, qy, qz = qreal, qi, qj, qk
            else:
                qw, qx, qy, qz = 1.0, 0.0, 0.0, 0.0

            # BNO085 doesn't expose calibration levels; use gyro activity as a proxy
            calibrated = av > 0.0 or (qx != 0.0 or qy != 0.0 or qz != 0.0)

            with self._lock:
                self._quaternion             = (qw, qx, qy, qz)
                self._angular_velocity       = av
                self._linear_accel_magnitude = lam
                self._fully_calibrated       = calibrated

            if DEBUG_SENSOR:
                self._debug_tick += 1
                if self._debug_tick % 50 == 0:  # ~1 Hz at 50 Hz poll rate
                    print(
                        f"[BNO085] q=({qw:+.3f} {qx:+.3f} {qy:+.3f} {qz:+.3f})"
                        f"  av={av:5.1f}°/s  la={lam:.2f}m/s²"
                        f"  cal={'ready' if calibrated else 'warming'}"
                    )

        except OSError:
            # Transient I²C errors (bus glitch, sensor briefly unresponsive)
            # are non-fatal — keep running and retry next cycle.
            pass

    def run(self):
        while True:
            self._active.wait()   # blocks at zero CPU cost while suspended
            self._poll()
            time.sleep(self._PERIOD)
