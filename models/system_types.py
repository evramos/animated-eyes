# system_types.py
from dataclasses import dataclass

import pi3d

from snake_eyes_bonnet import SnakeEyesBonnet


@dataclass
class HardwareContext:
    bonnet: SnakeEyesBonnet | None  # None if no ADC channels configured

@dataclass
class DisplayContext:
    display: pi3d.Display
    eye_radius: float
    eye_position: float
    cam: pi3d.Camera
    shader: pi3d.Shader
    light: pi3d.Light