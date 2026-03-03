import random
import math
import RPi.GPIO as GPIO
from constants import *

class EyeState:
    def __init__(self):
        start_x = random.uniform(-30.0, 30.0)
        n = math.sqrt(900.0 - start_x * start_x)
        start_y = random.uniform(-n, n)

        self.start_x = start_x
        self.start_y = start_y
        self.dest_x = start_x
        self.dest_y = start_y
        self.cur_x = start_x
        self.cur_y = start_y
        self.move_duration = random.uniform(0.075, 0.175)
        self.hold_duration = random.uniform(0.1, 1.1)
        self.start_time = 0.0
        self.is_moving = False

        self.blink_state = NO_BLINK
        self.blink_start_time = 0.0
        self.blink_duration = 0.1
        self.tracking_pos = 0.3

    def start_blink(self, now, duration):
        self.blink_state = EN_BLINKING
        self.blink_start_time = now
        self.blink_duration = duration

    def update_position(self, now):

        dt = now - self.start_time

        if self.is_moving:
            if dt <= self.move_duration:
                scale = dt / self.move_duration
                scale = 3.0 * scale * scale - 2.0 * scale * scale * scale
                self.cur_x = self.start_x + (self.dest_x - self.start_x) * scale
                self.cur_y = self.start_y + (self.dest_y - self.start_y) * scale
            else:
                self.start_x = self.dest_x
                self.start_y = self.dest_y
                self.cur_x = self.dest_x
                self.cur_y = self.dest_y
                self.hold_duration = random.uniform(0.1, 1.1)
                self.start_time = now
                self.is_moving = False
        else:
            if dt >= self.hold_duration:
                self.dest_x = random.uniform(-30.0, 30.0)
                n = math.sqrt(900.0 - self.dest_x * self.dest_x)
                self.dest_y = random.uniform(-n, n)
                self.move_duration = random.uniform(0.075, 0.175)
                self.start_time = now
                self.is_moving = True


    def update_blink(self, wink_pin, now):
        """Advance the blink state machine for one eye and return updated state.

        State values: 0 = NOBLINK, 1 = ENBLINKING (closing), 2 = DEBLINKING (opening).

        Args:
            blink_state      (int):   Current blink state (0, 1, or 2).
            blink_start_time (float): Timestamp when current state began (seconds).
            blink_duration   (float): How long the current state should last (seconds).
            wink_pin         (int):   GPIO pin for this eye's wink button (-1 if unused).
            now              (float): Current timestamp (seconds).

        Returns:
            tuple(int, float, float): Updated (blink_state, blink_start_time, blink_duration).

        Notes:
            - If the eye is mid-blink and the hold condition is met (BLINK_PIN or wink_pin held LOW), the state is frozen until the button is released.
            - On state advance, duration doubles to give the opening phase the same length as the closing phase.
            - If idle (state 0) and wink_pin is held LOW, a new blink is triggered.
        """
        if self.blink_state:
            if (now - self.blink_start_time) >= self.blink_duration:
                if (self.blink_state == EN_BLINKING and
                        ((BLINK_PIN >= 0 and GPIO.input(BLINK_PIN) == GPIO.LOW) or
                         (wink_pin >= 0 and GPIO.input(wink_pin) == GPIO.LOW))):
                    pass  # eye held closed, don't advance
                else:
                    self.blink_state += 1
                    if self.blink_state > DE_BLINKING:
                        self.blink_state = 0
                    else:
                        self.blink_duration *= 2.0
                        self.blink_start_time = now
        else:
            if wink_pin >= 0 and GPIO.input(wink_pin) == GPIO.LOW:
                self.blink_state = EN_BLINKING
                self.blink_start_time = now
                self.blink_duration = random.uniform(0.035, 0.06)