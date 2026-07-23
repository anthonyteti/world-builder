"""
Build script for "Richard the Penguin Knight" game assets.

Procedurally builds, rigs, and exports two game-ready assets for Godot 4:
  * CH_Penguin      - low-poly penguin warrior (rigged, GLB)
  * WPN_Greatsword  - oversized low-poly greatsword (GLB)

Run with:  python3 scripts/build_penguin_assets.py
Requires:  the `bpy` pip module (Blender 4.x/5.x as a Python library).

Style targets: stylized 3D pixel art, chunky faceted low-poly forms, flat
colour blocking, strong silhouette for an elevated three-quarter top-down
orthographic camera.
"""

import math
import os
import sys

import bpy
from mathutils import Euler, Matrix, Vector

# ----------------------------------------------------------------------------
# paths / config
# ----------------------------------------------------------------------------
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.path.join(REPO, "assets")
EXPORT_DIR = os.path.join(ASSET_DIR, "exports")
PREVIEW_DIR = os.path.join(ASSET_DIR, "previews")
BLEND_PATH = os.path.join(ASSET_DIR, "penguin_warrior.blend")

DO_RENDERS = os.environ.get("RENDERS", "1") != "0"
RENDER_SAMPLES = int(os.environ.get("SAMPLES", "48"))

TAU = math.tau
D = math.radians

# ----------------------------------------------------------------------------
# palette (hex sRGB from the concept sheet)
# ----------------------------------------------------------------------------
def srgb(hexcode, alpha=1.0):
    """hex sRGB -> linear RGBA tuple for Principled base color."""
    h = hexcode.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    out.append(alpha)
    return tuple(out)


PAL = {
    "body_dark":  "#313C55",
    "slate":      "#36415C",
    "cape_blue":  "#4B8FE2",
    "white":      "#F5F5F5",
    "orange":     "#F2A23B",
    "gold":       "#C9A24B",
    "gold_dark":  "#9E7B33",
    "eye_black":  "#0B0F1A",
    "steel":      "#C9CED8",
    "steel_dark": "#3B4150",
    "wrap_dark":  "#2B3040",
    "ground":     "#7E8D84",
}

# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------
def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scn = bpy.context.scene
    scn.unit_settings.system = "METRIC"
    scn.unit_settings.scale_length = 1.0
    scn.name = "PenguinWarrior_Scene"


def get_collection(name):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col


def move_to_collection(obj, col_name):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    get_collection(col_name).objects.link(obj)


def make_material(name, hexcode, roughness=0.9, metallic=0.0, spec=0.2):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = srgb(hexcode)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = spec
    mat.diffuse_color = srgb(hexcode)  # viewport
    return mat


def set_active(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def shade_flat(obj):
    for p in obj.data.polygons:
        p.use_smooth = False


def shade_smooth(obj):
    for p in obj.data.polygons:
        p.use_smooth = True


def recalc_normals(obj):
    set_active(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")


def merge_doubles(obj, dist=0.0004):
    set_active(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=dist)
    bpy.ops.object.mode_set(mode="OBJECT")


def apply_modifiers(obj):
    set_active(obj)
    for m in list(obj.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)


def assign_weights(obj, weight_fn):
    """weight_fn(local_co) -> {bone_name: weight}; applied to every vertex."""
    groups = {}
    for v in obj.data.vertices:
        w = weight_fn(v.co)
        total = sum(w.values()) or 1.0
        for name, val in w.items():
            if val <= 0.0:
                continue
            vg = groups.get(name)
            if vg is None:
                vg = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
                groups[name] = vg
            vg.add([v.index], val / total, "REPLACE")


def smoothstep(a, b, x):
    if x <= a:
        return 0.0
    if x >= b:
        return 1.0
    t = (x - a) / (b - a)
    return t * t * (3.0 - 2.0 * t)


def transform_mesh(obj, mtx):
    obj.data.transform(mtx)


def new_object(name, mesh):
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def uv_sphere(name, segments=12, rings=8, radius=1.0):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, radius=radius)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.name = name + "_Mesh"
    return obj


def cone(name, verts=8, r1=1.0, r2=0.0, depth=1.0):
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r1, radius2=r2, depth=depth)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.name = name + "_Mesh"
    return obj


def ngon_prism(name, points_xz, y0, y1):
    """Extruded prism from a 2D outline in the XZ plane, spanning y0..y1.

    points_xz must be ordered counter-clockwise when viewed from -Y.
    """
    n = len(points_xz)
    verts = [(x, y0, z) for x, z in points_xz] + [(x, y1, z) for x, z in points_xz]
    faces = [list(range(n - 1, -1, -1)),          # front cap (-Y side)
             list(range(n, 2 * n))]               # back cap (+Y side)
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j, n + i])
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return new_object(name, mesh)


def lathe(name, profile, nseg=8, twist_per_ring=0.0):
    """Surface of revolution around Z. profile = [(radius, z), ...] bottom->top.
    Caps both ends. twist_per_ring adds a small rotation per ring (wrap look).
    """
    verts, faces = [], []
    nring = len(profile)
    for ri, (r, z) in enumerate(profile):
        off = twist_per_ring * ri
        for si in range(nseg):
            a = TAU * si / nseg + off
            verts.append((r * math.cos(a), r * math.sin(a), z))
    for ri in range(nring - 1):
        for si in range(nseg):
            a = ri * nseg + si
            b = ri * nseg + (si + 1) % nseg
            faces.append([a, b, b + nseg, a + nseg])
    faces.append(list(range(nseg - 1, -1, -1)))                       # bottom cap
    faces.append(list(range((nring - 1) * nseg, nring * nseg)))       # top cap
    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return new_object(name, mesh)


def crown_outline(w, h):
    """Three-point crown polygon in XZ, centred on origin, CCW from -Y view."""
    x = w / 2.0
    return [(-x, -h * 0.42), (x, -h * 0.42), (x * 1.10, 0.02),
            (x * 0.68, h * 0.52), (x * 0.34, 0.05), (0.0, h * 0.58),
            (-x * 0.34, 0.05), (-x * 0.68, h * 0.52), (-x * 1.10, 0.02)]


# ============================================================================
# PENGUIN
# ============================================================================
# Body ellipsoid parameters (world coords, character faces -Y).
BODY_C = Vector((0.0, 0.0, 0.52))
BODY_R = Vector((0.35, 0.32, 0.46))
EGG = 0.14  # taper: top narrower, bottom wider (pear/egg shape)


def body_radius_factor(zn):
    return 1.0 - EGG * zn


def build_penguin_parts(mats):
    parts = []

    # ------------------------------------------------------------------ body
    body = uv_sphere("CH_Penguin_Body", segments=20, rings=14, radius=1.0)
    for v in body.data.vertices:
        f = body_radius_factor(v.co.z)
        v.co.x *= BODY_R.x * f
        v.co.y *= BODY_R.y * f
        v.co.z *= BODY_R.z
    transform_mesh(body, Matrix.Translation(BODY_C))
    body.data.materials.append(mats["body"])
    body.data.materials.append(mats["white"])
    for p in body.data.polygons:
        c = p.center
        in_oval = (c.x / 0.29) ** 2 + ((c.z - 0.34) / 0.245) ** 2 <= 1.0
        if c.y < -0.02 and in_oval and c.z < 0.55:   # cap keeps white under the collar
            p.material_index = 1

    def body_w(co):
        z = co.z
        a = smoothstep(0.33, 0.52, z)      # Body -> Chest
        b = smoothstep(0.52, 0.70, z)      # Chest -> Head
        return {"Body": (1 - a), "Chest": a * (1 - b), "Head": a * b}
    assign_weights(body, body_w)
    parts.append(body)

    # ------------------------------------------------------------------ eyes
    # big dark pupil with an even thin white ring, facing forward (-Y)
    for side in (1, -1):
        yaw = D(4) * side  # barely outward, keeps them from looking cross-eyed
        n = Euler((0, 0, yaw)).to_matrix() @ Vector((0.0, -1.0, 0.0))
        center = Vector((0.116 * side, -0.250, 0.712))

        eye = uv_sphere("CH_Penguin_Eye" + ("_R" if side > 0 else "_L"),
                        segments=14, rings=10, radius=0.099)
        transform_mesh(eye, Matrix.Diagonal((1.0, 0.30, 1.0, 1.0)))
        transform_mesh(eye, Euler((0, 0, yaw)).to_matrix().to_4x4())
        transform_mesh(eye, Matrix.Translation(center))
        eye.data.materials.append(mats["white"])
        shade_smooth(eye)
        assign_weights(eye, lambda co: {"Head": 1.0})
        parts.append(eye)

        pup = uv_sphere("CH_Penguin_Pupil" + ("_R" if side > 0 else "_L"),
                        segments=12, rings=8, radius=0.079)
        transform_mesh(pup, Matrix.Diagonal((1.0, 0.28, 1.0, 1.0)))
        transform_mesh(pup, Euler((0, 0, yaw)).to_matrix().to_4x4())
        transform_mesh(pup, Matrix.Translation(center + n * 0.014))
        pup.data.materials.append(mats["eye"])
        shade_smooth(pup)
        assign_weights(pup, lambda co: {"Head": 1.0})
        parts.append(pup)

    # ------------------------------------------------------------------ beak
    # small wide flat bill sitting just under the eye line
    beak = cone("CH_Penguin_Beak", verts=8, r1=0.06, r2=0.02, depth=0.11)
    transform_mesh(beak, Euler((D(96), 0, 0)).to_matrix().to_4x4())
    transform_mesh(beak, Matrix.Diagonal((1.0, 1.0, 0.5, 1.0)))
    transform_mesh(beak, Matrix.Translation((0.0, -0.33, 0.645)))
    beak.data.materials.append(mats["orange"])
    assign_weights(beak, lambda co: {"Head": 1.0})
    parts.append(beak)

    # ------------------------------------------------------------------ tuft
    # three little feather spikes on the crown of the head
    for dx, tilt, h in ((0.0, D(-18), 0.085), (0.045, D(24), 0.06), (-0.05, D(-40), 0.055)):
        tuft = cone("CH_Penguin_Tuft", verts=5, r1=0.026, r2=0.004, depth=h)
        transform_mesh(tuft, Euler((tilt if dx == 0 else D(-12), 0,
                                    0 if dx == 0 else math.copysign(D(28), dx))).to_matrix().to_4x4())
        transform_mesh(tuft, Matrix.Translation((dx, 0.02 if dx == 0 else 0.0, 0.985)))
        tuft.data.materials.append(mats["body"])
        assign_weights(tuft, lambda co: {"Head": 1.0})
        parts.append(tuft)

    # ---------------------------------------------------------------- collar
    # draped shoulder cowl with a V-dip at the chest (replaces the old torus)
    nu_c, rows = 18, 3
    row_off = (0.014, 0.048, 0.075)     # radial offset from body surface per row
    row_z = (0.625, 0.565, 0.505)       # base heights, top -> bottom
    cverts, cfaces = [], []
    for ri in range(rows):
        for ui in range(nu_c):
            th = TAU * ui / nu_c        # 0 = front (-Y)
            dip = max(0.0, math.cos(th)) ** 3
            back = (1.0 - math.cos(th)) * 0.5
            z = row_z[ri] + 0.035 * back - 0.045 * dip
            off = row_off[ri] * (1.0 - 0.45 * dip)   # hug the chest at the V
            zn = (z - BODY_C.z) / BODY_R.z
            f = body_radius_factor(zn)
            rx = BODY_R.x * f * math.sqrt(max(0.0, 1.0 - zn * zn)) + off
            ry = BODY_R.y * f * math.sqrt(max(0.0, 1.0 - zn * zn)) + off
            cverts.append((rx * math.sin(th), -ry * math.cos(th), z))
    for ri in range(rows - 1):
        for ui in range(nu_c):
            a = ri * nu_c + ui
            b = ri * nu_c + (ui + 1) % nu_c
            cfaces.append([a, b, b + nu_c, a + nu_c])
    cmesh0 = bpy.data.meshes.new("CH_Penguin_Collar_Mesh")
    cmesh0.from_pydata(cverts, [], cfaces)
    cmesh0.update()
    collar = new_object("CH_Penguin_Collar", cmesh0)
    collar.data.materials.append(mats["cape"])
    solc = collar.modifiers.new("Solidify", "SOLIDIFY")
    solc.thickness = 0.022
    solc.offset = 1.0
    apply_modifiers(collar)
    assign_weights(collar, lambda co: {"Chest": 1.0})
    parts.append(collar)

    # ------------------------------------------------------------- medallion
    bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=0.056, depth=0.03)
    med = bpy.context.active_object
    med.name = "CH_Penguin_Medallion"
    med.data.name = "CH_Penguin_Medallion_Mesh"
    transform_mesh(med, Euler((D(90), 0, 0)).to_matrix().to_4x4())
    transform_mesh(med, Matrix.Translation((0.0, -0.383, 0.49)))
    med.data.materials.append(mats["gold"])
    assign_weights(med, lambda co: {"Chest": 1.0})
    parts.append(med)

    # ------------------------------------------------------------------ cape
    nu, nv = 13, 9
    verts, faces = [], []
    for vi in range(nv):
        t = vi / (nv - 1)
        theta_max = D(72 + 20 * t)
        r = 0.355 + 0.035 * t
        z = 0.62 - 0.52 * (t ** 0.94)
        for ui in range(nu):
            u = ui / (nu - 1)
            th = -theta_max + 2 * theta_max * u
            zz = z + (0.022 * math.cos(3.0 * th) if vi == nv - 1 else 0.0)
            verts.append((r * math.sin(th), r * math.cos(th) + 0.05 * t, zz))
    for vi in range(nv - 1):
        for ui in range(nu - 1):
            a = vi * nu + ui
            faces.append([a, a + 1, a + 1 + nu, a + nu])
    cmesh = bpy.data.meshes.new("CH_Penguin_Cape_Mesh")
    cmesh.from_pydata(verts, [], faces)
    cmesh.update()
    cape = new_object("CH_Penguin_Cape", cmesh)
    cape.data.materials.append(mats["cape"])
    sol = cape.modifiers.new("Solidify", "SOLIDIFY")
    sol.thickness = 0.022
    sol.offset = 1.0
    apply_modifiers(cape)

    def cape_w(co):
        t = min(max((0.62 - co.z) / 0.52, 0.0), 1.0)
        blend = smoothstep(0.25, 0.85, t)
        w = {"Cape.1": 1 - blend, "Cape.2": blend}
        if t < 0.10:
            w["Chest"] = 0.4 * (1 - t / 0.10)
        return w
    assign_weights(cape, cape_w)
    parts.append(cape)

    # --------------------------------------------------------- crown emblem
    # bent onto the cape's cylindrical curve so its edges hug the cloth
    crown = ngon_prism("CH_Penguin_CapeCrown", crown_outline(0.19, 0.15), -0.012, 0.026)
    r_bend = 0.40
    for v in crown.data.vertices:
        th = v.co.x / r_bend
        rr = r_bend + v.co.y
        v.co.x = rr * math.sin(th)
        v.co.y = rr * math.cos(th) - r_bend
    transform_mesh(crown, Euler((D(10), 0, 0)).to_matrix().to_4x4())
    transform_mesh(crown, Matrix.Translation((0.0, 0.408, 0.36)))
    crown.data.materials.append(mats["gold"])
    assign_weights(crown, cape_w)
    parts.append(crown)

    # -------------------------------------------------------------- flippers
    for side, lbl in ((1, ".R"), (-1, ".L")):
        fl = uv_sphere("CH_Penguin_Flipper" + lbl, segments=10, rings=8, radius=1.0)
        transform_mesh(fl, Matrix.Diagonal((0.05, 0.095, 0.20, 1.0)))
        zs = [v.co.z for v in fl.data.vertices]

        def flip_w(co, _zs=zs):
            t = (0.20 - co.z) / 0.40          # 0 at shoulder end, 1 at tip
            blend = smoothstep(0.30, 0.72, t)
            w = {"Flipper" + lbl: 1 - blend, "FlipperTip" + lbl: blend}
            if t < 0.12:
                w["Chest"] = 0.35 * (1 - t / 0.12)
            return w
        assign_weights(fl, flip_w)
        transform_mesh(fl, Euler((0, D(-22) * side, 0)).to_matrix().to_4x4())
        transform_mesh(fl, Matrix.Translation((0.40 * side, 0.012, 0.36)))
        fl.data.materials.append(mats["body"])
        parts.append(fl)

    # ------------------------------------------------------------------ feet
    for side, lbl in ((1, ".R"), (-1, ".L")):
        ft = uv_sphere("CH_Penguin_Foot" + lbl, segments=10, rings=6, radius=1.0)
        transform_mesh(ft, Matrix.Diagonal((0.08, 0.14, 0.05, 1.0)))
        assign_weights(ft, lambda co: {"Foot" + lbl: 1.0})
        transform_mesh(ft, Euler((0, 0, D(-8) * side)).to_matrix().to_4x4())
        transform_mesh(ft, Matrix.Translation((0.155 * side, -0.125, 0.042)))
        ft.data.materials.append(mats["orange"])
        parts.append(ft)

    # ------------------------------------------------------------------ tail
    tail = uv_sphere("CH_Penguin_Tail", segments=8, rings=6, radius=1.0)
    transform_mesh(tail, Matrix.Diagonal((0.065, 0.13, 0.04, 1.0)))

    def tail_w(co):
        blend = smoothstep(-0.06, 0.05, co.y)
        return {"Body": 1 - blend, "Tail": blend}
    assign_weights(tail, tail_w)
    transform_mesh(tail, Euler((D(-18), 0, 0)).to_matrix().to_4x4())
    transform_mesh(tail, Matrix.Translation((0.0, 0.33, 0.075)))
    tail.data.materials.append(mats["body"])
    parts.append(tail)

    return parts


def join_parts(parts, name):
    for p in parts:
        recalc_normals(p)
        if p.data.polygons and not p.data.polygons[0].use_smooth:
            shade_flat(p)
    set_active(parts[0])
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    obj = bpy.context.active_object
    obj.name = name
    obj.data.name = name + "_Mesh"
    return obj


# ============================================================================
# ARMATURE
# ============================================================================
BONES = [
    # name, head, tail, parent, connected, deform
    ("Root",         (0, 0, 0),            (0, 0.25, 0),          None,        False, False),
    ("Body",         (0, 0, 0.28),         (0, 0, 0.50),          "Root",      False, True),
    ("Chest",        (0, 0, 0.50),         (0, 0, 0.68),          "Body",      True,  True),
    ("Head",         (0, 0, 0.68),         (0, 0, 0.99),          "Chest",     True,  True),
    ("Flipper.R",    (0.335, 0.01, 0.545), (0.41, 0.01, 0.40),    "Chest",     False, True),
    ("FlipperTip.R", (0.41, 0.01, 0.40),   (0.475, 0.01, 0.205),  "Flipper.R", True,  True),
    ("Grip.R",       (0.475, 0.01, 0.205), (0.475, -0.11, 0.205), "FlipperTip.R", False, False),
    ("Flipper.L",    (-0.335, 0.01, 0.545),(-0.41, 0.01, 0.40),   "Chest",     False, True),
    ("FlipperTip.L", (-0.41, 0.01, 0.40),  (-0.475, 0.01, 0.205), "Flipper.L", True,  True),
    ("Grip.L",       (-0.475, 0.01, 0.205),(-0.475, -0.11, 0.205),"FlipperTip.L", False, False),
    ("Leg.R",        (0.155, -0.02, 0.20), (0.155, -0.02, 0.075), "Body",      False, True),
    ("Foot.R",       (0.155, -0.02, 0.075),(0.155, -0.21, 0.045), "Leg.R",     True,  True),
    ("Leg.L",        (-0.155, -0.02, 0.20),(-0.155, -0.02, 0.075),"Body",      False, True),
    ("Foot.L",       (-0.155, -0.02, 0.075),(-0.155, -0.21, 0.045),"Leg.L",    True,  True),
    ("Tail",         (0, 0.20, 0.10),      (0, 0.42, 0.05),       "Body",      False, True),
    ("Cape.1",       (0, 0.33, 0.60),      (0, 0.355, 0.38),      "Chest",     False, True),
    ("Cape.2",       (0, 0.355, 0.38),     (0, 0.40, 0.10),       "Cape.1",    True,  True),
    ("Weapon_Back",  (0, 0.46, 0.42),      (0.28, 0.46, 0.86),    "Chest",     False, False),
    ("Weapon_Ground",(0.55, 0, 0.0),       (0.55, 0, 0.30),       "Root",      False, False),
]


def build_armature():
    arm_data = bpy.data.armatures.new("RIG_Penguin_Data")
    arm = bpy.data.objects.new("RIG_Penguin", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    set_active(arm)
    bpy.ops.object.mode_set(mode="EDIT")
    ebones = arm_data.edit_bones
    for name, head, tail, parent, connected, deform in BONES:
        b = ebones.new(name)
        b.head, b.tail = head, tail
        b.use_deform = deform
        if parent:
            b.parent = ebones[parent]
            b.use_connect = connected
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.show_in_front = True
    return arm


def bind(mesh_obj, arm):
    mesh_obj.parent = arm
    mod = mesh_obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    mod.use_vertex_groups = True


# ============================================================================
# SWORD
# ============================================================================
def blade_outline():
    """CCW outline (from -Y) of the blade in XZ. Includes edge chips."""
    right = [
        (0.045, 0.185),   # emerges from guard
        (0.185, 0.22),
        (0.175, 0.26),
        # chip on right edge
        (0.168, 0.575),
        (0.136, 0.615),
        (0.167, 0.655),
        (0.152, 1.55),
        (0.058, 1.82),
        (0.008, 1.895),
    ]
    left = [
        (-0.012, 1.90),
        (-0.048, 1.855),
        (-0.150, 1.58),
        # small chip
        (-0.151, 1.50),
        (-0.135, 1.478),
        (-0.152, 1.455),
        # big chip
        (-0.157, 1.15),
        (-0.124, 1.112),
        (-0.158, 1.075),
        (-0.175, 0.26),
        (-0.185, 0.22),
        (-0.045, 0.185),
    ]
    return right + left


def build_sword(mats):
    import bmesh
    parts = []

    # ----------------------------------------------------------------- blade
    blade = ngon_prism("WPN_Blade", blade_outline(), -0.027, 0.027)
    blade.data.materials.append(mats["steel"])
    bev = blade.modifiers.new("Bevel", "BEVEL")
    bev.width = 0.011
    bev.segments = 1
    bev.limit_method = "ANGLE"
    bev.angle_limit = D(40)
    apply_modifiers(blade)

    # clean explicit triangulation of the big concave caps
    bm = bmesh.new()
    bm.from_mesh(blade.data)
    bm.faces.ensure_lookup_table()
    caps = sorted(bm.faces, key=lambda f: f.calc_area(), reverse=True)[:2]
    bmesh.ops.triangulate(bm, faces=caps, quad_method="BEAUTY", ngon_method="BEAUTY")
    bm.to_mesh(blade.data)
    bm.free()
    parts.append(blade)

    # dark core plate on both faces (clean outline, clears the edge chips)
    panel_pts = [(0.118, 0.235), (0.108, 1.555), (0.028, 1.79), (0.0, 1.835),
                 (-0.03, 1.80), (-0.108, 1.585), (-0.118, 0.235)]
    panel = ngon_prism("WPN_BladePanel", panel_pts, -0.0285, 0.0285)
    panel.data.materials.append(mats["steel_dark"])
    parts.append(panel)

    # crown mark on both faces near the tip
    for y0, y1, flip in ((-0.0295, -0.0355, False), (0.0295, 0.0355, True)):
        pts = crown_outline(0.085, 0.07)
        if flip:
            pts = [(-x, z) for x, z in reversed(pts)]
        mark = ngon_prism("WPN_BladeMark", pts, y0, y1)
        transform_mesh(mark, Matrix.Translation((0.0, 0.0, 1.52)))
        mark.data.materials.append(mats["steel"])
        parts.append(mark)

    # ----------------------------------------------------------------- guard
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    guard = bpy.context.active_object
    guard.name = "WPN_Guard"
    guard.data.name = "WPN_Guard_Mesh"
    transform_mesh(guard, Matrix.Diagonal((0.48, 0.115, 0.10, 1.0)))
    for v in guard.data.vertices:   # taper the top toward the blade
        if v.co.z > 0:
            v.co.x *= 0.88
            v.co.y *= 0.72
        else:
            v.co.y *= 0.95
    transform_mesh(guard, Matrix.Translation((0.0, 0.0, 0.15)))
    gb = guard.modifiers.new("Bevel", "BEVEL")
    gb.width = 0.012
    gb.segments = 1
    gb.limit_method = "ANGLE"
    gb.angle_limit = D(40)
    apply_modifiers(guard)
    guard.data.materials.append(mats["gold"])
    parts.append(guard)

    # diamond studs front/back of guard
    for sy in (-1, 1):
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        stud = bpy.context.active_object
        stud.name = "WPN_GuardStud"
        stud.data.name = "WPN_GuardStud_Mesh"
        transform_mesh(stud, Matrix.Diagonal((0.052, 0.03, 0.052, 1.0)))
        transform_mesh(stud, Euler((0, D(45), 0)).to_matrix().to_4x4())
        transform_mesh(stud, Matrix.Translation((0.0, 0.052 * sy, 0.15)))
        stud.data.materials.append(mats["gold_dark"])
        parts.append(stud)

    # ------------------------------------------------------------------ grip
    prof = []
    z = -0.30
    rings = 6
    for i in range(rings + 1):
        r = 0.036 if i % 2 == 0 else 0.042
        prof.append((r, z))
        z += 0.40 / rings
    grip = lathe("WPN_Grip", prof, nseg=8, twist_per_ring=D(9))
    grip.data.materials.append(mats["wrap"])
    parts.append(grip)

    # ---------------------------------------------------------------- pommel
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    pom = bpy.context.active_object
    pom.name = "WPN_Pommel"
    pom.data.name = "WPN_Pommel_Mesh"
    transform_mesh(pom, Matrix.Diagonal((0.115, 0.095, 0.115, 1.0)))
    for v in pom.data.vertices:
        if v.co.z < 0:
            v.co.x *= 0.72
            v.co.y *= 0.72
    transform_mesh(pom, Matrix.Translation((0.0, 0.0, -0.355)))
    pb = pom.modifiers.new("Bevel", "BEVEL")
    pb.width = 0.010
    pb.segments = 1
    pb.limit_method = "ANGLE"
    pb.angle_limit = D(40)
    apply_modifiers(pom)
    pom.data.materials.append(mats["gold"])
    parts.append(pom)

    # blue gem set into the pommel (octahedron via 4-seg sphere)
    gem = uv_sphere("WPN_PommelGem", segments=4, rings=2, radius=0.052)
    transform_mesh(gem, Matrix.Diagonal((1.0, 1.0, 1.25, 1.0)))
    transform_mesh(gem, Euler((0, 0, D(45))).to_matrix().to_4x4())
    transform_mesh(gem, Matrix.Translation((0.0, 0.0, -0.425)))
    gem.data.materials.append(mats["gem"])
    parts.append(gem)

    sword = join_parts(parts, "WPN_Greatsword")
    return sword


# ============================================================================
# ENVIRONMENT / PREVIEW
# ============================================================================
def build_env(mats):
    bpy.ops.mesh.primitive_plane_add(size=7.0)
    ground = bpy.context.active_object
    ground.name = "ENV_GroundPlane"
    ground.data.name = "ENV_GroundPlane_Mesh"
    ground.data.materials.append(mats["ground"])

    cam_data = bpy.data.cameras.new("CAM_Gameplay_Preview_Data")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 3.4
    cam_data.clip_end = 100.0
    cam = bpy.data.objects.new("CAM_Gameplay_Preview", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    place_gameplay_cam(cam, yaw_deg=42.0, target=Vector((0.0, 0.0, 0.42)))
    bpy.context.scene.camera = cam

    key_data = bpy.data.lights.new("LGT_Sun_Key_Data", type="SUN")
    key_data.energy = 3.2
    key_data.angle = D(4)
    key = bpy.data.objects.new("LGT_Sun_Key", key_data)
    key.rotation_euler = Euler((D(40), D(-18), D(-30)))
    bpy.context.scene.collection.objects.link(key)

    fill_data = bpy.data.lights.new("LGT_Sun_Fill_Data", type="SUN")
    fill_data.energy = 1.0
    fill_data.angle = D(30)
    fill_data.color = (0.75, 0.82, 1.0)
    fill = bpy.data.objects.new("LGT_Sun_Fill", fill_data)
    fill.rotation_euler = Euler((D(55), D(20), D(140)))
    bpy.context.scene.collection.objects.link(fill)

    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = srgb("#CBD3D9")
    bg.inputs[1].default_value = 0.55
    return ground, cam, (key, fill)


def place_gameplay_cam(cam, yaw_deg, target, pitch_deg=39.0, dist=9.0):
    """Elevated three-quarter top-down orthographic view (not perfectly iso)."""
    rot = Euler((D(pitch_deg), 0.0, D(yaw_deg)))
    direction = rot.to_matrix() @ Vector((0.0, 0.0, -1.0))
    cam.rotation_euler = rot
    cam.location = target - direction * dist


# ============================================================================
# EXPORT / VERIFY
# ============================================================================
def export_glb(objects, filepath):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.export_scene.gltf(
        filepath=filepath,
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_apply=True,
        export_animations=False,
        export_skins=True,
        export_def_bones=False,
    )


def uv_unwrap(obj):
    set_active(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=D(66), island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")


def verify(penguin, arm, sword):
    report = []
    for obj in (penguin, sword):
        assert max(abs(s - 1.0) for s in obj.scale) < 1e-6, obj.name + " scale not applied"
    # every vertex weighted
    unweighted = 0
    for v in penguin.data.vertices:
        if not v.groups or sum(g.weight for g in v.groups) < 0.5:
            unweighted += 1
    report.append(f"unweighted verts: {unweighted}")
    report.append(f"penguin tris ~ {sum(len(p.vertices) - 2 for p in penguin.data.polygons)}")
    report.append(f"sword tris ~ {sum(len(p.vertices) - 2 for p in sword.data.polygons)}")
    report.append(f"penguin dims: {tuple(round(d, 3) for d in penguin.dimensions)}")
    report.append(f"sword dims: {tuple(round(d, 3) for d in sword.dimensions)}")
    report.append(f"bones: {len(arm.data.bones)}")

    # blade panel sanity: no folded/flipped triangles on the flat dark faces
    flipped = 0
    for p in sword.data.polygons:
        if abs(abs(p.center.y) - 0.0285) < 0.0005 and abs(p.normal.y) > 0.5:
            if p.normal.y * p.center.y < 0:   # normal points into the blade
                flipped += 1
    report.append(f"flipped blade-panel faces: {flipped}")
    assert flipped == 0, "blade panel has folded geometry"

    # deformation smoke test: rotate a flipper, confirm the mesh follows
    pb = arm.pose.bones["Flipper.R"]
    pb.rotation_mode = "XYZ"
    pb.rotation_euler = Euler((D(60), 0, 0))
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    eval_mesh = penguin.evaluated_get(dg).to_mesh()
    moved = max((eval_mesh.vertices[v.index].co - v.co).length
                for v in penguin.data.vertices
                if any(penguin.vertex_groups[g.group].name == "FlipperTip.R"
                       for g in v.groups))
    penguin.evaluated_get(dg).to_mesh_clear()
    pb.rotation_euler = Euler((0, 0, 0))
    bpy.context.view_layer.update()
    report.append(f"flipper deform displacement: {moved:.3f} m")
    assert moved > 0.05, "flipper weights not deforming"
    return report


# ============================================================================
# MAIN
# ============================================================================
def main():
    clear_scene()

    mats = {
        "body":       make_material("M_Penguin_Dark", PAL["body_dark"]),
        "white":      make_material("M_Penguin_White", PAL["white"]),
        "orange":     make_material("M_Penguin_Orange", PAL["orange"]),
        "eye":        make_material("M_Penguin_EyeBlack", PAL["eye_black"], roughness=0.6),
        "cape":       make_material("M_Cape_Blue", PAL["cape_blue"]),
        "gold":       make_material("M_Gold", PAL["gold"], roughness=0.65),
        "gold_dark":  make_material("M_Gold_Dark", PAL["gold_dark"], roughness=0.65),
        "steel":      make_material("M_Sword_Steel", PAL["steel"], roughness=0.75),
        "steel_dark": make_material("M_Sword_Face", PAL["steel_dark"], roughness=0.85),
        "wrap":       make_material("M_Sword_Wrap", PAL["wrap_dark"]),
        "gem":        make_material("M_Sword_Gem", PAL["cape_blue"], roughness=0.35),
        "ground":     make_material("M_Env_Ground", PAL["ground"]),
    }

    # ---- penguin
    parts = build_penguin_parts(mats)
    penguin = join_parts(parts, "CH_Penguin")
    uv_unwrap(penguin)

    # ---- armature
    arm = build_armature()
    bind(penguin, arm)

    # ---- sword
    sword = build_sword(mats)
    uv_unwrap(sword)
    # scene placement (presentation only; zeroed for export)
    sword.location = (0.95, 0.45, 0.033)
    sword.rotation_euler = Euler((D(90), 0, D(-25)))

    # ---- environment
    ground, cam, lights = build_env(mats)

    # ---- collections
    move_to_collection(penguin, "CH_PenguinWarrior")
    move_to_collection(arm, "CH_PenguinWarrior")
    move_to_collection(sword, "WPN_Greatsword_Asset")
    move_to_collection(ground, "ENV_Ground")
    move_to_collection(cam, "PREVIEW_Camera")
    for l in lights:
        move_to_collection(l, "PREVIEW_Lighting")

    # ---- verify
    report = verify(penguin, arm, sword)
    print("\n".join(report))

    # ---- exports
    os.makedirs(EXPORT_DIR, exist_ok=True)
    export_glb([penguin, arm], os.path.join(EXPORT_DIR, "penguin_warrior.glb"))

    saved = sword.matrix_world.copy()
    sword.location = (0, 0, 0)
    sword.rotation_euler = Euler((0, 0, 0))
    bpy.context.view_layer.update()
    export_glb([sword], os.path.join(EXPORT_DIR, "greatsword.glb"))
    sword.matrix_world = saved

    # ---- save
    os.makedirs(ASSET_DIR, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    print("saved", BLEND_PATH)

    # ---- renders
    if DO_RENDERS:
        do_renders(penguin, arm, sword, cam)


# ----------------------------------------------------------------------------
# preview renders
# ----------------------------------------------------------------------------
def setup_render(res=720):
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.samples = RENDER_SAMPLES
    scn.cycles.use_denoising = True
    scn.render.resolution_x = scn.render.resolution_y = res
    scn.view_settings.view_transform = "Standard"


def render_to(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("rendered", path)


def pose_hold_sword(arm, sword):
    """Two-handed ready pose; returns sword's original matrix."""
    saved = sword.matrix_world.copy()

    def aim(bone_name, target):
        pb = arm.pose.bones[bone_name]
        head = (arm.matrix_world @ pb.matrix).translation
        d0 = (arm.matrix_world @ pb.matrix).col[1].to_3d().normalized()
        d1 = (Vector(target) - head).normalized()
        rot = d0.rotation_difference(d1).to_matrix().to_4x4()
        m = Matrix.Translation(head) @ rot @ Matrix.Translation(-head)
        pb.matrix = m @ pb.matrix
        bpy.context.view_layer.update()

    grip = Vector((0.03, -0.37, 0.52))
    aim("Flipper.R", grip + Vector((0.03, 0.02, 0.05)))
    aim("Flipper.L", grip + Vector((-0.05, -0.02, -0.09)))

    # blade up over the right shoulder
    sword.rotation_euler = Euler((D(-30), D(12), D(8)))
    sword.location = grip
    bpy.context.view_layer.update()
    return saved


def reset_pose(arm, sword, saved):
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    sword.matrix_world = saved
    bpy.context.view_layer.update()


def do_renders(penguin, arm, sword, cam):
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    setup_render()
    target = Vector((0.0, 0.0, 0.42))

    # main gameplay view + rotation checks
    for yaw, tag in ((42, "three_quarter"), (135, "back_right"),
                     (222, "back"), (315, "front_left")):
        place_gameplay_cam(cam, yaw_deg=yaw, target=target)
        render_to(os.path.join(PREVIEW_DIR, f"gameplay_{tag}.png"))

    # straight front / side orthos (compare against the concept turnaround)
    for yaw, pitch, tag in ((0, 87, "front"), (90, 87, "side")):
        place_gameplay_cam(cam, yaw_deg=yaw, target=Vector((0, 0, 0.5)), pitch_deg=pitch)
        cam.data.ortho_scale = 1.6
        render_to(os.path.join(PREVIEW_DIR, f"ortho_{tag}.png"))
    cam.data.ortho_scale = 3.4

    # held pose
    saved = pose_hold_sword(arm, sword)
    place_gameplay_cam(cam, yaw_deg=42, target=target)
    render_to(os.path.join(PREVIEW_DIR, "gameplay_sword_held.png"))
    reset_pose(arm, sword, saved)

    # closeup perspective
    cam.data.type = "PERSP"
    cam.data.lens = 55
    cam.location = (1.35, -1.75, 1.15)
    cam.rotation_euler = Euler((D(72), 0, D(38)))
    render_to(os.path.join(PREVIEW_DIR, "closeup.png"))

    # sword detail (temporarily stand it at origin, hide penguin)
    sw_saved = sword.matrix_world.copy()
    sword.location = (0, 0, 0.47)
    sword.rotation_euler = Euler((0, 0, 0))
    penguin.hide_render = True
    arm.hide_render = True
    cam.location = (2.6, -3.4, 1.9)
    cam.rotation_euler = Euler((D(78), 0, D(37)))
    render_to(os.path.join(PREVIEW_DIR, "sword_detail.png"))
    penguin.hide_render = False
    arm.hide_render = False
    sword.matrix_world = sw_saved

    # pixelated in-game look
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 3.4
    place_gameplay_cam(cam, yaw_deg=42, target=target)
    setup_render(res=180)
    render_to(os.path.join(PREVIEW_DIR, "_lowres.png"))
    try:
        from PIL import Image
        img = Image.open(os.path.join(PREVIEW_DIR, "_lowres.png"))
        img = img.resize((720, 720), Image.NEAREST)
        img.save(os.path.join(PREVIEW_DIR, "gameplay_pixelated.png"))
        os.remove(os.path.join(PREVIEW_DIR, "_lowres.png"))
    except ImportError:
        pass
    setup_render()


if __name__ == "__main__":
    main()
