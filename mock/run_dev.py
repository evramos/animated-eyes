#!/usr/bin/env python3
"""
Development launcher for macOS (no Raspberry Pi hardware).
Point PyCharm's Run Configuration at THIS file, not eyes.py.

Import order matters:
  1. mock_hardware — patches find_library so pi3d uses macOS native OpenGL
     (compatible with SDL2), and mocks RPi/board/busio before eyes loads.
  2. eyes — runs normally; all Pi hardware calls hit MagicMock silently.
"""

from mock import hardware  # noqa: F401 — side effect import, must be before eyes
import main            # noqa: E402 — intentional late import

if __name__ == "__main__":
    main.main()

