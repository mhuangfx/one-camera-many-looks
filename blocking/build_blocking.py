# Blocking: one car on one street, one camera move.
# Colored primitives only (no simulation). The video model re-renders this in each brand look.
# Run: blender -b -P build_blocking.py -- --out <dir> [--seconds 10] [--fps 24] [--preview]
import bpy, math, sys, os
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(name, default):
    return argv[argv.index(name) + 1] if name in argv else default
OUT = arg("--out", os.path.join(os.path.dirname(__file__), "v1"))
SECONDS = float(arg("--seconds", 10))
FPS = int(arg("--fps", 24))
PREVIEW = "--preview" in argv
FRAMES = int(SECONDS * FPS)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.fps = FPS
scene.frame_start, scene.frame_end = 1, FRAMES
scene.render.resolution_x, scene.render.resolution_y = (640, 360) if PREVIEW else (1280, 720)

def mat(name, rgb):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*rgb, 1)
    m.use_nodes = True
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*rgb, 1)
    m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.8
    return m

def box(name, loc, size, m, parent=None):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    o.data.materials.append(m)
    if parent: o.parent = parent
    return o

# Colors: one per kind of thing.
ROAD = mat("road", (0.18, 0.18, 0.2))
LINE = mat("lane_line", (0.95, 0.85, 0.2))
WALK = mat("sidewalk", (0.6, 0.6, 0.58))
BODY = mat("car_body", (0.85, 0.1, 0.1))
GLASS = mat("car_glass", (0.1, 0.35, 0.8))
TIRE = mat("tire", (0.05, 0.05, 0.05))
LAMP = mat("headlight", (1.0, 1.0, 0.85))
TAIL = mat("taillight", (1.0, 0.4, 0.0))
BLD = [mat(f"building_{i}", c) for i, c in enumerate([
    (0.3, 0.6, 0.35), (0.75, 0.55, 0.3), (0.45, 0.4, 0.7), (0.3, 0.6, 0.65), (0.7, 0.4, 0.5)])]
POLE = mat("pole", (0.9, 0.9, 0.9))

# Street along +Y. Road 10 m wide, sidewalks 4 m, buildings behind them.
L = 260
box("road", (0, L / 2 - 40, -0.05), (10, L, 0.1), ROAD)
for y in range(-40, L - 40, 8):
    box(f"lane_{y}", (0, y, 0.005), (0.2, 4, 0.01), LINE)
for side in (-1, 1):
    box(f"walk_{side}", (side * 7, L / 2 - 40, 0.1), (4, L, 0.2), WALK)
    y, i = -40, 0
    while y < L - 40:
        w = 12 + (i * 7) % 9
        h = 9 + (i * 13) % 22
        box(f"bld_{side}_{i}", (side * (9 + 4), y + w / 2, h / 2), (8, w - 0.6, h), BLD[(i + (side > 0) * 2) % len(BLD)])
        y += w; i += 1
    for py in range(-30, L - 40, 18):
        box(f"pole_{side}_{py}", (side * 5.4, py, 2.5), (0.18, 0.18, 5), POLE)

# Car: 4.6 m long, faces +Y. Root empty drives it.
bpy.ops.object.empty_add(location=(1.8, 0, 0))
car = bpy.context.object; car.name = "car"
box("car_body", (0, 0, 0.7), (1.9, 4.6, 0.7), BODY, car)
box("car_cabin", (0, -0.3, 1.3), (1.6, 2.3, 0.6), GLASS, car)
box("car_roof", (0, -0.3, 1.63), (1.5, 2.0, 0.06), BODY, car)
for s in (-1, 1):
    box(f"headlight_{s}", (s * 0.65, 2.31, 0.8), (0.4, 0.04, 0.18), LAMP, car)
    box(f"taillight_{s}", (s * 0.65, -2.31, 0.8), (0.4, 0.04, 0.18), TAIL, car)
    for wy in (1.45, -1.45):
        bpy.ops.mesh.primitive_cylinder_add(radius=0.38, depth=0.3, location=(s * 0.92, wy, 0.38), rotation=(0, math.pi / 2, 0))
        w = bpy.context.object; w.data.materials.append(TIRE); w.parent = car

# Car drives at a steady 9 m/s (about 32 km/h).
SPEED = 9.0
def car_y(f): return SPEED * (f - 1) / FPS
for f in range(1, FRAMES + 1):
    car.location = (1.8, car_y(f), 0); car.keyframe_insert("location", frame=f)

# Camera: keyed relative to the car, then offset by the car's travel.
# Phase A (0-55%): low (0.9 m), left of the car at 4.5 m, slides from rear quarter to front quarter.
# Phase B (55-100%): cranes up and over to a high view ahead of the car, looking down at it.
bpy.ops.object.camera_add()
cam = bpy.context.object; cam.name = "camera"
scene.camera = cam
cam.data.lens = 28
bpy.ops.object.empty_add(location=(0, 0, 0))
aim = bpy.context.object; aim.name = "aim"
cam_c = cam.constraints.new("TRACK_TO"); cam_c.target = aim
cam_c.track_axis, cam_c.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"

KEYS = [  # (time fraction, camera offset from car, aim offset from car)
    (0.00, (-6.0, -5.0, 1.0), (0, 0.5, 0.8)),
    (0.55, (-6.0, 5.0, 1.0), (0, -0.5, 0.8)),
    (0.80, (-3.0, 9.0, 6.0), (0, 0.0, 0.6)),
    (1.00, (0.0, 11.0, 13.0), (0, 0.5, 0.3)),
]
# One smooth curve through all keys (cubic Hermite with time-scaled tangents): the camera never
# slows to zero at a key. The ends keep their speed too, so the shot starts and ends in motion.
def tangent(i, k):
    T = [x[0] for x in KEYS]; P = [x[k] for x in KEYS]
    a, b = max(i - 1, 0), min(i + 1, len(KEYS) - 1)
    return tuple((q - p) / (T[b] - T[a]) for p, q in zip(P[a], P[b]))
def hermite(u, i, k):
    t0, t1 = KEYS[i][0], KEYS[i + 1][0]; h = t1 - t0; s = (u - t0) / h
    p0, p1, m0, m1 = KEYS[i][k], KEYS[i + 1][k], tangent(i, k), tangent(i + 1, k)
    h00, h10, h01, h11 = 2*s**3 - 3*s**2 + 1, s**3 - 2*s**2 + s, -2*s**3 + 3*s**2, s**3 - s**2
    return tuple(h00*a + h10*h*c + h01*b + h11*h*d for a, b, c, d in zip(p0, p1, m0, m1))
def offsets(u):
    for i in range(len(KEYS) - 1):
        if u <= KEYS[i + 1][0]:
            return hermite(u, i, 1), hermite(u, i, 2)
    return KEYS[-1][1], KEYS[-1][2]
for f in range(1, FRAMES + 1):
    c, a = offsets((f - 1) / (FRAMES - 1))
    base = Vector((1.8, car_y(f), 0))
    cam.location = base + Vector(c); cam.keyframe_insert("location", frame=f)
    aim.location = base + Vector(a); aim.keyframe_insert("location", frame=f)

# Light: sun plus soft world, Eevee for fast clean shapes.
bpy.ops.object.light_add(type="SUN", rotation=(math.radians(50), 0, math.radians(30)))
bpy.context.object.data.energy = 3.5
world = bpy.data.worlds.new("w"); scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.65, 0.78, 0.95, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.9
scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
scene.view_settings.view_transform = "Standard"

os.makedirs(OUT, exist_ok=True)
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = os.path.join(OUT, "frames", "f_")
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "blocking.blend"))
bpy.ops.render.render(animation=True)
