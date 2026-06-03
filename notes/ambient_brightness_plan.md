# Ambient Light Brightness — Design Notes

## Overview

Automatically adjusts OLED display brightness based on measured ambient light, using a VEML7700
or BH1750 I²C ambient light sensor. The system is designed to support three input sources for
brightness — sensor, manual gamepad override, and future web UI — all writing to the same
`BrightnessController` target value.

Brightness control is **dual-layer**:
- **Hardware** — fbx2.c dynamically updates the SSD1351 `0xC7` Contrast Master register (0–15)
  to reduce OLED panel drive and save power.
- **Software** — Python updates `pi3d.Light` ambient each frame so rendered content stays
  visually consistent with the dimmed panel.

---

## 1. Signal Flow

```
VEML7700 / BH1750 (I²C)
        │
        ▼
ALSReader thread (sensor/als_reader.py)
  └─ samples lux every ~0.5 s
  └─ normalizes to 0.0–1.0

        │
        ▼
BrightnessController (lighting/brightness.py)
  ├─ exponential smoothing (slow transitions)
  ├─ manual_override: float | None  ← gamepad / web UI writes here
  └─ writes current value to /tmp/pi-eyes-brightness

        │
        ├──────────────────────────────────────────────────────────────┐
        ▼                                                              ▼
update_brightness stage (pipeline/stages.py)                    fbx2.c main loop
  └─ scales pi3d.Light ambient (0.05–0.4 range)                  └─ reads file every ~60 frames
  └─ purely rendered-scene darkening                              └─ maps 0.0–1.0 → 0x00–0x0F
                                                                  └─ issues 0xC7 command to both screens
```

---

## 2. Hardware

### Sensor options

| Chip | I²C address | Lux range | Library |
|------|------------|-----------|---------|
| VEML7700 | 0x10 | 0 – 120,000 lux | `adafruit-circuitpython-veml7700` |
| BH1750 | 0x23 or 0x5C | 1 – 65,535 lux | `smbus2` or `adafruit-circuitpython-bh1750` |

Both use the existing I²C bus (same as BNO055/085). No additional SPI pins needed.

### Typical lux reference

| Environment | Approximate lux |
|-------------|----------------|
| Direct sunlight | 100,000 |
| Overcast outdoors | 1,000–10,000 |
| Bright indoor office | 300–500 |
| Living room / dim indoor | 50–150 |
| Night / candlelight | 1–10 |

Suggested normalization: `sqrt(lux / MAX_LUX)` maps the wide lux range to a perceptually even
0.0–1.0 curve (square-root approximates how the eye perceives brightness). `MAX_LUX` can be
tuned in `constants.py`.

---

## 3. New constants (`constants.py`)

```python
# ── Ambient Light Sensor ──────────────────────────────────────────────────────
class ALSSensorType(Enum):
    NONE    = auto()  # No ALS; brightness stays at ALS_BRIGHTNESS_DEFAULT
    VEML7700 = auto() # Adafruit VEML7700 over I²C (address 0x10)
    BH1750   = auto() # BH1750 over I²C (address 0x23 / 0x5C)

ALS_SENSOR_TYPE:        Final = ALSSensorType.VEML7700
ALS_BRIGHTNESS_MIN:     Final = 0.1   # never go fully dark (0.0 = panel off)
ALS_BRIGHTNESS_MAX:     Final = 1.0   # full brightness ceiling
ALS_BRIGHTNESS_DEFAULT: Final = 0.8   # fallback when no sensor available
ALS_SMOOTH_FACTOR:      Final = 0.02  # exponential smoothing weight (lower = slower)
ALS_MAX_LUX:            Final = 5000.0  # lux mapped to brightness 1.0 (tune to environment)
BRIGHTNESS_FILE:        Final = "/tmp/pi-eyes-brightness"
```

---

## 4. New module: `sensor/als_reader.py`

```python
class ALSReader(threading.Thread, ABC):
    """Background thread that polls an I²C ambient light sensor."""

    @property
    @abstractmethod
    def lux(self) -> float:
        """Current lux reading (raw, unsmoothed)."""
        ...

    def run(self):
        while True:
            self._sample()
            time.sleep(0.5)  # 2 Hz is plenty for ambient light


class VEML7700Reader(ALSReader):
    """Adafruit VEML7700 (I²C 0x10)."""
    def __init__(self):
        super().__init__(daemon=True)
        import board, busio, adafruit_veml7700
        i2c = busio.I2C(board.SCL, board.SDA)
        self._sensor = adafruit_veml7700.VEML7700(i2c)
        self._lux = 0.0
        self._lock = threading.Lock()

    def _sample(self):
        try:
            val = self._sensor.lux
            with self._lock:
                self._lux = val
        except OSError:
            pass  # I²C hiccup; keep last reading

    @property
    def lux(self) -> float:
        with self._lock:
            return self._lux


class BH1750Reader(ALSReader):
    # Same structure; uses adafruit-circuitpython-bh1750 or smbus2
    ...
```

---

## 5. New module: `lighting/brightness.py`

```python
class BrightnessController:
    """
    Manages display brightness from ambient light sensor + optional manual override.
    Call update() once per frame. The smoothed value is written to BRIGHTNESS_FILE
    for fbx2.c to read, and is also available as .current for pi3d.Light scaling.
    """

    def __init__(self, als: ALSReader | None):
        self._als = als
        self._smoothed = ALS_BRIGHTNESS_DEFAULT
        self._last_written = -1.0
        self.manual_override: float | None = None  # set by gamepad or web UI

    def update(self, now: float) -> None:
        target = self._sense()
        self._smoothed += ALS_SMOOTH_FACTOR * (target - self._smoothed)
        self._maybe_write()

    def _sense(self) -> float:
        if self.manual_override is not None:
            return self.manual_override
        if self._als is not None:
            lux = self._als.lux
            normalized = math.sqrt(max(lux, 0.0) / ALS_MAX_LUX)
            return ALS_BRIGHTNESS_MIN + normalized * (ALS_BRIGHTNESS_MAX - ALS_BRIGHTNESS_MIN)
        return ALS_BRIGHTNESS_DEFAULT

    def _maybe_write(self) -> None:
        if abs(self._smoothed - self._last_written) > 0.005:
            try:
                with open(BRIGHTNESS_FILE, "w") as f:
                    f.write(f"{self._smoothed:.4f}\n")
                self._last_written = self._smoothed
            except OSError:
                pass

    @property
    def current(self) -> float:
        return self._smoothed
```

---

## 6. `lighting/__init__.py`

```python
from lighting.brightness import BrightnessController
```

---

## 7. `init.py` additions

```python
from lighting import BrightnessController
from sensor.als_reader import VEML7700Reader, BH1750Reader

def init_als_sensor() -> ALSReader | None:
    match ALS_SENSOR_TYPE:
        case ALSSensorType.NONE:
            return None
        case ALSSensorType.VEML7700:
            reader = VEML7700Reader()
            reader.start()
            return reader
        case ALSSensorType.BH1750:
            reader = BH1750Reader()
            reader.start()
            return reader

def init_brightness(als: ALSReader | None) -> BrightnessController:
    return BrightnessController(als)
```

---

## 8. `models/system_types.py` changes

Add `brightness: BrightnessController | None` to `HardwareContext`:

```python
@dataclass
class HardwareContext:
    bonnet:     SnakeEyesBonnet | None
    brightness: BrightnessController | None  # None if ALS_SENSOR_TYPE is NONE and no override
```

---

## 9. `pipeline/stages.py` — new `update_brightness` stage

Insert between `update_eye_set` and `update_blinks` in the stage order.

```python
def update_brightness(ctx: _StageCtx, now: float) -> None:
    if ctx.hw.brightness is None:
        return
    ctx.hw.brightness.update(now)
    b = ctx.hw.brightness.current

    # Scale pi3d.Light ambient — base is (0.2, 0.2, 0.2) at full brightness
    ambient_base = 0.2
    scaled = ambient_base * b
    pi3d.Light(
        lightpos=ctx.display_ctx.light.lightpos,
        lightamb=(scaled, scaled, scaled),
        lightdiff=ctx.display_ctx.light.lightdiff,
    )
```

Note: if `pi3d.Light` supports in-place mutation of `lightamb`, prefer that over
constructing a new instance each frame to avoid the uniform re-upload overhead.

---

## 10. `fbx2.c` changes

### 10a. Global state (near top, after screenType declaration)

```c
#define BRIGHTNESS_FILE "/tmp/pi-eyes-brightness"

static float  currentBrightness    = 1.0f;
static uint8_t currentContrastLevel = 0x0F;  // matches initOLED 0xC7 init value
```

### 10b. New helper: `applyContrast`

Must be called from the main thread only, between the two `pthread_barrier_wait` calls
(after first barrier, before second), where the DC pin and SPI file descriptors are safe.

```c
static void applyContrast(uint8_t level) {
    dcX2(0xC7, COMMAND);   // Contrast Master command
    dcX2(level, DATA);     // 0x00 (min) – 0x0F (max)
    currentContrastLevel = level;
}
```

### 10c. New helper: `readBrightnessFile`

```c
static float readBrightnessFile(void) {
    FILE *fp = fopen(BRIGHTNESS_FILE, "r");
    if(!fp) return currentBrightness;  // keep last value
    float val = currentBrightness;
    fscanf(fp, "%f", &val);
    fclose(fp);
    if(val < 0.0f) val = 0.0f;
    if(val > 1.0f) val = 1.0f;
    return val;
}
```

### 10d. Main loop additions

In the main loop, after `pthread_barrier_wait(&barr)` (the "after" wait / before screen window
commands), add a brightness check every 60 frames:

```c
static int brightnessCheckFrame = 0;
if(++brightnessCheckFrame >= 60) {
    brightnessCheckFrame = 0;
    float newBrightness = readBrightnessFile();
    if(fabsf(newBrightness - currentBrightness) > 0.01f) {
        currentBrightness = newBrightness;
        uint8_t level = (uint8_t)(newBrightness * 15.0f + 0.5f);
        if(level > 0x0F) level = 0x0F;
        if(level != currentContrastLevel && screenType == SCREEN_OLED) {
            applyContrast(level);
        }
    }
}
```

Place this block before the `commandList(screenInfo[screenType].win)` call so it doesn't
interleave with the window-reset SPI sequence.

Note: `0xC7` is SSD1351-specific. For ST7789 (TFT/IPS), a different register handles
brightness (`0x51` — display brightness, if CABC is supported). The `screenType == SCREEN_OLED`
guard skips the register write on TFT/IPS screens.

---

## 11. `pipeline/pipeline.py` additions

```python
from init import init_als_sensor, init_brightness

# In __init__:
_als = init_als_sensor()
# Pass brightness into HardwareContext via init_adc, or init separately:
self._c = _StageCtx(
    ...
    hw = HardwareContext(bonnet=..., brightness=init_brightness(_als)),
)
```

---

## 12. Future web UI integration

The web server only needs to:
1. Write a float to `BRIGHTNESS_FILE` (replaces the sensor's write)
2. Set `pipeline.hw.brightness.manual_override = value` (0.0–1.0)

Setting `manual_override = None` returns control to the ALS sensor.

A REST endpoint would look like:
```
POST /brightness { "value": 0.6 }   → sets manual override
DELETE /brightness                   → clears override, restores sensor control
GET /brightness                      → returns { "current": 0.6, "source": "manual" | "sensor" }
```

---

## 13. Implementation order

1. Add constants to `constants.py`
2. Write `sensor/als_reader.py` (VEML7700Reader first, BH1750Reader later)
3. Write `lighting/brightness.py` + `lighting/__init__.py`
4. Update `models/system_types.py`
5. Update `init.py` (`init_als_sensor`, `init_brightness`)
6. Update `pipeline/stages.py` (add `update_brightness` stage)
7. Update `pipeline/pipeline.py` (wire up the stage)
8. Modify `fbx2.c` (globals → `readBrightnessFile` → `applyContrast` → main loop hook)
9. Recompile fbx2: `gcc -O2 -o fbx2 fbx2.c -lpthread -lm -lX11 -lXext`
10. Test: indoor → outdoor transition; verify both OLED hardware contrast and rendered ambient change

---

## 14. macOS dev notes

`fbx2.c` does not run on macOS. The software path (pi3d.Light ambient) will still visually
dim the rendered window on macOS, giving a useful preview of the behavior. The brightness file
write is a no-op if `/tmp/pi-eyes-brightness` is not consumed by anyone.

For macOS testing, `BrightnessController.manual_override` can be wired to a keyboard key in
`mock/keyboardGPIO.py` (e.g., `[` / `]` to dim / brighten).
