class KeyboardGPIO:
    """GPIO mock that maps keyboard keys to pin states via SDL2.

    Pressing a key simulates holding the corresponding button LOW.
    Key mapping (edit _PIN_KEYS to rebind):
        Space  ->  BLINK_PIN  (pin 23)
        J      ->  WINK_L_PIN (pin 22)
        F      ->  WINK_R_PIN (pin 24)
    """
    BCM    = 11
    IN     = 1
    LOW    = 0
    HIGH   = 1
    PUD_UP = 22

    _PIN_KEYS = {
        22: 'SDL_SCANCODE_J',      # WINK_L_PIN
        23: 'SDL_SCANCODE_SPACE',  # BLINK_PIN
        24: 'SDL_SCANCODE_F',      # WINK_R_PIN
    }

    def setmode(self, mode): pass
    def setup(self, pin, direction, **kwargs): pass

    def input(self, pin):
        try:
            import sdl2
            scancode = getattr(sdl2, self._PIN_KEYS.get(pin, ''), None)
            if scancode is not None:
                keys = sdl2.SDL_GetKeyboardState(None)
                if keys[scancode]:
                    return self.LOW
        except Exception:
            pass
        return self.HIGH
