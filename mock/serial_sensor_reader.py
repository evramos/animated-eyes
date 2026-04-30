"""
mock/serial_sensor_reader.py

Base class and concrete subclasses for DragonEyes Arduino USB serial readers.
Both Arduino sketches share the same wire format, so all logic lives here;
subclasses only differ in the WHO/ACK handshake string and log prefix.

    SerialBNO055Reader — targets bno055_serial.ino  (ACK:DRAGON_EYES_BNO055)
    SerialBNO08xReader — targets bno08x_serial.ino  (ACK:DRAGON_EYES_BNO08X)

Wire format (shared by both sketches, ~50 Hz, 115200 baud):
    QUATERNION mode (default, 10 fields):
        w,x,y,z,gx,gy,gz,lax,lay,laz
    EULER mode (9 fields, after TOGGLE_ANGLE_TYPE):
        yaw,pitch,roll,gx,gy,gz,lax,lay,laz
    (both modes):
        Calibration: System=N, Gyro=N, Accelerometer=N, Magnetometer=N

Calibration note (BNO085 / BNO08x):
    Saves calibration automatically to internal flash via DCD — no EEPROM.
    System/Gyro/Accel reflect the SH2 ROTATION_VECTOR accuracy (0-3).
    Magnetometer is always 0 (fused internally, not reported separately).
    fully_calibrated becomes True when System reaches 3, same as BNO055.

suspend() closes the serial port (saves USB power / OS resources).
resume() reopens it and resumes streaming. The Arduino keeps running; it just
buffers until we reconnect.
"""

import math
import threading
import time

import serial
from serial.tools import list_ports

from sensor.base import SensorReader, SensorSnapshot


class SerialSensorReader(SensorReader):
    """USB serial reader for DragonEyes Arduino sensor sketches.

    Subclasses set _PROBE_ACK to match the sketch's response to WHO, and
    _LOG_PREFIX for per-device log lines.

    Usage:
        reader = SerialBNO055Reader()   # or SerialBNO08xReader()
        reader.start()
        reader.resume()                 # begin reading
        ...
        snap = reader.snapshot()
        reader.suspend()                # close port; re-open with resume()

    If the port is not found the thread scans all USB serial ports
    automatically and re-scans on disconnect, so unplug/replug is handled
    without restarting the process.
    """

    _BAUD        = 115200
    _TIMEOUT     = 0.1    # readline timeout — keeps loop responsive to suspend
    _RECONNECT_S = 2.0    # seconds between reconnect attempts after a serial error

    _PROBE_CMD      = b"WHO\n"
    _PROBE_ACK      = ""        # must be overridden by subclass
    _PROBE_BOOT     = 3.0       # seconds after port open for Arduino DTR-reset + boot
    _PROBE_INTERVAL = 0.5       # seconds between WHO retries on the same connection
    _PROBE_RETRIES  = 6         # WHO attempts per open connection before giving up

    _BUMP_THRESHOLD  = 8.0      # Euclidean distance (m/s²) between consecutive laccel samples
    _BUMP_DEBOUNCE_S = 0.3      # seconds to ignore further bumps after one fires

    _LOG_PREFIX = "SensorReader"  # overridden by subclasses for distinct log labels

    def __init__(self, *, name: str):
        super().__init__(daemon=True, name=name)

        self._port   = None
        self._lock   = threading.Lock()
        self._active = threading.Event()   # set = reading; clear = suspended

        # Cached sensor readings, updated under _lock
        self._quaternion:             tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
        self._angular_velocity:       float = 0.0
        self._linear_accel_magnitude: float = 0.0
        self._fully_calibrated:       bool  = False

        # Bump detection state
        self._prev_laccel:   tuple[float, float, float] | None = None
        self._bump_detected: bool  = False
        self._last_bump_t:   float = 0.0

        self._ser: serial.Serial | None = None

    # ── Public interface ───────────────────────────────────────────────────────

    def snapshot(self) -> SensorSnapshot:
        """Capture quaternion, angular_velocity, and bump_detected in a single lock acquire."""
        with self._lock:
            return SensorSnapshot(
                angular_velocity=self._angular_velocity,
                bump_detected=self._bump_detected_action(),
                fully_calibrated=self._fully_calibrated,
                quaternion=self._quaternion,
            )

    @property
    def linear_accel_magnitude(self) -> float:
        """Gravity-subtracted linear acceleration magnitude in m/s²."""
        with self._lock:
            return self._linear_accel_magnitude

    def _bump_detected_action(self) -> bool:
        fired = self._bump_detected
        self._bump_detected = False
        return fired

    @property
    def bump_detected(self) -> bool:
        """True if a bump was detected since the last read. Clears on read."""
        with self._lock:
            return self._bump_detected_action()

    @property
    def fully_calibrated(self) -> bool:
        """True when sensor accuracy reaches 3 (high accuracy / full NDOF)."""
        with self._lock:
            return self._fully_calibrated

    # ── Power management ───────────────────────────────────────────────────────

    def suspend(self):
        """Stop reading and close the serial port.

        The Arduino continues streaming; data is discarded until resume() is called.
        Closing the port also releases the OS file descriptor.
        """
        self._active.clear()
        self._close_port()

    def resume(self):
        """Open the serial port and start reading.

        Safe to call from the main thread at any time, including before start().
        """
        self._active.set()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _open_port(self) -> bool:
        try:
            self._ser = serial.Serial(self._port, self._BAUD, timeout=self._TIMEOUT)
            self._ser.reset_input_buffer()
            return True
        except serial.SerialException as exc:
            print(f"[{self._LOG_PREFIX}] Cannot open {self._port}: {exc}")
            self._ser = None
            return False

    def _close_port(self):
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    @staticmethod
    def _euler_to_quat(yaw_deg: float, pitch_deg: float, roll_deg: float) -> tuple[float, float, float, float]:
        """Convert (yaw, pitch, roll) in degrees to a unit quaternion (w, x, y, z).

        ZYX / aerospace convention — used when Arduino is streaming in EULER mode (9 fields).
        """
        y = math.radians(yaw_deg)   * 0.5
        p = math.radians(pitch_deg) * 0.5
        r = math.radians(roll_deg)  * 0.5
        cy, sy = math.cos(y), math.sin(y)
        cp, sp = math.cos(p), math.sin(p)
        cr, sr = math.cos(r), math.sin(r)
        return (
            cr * cp * cy + sr * sp * sy,
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
        )

    def _parse_csv(self, line: str):
        """Parse a CSV data line and update cached readings.

        Routes by field count:
            9 fields  — EULER:      yaw,pitch,roll,gx,gy,gz,lax,lay,laz
            10 fields — QUATERNION: w,x,y,z,gx,gy,gz,lax,lay,laz
        Euler angles are converted to a unit quaternion before storing.
        """
        parts = line.split(',')
        n = len(parts)
        if n not in (9, 10):
            return
        try:
            if n == 10:
                w, x, y, z   = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
                quaternion    = (w, x, y, z)
                gx, gy, gz    = float(parts[4]), float(parts[5]), float(parts[6])
                lax, lay, laz = float(parts[7]), float(parts[8]), float(parts[9])
            else:
                yaw, pitch, roll = float(parts[0]), float(parts[1]), float(parts[2])
                quaternion        = self._euler_to_quat(yaw, pitch, roll)
                gx, gy, gz        = float(parts[3]), float(parts[4]), float(parts[5])
                lax, lay, laz     = float(parts[6]), float(parts[7]), float(parts[8])
        except ValueError:
            return

        linear_acceleration = (lax, lay, laz)
        angular_velocity    = math.sqrt(gx * gx + gy * gy + gz * gz)

        with self._lock:
            self._quaternion             = quaternion
            self._angular_velocity       = angular_velocity
            self._linear_accel_magnitude = math.sqrt(lax * lax + lay * lay + laz * laz)
            self._prev_laccel            = linear_acceleration

    def _parse_calibration(self, line: str):
        """Parse a Calibration line and update calibration status.

        Expected: Calibration: System=N, Gyro=N, Accelerometer=N, Magnetometer=N
        Sets fully_calibrated=True when System reaches 3.
        """
        try:
            sys_idx = line.index("System=") + 7
            sys_val = int(line[sys_idx])
            with self._lock:
                self._fully_calibrated = (sys_val == 3)
        except (ValueError, IndexError):
            pass

    def _find_arduino_port(self) -> str | None:
        """Scan USB serial ports for the target Arduino sketch.

        Sends a WHO probe to each candidate port and waits for _PROBE_ACK.
        Blocks indefinitely until the device is found.

        The port is opened once per candidate and WHO is retried (_PROBE_RETRIES
        times, _PROBE_INTERVAL apart) so the Arduino only resets once via DTR
        instead of being reset on every retry.
        """
        _warned_no_ports = False
        while True:
            candidates = [p.device for p in list_ports.comports() if p.vid is not None]
            if not candidates:
                if not _warned_no_ports:
                    print(f"[{self._LOG_PREFIX}] No USB serial ports found — retrying...")
                    _warned_no_ports = True
                time.sleep(self._RECONNECT_S)
                continue

            _warned_no_ports = False
            print(f"[{self._LOG_PREFIX}] Probing {len(candidates)} USB port(s): {candidates}")

            for port in candidates:
                try:
                    with serial.Serial(port, self._BAUD, timeout=self._PROBE_INTERVAL) as s:
                        time.sleep(self._PROBE_BOOT)
                        s.reset_input_buffer()

                        for _ in range(self._PROBE_RETRIES):
                            s.write(self._PROBE_CMD)
                            deadline = time.monotonic() + self._PROBE_INTERVAL
                            while time.monotonic() < deadline:
                                line = s.readline().decode("ascii", errors="replace").strip()
                                if line == self._PROBE_ACK:
                                    print(f"[{self._LOG_PREFIX}] Found Arduino on {port}")
                                    return port
                except (serial.SerialException, OSError):
                    continue

            print(f"[{self._LOG_PREFIX}] No Arduino found — retrying...")
            time.sleep(self._RECONNECT_S)

    def run(self):
        while True:
            self._active.wait()

            if self._port is None:
                self._port = self._find_arduino_port()

            if self._ser is None:
                if not self._open_port():
                    time.sleep(self._RECONNECT_S)
                    continue

            try:
                raw = self._ser.readline()
            except serial.SerialException as exc:
                print(f"[{self._LOG_PREFIX}] Read error on {self._port}: {exc}")
                self._close_port()
                self._port = None
                time.sleep(self._RECONNECT_S)
                continue

            if not raw:
                continue

            line = raw.decode("ascii", errors="replace").strip()
            print(f"[{self._LOG_PREFIX}] {line}")

            if line.startswith("Calibration:"):
                self._parse_calibration(line)
            elif line and (line[0].isdigit() or line[0] == '-'):
                self._parse_csv(line)


class SerialBNO055Reader(SerialSensorReader):
    _PROBE_ACK  = "ACK:DRAGON_EYES_BNO055"
    _LOG_PREFIX = "BNO055Reader"
    def __init__(self): super().__init__(name="SerialBNO055Reader")


class SerialBNO08xReader(SerialSensorReader):
    _PROBE_ACK  = "ACK:DRAGON_EYES_BNO08X"
    _LOG_PREFIX = "BNO08xReader"
    def __init__(self): super().__init__(name="SerialBNO08xReader")
