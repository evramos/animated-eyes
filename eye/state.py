import random
import math
import RPi.GPIO as GPIO
from models.point import Point, smoothstep
from constants import *


class EyeState:

    def _random_point(self):
        x = random.uniform(-30.0, 30.0)
        n = math.sqrt(900.0 - x * x)
        y = random.uniform(-n, n)
        return Point(x, y)

    def __init__(self):
        random_point = self._random_point()

        self.start = random_point
        self.destination = Point(random_point.x, random_point.y)
        self.current = Point(random_point.x, random_point.y)

        self.move_duration = random.uniform(0.075, 0.175)
        self.hold_duration = random.uniform(0.1, 1.1)
        self.start_time = 0.0
        self.is_moving = False

        self.blink_state = NO_BLINK
        self.blink_start_time = 0.0
        self.blink_duration = 0.1

        self.upper_tracking_pos = 0.3
        self.lower_tracking_pos = 0.7

    def start_blink(self, now, duration):
        self.blink_state = EN_BLINKING
        self.blink_start_time = now
        self.blink_duration = duration

    def update_position(self, now):

        dt = now - self.start_time

        if self.is_moving:
            if dt <= self.move_duration:
                scale = dt / self.move_duration
                scale = smoothstep(scale)
                self.current.set(
                    self.start.x + (self.destination.x - self.start.x) * scale,
                    self.start.y + (self.destination.y - self.start.y) * scale,
                )
            else:
                self.start.copy_from(self.destination)
                self.current.copy_from(self.destination)
                self.hold_duration = random.uniform(0.1, 1.1)
                self.start_time = now
                self.is_moving = False
        else:
            if dt >= self.hold_duration:
                self.destination = self._random_point()
                self.move_duration = random.uniform(0.075, 0.175)
                self.start_time = now
                self.is_moving = True


    def update_blink(self, wink_pin, now, wink_held=False):
        """Advance the blink state machine for this eye.

        Args:
            wink_pin  (int):   GPIO pin for this eye's wink button (-1 if unused).
            now       (float): Current timestamp in seconds.
            wink_held (bool):  True while a gamepad wink button is held (supplements wink_pin).

        Notes:
            - If the eye is mid-blink and the hold condition is met (BLINK_PIN or wink_pin held LOW, or wink_held), the state is frozen until released.
            - On state advance, duration doubles to give the opening phase the same length as the closing phase.
            - If idle (state 0) and wink_pin is held LOW or wink_held is True, a new blink is triggered.
        """
        held = (wink_held or
                (BLINK_PIN >= 0 and GPIO.input(BLINK_PIN) == GPIO.LOW) or
                (wink_pin >= 0 and GPIO.input(wink_pin) == GPIO.LOW))

        if self.blink_state:
            if (now - self.blink_start_time) >= self.blink_duration:
                if self.blink_state == EN_BLINKING and held:
                    pass  # eye held closed, don't advance
                else:
                    self.blink_state += 1
                    if self.blink_state > DE_BLINKING:
                        self.blink_state = NO_BLINK
                    else:
                        self.blink_duration *= 2.0
                        self.blink_start_time = now
        else:
            if wink_held or (wink_pin >= 0 and GPIO.input(wink_pin) == GPIO.LOW):
                self.blink_state = EN_BLINKING
                self.blink_start_time = now
                self.blink_duration = random.uniform(0.035, 0.06)

    def blink_weight(self, now):
        """Returns blink progress n (0.0 = open, 1.0 = closed)."""
        if self.blink_state:
            n = min((now - self.blink_start_time) / self.blink_duration, 1.0)
            if self.blink_state == DE_BLINKING:
                n = 1.0 - n
        else:
            n = 0.0
        return n

    def update_tracking(self, upper_bias, lower_bias):
        """Advance the eyelid tracking positions toward the eye's current vertical angle.

        Computes a target weight for each lid based on the eye's vertical position and
        a bias value that sets the resting position at center gaze. The result is smoothed
        using an exponential moving average (75% old, 25% new) so the lids lazily follow
        the eye rather than snapping instantly.

        Upper lid target:  upper_bias - (current.y / 60.0)
            Eye looks down → target decreases (lid lifts)
            Eye looks up   → target increases (lid droops)

        Lower lid target:  lower_bias + (current.y / 60.0)
            Eye looks down → target increases (lid rises to meet eye)
            Eye looks up   → target decreases (lid falls away)

        Both targets are clamped to [0.0, 1.0] before smoothing.

        Args:
            upper_bias (float): Resting weight for the upper lid at center gaze (0.0–1.0).
                                Default 0.4 — slight droop at neutral.
            lower_bias (float): Resting weight for the lower lid at center gaze (0.0–1.0).
                                Default 0.6 — complement of upper_bias.

        Updates:
            self.upper_tracking_pos: Smoothed weight fed into the upper lid blink blend.
            self.lower_tracking_pos: Smoothed weight fed into the lower lid blink blend.
        """
        u = max(0.0, min(upper_bias - self.current.y / 60.0, 1.0))
        l = max(0.0, min(lower_bias + self.current.y / 60.0, 1.0))
        self.upper_tracking_pos = (self.upper_tracking_pos * 3.0 + u) * 0.25
        self.lower_tracking_pos = (self.lower_tracking_pos * 3.0 + l) * 0.25

    def to_dict(self):
        s, d, c = self.start, self.destination, self.current
        pos = {"pos": [round(c.x, 2), round(c.y, 2)]} if s == d == c else\
        {
            "s": [round(s.x, 2), round(s.y, 2)],
            "d": [round(d.x, 2), round(d.y, 2)],
            "c": [round(c.x, 2), round(c.y, 2)],
        }
        return {
            **pos,
            **({"is_moving": True} if self.is_moving else {}),
            **({"blink_state": self.blink_state} if self.blink_state else {}),
            "upper_tracking": round(self.upper_tracking_pos, 3),
            "lower_tracking": round(self.lower_tracking_pos, 3),
        }
