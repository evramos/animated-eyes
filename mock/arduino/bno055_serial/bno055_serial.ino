/*
 * bno055_serial.ino
 *
 * Reads the Adafruit BNO055 9-DOF IMU and streams sensor data over USB serial
 * at ~50 Hz for use with DragonEyes SerialSensorReader on macOS.
 *
 * Output (two lines per sample, 115200 baud):
 *   yaw,pitch,roll,gx,gy,gz,lax,lay,laz\n
 *   Calibration: System=N, Gyro=N, Accelerometer=N, Magnetometer=N\n
 *
 *   yaw/pitch/roll  — Euler angles in degrees
 *   gx/gy/gz        — Gyro angular velocity in °/s
 *   lax/lay/laz     — Gravity-subtracted linear acceleration in m/s²
 *
 * Serial commands (sent from host):
 *   WHO   → ACK:DRAGON_EYES_BNO055  (port auto-detection handshake)
 *   CLEAR → wipes saved EEPROM offsets (forces full re-calibration next boot)
 *
 * EEPROM layout (address 0):
 *   [0x00] uint16_t  magic  (0xDE0B = valid offsets present)
 *   [0x02] adafruit_bno055_offsets_t  (22 bytes)
 *
 * Wiring (Arduino Micro):
 *   BNO055 VIN → 3.3V (or 5V if your breakout has a regulator)
 *   BNO055 GND → GND
 *   BNO055 SDA → D2 (SDA)
 *   BNO055 SCL → D3 (SCL)
 *
 * Dependencies (install via Arduino Library Manager):
 *   - Adafruit BNO055
 *   - Adafruit Unified Sensor
 *   - Adafruit BusIO
 */

#include <Wire.h>
#include <EEPROM.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>
#include <utility/imumaths.h>

#define BNO055_SAMPLERATE_DELAY_MS  20       // 50 Hz
#define EEPROM_MAGIC                0xDE0B   // sentinel: valid offsets stored
#define EEPROM_ADDR                 0
#define CLEAR_PIN                   7        // hold LOW at boot to wipe saved offsets

Adafruit_BNO055 bno = Adafruit_BNO055(-1, 0x28, &Wire);

bool offsetsSaved = false;  // write once per session when sys hits 3

// ── EEPROM helpers ────────────────────────────────────────────────────────────

void loadOffsets() {
    uint16_t magic;
    EEPROM.get(EEPROM_ADDR, magic);
    if (magic != EEPROM_MAGIC) {
        Serial.println(F("EEPROM: no saved offsets — calibrate and they will be stored automatically"));
        return;
    }
    adafruit_bno055_offsets_t offsets;
    EEPROM.get(EEPROM_ADDR + sizeof(magic), offsets);
    bno.setSensorOffsets(offsets);  // sensor must be in CONFIG_MODE — safe here, bno.begin() leaves it there
    Serial.println(F("EEPROM: offsets restored — starting pre-calibrated"));
}

void saveOffsets() {
    adafruit_bno055_offsets_t offsets;
    bno.getSensorOffsets(offsets);
    uint16_t magic = EEPROM_MAGIC;
    EEPROM.put(EEPROM_ADDR, magic);
    EEPROM.put(EEPROM_ADDR + sizeof(magic), offsets);
    Serial.println(F("EEPROM: offsets saved"));
}

void clearOffsets() {
    uint16_t zero = 0x0000;
    EEPROM.put(EEPROM_ADDR, zero);
    offsetsSaved = false;
    Serial.println(F("EEPROM: offsets cleared — will re-calibrate from scratch next boot"));
}

// ── Setup ─────────────────────────────────────────────────────────────────────

void setup(void) {
    Serial.begin(115200);
    while (!Serial) delay(10);

    if (!bno.begin()) {
        Serial.println(F("BNO055 not detected — check wiring or I2C address"));
        while (1);
    }

    // Hold CLEAR_PIN LOW at boot to wipe saved offsets and force re-calibration
    pinMode(CLEAR_PIN, INPUT_PULLUP);
    if (digitalRead(CLEAR_PIN) == LOW) {
        clearOffsets();
    }

    // Read revision registers directly (0x01–0x06, PAGE_ID=0, CONFIG_MODE)
    Wire.beginTransmission(0x28);
    Wire.write(0x01);  // ACCEL_REV_ID
    Wire.endTransmission();
    Wire.requestFrom((uint8_t)0x28, (uint8_t)6);
    uint8_t accel_rev = Wire.read();
    uint8_t mag_rev   = Wire.read();
    uint8_t gyro_rev  = Wire.read();
    uint8_t sw_lsb    = Wire.read();
    uint8_t sw_msb    = Wire.read();
    uint8_t bl_rev    = Wire.read();
    uint16_t sw_rev   = ((uint16_t)sw_msb << 8) | sw_lsb;

    char verBuf[96];
    snprintf(verBuf, sizeof(verBuf),
        "BNO055 Rev — SW: %d.%d  BL: %d  Accel: 0x%02X  Gyro: 0x%02X  Mag: 0x%02X",
        (sw_rev >> 8), (sw_rev & 0xFF),
        bl_rev, accel_rev, gyro_rev, mag_rev);
    Serial.println(verBuf);

    // Restore saved calibration offsets before activating the sensor
    loadOffsets();

    delay(200);
    bno.setExtCrystalUse(true);
}

// ── Loop ──────────────────────────────────────────────────────────────────────

void loop(void) {
    // Handle serial commands from host
    if (Serial.available() > 0) {
        String cmd = Serial.readStringUntil('\n');
        cmd.trim();
        if (cmd == "WHO") {
            Serial.println(F("ACK:DRAGON_EYES_BNO055"));
        } else if (cmd == "CLEAR") {
            clearOffsets();
        }
    }

    // Euler angles: x = heading (yaw), y = roll, z = pitch
    imu::Vector<3> euler  = bno.getVector(Adafruit_BNO055::VECTOR_EULER);
    imu::Vector<3> angVel = bno.getVector(Adafruit_BNO055::VECTOR_GYROSCOPE);
    imu::Vector<3> laccel = bno.getVector(Adafruit_BNO055::VECTOR_LINEARACCEL);

    // CSV: yaw,pitch,roll,gx,gy,gz,lax,lay,laz
    Serial.print(euler.x(), 2);   Serial.print(',');
    Serial.print(euler.z(), 2);   Serial.print(',');
    Serial.print(euler.y(), 2);   Serial.print(',');
    Serial.print(angVel.x(), 2);  Serial.print(',');
    Serial.print(angVel.y(), 2);  Serial.print(',');
    Serial.print(angVel.z(), 2);  Serial.print(',');
    Serial.print(laccel.x(), 2);  Serial.print(',');
    Serial.print(laccel.y(), 2);  Serial.print(',');
    Serial.println(laccel.z(), 2);

    uint8_t sys, gyro, accel, mag = 0;
    bno.getCalibration(&sys, &gyro, &accel, &mag);
    Serial.print(F("Calibration: "));
    Serial.print(F("System="));        Serial.print(sys,   DEC); Serial.print(F(", "));
    Serial.print(F("Gyro="));          Serial.print(gyro,  DEC); Serial.print(F(", "));
    Serial.print(F("Accelerometer=")); Serial.print(accel, DEC); Serial.print(F(", "));
    Serial.print(F("Magnetometer="));  Serial.println(mag, DEC);

    // Save offsets to EEPROM once per session when fully calibrated
    if (sys == 3 && !offsetsSaved) {
        saveOffsets();
        offsetsSaved = true;
    }

    delay(BNO055_SAMPLERATE_DELAY_MS);
}
