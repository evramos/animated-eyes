"""
sensor/reader.py

Background thread that reads the Adafruit BNO055 9-DOF IMU at ~50 Hz over I²C.
Exposes euler angles, angular velocity magnitude, linear acceleration magnitude,
and calibration status as thread-safe properties.

Power states:
  Starts suspended (~40µA, retains calibration) immediately after init.
  Call resume() to activate; suspend() to park again.

Wiring (shares existing I²C bus with Snake Eyes Bonnet):
  VIN → 3.3V
  GND → GND
  SDA → GPIO 2
  SCL → GPIO 3
  RST → GPIO BNO_RST_PIN  (or leave unconnected; set BNO_RST_PIN = -1)
"""

import math
import time
import threading
from typing import NamedTuple

import board
import busio
import adafruit_bno055

from sensor.base import SensorReader


class CalibrationStatus(NamedTuple):
    system:        int  # 0–3: overall sensor fusion quality
    gyroscope:     int  # 0–3: gyroscope calibration
    accelerometer: int  # 0–3: accelerometer calibration
    magnetometer:  int  # 0–3: magnetometer calibration


class BNO055SensorReader(SensorReader):
    """Reads BNO055 IMU sensor in the background over I²C.

    Instantiate, then call start() once from init. The thread begins suspended — call resume() when GYRO mode
    is selected, suspend() when leaving those modes.
    """

    _PERIOD = 1.0 / 50.0  # 50 Hz poll rate

    def __init__(self):
        super().__init__(daemon=True, name="BNO055SensorReader")

        self._lock   = threading.Lock()
        self._active = threading.Event() # set = polling; clear = suspended

        # Cached sensor readings, updated under _lock
        self._euler:                   tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._angular_velocity:        float             = 0.0
        self._linear_accel_magnitude:  float             = 0.0
        self._fully_calibrated:        bool              = False
        self._calibration_status:      CalibrationStatus = CalibrationStatus(0, 0, 0, 0)

        # Set up I²C and sensor
        self._i2c = busio.I2C(board.SCL, board.SDA)
        self._bno = adafruit_bno055.BNO055_I2C(self._i2c)

        # Park in suspend immediately — saves power until GYRO mode is selected
        self._power_suspend()

    # ── Public properties ──────────────────────────────────────────────────────

    @property
    def euler_and_velocity(self) -> tuple[tuple[float, float, float], float]:
        """(euler, angular_velocity) in a single lock acquire."""
        with self._lock:
            return self._euler, self._angular_velocity

    @property
    def linear_accel_magnitude(self) -> float:
        """Gravity-subtracted linear acceleration magnitude in m/s². Used for bump detection."""
        with self._lock:
            return self._linear_accel_magnitude

    @property
    def fully_calibrated(self) -> bool:
        """True when all four BNO055 sensors report calibration level 3 (Sys=3)."""
        with self._lock:
            return self._fully_calibrated

    @property
    def calibration_status(self) -> CalibrationStatus:
        """Per-sensor calibration levels (0=uncalibrated, 3=fully calibrated).

        Returns a CalibrationStatus(system, gyro, accel, mag) named tuple.
        """
        with self._lock:
            return self._calibration_status

    # ── Power management ───────────────────────────────────────────────────────

    def suspend(self):
        """Pause polling and software-suspend the BNO055 (~40µA).

        Calibration data is retained; resume() wakes the sensor in milliseconds with no recalibration needed.
        Prefer this over reset() for routine mode switching.
        """
        self._active.clear()
        self._power_suspend()

    def resume(self):
        """Wake BNO055 from suspend and start polling. Safe to call from the main thread at any time."""
        self._power_normal()
        self._active.set()


    # ── Internal ───────────────────────────────────────────────────────────────

    def _power_suspend(self):
        # CONFIG_MODE must be set before changing the power register.
        self._bno.mode = adafruit_bno055.CONFIG_MODE
        self._bno.set_suspend_mode()

    def _power_normal(self):
        self._bno.set_normal_mode()
        self._bno.mode = adafruit_bno055.NDOF_MODE

    def _poll(self):
        """Read one sample from the sensor and update cached values."""
        try:
            # adafruit_bno055 returns (heading, roll, pitch); remap to (yaw, pitch, roll)
            raw = self._bno.euler
            heading, roll, pitch = raw if raw else (0.0, 0.0, 0.0)

            # Gyro angular velocity (°/s); compute scalar magnitude
            gyro = self._bno.gyro
            gx, gy, gz = gyro if gyro else (0.0, 0.0, 0.0)
            av = math.sqrt(gx * gx + gy * gy + gz * gz)

            # Gravity-subtracted linear acceleration (m/s²); scalar magnitude for bump detection
            la = self._bno.linear_acceleration
            lax, lay, laz = la if la else (0.0, 0.0, 0.0)
            lam = math.sqrt(lax * lax + lay * lay + laz * laz)

            cal_status = CalibrationStatus._make(self._bno.calibration_status)

            with self._lock:
                self._euler                  = (heading, pitch, roll)
                self._angular_velocity       = av
                self._linear_accel_magnitude = lam
                self._fully_calibrated       = (cal_status.system == 3)
                self._calibration_status     = cal_status

        except OSError:
            # Transient I²C errors (bus glitch, sensor briefly unresponsive)
            # are non-fatal — keep running and retry next cycle.
            pass

    def run(self):
        while True:
            self._active.wait()   # blocks at zero CPU cost while suspended
            self._poll()
            time.sleep(self._PERIOD)
