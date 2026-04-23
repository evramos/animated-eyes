"""
gamepad.py — Cross-platform gamepad input for 8BitDo Micro.

macOS : PyObjC GCController API — requires S mode (Switch) and
        Controller Shortcuts disabled (System Settings → General → Game Controller).
Linux : evdev reads from /dev/input (standard Pi path for paired BT gamepads).

All button events funnel through _on_press / _on_release using GCController
button names on both platforms. Combo callbacks fire once when all buttons are
held simultaneously, and reset when any button is released.

Install (macOS only):
    venv/bin/pip install pyobjc-framework-GameController
"""

import platform
import threading
import time

from bluetooth.constants import *


class GamepadListener:
    """Waits for the 8BitDo Micro and dispatches button events on a background thread.

    Button presses print to stdout. Combo callbacks fire once when all buttons
    are held; they reset when any member button is released.
    Reconnects automatically if the controller disconnects.
    """

    def __init__(self):
        self._quit         = threading.Event()
        self._held         = set()   # GC button names currently held
        self._combo_active = set()   # frozensets of combos already fired
        self._press_cbs    = {}      # button name → [callback]
        self._release_cbs  = {}      # button name → [callback]
        self._combos       = []

        target = self._run_objc if platform.system() == "Darwin" else self._run_evdev
        self._thread = threading.Thread(target=target, daemon=True, name="gamepad")

    def request_quit(self) -> None:
        """Signal the application to exit cleanly."""
        self._quit.set()

    @property
    def quit_requested(self) -> bool:
        """True once request_quit() has been called."""
        return self._quit.is_set()

    def add_combo(self, buttons, callback):
        """Register a combo callback. Must be called before start()."""
        self._combos.append((frozenset(buttons), callback))

    def add_on_press(self, button: str, callback):
        """Register a single-button press callback. Must be called before start()."""
        self._press_cbs.setdefault(button, []).append(callback)

    def add_on_release(self, button: str, callback):
        """Register a single-button release callback. Must be called before start()."""
        self._release_cbs.setdefault(button, []).append(callback)

    def start(self):
        self._thread.start()

    # ── Shared event dispatch ─────────────────────────────────────────────────

    def _on_press(self, name: str):
        if name in self._held:
            return
        self._held.add(name)
        print(f"[gamepad] ▼ {name}", flush=True)

        for cb in self._press_cbs.get(name, []):
            cb()
        for buttons, cb in self._combos:
            if buttons.issubset(self._held) and buttons not in self._combo_active:
                self._combo_active.add(buttons)
                cb()

    def _on_release(self, name: str):
        if name not in self._held:
            return
        self._held.discard(name)
        for cb in self._release_cbs.get(name, []):
            cb()
        if self._combo_active:
            self._combo_active = {c for c in self._combo_active if name not in c}

    def _reset(self):
        """Release all held buttons (called on disconnect)."""
        for name in list(self._held):
            self._on_release(name)

    def _dpad_axis(self, value, neg, pos, mapping):
        self._on_release(neg)
        self._on_release(pos)
        if mapping is not None:
            if value in mapping:
                self._on_press(mapping[value])
        else:
            btn = neg if value < 64 else pos if value > 192 else None
            if btn:
                self._on_press(btn)

    # ── macOS — GCController via PyObjC ───────────────────────────────────────

    def _run_objc(self):
        try:
            from GameController import GCController
            import Foundation
        except ImportError:
            print("[gamepad] pyobjc-framework-GameController not installed")
            print("          run: venv/bin/pip install pyobjc-framework-GameController")
            return

        GCController.setShouldMonitorBackgroundEvents_(True)

        def tick(interval=0.016):
            Foundation.NSRunLoop.currentRunLoop().runUntilDate_(
                Foundation.NSDate.dateWithTimeIntervalSinceNow_(interval)
            )

        print(f"[gamepad] waiting for controller...  quit combo: {" + ".join(sorted(GAMEPAD_QUIT_COMBO))}")

        while not self._quit.is_set():
            tick(0.5)
            controllers = GCController.controllers()
            if not controllers:
                continue

            ctrl = controllers[0]
            print(f"[gamepad] connected: {ctrl.vendorName()}")

            profile = ctrl.physicalInputProfile()
            if not profile:
                continue

            profile_buttons = profile.buttons()
            buttons = [
                (gc_name, profile_buttons[profile_key])
                for profile_key, gc_name in PROFILE_TO_GC.items()
                if profile_key in profile_buttons
            ]
            print(f"[gamepad] mapped {len(buttons)} buttons")

            while not self._quit.is_set():
                tick()

                if not GCController.controllers():
                    print("[gamepad] disconnected — waiting to reconnect...")
                    self._reset()
                    break

                for name, btn in buttons:
                    if btn.isPressed():
                        self._on_press(name)
                    else:
                        self._on_release(name)

    # ── Linux / Pi — evdev ────────────────────────────────────────────────────

    def _run_evdev(self):
        try:
            import evdev
        except ImportError:
            print("[gamepad] evdev not installed — run: pip install evdev")
            return

        code_to_name = {
            getattr(evdev.ecodes, ev_name): gc_name
            for ev_name, gc_name in EVDEV_TO_GC.items()
            if hasattr(evdev.ecodes, ev_name)
        }

        abs_axes = {
            evdev.ecodes.ABS_HAT0X: (DPAD_LEFT, DPAD_RIGHT, DPAD_X),
            evdev.ecodes.ABS_HAT0Y: (DPAD_UP,   DPAD_DOWN,  DPAD_Y),
            evdev.ecodes.ABS_X:     (DPAD_LEFT, DPAD_RIGHT, None),
            evdev.ecodes.ABS_Y:     (DPAD_UP,   DPAD_DOWN,  None),
        }

        print(f"[gamepad] waiting for controller...  quit combo: {" + ".join(sorted(GAMEPAD_QUIT_COMBO))}")

        while not self._quit.is_set():
            gamepad = None
            for path in evdev.list_devices():
                dev = evdev.InputDevice(path)
                if "8BitDo" in dev.name or "Micro" in dev.name:
                    gamepad = dev
                    break
                dev.close()
            if gamepad is None:
                time.sleep(2.0)
                continue

            print(f"[gamepad] connected: {gamepad.name}")

            try:
                for event in gamepad.read_loop():
                    if self._quit.is_set():
                        return

                    if event.type == evdev.ecodes.EV_KEY:
                        name = code_to_name.get(event.code)
                        if name:
                            if event.value == 1:
                                self._on_press(name)
                            elif event.value == 0:
                                self._on_release(name)

                    elif event.type == evdev.ecodes.EV_ABS:
                        if entry := abs_axes.get(event.code):
                            self._dpad_axis(event.value, *entry)

            except OSError:
                print("[gamepad] disconnected — waiting to reconnect...")
                self._reset()
