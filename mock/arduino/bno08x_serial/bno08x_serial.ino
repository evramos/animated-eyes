/*
 * bno08x_serial.ino
 *
 * Reads the Adafruit BNO085 9-DOF IMU and streams sensor data over USB serial
 * at ~50 Hz for use with DragonEyes SerialBNO08xReader on macOS.
 *
 * Output format (two lines per sample, 115200 baud) — identical to bno055_serial:
 *   QUATERNION mode (default, 10 fields):
 *     w,x,y,z,gx,gy,gz,lax,lay,laz\n
 *   EULER mode (9 fields, after TOGGLE_ANGLE_TYPE):
 *     yaw,pitch,roll,gx,gy,gz,lax,lay,laz\n
 *   (both modes):
 *     Calibration: System=N, Gyro=N, Accelerometer=N, Magnetometer=0\n
 *
 *   w/x/y/z         — Unit quaternion (ROTATION_VECTOR report)
 *   yaw/pitch/roll  — Euler in degrees, computed from quaternion (ZYX convention)
 *   gx/gy/gz        — Gyro angular velocity in °/s (converted from rad/s)
 *   lax/lay/laz     — Gravity-subtracted linear acceleration in m/s²
 *   System/Gyro/Accel N — SH2 accuracy status 0-3 (3 = fully calibrated)
 *                         Magnetometer always 0 (ROTATION_VECTOR fuses internally)
 *
 * Calibration differences from BNO055:
 *   The BNO085 saves calibration automatically to internal flash via DCD
 *   (Dynamic Calibration Data). No EEPROM is needed. A single explicit
 *   sh2_saveDcdNow() call is made once per session when accuracy reaches 3,
 *   which commits the current calibration to flash for next boot.
 *   CLEAR resets the in-session save flag so calibration will NOT be re-saved
 *   this session; the previously saved flash data remains until a new save occurs.
 *
 * Serial commands (sent from host):
 *   WHO               → ACK:DRAGON_EYES_BNO08X  (port auto-detection handshake)
 *   CLEAR             → reset in-session calibration save flag (see note above)
 *   TOGGLE_DATA       → toggle CSV data output on/off
 *   TOGGLE_ANGLE_TYPE → switch between QUATERNION (10 fields) and EULER (9 fields)
 *
 * Wiring (Arduino Micro or similar):
 *   BNO085 VIN  → 3.3V (Adafruit breakout has onboard regulator; 5V is fine too)
 *   BNO085 GND  → GND
 *   BNO085 SDA  → SDA (D2 on Micro)
 *   BNO085 SCL  → SCL (D3 on Micro)
 *   BNO085 PS0  → GND  (selects I2C mode on Adafruit breakout)
 *   BNO085 PS1  → GND
 *
 * Dependencies (install via Arduino Library Manager):
 *   - Adafruit BNO08x
 *   - Adafruit BusIO
 */

#include <Wire.h>
#include <Adafruit_BNO08x.h>

// -1 = no dedicated RESET pin wired; the library leaves reset unused
#define BNO08X_RESET -1

// ~50 Hz output cadence; the sensor itself reports at 100 Hz (10 000 µs)
#define SAMPLERATE_MS 20

Adafruit_BNO08x bno08x(BNO08X_RESET);
sh2_SensorValue_t sensorValue;

// Latest decoded sensor state (updated from SH2 events, read in output phase)
float qw = 1.0f, qx = 0.0f, qy = 0.0f, qz = 0.0f;
float gx = 0.0f, gy = 0.0f, gz = 0.0f;     // deg/s
float lax = 0.0f, lay = 0.0f, laz = 0.0f;  // m/s²
uint8_t rotAccuracy = 0;                   // 0-3 from SH2 status field

bool useQuaternion = true;  // true = 10-field quat; false = 9-field euler
bool printData = true;
bool calibrationSaved = false;  // write once per session when accuracy == 3

unsigned long lastSampleMs = 0;

// ── Report setup ─────────────────────────────────────────────────────────────

void setReports() {
  // 10 000 µs = 100 Hz — sensor delivers events at this rate; we output at 50 Hz
  if (!bno08x.enableReport(SH2_ROTATION_VECTOR, 10000)) {
    Serial.println(F("Could not enable ROTATION_VECTOR report"));
  }
  if (!bno08x.enableReport(SH2_GYROSCOPE_CALIBRATED, 10000)) {
    Serial.println(F("Could not enable GYROSCOPE_CALIBRATED report"));
  }
  if (!bno08x.enableReport(SH2_LINEAR_ACCELERATION, 10000)) {
    Serial.println(F("Could not enable LINEAR_ACCELERATION report"));
  }
}

// ── Setup ─────────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  if (!bno08x.begin_I2C()) {
    Serial.println(F("BNO08x not detected — check wiring, PS0/PS1 grounded, I2C address 0x4A"));
    while (1) delay(10);
  }

  setReports();
  Serial.println(F("BNO08x ready — calibrating, move sensor in figure-8 pattern"));
}

// ── Loop ──────────────────────────────────────────────────────────────────────

void loop() {
  // Handle serial commands from host
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "WHO") {
      Serial.println(F("ACK:DRAGON_EYES_BNO08X"));
    } else if (cmd == "CLEAR") {
      // Resets the in-session save flag; previously committed flash data is not erased.
      // Un-comment bno08x.hardwareReset() if you need a full sensor reset.
      calibrationSaved = false;
      Serial.println(F("Calibration save flag reset — will re-save when accuracy reaches 3"));
    } else if (cmd == "TOGGLE_DATA") {
      printData = !printData;
      Serial.print(F("Data output: "));
      Serial.println(printData ? F("ON") : F("OFF"));
    } else if (cmd == "TOGGLE_ANGLE_TYPE") {
      useQuaternion = !useQuaternion;
      Serial.print(F("Angle type: "));
      Serial.println(useQuaternion ? F("QUATERNION (10 fields)") : F("EULER (9 fields)"));
    }
  }

  // Drain all pending SH2 events — each getSensorEvent() call returns one report
  while (bno08x.getSensorEvent(&sensorValue)) {
    switch (sensorValue.sensorId) {
      case SH2_ROTATION_VECTOR:
        qw = sensorValue.un.rotationVector.real;
        qx = sensorValue.un.rotationVector.i;
        qy = sensorValue.un.rotationVector.j;
        qz = sensorValue.un.rotationVector.k;
        // bits 0-1 of status field carry the SH2 accuracy estimate (0=unreliable, 3=high)
        rotAccuracy = sensorValue.status & 0x03;
        break;
      case SH2_GYROSCOPE_CALIBRATED:
        // SH2 delivers rad/s — convert to deg/s to match BNO055 output
        gx = sensorValue.un.gyroscope.x * (180.0f / M_PI);
        gy = sensorValue.un.gyroscope.y * (180.0f / M_PI);
        gz = sensorValue.un.gyroscope.z * (180.0f / M_PI);
        break;
      case SH2_LINEAR_ACCELERATION:
        lax = sensorValue.un.linearAcceleration.x;
        lay = sensorValue.un.linearAcceleration.y;
        laz = sensorValue.un.linearAcceleration.z;
        break;
    }
  }

  // Output at ~50 Hz
  unsigned long now = millis();
  if (now - lastSampleMs < SAMPLERATE_MS) return;
  lastSampleMs = now;

  if (printData) {
    if (useQuaternion) {
      // 10 fields: w,x,y,z,gx,gy,gz,lax,lay,laz
      Serial.print(qw, 4);
      Serial.print(',');
      Serial.print(qx, 4);
      Serial.print(',');
      Serial.print(qy, 4);
      Serial.print(',');
      Serial.print(qz, 4);
      Serial.print(',');
    } else {
      // 9 fields: yaw,pitch,roll,gx,gy,gz,lax,lay,laz
      // ZYX / aerospace convention, matching BNO055 NDOF output
      float yaw = atan2f(2.0f * (qw * qz + qx * qy), 1.0f - 2.0f * (qy * qy + qz * qz)) * (180.0f / M_PI);
      float pitch = asinf(2.0f * (qw * qy - qz * qx)) * (180.0f / M_PI);
      float roll = atan2f(2.0f * (qw * qx + qy * qz), 1.0f - 2.0f * (qx * qx + qy * qy)) * (180.0f / M_PI);
      Serial.print(yaw, 2);
      Serial.print(',');
      Serial.print(pitch, 2);
      Serial.print(',');
      Serial.print(roll, 2);
      Serial.print(',');
    }
    Serial.print(gx, 2);
    Serial.print(',');
    Serial.print(gy, 2);
    Serial.print(',');
    Serial.print(gz, 2);
    Serial.print(',');
    Serial.print(lax, 2);
    Serial.print(',');
    Serial.print(lay, 2);
    Serial.print(',');
    Serial.println(laz, 2);
  }

  // Calibration line — same format as BNO055 for Python parser compatibility.
  // System/Gyro/Accel all reflect the SH2 ROTATION_VECTOR accuracy (0-3).
  // Magnetometer is always 0: BNO085 fuses mag internally and doesn't expose it separately.
  Serial.print(F("Calibration: System="));
  Serial.print(rotAccuracy);
  Serial.print(F(", Gyro="));
  Serial.print(rotAccuracy);
  Serial.print(F(", Accelerometer="));
  Serial.print(rotAccuracy);
  Serial.println(F(", Magnetometer=0"));

  // Commit calibration to sensor flash once per session when fully accurate.
  // On next boot the BNO085 loads the saved DCD and starts pre-calibrated.
  if (rotAccuracy >= 3 && !calibrationSaved) {
    sh2_saveDcdNow();
    calibrationSaved = true;
    Serial.println(F("Calibration saved to sensor flash (DCD)"));
  }
}
