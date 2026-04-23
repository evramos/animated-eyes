"""
mock/bno055_reader.py

SensorReader — reads the BNO055 sensor data streamed by the Arduino sketch
(arduino/bno055_serial/bno055_serial.ino) over USB serial at 115200 baud.

Exposes the same interface as sensor.reader.SensorReader, so the frame pipeline
is unaware of which implementation is running.

Arduino output format (two lines per sample, ~50 Hz):
    yaw,pitch,roll,gx,gy,gz,lax,lay,laz
    CALIBRATION: System=N Gyro=N Accelerometer=N Magnetometer=N

suspend() closes the serial port (saves USB power / OS resources).
resume() reopens it and resumes streaming. The Arduino keeps running; it just buffers until we reconnect.
"""

import math
import threading
import time

import serial
from serial.tools import list_ports

from sensor.base import SensorReader


class SerialSensorReader(SensorReader):
    """Reads the BNO055 sensor data from an Arduino over USB serial.

    Usage:
        reader = SensorReader() # auto-detect Arduino port
        reader.start()          #
        reader.resume()         # begin reading
        ...
        yaw, pitch, roll = reader.euler
        reader.suspend()       # close port; re-open with resume()

    If no port is given (or port is ""), the thread scans for the Arduino
    automatically and re-scans on disconnect, so unplug/replug is handled
    without restarting the process.
    """

    _BAUD        = 115200
    _TIMEOUT     = 0.1  # readline timeout in seconds — keeps loop responsive to suspend
    _RECONNECT_S = 2.0  # seconds to wait between reconnect attempts after a serial error

    _PROBE_CMD      = b"WHO\n"
    _PROBE_ACK      = "ACK:DRAGON_EYES_BNO055"
    _PROBE_BOOT     = 3.0  # seconds to wait after port open for Arduino DTR-reset + boot
    _PROBE_INTERVAL = 0.5  # seconds between WHO retries on the same open connection
    _PROBE_RETRIES  = 6    # WHO attempts per open connection before giving up on a port

    def __init__(self):
        super().__init__(daemon=True, name="SerialSensorReader")

        self._port    = None
        self._lock    = threading.Lock()
        self._active  = threading.Event()   # set = reading; clear = suspended

        # Cached sensor readings, updated under _lock
        self._euler:                  tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._angular_velocity:       float = 0.0
        self._linear_accel_magnitude: float = 0.0
        self._fully_calibrated:       bool  = False

        self._ser: serial.Serial | None = None

    # ── Public interface (mirrors AHRSReader exactly) ──────────────────────────

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
        """True when BNO055 reports Sys=3 (full NDOF sensor fusion active)."""
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
        """Try to open the serial port. Returns True on success."""
        try:
            self._ser = serial.Serial(self._port, self._BAUD, timeout=self._TIMEOUT)
            self._ser.reset_input_buffer()   # discard stale bytes from previous session
            return True
        except serial.SerialException as exc:
            print(f"[SensorReader] Cannot open {self._port}: {exc}")
            self._ser = None
            return False

    def _close_port(self):
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def _parse_csv(self, line: str):
        """Parse a CSV data line and update cached readings.

        Expected: yaw,pitch,roll,gx,gy,gz,lax,lay,laz
        """
        parts = line.split(',')
        if len(parts) != 9:
            return
        try:
            yaw, roll, pitch = float(parts[0]), float(parts[1]), float(parts[2])  # swap: BNO055 pitch/roll depend on chip orientation
            gx, gy, gz       = float(parts[3]), float(parts[4]), float(parts[5])
            lax, lay, laz    = float(parts[6]), float(parts[7]), float(parts[8])
        except ValueError:
            return

        with self._lock:
            self._euler                  = (yaw, pitch, roll)
            self._angular_velocity       = math.sqrt(gx * gx + gy * gy + gz * gz)
            self._linear_accel_magnitude = math.sqrt(lax * lax + lay * lay + laz * laz)

    def _parse_calibration(self, line: str):
        """Parse a Calibration line and update calibration status.

        Expected: Calibration: System=N, Gyro=N, Accelerometer=N, Magnetometer=N
        Sets fully_calibrated=True when System reaches 3 (full NDOF sensor fusion).
        """
        try:
            sys_idx = line.index("System=") + 7
            sys_val = int(line[sys_idx])
            with self._lock:
                self._fully_calibrated = (sys_val == 3)
        except (ValueError, IndexError):
            pass

    def _find_arduino_port(self) -> str | None:
        """Scan USB serial ports for the BNO055 Arduino sketch.

        Sends a WHO probe to each candidate port and waits for ACK:DRAGON_EYES_BNO055.
        Blocks indefinitely until the device is found.

        The port is opened once per candidate and WHO is retried on the same connection
        (_PROBE_RETRIES times, _PROBE_INTERVAL apart) so the Arduino only resets once
        via DTR instead of being reset on every retry.
        """

        _warned_no_ports = False
        while True:
            candidates = [p.device for p in list_ports.comports() if p.vid is not None]
            if not candidates:
                if not _warned_no_ports:
                    print("[SensorReader] No USB serial ports found — retrying...")
                    _warned_no_ports = True
                time.sleep(self._RECONNECT_S)
                continue

            _warned_no_ports = False

            print(f"[SensorReader] Probing {len(candidates)} USB port(s): {candidates}")

            for port in candidates:
                try:
                    with serial.Serial(port, self._BAUD, timeout=self._PROBE_INTERVAL) as s:
                        # One boot wait per port open — Arduino only resets here via DTR.
                        time.sleep(self._PROBE_BOOT)
                        s.reset_input_buffer()

                        for _ in range(self._PROBE_RETRIES):
                            s.write(self._PROBE_CMD)
                            deadline = time.monotonic() + self._PROBE_INTERVAL
                            while time.monotonic() < deadline:
                                line = s.readline().decode("ascii", errors="replace").strip()
                                if line == self._PROBE_ACK:
                                    print(f"[SensorReader] Found Arduino on {port}")
                                    return port
                except (serial.SerialException, OSError):
                    continue

            print("[SensorReader] No Arduino found — retrying...")
            time.sleep(self._RECONNECT_S)

    def run(self):
        # _last_log = 0.0
        while True:
            self._active.wait()   # blocks at zero CPU cost while suspended

            if self._port is None:
                self._port = self._find_arduino_port()   # blocks thread until found

            if self._ser is None:
                if not self._open_port():
                    # Port unavailable — wait before retrying so we don't spin
                    time.sleep(self._RECONNECT_S)
                    continue

            try:
                raw = self._ser.readline()
            except serial.SerialException as exc:
                print(f"[SensorReader] Read error on {self._port}: {exc}")
                self._close_port()
                self._port = None   # re-scan on next iteration; device may have re-enumerated
                time.sleep(self._RECONNECT_S)
                continue

            if not raw:
                # readline() timed out (no data) — loop and check _active again
                continue

            line = raw.decode("ascii", errors="replace").strip()
            # now = time.monotonic()
            # if now - _last_log >= 1.0:
            print(f"[SensorReader] {line}")
                # _last_log = now

            if line.startswith("Calibration:"):
                self._parse_calibration(line)
            elif line and line[0].isdigit() or (line and line[0] == '-'):
                self._parse_csv(line)
