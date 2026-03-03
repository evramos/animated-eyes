from unittest.mock import MagicMock
import sys
import ctypes.util
from KeyboardGPIO import KeyboardGPIO

# Redirect pi3d's GLES library lookup to macOS native OpenGL so that
# SDL2-created contexts share the same GL implementation.
_real_find_library = ctypes.util.find_library
def _find_library_patch(name):
    if name == 'GLESv2.2':
        return '/System/Library/Frameworks/OpenGL.framework/OpenGL'
    return _real_find_library(name)
ctypes.util.find_library = _find_library_patch


_gpio = KeyboardGPIO()
_rpi  = MagicMock()
_rpi.GPIO = _gpio
sys.modules['RPi']                        = _rpi
sys.modules['RPi.GPIO']                   = _gpio
# sys.modules['RPi']                        = MagicMock()
# sys.modules['RPi.GPIO']                   = MagicMock()

sys.modules['board']                      = MagicMock()
sys.modules['busio']                      = MagicMock()
sys.modules['adafruit_ads1x15']           = MagicMock()
sys.modules['adafruit_ads1x15.ads1015']   = MagicMock()
sys.modules['adafruit_ads1x15.analog_in'] = MagicMock()