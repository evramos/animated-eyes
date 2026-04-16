"""
eye_sets/config.py

Base configuration dataclass shared by all live-generated eye sets.
"""

from dataclasses import dataclass


@dataclass
class EyeSetConfig:
    name:      str = "default"  # preset label
    size:      int = 256        # texture resolution — must be power of 2
    update_hz: int = 30         # texture redraws per second
