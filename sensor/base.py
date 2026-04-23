"""
sensor/base.py

Abstract base class for all sensor readers in DragonEyes.

Concrete implementations:
    sensor.reader.BNO055SensorReader   — direct I²C on Raspberry Pi
    mock.bno055_reader.SerialSensorReader — Arduino USB serial bridge (macOS dev)

Methods that accept a sensor reader should type-annotate with SensorReader so
they are independent of which implementation is running.
"""

import threading
from abc import ABC, abstractmethod


class SensorReader(threading.Thread, ABC):
    """Common interface for BNO055 attitude readers.

    Subclasses must implement all abstract properties and methods.
    The thread is started externally (via start()); subclasses drive their own
    run() loop and block inside _active.wait() while suspended.
    """

    # ── Sensor data ────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def euler_and_velocity(self) -> tuple[tuple[float, float, float], float]:
        """(euler, angular_velocity) in a single lock acquire."""
        ...

    @property
    @abstractmethod
    def linear_accel_magnitude(self) -> float:
        """Gravity-subtracted linear acceleration magnitude in m/s²."""
        ...

    @property
    @abstractmethod
    def fully_calibrated(self) -> bool:
        """True when the sensor reports full NDOF fusion (Sys=3)."""
        ...

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    @abstractmethod
    def suspend(self) -> None:
        """Pause polling and release hardware resources (power/port)."""
        ...

    @abstractmethod
    def resume(self) -> None:
        """Activate polling. Safe to call from the main thread at any time."""
        ...
