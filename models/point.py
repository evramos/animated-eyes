from dataclasses import dataclass


def smoothstep(t: float) -> float:
    """Smooth ease-in/out: velocity=0 at t=0 and t=1."""
    return 3*t*t - 2*t*t*t


@dataclass
class Point:
    x: float = 0.0
    y: float = 0.0

    def copy_from(self, other):
        self.x = other.x
        self.y = other.y

    def set(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar):
        return Point(self.x * scalar, self.y * scalar)

    def __truediv__(self, scalar):
        return Point(self.x / scalar, self.y / scalar)
