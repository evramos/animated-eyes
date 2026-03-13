from gfxutil import *

class EyeLidMesh:
    def __init__(self, lid_map, shader, x_pos, eye_radius):
        z_pos = -eye_radius - 42

        self.upper = mesh_init((33, 5), (0, 0.5 / lid_map.iy), False, True)
        self.upper.set_textures([lid_map])
        self.upper.set_shader(shader)
        self.upper.positionX(x_pos)
        self.upper.positionZ(z_pos)

        self.lower = mesh_init((33, 5), (0, 0.5 / lid_map.iy), False, True)
        self.lower.set_textures([lid_map])
        self.lower.set_shader(shader)
        self.lower.positionX(x_pos)
        self.lower.positionZ(z_pos)

    def draw(self):
        self.upper.draw()
        self.lower.draw()

    def rotateToZ(self, angle):
        self.upper.rotateToZ(angle)
        self.lower.rotateToZ(angle)


class LidState:
    def __init__(self, open_pts, closed_pts, initial_weight=0.5):
        self.prev_pts = points_interp(open_pts, closed_pts, initial_weight)
        self.prev_weight = initial_weight
        self.regen = True

    def update(self, mesh, open_pts, closed_pts, edge_pts, new_weight, threshold, flip):
        if self.regen or abs(new_weight - self.prev_weight) >= threshold:
            new_pts = points_interp(open_pts, closed_pts, new_weight)
            if new_weight > self.prev_weight:
                mesh.re_init(pts=points_mesh((edge_pts, self.prev_pts, new_pts), 5, 0, flip))
            else:
                mesh.re_init(pts=points_mesh((edge_pts, new_pts, self.prev_pts), 5, 0, flip))
            self.prev_pts = new_pts
            self.prev_weight = new_weight
            self.regen = True
        else:
            self.regen = False


class EyeLidState:
    def __init__(self, upper_open, upper_closed, lower_open, lower_closed):
        self.upper = LidState(upper_open, upper_closed)
        self.lower = LidState(lower_open, lower_closed)