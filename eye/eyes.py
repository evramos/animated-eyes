from eye.state import EyeState
from eye.lid   import EyeLidState


class Eye(EyeState):
    """An EyeState paired with its lid animation state.

    Inherits all position, blink, and tracking behaviour from EyeState.
    Adds `.lids` so a single Eye instance carries everything needed to
    animate one physical eye — position and lid geometry together.

    Args:
        svg (SvgPoints): Parsed SVG data; provides the open/closed lid point lists.
    """

    def __init__(self, svg):
        super().__init__()
        self.lids = EyeLidState(
            svg.upper_lid.open,
            svg.upper_lid.closed,
            svg.lower_lid.open,
            svg.lower_lid.closed,
        )


class Eyes:
    def __init__(self, svg):
        self.left = Eye(svg)
        self.right = Eye(svg)
