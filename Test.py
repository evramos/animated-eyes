import ctypes.util
_real_find_library = ctypes.util.find_library
def _find_library_patch(name):
    if name == 'GLESv2.2':
        return '/System/Library/Frameworks/OpenGL.framework/OpenGL'
    return _real_find_library(name)
ctypes.util.find_library = _find_library_patch

import pi3d
# Test by initializing a display
DISPLAY = pi3d.Display.create(w=800, h=600, use_sdl2=True)
print("pi3d initialized successfully")
DISPLAY.destroy()