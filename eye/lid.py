from gfxutil import mesh_init, points_interp, points_mesh
from models.scene_types import LidPoints

class EyeLidMesh:
    """
    Represents the mesh for the upper and lower eyelids in the eye animation system.

    This class manages two mesh objects (upper and lower eyelids) that are initialized with the same texture, shader,
    and positioning parameters. The meshes are positioned symmetrically around the eye center.
    """
    def __init__(self, lid_map, shader, x_pos, eye_radius):
        """
        Initializes the upper and lower eyelid meshes.

        Args:
            lid_map: The texture map for the eyelid surface.
            shader: The shader program to use for rendering the meshes.
            x_pos (float): The X-axis position offset for the meshes.
            eye_radius (float): The radius of the eye, used to calculate Z-axis positioning.
        """
        z_pos = -eye_radius - 42

        def create_mesh():
            mesh = mesh_init((33, 5), (0, 0.5 / lid_map.iy), False, True)
            mesh.set_textures([lid_map])
            mesh.set_shader(shader)
            mesh.positionX(x_pos)
            mesh.positionZ(z_pos)
            return mesh

        self.upper = create_mesh()
        self.lower = create_mesh()

    def draw(self):
        """
        Renders both the upper and lower eyelid meshes.
        """
        self.upper.draw()
        self.lower.draw()

    def rotateToZ(self, angle):
        """
        Rotates both eyelid meshes around the Z-axis to the specified angle.

        Args:
            angle (float): The rotation angle in degrees.
        """
        self.upper.rotateToZ(angle)
        self.lower.rotateToZ(angle)


class _LidState:
    def __init__(self, open_pts, closed_pts, initial_weight=0.5):
        self.prev_pts = points_interp(open_pts, closed_pts, initial_weight)
        self.prev_weight = initial_weight
        self.regen = True

    def update(self, mesh, pts: LidPoints, new_weight, threshold, flip) -> bool:
        """
        Updates the eyelid mesh based on the new weight value.

        This method determines whether the mesh needs to be regenerated based on weight changes and updates the mesh
        geometry accordingly. The mesh is regenerated if the flag is set or if the weight change exceeds the threshold.
        The order of point layers depends on whether the weight is increasing or decreasing to maintain proper depth ordering.

        Args:
            mesh: The mesh object to update with new point geometry.
            pts (LidPoints): A LidPoints object containing open, closed, and edge point configurations.
            new_weight (float): The new interpolation weight value (typically 0.0 to 1.0, where 0 is closed and 1 is open).
            threshold (float): The minimum weight change required to trigger mesh regeneration. Changes below
                              this threshold are ignored to optimize performance.
            flip (bool): A flag determining the orientation/flipping of the mesh geometry.

        Returns:
            bool: True if the mesh was regenerated in this call, False otherwise.

        Note:
            - If regeneration occurs, self.prev_pts and self.prev_weight are updated to the new values.
            - self.regen is updated to indicate whether the weight differs from the previous frame.
        """
        if self.regen or abs(new_weight - self.prev_weight) >= threshold:
            new_pts = points_interp(pts.open, pts.closed, new_weight)

            layer_order = (self.prev_pts, new_pts) if new_weight > self.prev_weight else (new_pts, self.prev_pts)
            mesh.re_init(pts=points_mesh((pts.edge, *layer_order), 5, 0, flip))

            self.prev_pts = new_pts
            self.regen = new_weight != self.prev_weight
            self.prev_weight = new_weight
        else:
            self.regen = False

        return self.regen


class EyeLidState:
    """
    Manages the state of both upper and lower eyelids for animation.

    This class encapsulates the state management for eyelid animations by holding separate _LidState instances for the
    upper and lower eyelids. It provides a unified interface for initializing eyelid states with their respective open
    and closed point configurations.
    """
    def __init__(self, upper_open, upper_closed, lower_open, lower_closed):
        """
        Initializes the eyelid states for upper and lower eyelids.

        Args:
            upper_open: Point configuration for the upper eyelid in the open position.
            upper_closed: Point configuration for the upper eyelid in the closed position.
            lower_open: Point configuration for the lower eyelid in the open position.
            lower_closed: Point configuration for the lower eyelid in the closed position.
        """
        self.upper = _LidState(upper_open, upper_closed)
        self.lower = _LidState(lower_open, lower_closed)