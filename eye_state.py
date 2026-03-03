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

        self.blink_state = 0
        self.blink_start_time = 0.0
        self.blink_duration = 0.1
        self.tracking_pos = 0.3

    def update_blink(self, wink_pin, now):
        """Advance blink state machine for this eye."""
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