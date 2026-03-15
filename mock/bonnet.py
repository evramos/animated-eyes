import sdl2
import threading
import time


class Channel:
    def __init__(self, key_inc, key_dec, initial=0.5, speed=0.5, spring=False):
        self._value     = initial
        self._inc       = getattr(sdl2, key_inc, None)   # resolve scancode once at init
        self._dec       = getattr(sdl2, key_dec, None)
        self._speed     = speed
        self._spring    = spring      # if True, returns to 0.5 when no key held
        self._last_time = time.time()

    @property
    def value(self):
        now = time.time()
        dt  = min(now - self._last_time, 0.1)  # cap to avoid large jumps on resume
        self._last_time = now

        keys = sdl2.SDL_GetKeyboardState(None)

        if self._inc and keys[self._inc]:
            self._value = min(1.0, self._value + self._speed * dt)
        elif self._dec and keys[self._dec]:
            self._value = max(0.0, self._value - self._speed * dt)
        elif self._spring:
            if self._value > 0.5:
                self._value = max(0.5, self._value - self._speed * dt)
            elif self._value < 0.5:
                self._value = min(0.5, self._value + self._speed * dt)

        return self._value


class Bonnet(threading.Thread):
    # https: // wiki.libsdl.org / SDL3 / SDL_Scancode
    _CHANNEL_KEYS = {
        0: dict(key_inc='SDL_SCANCODE_LEFTBRACKET', key_dec='SDL_SCANCODE_RIGHTBRACKET', initial=0.5, speed=0.4, spring=False),  # pupil
        1: dict(key_inc='SDL_SCANCODE_LEFT', key_dec='SDL_SCANCODE_RIGHT', initial=0.5, speed=2.0, spring=True),   # joystick X
        2: dict(key_inc='SDL_SCANCODE_UP', key_dec='SDL_SCANCODE_DOWN', initial=0.5, speed=2.0, spring=True),   # joystick Y
    }

    def __init__(self, daemon=True):
        super().__init__(daemon=daemon)
        self.channel = {}

    def setup_channel(self, index, reverse=False):
        if index < 0:
            return
        kwargs = dict(self._CHANNEL_KEYS[index])
        if reverse:
            kwargs['key_inc'], kwargs['key_dec'] = kwargs['key_dec'], kwargs['key_inc']
        self.channel[index] = Channel(**kwargs)

    def run(self):
        pass  # value property updates lazily on the main thread — no background polling needed
