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
import numpy as np
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
    "body_dark":  "#4B5665",
    "slate":      "#36415C",
    "cape_blue":  "#4B8FE2",
    "white":      "#F5F5F5",
    "orange":     "#F2A23B",
    "gold":       "#C9A24B",
    "gold_dark":  "#9E7B33",
    "eye_black":  "#1A2138",   # dark navy pupils, warmer than pure black
    "steel":      "#C9CED8",
    "steel_dark": "#3B4150",
    "wrap_dark":  "#2B3040",
    "ground":     "#D9CDB2",   # warm sand, close to the concept sheet's cream
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
# Body profile (world coords, character faces -Y).
# Explicit bell/snowman silhouette from the concept sheet: broad flat-ish
# base, widest at hip height, A-line flare, a soft neck indent under the
# scarf, then a distinct round head. Half-width (x) per height; the
# cross-section is an ellipse squashed front-to-back by BODY_YSCALE.
BODY_PROFILE = [
    (0.035, 0.10), (0.06, 0.17), (0.10, 0.235), (0.14, 0.28),
    (0.20, 0.315), (0.27, 0.33), (0.34, 0.325), (0.42, 0.30),
    (0.50, 0.26), (0.56, 0.225), (0.615, 0.215), (0.66, 0.235),
    (0.71, 0.24), (0.76, 0.235), (0.82, 0.205), (0.875, 0.16),
    (0.915, 0.10), (0.935, 0.03),
]
BODY_YSCALE = 0.96


def head_shift(z):
    """Forward (-Y) offset of the upper body/head, like the reference."""
    return 0.045 * smoothstep(0.50, 0.72, z)


def body_half_width(z):
    """C1 interpolation (finite-difference Hermite) through BODY_PROFILE."""
    pts = BODY_PROFILE
    if z <= pts[0][0]:
        return pts[0][1]
    if z >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        z0, r0 = pts[i]
        z1, r1 = pts[i + 1]
        if z0 <= z <= z1:
            zm1, rm1 = pts[max(i - 1, 0)]
            z2, r2 = pts[min(i + 2, len(pts) - 1)]
            m0 = (r1 - rm1) / (z1 - zm1)
            m1 = (r2 - r0) / (z2 - z0)
            h = z1 - z0
            t = (z - z0) / h
            t2, t3 = t * t, t * t * t
            return ((2 * t3 - 3 * t2 + 1) * r0 + (t3 - 2 * t2 + t) * h * m0
                    + (-2 * t3 + 3 * t2) * r1 + (t3 - t2) * h * m1)
    return pts[-1][1]


def build_penguin_parts(mats):
    parts = []

    # ------------------------------------------------------------------ body
    # lathe of the bell profile, oval cross-section (squashed front-to-back)
    ring_zs = []
    for i in range(len(BODY_PROFILE) - 1):
        z0, z1 = BODY_PROFILE[i][0], BODY_PROFILE[i + 1][0]
        ring_zs.extend((z0, (z0 + z1) * 0.5))
    ring_zs.append(BODY_PROFILE[-1][0])
    body = lathe("CH_Penguin_Body", [(body_half_width(z), z) for z in ring_zs],
                 nseg=28)
    transform_mesh(body, Matrix.Diagonal((1.0, BODY_YSCALE, 1.0, 1.0)))
    for v in body.data.vertices:        # head leans a touch forward
        v.co.y -= head_shift(v.co.z)
    body.data.materials.append(mats["body"])
    shade_smooth(body)

    def body_w(co):
        z = co.z
        a = smoothstep(0.32, 0.50, z)      # Body -> Chest
        b = smoothstep(0.50, 0.68, z)      # Chest -> Head
        return {"Body": (1 - a), "Chest": a * (1 - b), "Head": a * b}
    assign_weights(body, body_w)
    parts.append(body)

    def surface_y(x, z):
        """Front (-Y) surface of the profiled body at a given x, z."""
        w = body_half_width(z)
        arg = 1.0 - (x / w) ** 2
        return -BODY_YSCALE * w * math.sqrt(max(arg, 0.0)) - head_shift(z)

    def surface_normal(x, y, z):
        """Outward normal of the implicit surface (x/w)^2 + (y/(s*w))^2 = 1."""
        w = body_half_width(z)
        yc = y + head_shift(z)          # back to the profile's centred frame
        s2 = BODY_YSCALE * BODY_YSCALE
        eps = 0.004
        dw = (body_half_width(z + eps) - body_half_width(z - eps)) / (2 * eps)
        n = Vector((x / (w * w), yc / (s2 * w * w),
                    -(x * x + yc * yc / s2) * dw / (w ** 3)))
        n.normalize()
        return n

    # ----------------------------------------------------------------- belly
    # plumage layer conformal to the pear profile: an oval shell floating a
    # few mm proud of the surface. The rim never touches the faceted body
    # (that would zigzag across polygon chords) — it hovers just above it,
    # reading as a crisp fabric/feather edge with a fine shadow seam.
    rim_n = 28
    bc_z, b_rx, b_rz = 0.30, 0.25, 0.225
    s_rings = (0.30, 0.60, 0.80, 0.93, 1.0)
    s_offs = (0.0075, 0.0070, 0.0060, 0.0052, 0.0045)
    bverts = [(0.0, surface_y(0.0, bc_z) - 0.0075, bc_z)]
    for srad, off in zip(s_rings, s_offs):
        for a in range(rim_n):
            ang = TAU * a / rim_n
            x = b_rx * srad * math.cos(ang)
            z = bc_z + b_rz * srad * math.sin(ang)
            bverts.append((x, surface_y(x, z) - off, z))
    bfaces = [[0, 1 + a, 1 + (a + 1) % rim_n] for a in range(rim_n)]
    for s in range(len(s_rings) - 1):
        base = 1 + s * rim_n
        for a in range(rim_n):
            i, j = base + a, base + (a + 1) % rim_n
            bfaces.append([i, j, j + rim_n, i + rim_n])
    bmesh0 = bpy.data.meshes.new("CH_Penguin_Belly_Mesh")
    bmesh0.from_pydata(bverts, [], bfaces)
    bmesh0.update()
    belly = new_object("CH_Penguin_Belly", bmesh0)
    belly.data.materials.append(mats["white"])
    shade_smooth(belly)
    assign_weights(belly, body_w)
    parts.append(belly)

    # ------------------------------------------------------------------ eyes
    # flat calm ovals hugging the head: each disc is oriented along the local
    # surface normal and dished to the head's curvature, so the thin white rim
    # stays even all the way around instead of sinking or goggling
    for side in (1, -1):
        ex, ez = 0.140 * side, 0.70
        ey = surface_y(ex, ez)
        n = surface_normal(ex, ey, ez)
        p0 = Vector((ex, ey, ez))
        rot = Vector((0.0, -1.0, 0.0)).rotation_difference(n).to_matrix().to_4x4()

        def make_disc(name, radius, th_scale, mat, lift):
            d = uv_sphere(name, segments=16, rings=10, radius=radius)
            transform_mesh(d, Matrix.Diagonal((0.95, th_scale, 1.06, 1.0)))
            for v in d.data.vertices:   # dish to the head curvature
                v.co.y += (v.co.x ** 2 + v.co.z ** 2) / (2.0 * 0.26)
            transform_mesh(d, rot)
            transform_mesh(d, Matrix.Translation(p0 + n * lift))
            d.data.materials.append(mat)
            shade_smooth(d)
            assign_weights(d, lambda co: {"Head": 1.0})
            parts.append(d)

        sfx = "_R" if side > 0 else "_L"
        make_disc("CH_Penguin_Eye" + sfx, 0.066, 0.20, mats["white"], 0.003)
        make_disc("CH_Penguin_Pupil" + sfx, 0.053, 0.15, mats["eye"], 0.013)

    # ------------------------------------------------------------------ beak
    # two soft rounded lobes: wide flat upper bill over a smaller lower lip
    # (anchored to the face surface so they track the pear profile)
    for nm, sc, pos in (("Upper", (0.042, 0.040, 0.022),
                         (0.0, surface_y(0.0, 0.660) - 0.024, 0.660)),
                        ("Lower", (0.032, 0.031, 0.015),
                         (0.0, surface_y(0.0, 0.638) - 0.019, 0.638))):
        lobe = uv_sphere("CH_Penguin_Beak" + nm, segments=12, rings=8, radius=1.0)
        transform_mesh(lobe, Matrix.Diagonal((sc[0], sc[1], sc[2], 1.0)))
        transform_mesh(lobe, Matrix.Translation(pos))
        lobe.data.materials.append(mats["orange"])
        shade_smooth(lobe)
        assign_weights(lobe, lambda co: {"Head": 1.0})
        parts.append(lobe)

    # ------------------------------------------------------------------ tuft
    # three rounded, asymmetrical little feathers on the crown
    for dx, dy, rot, sc in ((0.005, 0.015, (D(-14), 0, D(6)), 1.0),
                            (0.048, 0.005, (D(-8), 0, D(32)), 0.8),
                            (-0.042, 0.028, (D(-30), 0, D(-26)), 0.72)):
        tuft = uv_sphere("CH_Penguin_Tuft", segments=8, rings=6, radius=1.0)
        transform_mesh(tuft, Matrix.Diagonal((0.024 * sc, 0.024 * sc, 0.055 * sc, 1.0)))
        transform_mesh(tuft, Euler(rot).to_matrix().to_4x4())
        transform_mesh(tuft, Matrix.Translation((dx, dy - 0.04, 0.94)))
        tuft.data.materials.append(mats["body"])
        shade_smooth(tuft)
        assign_weights(tuft, lambda co: {"Head": 1.0})
        parts.append(tuft)

    # ---------------------------------------------------------------- collar
    # soft gathered cowl: fabric folds ripple around the shoulders and dip
    # into a V at the chest where the medallion pins it
    nu_c, rows = 26, 4
    row_off = (0.012, 0.036, 0.056, 0.075)   # radial offset per row, top -> bottom
    row_z = (0.60, 0.555, 0.51, 0.462)
    cverts, cfaces = [], []
    for ri in range(rows):
        rt = ri / (rows - 1)
        for ui in range(nu_c):
            th = TAU * ui / nu_c        # 0 = front (-Y)
            dip = max(0.0, math.cos(th)) ** 3
            back = (1.0 - math.cos(th)) * 0.5
            gather = 1.0 + 0.30 * rt * math.sin(3.5 * th + 0.8) ** 2   # cloth folds
            z = row_z[ri] + 0.035 * back - 0.042 * dip \
                + 0.012 * rt * math.sin(2.5 * th + 1.7)                # organic hem
            off = row_off[ri] * gather * (1.0 - 0.45 * dip)
            w = body_half_width(z)
            rx = w + off
            ry = BODY_YSCALE * w + off
            cverts.append((rx * math.sin(th),
                           -ry * math.cos(th) - head_shift(z), z))
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
    solc.thickness = 0.018
    solc.offset = 1.0
    apply_modifiers(collar)
    shade_smooth(collar)
    assign_weights(collar, lambda co: {"Chest": 1.0})
    parts.append(collar)

    # ------------------------------------------------------------- medallion
    bpy.ops.mesh.primitive_cylinder_add(vertices=10, radius=0.056, depth=0.03)
    med = bpy.context.active_object
    med.name = "CH_Penguin_Medallion"
    med.data.name = "CH_Penguin_Medallion_Mesh"
    transform_mesh(med, Euler((D(90), 0, 0)).to_matrix().to_4x4())
    transform_mesh(med, Matrix.Translation((0.0, -0.315, 0.48)))
    med.data.materials.append(mats["gold"])
    assign_weights(med, lambda co: {"Chest": 1.0})
    parts.append(med)

    # ------------------------------------------------------------------ cape
    # soft cloth: vertical fold ripples, hem falling into two long tapered
    # tails at the back corners
    # full A-line cloak like the reference: attaches at the neck, wraps the
    # back and sides, and flares out to the ground
    nu, nv = 25, 15
    verts, faces = [], []
    for vi in range(nv):
        t = vi / (nv - 1)
        theta_max = D(94 + 34 * t)             # wraps past the sides, more at the hem
        z_base = 0.60 - 0.60 * (t ** 0.86)     # neck -> below the feet
        for ui in range(nu):
            u = ui / (nu - 1)
            th = -theta_max + 2 * theta_max * u
            # near the neck the cloth hugs the body; lower down it becomes a
            # free A-line skirt whose radius grows toward the hem
            hug = body_half_width(max(z_base, 0.30)) * (1 - smoothstep(0.20, 0.9, t))
            flare = (0.235 + 0.145 * t) * smoothstep(0.20, 0.9, t)
            standoff = 0.008 + 0.03 * t          # clings at the neck, free lower
            r = hug + flare + standoff + 0.02 * t * math.sin(5.0 * th)   # folds
            # slight scalloped hem, lifts a touch at the very front opening
            open_lift = smoothstep(0.75, 1.0, t) * max(0.0, math.cos(th)) * 0.05
            zz = z_base + open_lift + (0.012 * math.cos(4.0 * th) if vi == nv - 1 else 0.0)
            verts.append((r * math.sin(th), r * math.cos(th) + 0.045 * t, zz))
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
    sol.thickness = 0.018
    sol.offset = 1.0
    apply_modifiers(cape)
    shade_smooth(cape)

    def cape_w(co):
        t = min(max((0.60 - co.z) / 0.60, 0.0), 1.0)
        blend = smoothstep(0.25, 0.85, t)
        w = {"Cape.1": 1 - blend, "Cape.2": blend}
        if t < 0.10:
            w["Chest"] = 0.4 * (1 - t / 0.10)
        return w
    assign_weights(cape, cape_w)
    parts.append(cape)

    # --------------------------------------------------------- crown emblem
    # bent onto the cape's cylindrical curve so its edges hug the cloth
    crown = ngon_prism("CH_Penguin_CapeCrown", crown_outline(0.17, 0.135), -0.014, 0.026)
    r_bend = 0.34
    for v in crown.data.vertices:
        th = v.co.x / r_bend
        rr = r_bend + v.co.y
        v.co.x = rr * math.sin(th)
        v.co.y = rr * math.cos(th) - r_bend
    transform_mesh(crown, Euler((D(10), 0, 0)).to_matrix().to_4x4())
    transform_mesh(crown, Matrix.Translation((0.0, 0.388, 0.36)))
    crown.data.materials.append(mats["gold"])
    assign_weights(crown, cape_w)
    parts.append(crown)

    # -------------------------------------------------------------- flippers
    # broader, softer paddles hanging down-and-out from under the cowl
    for side, lbl in ((1, ".R"), (-1, ".L")):
        fl = uv_sphere("CH_Penguin_Flipper" + lbl, segments=12, rings=9, radius=1.0)
        transform_mesh(fl, Matrix.Diagonal((0.045, 0.085, 0.16, 1.0)))
        zs = [v.co.z for v in fl.data.vertices]

        def flip_w(co, _zs=zs):
            t = (0.16 - co.z) / 0.32          # 0 at shoulder end, 1 at tip
            blend = smoothstep(0.30, 0.72, t)
            w = {"Flipper" + lbl: 1 - blend, "FlipperTip" + lbl: blend}
            if t < 0.12:
                w["Chest"] = 0.35 * (1 - t / 0.12)
            return w
        assign_weights(fl, flip_w)
        transform_mesh(fl, Euler((0, D(-26) * side, 0)).to_matrix().to_4x4())
        transform_mesh(fl, Matrix.Translation((0.30 * side, 0.005, 0.33)))
        fl.data.materials.append(mats["body"])
        shade_smooth(fl)
        parts.append(fl)

    # ------------------------------------------------------------------ feet
    # broad soft feet with three visible toes to ground the character
    for side, lbl in ((1, ".R"), (-1, ".L")):
        foot_parts = []
        heel = uv_sphere("CH_Penguin_Foot" + lbl, segments=12, rings=7, radius=1.0)
        transform_mesh(heel, Matrix.Diagonal((0.085, 0.085, 0.048, 1.0)))
        transform_mesh(heel, Matrix.Translation((0.0, -0.02, 0.0)))
        foot_parts.append(heel)
        for ti, ang in enumerate((-17, 0, 17)):
            toe = uv_sphere("CH_Penguin_Toe" + lbl, segments=10, rings=6, radius=1.0)
            transform_mesh(toe, Matrix.Diagonal((0.036, 0.088, 0.042, 1.0)))
            transform_mesh(toe, Euler((0, 0, D(ang))).to_matrix().to_4x4())
            reach = 0.085 if ti == 1 else 0.072
            toe_pos = Vector((math.sin(D(ang)) * reach, -math.cos(D(ang)) * reach - 0.02, -0.003))
            transform_mesh(toe, Matrix.Translation(toe_pos))
            foot_parts.append(toe)
        for fp in foot_parts:
            assign_weights(fp, lambda co: {"Foot" + lbl: 1.0})
            transform_mesh(fp, Euler((0, 0, D(-9) * side)).to_matrix().to_4x4())
            transform_mesh(fp, Matrix.Translation((0.135 * side, -0.10, 0.045)))
            fp.data.materials.append(mats["orange"])
            shade_smooth(fp)
            parts.append(fp)

    # ------------------------------------------------------------------ tail
    tail = uv_sphere("CH_Penguin_Tail", segments=10, rings=7, radius=1.0)
    transform_mesh(tail, Matrix.Diagonal((0.075, 0.13, 0.045, 1.0)))

    def tail_w(co):
        blend = smoothstep(-0.06, 0.05, co.y)
        return {"Body": 1 - blend, "Tail": blend}
    assign_weights(tail, tail_w)
    transform_mesh(tail, Euler((D(-18), 0, 0)).to_matrix().to_4x4())
    transform_mesh(tail, Matrix.Translation((0.0, 0.26, 0.075)))
    tail.data.materials.append(mats["body"])
    shade_smooth(tail)
    parts.append(tail)

    return parts


REF_BLEND = os.path.join(ASSET_DIR, "reference", "meshy_penguin.blend")
REF_SCALE = 0.94 / 1.897          # reference height -> our 0.94 m
REF_Z_LIFT = 0.952                # reference feet -> ground plane

# Meshy part-segmentation source: each region is a separate mesh object, so
# assigning one flat material per part gives perfectly clean colour borders.
# Committed as a zip (compact); extracted to the .blend on first build.
REF_SEG = os.path.join(ASSET_DIR, "reference", "meshy_segmented.blend")
REF_SEG_ZIP = os.path.join(ASSET_DIR, "reference", "meshy_segmented.zip")
SEG_TARGET_H = 0.94               # game height, metres


def ensure_segmented_blend():
    if os.path.exists(REF_SEG):
        return True
    if os.path.exists(REF_SEG_ZIP):
        import zipfile
        with zipfile.ZipFile(REF_SEG_ZIP) as z:
            inner = next((n for n in z.namelist() if n.endswith(".blend")), None)
            if inner:
                with z.open(inner) as s, open(REF_SEG, "wb") as d:
                    d.write(s.read())
    return os.path.exists(REF_SEG)
# part -> material key (identified by rendering each part in isolation).
# Note p8 is the whole lower body: it contains both flippers AND both feet, so
# feet are re-coloured by position after assembly, and the cloak's front drape
# is trimmed away to reveal the gray flippers.
SEG_MAT = {
    "model_part9": "body",        # head + upper torso
    "model_part8": "body",        # lower body incl. flippers + feet
    "model_part1": "white",       # left eye disc
    "model_part3": "white",       # right eye disc
    "model_part2": "orange",      # beak
    "model_part10": "cape",       # scarf + cloak
}
SEG_EYES = ("model_part1", "model_part3")
SEG_CAPE = "model_part10"
SEG_DROP = ("model_part0", "model_part4", "model_part5",
            "model_part6", "model_part7")  # duplicate feet + hidden inner shells
SEG_DECIMATE = {"model_part10": 0.05, "model_part9": 0.10, "model_part8": 0.09}
SEG_DECIMATE_DEFAULT = 0.16


def build_penguin_from_segments(donor, mats):
    """Ship the user's Meshy part-segmented sculpt: one flat material per part
    (clean borders by construction), decimated to a game budget, pupils and a
    medallion added, then skin-weighted from the procedural donor."""
    from mathutils import kdtree

    names = list(SEG_MAT) + list(SEG_EYES) + list(SEG_DROP)
    with bpy.data.libraries.load(REF_SEG) as (src, dst):
        dst.objects = [n for n in dict.fromkeys(names) if n in src.objects]
    loaded = {o.name.split(".")[0]: o for o in dst.objects if o}
    for o in loaded.values():
        bpy.context.scene.collection.objects.link(o)

    mat_of = {"body": mats["body"], "white": mats["white"],
              "orange": mats["orange"], "cape": mats["cape"],
              "eye": mats["eye"], "gold": mats["gold"]}

    parts = []
    for pname, key in SEG_MAT.items():
        o = loaded.get(pname)
        if not o:
            continue
        o.data.materials.clear()
        o.data.materials.append(mat_of[key])
        ratio = SEG_DECIMATE.get(pname, SEG_DECIMATE_DEFAULT)
        d = o.modifiers.new("Decimate", "DECIMATE")
        d.ratio = ratio
        apply_modifiers(o)
        shade_smooth(o)
        parts.append(o)

    # flatten the protruding eye discs, then add big navy pupils
    for en in SEG_EYES:
        eye = loaded.get(en)
        if not eye:
            continue
        vs = [v.co.copy() for v in eye.data.vertices]
        c = sum(vs, Vector()) / len(vs)
        nrm = sum((v.normal for v in eye.data.vertices), Vector())
        nrm = (nrm.normalized() if nrm.length > 1e-6
               else Vector((math.copysign(0.3, c.x), -1, 0)).normalized())
        rad = max((v - c).length for v in vs)
        # push the disc back toward the head so it bulges less
        for v in eye.data.vertices:
            along = (v.co - c).dot(nrm)
            if along > 0:
                v.co -= 0.6 * along * nrm
        pup = uv_sphere("CH_Penguin_Pupil", segments=16, rings=9, radius=rad * 0.7)
        transform_mesh(pup, Matrix.Diagonal((1, 1, 0.3, 1)))
        rot = Vector((0, 0, 1)).rotation_difference(nrm).to_matrix().to_4x4()
        transform_mesh(pup, rot)
        transform_mesh(pup, Matrix.Translation(c + nrm * (rad * 0.12)))
        pup.data.materials.append(mat_of["eye"])
        shade_smooth(pup)
        parts.append(pup)

    # gold medallion at the front of the scarf
    scarf = loaded.get("model_part10")
    if scarf:
        band = [v.co for v in scarf.data.vertices if v.co.y < 0]
        if band:
            zmid = sorted(v.z for v in band)[len(band) // 2]
            front = [v for v in band if abs(v.z - zmid) < 0.06]
            fc = min(front, key=lambda v: v.y)
            med = uv_sphere("CH_Penguin_Medallion", segments=14, rings=8, radius=0.05)
            transform_mesh(med, Matrix.Diagonal((1, 1, 0.5, 1)))
            transform_mesh(med, Matrix.Translation(fc + Vector((0, -0.02, 0))))
            med.data.materials.append(mat_of["gold"])
            shade_smooth(med)
            parts.append(med)

    for pname in SEG_DROP:
        o = loaded.get(pname)
        if o:
            bpy.data.objects.remove(o, do_unlink=True)

    penguin = join_parts(parts, "CH_Penguin")

    # orient to game space: feet on the ground, centred, target height, -Y front
    vs = [v.co for v in penguin.data.vertices]
    xs = [v.x for v in vs]; ys = [v.y for v in vs]; zs = [v.z for v in vs]
    scale = SEG_TARGET_H / (max(zs) - min(zs))
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    transform_mesh(penguin, Matrix.Translation((-cx, -cy, -min(zs))))
    transform_mesh(penguin, Matrix.Scale(scale, 4))
    # nudge body centroid to y=0 so donor weight transfer lines up
    ys2 = [v.co.y for v in penguin.data.vertices]
    transform_mesh(penguin, Matrix.Translation((0, -sum(ys2) / len(ys2), 0)))
    recalc_normals(penguin)

    # ---- two orange webbed feet at the bottom front (clear and readable;
    # the Meshy body's own feet are only faint bumps)
    zmin = min(v.co.z for v in penguin.data.vertices)
    fr_pts = [v.co for v in penguin.data.vertices
              if v.co.z < zmin + 0.12 and abs(v.co.x) < 0.22]
    yfoot = min(v.y for v in fr_pts) if fr_pts else -0.2
    feet = []
    for sgn in (1, -1):
        # smooth flat webbed paddle: a flattened ellipsoid, wider and rounded at
        # the front, with three shallow toe scallops carved by the mesh, not
        # separate balls
        foot = uv_sphere("CH_Penguin_Foot", segments=20, rings=10, radius=1.0)
        for v in foot.data.vertices:
            x, y, z = v.co
            scallop = 1.0 + 0.10 * math.cos(3.0 * math.atan2(x, -y)) if y < 0 else 1.0
            v.co.x = x * 0.085 * scallop
            v.co.y = y * 0.115
            v.co.z = z * 0.038
        transform_mesh(foot, Euler((D(-10), 0, D(-7) * sgn)).to_matrix().to_4x4())
        transform_mesh(foot, Matrix.Translation((0.14 * sgn, yfoot + 0.02, zmin + 0.028)))
        foot.data.materials.append(mats["orange"])
        shade_smooth(foot)
        feet.append(foot)
    set_active(penguin)
    for f in feet:
        f.select_set(True)
    penguin.select_set(True)
    bpy.context.view_layer.objects.active = penguin
    bpy.ops.object.join()
    recalc_normals(penguin)

    # ---- white belly patch: a radial oval disc projected onto a sphere fitted
    # to the belly, so it sits a few mm proud with a smooth elliptical rim
    front = [v.co for v in penguin.data.vertices
             if 0.24 < v.co.z < 0.34 and abs(v.co.x) < 0.10 and v.co.y < -0.05]
    side = [v.co for v in penguin.data.vertices
            if 0.22 < v.co.z < 0.36 and v.co.y < -0.03]
    if front and side:
        yfront = min(v.y for v in front)
        R = max(abs(v.x) for v in side)
        C = Vector((0.0, yfront + R, 0.27))
        Rc = R + 0.008
        a, b = 0.235, 0.285               # oval half-extents at the surface
        nring, nseg = 9, 48
        tu, tv = Vector((1, 0, 0)), Vector((0, 0, 1))
        pole = C + Vector((0, -Rc, 0))
        verts = [tuple(pole)]
        for r in range(1, nring + 1):
            fr = r / nring
            for s in range(nseg):
                ang = TAU * s / nseg
                p = pole + tu * (a * fr * math.cos(ang)) + tv * (b * fr * math.sin(ang))
                p = C + (p - C).normalized() * Rc
                verts.append(tuple(p))
        faces = [[0, 1 + s, 1 + (s + 1) % nseg] for s in range(nseg)]
        for r in range(nring - 1):
            base = 1 + r * nseg
            for s in range(nseg):
                i, j = base + s, base + (s + 1) % nseg
                faces.append([i, j, j + nseg, i + nseg])
        pmesh = bpy.data.meshes.new("CH_Penguin_BellyPatch_Mesh")
        pmesh.from_pydata(verts, [], faces)
        pmesh.update()
        cap = new_object("CH_Penguin_BellyPatch", pmesh)
        cap.data.materials.append(mats["white"])
        shade_smooth(cap)
        set_active(penguin)
        cap.select_set(True)
        penguin.select_set(True)
        bpy.context.view_layer.objects.active = penguin
        bpy.ops.object.join()
        recalc_normals(penguin)

    # skin weights: nearest donor vertex
    kd = kdtree.KDTree(len(donor.data.vertices))
    for i, v in enumerate(donor.data.vertices):
        kd.insert(v.co, i)
    kd.balance()
    dgroups = {g.index: g.name for g in donor.vertex_groups}
    dw = [[(dgroups[g.group], g.weight) for g in v.groups] for v in donor.data.vertices]
    for v in penguin.data.vertices:
        _, di, _ = kd.find(v.co)
        for nm, wt in dw[di]:
            vg = penguin.vertex_groups.get(nm) or penguin.vertex_groups.new(name=nm)
            vg.add([v.index], wt, "REPLACE")

    uv_unwrap(penguin)
    return penguin


def build_penguin_from_reference(donor, mats):
    """Use the user's Meshy sculpt as the character mesh: game-optimize it,
    then transfer materials and skin weights from the procedural donor
    (which was fitted to the same proportions)."""
    import bmesh
    from mathutils import kdtree, bvhtree

    with bpy.data.libraries.load(REF_BLEND) as (src, dst):
        dst.objects = ["mesh_node"]
    ref = dst.objects[0]
    bpy.context.scene.collection.objects.link(ref)
    ref.name = "CH_Penguin"
    ref.data.name = "CH_Penguin_Mesh"
    transform_mesh(ref, Matrix.Translation((0.0, 0.0, REF_Z_LIFT)))
    transform_mesh(ref, Matrix.Scale(REF_SCALE, 4))

    # ---- landmark detection on the full-res mesh (crisper than post-decimate)
    # scarf knot: front-most cluster at chest height
    knot_pts = [v.co.copy() for v in ref.data.vertices
                if 0.44 < v.co.z < 0.54 and abs(v.co.x) < 0.10 and v.co.y < -0.31]
    knot_c = sum(knot_pts, Vector()) / len(knot_pts) if knot_pts else None

    # game budget: ~166k tris -> ~13k
    dec = ref.modifiers.new("Decimate", "DECIMATE")
    dec.ratio = 0.08
    apply_modifiers(ref)
    merge_doubles(ref, 0.0006)
    shade_smooth(ref)

    # ---- skin weights: nearest donor vertex
    kd = kdtree.KDTree(len(donor.data.vertices))
    for i, v in enumerate(donor.data.vertices):
        kd.insert(v.co, i)
    kd.balance()
    donor_groups = {g.index: g.name for g in donor.vertex_groups}
    donor_w = []
    for v in donor.data.vertices:
        donor_w.append([(donor_groups[g.group], g.weight) for g in v.groups])
    for v in ref.data.vertices:
        _, di, _ = kd.find(v.co)
        for name, wgt in donor_w[di]:
            vg = ref.vertex_groups.get(name) or ref.vertex_groups.new(name=name)
            vg.add([v.index], wgt, "REPLACE")

    # ---- materials: analytic regions baked to a texture
    # Flat per-face material index can never be smoother than the triangle
    # size, so region borders zigzag. Instead we evaluate the analytic regions
    # per-texel into an image: borders become pixel-crisp and topology-
    # independent, and one textured material exports cleanly to Godot.
    me = ref.data

    # detect the two eye discs (forward-facing vertex clusters on the head)
    eye_discs = []
    for side in (1, -1):
        sel = [v for v in me.vertices
               if v.normal.y < -0.72 and 0.60 < v.co.z < 0.82
               and 0.03 < v.co.x * side < 0.26 and v.co.y < -0.14]
        if sel:
            cc = sum((v.co for v in sel), Vector()) / len(sel)
            nn = sum((v.normal for v in sel), Vector()) / len(sel)
            nn.normalize()
            eye_discs.append((np.array(cc), np.array(nn)))

    # store sRGB display values: the image is tagged sRGB and Blender converts
    # to linear on sample, so pre-linearizing here would darken everything
    def disp(hexcode):
        h = hexcode.lstrip("#")
        return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])
    C = {k: disp(PAL[k]) for k in
         ("body_dark", "white", "eye_black", "orange", "cape_blue", "gold")}

    def region_colors(P):
        """Vectorized analytic colouring. P: (N,3) object-space -> (N,3) RGB."""
        x, y, z = P[:, 0], P[:, 1], P[:, 2]
        rxy = np.hypot(x, y) + 1e-6
        front = -y / rxy                        # 1 at front (-Y), -1 at back
        out = np.tile(C["body_dark"], (len(P), 1))

        belly = (front > 0.30) & ((x / 0.235) ** 2
                                  + ((z - 0.245) / 0.215) ** 2 <= 1.0)
        out[belly] = C["white"]
        cape = (z < 0.585) & ((y > 0.03) | ((front < 0.15) & (z < 0.36)))
        out[cape] = C["cape_blue"]
        scarf_lo = 0.455 - 0.055 * np.clip(front, 0.0, None)
        out[(z > scarf_lo) & (z < 0.60)] = C["cape_blue"]

        flip = (np.abs(x) > 0.24) & (z > 0.12) & (z < 0.50) & (y < 0.06)
        out[flip] = C["body_dark"]
        out[(z < 0.065) & (y < 0.10) & (np.abs(x) < 0.24)] = C["orange"]      # feet
        out[(np.abs(x) < 0.075) & (z > 0.585) & (z < 0.685)
            & (y < -0.255)] = C["orange"]                                     # beak

        for cc, nn in eye_discs:
            rel = P - cc
            along = rel @ nn
            planar = np.linalg.norm(rel - np.outer(along, nn), axis=1)
            disc = np.abs(along) < 0.05
            out[disc & (planar < 0.072)] = C["white"]
            out[disc & (planar < 0.040)] = C["eye_black"]

        if knot_c is not None:
            out[np.linalg.norm(P - np.array(knot_c), axis=1) < 0.05] = C["gold"]
        return out

    # UV unwrap, then rasterize every triangle into the texture
    uv_unwrap(ref)
    SIZE = 1024
    buf = np.zeros((SIZE, SIZE, 3), np.float32)
    filled = np.zeros((SIZE, SIZE), bool)
    uv = me.uv_layers.active.data
    co = [np.array(v.co) for v in me.vertices]
    me.calc_loop_triangles()
    for lt in me.loop_triangles:
        pw = [co[vi] for vi in lt.vertices]
        pt = [np.array(uv[li].uv) * SIZE for li in lt.loops]
        (ax, ay), (bx, by), (cx, cy) = pt
        x0 = max(int(math.floor(min(ax, bx, cx))), 0)
        x1 = min(int(math.ceil(max(ax, bx, cx))), SIZE - 1)
        y0 = max(int(math.floor(min(ay, by, cy))), 0)
        y1 = min(int(math.ceil(max(ay, by, cy))), SIZE - 1)
        if x1 < x0 or y1 < y0:
            continue
        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(det) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5,
                             np.arange(y0, y1 + 1) + 0.5)
        w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / det
        w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / det
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -0.01) & (w1 >= -0.01) & (w2 >= -0.01)
        if not inside.any():
            continue
        P = (w0[..., None] * pw[0] + w1[..., None] * pw[1]
             + w2[..., None] * pw[2])[inside]
        cols = region_colors(P)
        ys = gy[inside].astype(int)
        xs = gx[inside].astype(int)
        buf[ys, xs] = cols
        filled[ys, xs] = True

    # dilate filled texels outward so UV-island edges don't show seams
    for _ in range(4):
        empty = ~filled
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            src = np.roll(np.roll(filled, dy, 0), dx, 1)
            take = empty & src
            if take.any():
                sb = np.roll(np.roll(buf, dy, 0), dx, 1)
                buf[take] = sb[take]
                filled[take] = True

    img = bpy.data.images.new("T_Penguin", SIZE, SIZE)
    img.colorspace_settings.name = "sRGB"
    rgba = np.dstack([buf, np.ones((SIZE, SIZE, 1), np.float32)])
    img.pixels = rgba.ravel()
    img.pack()
    os.makedirs(os.path.join(EXPORT_DIR, "textures"), exist_ok=True)
    img.filepath_raw = os.path.join(EXPORT_DIR, "textures", "penguin_albedo.png")
    img.file_format = "PNG"
    img.save()

    mat = bpy.data.materials.new("M_Penguin")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.9
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Closest"               # crisp pixel-art sampling
    mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    me.materials.clear()
    me.materials.append(mat)

    return ref


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
    ("Body",         (0, 0, 0.26),         (0, 0, 0.48),          "Root",      False, True),
    ("Chest",        (0, 0, 0.48),         (0, 0, 0.66),          "Body",      True,  True),
    ("Head",         (0, 0, 0.66),         (0, 0, 0.95),          "Chest",     True,  True),
    ("Flipper.R",    (0.26, 0.005, 0.47),  (0.315, 0.005, 0.36),  "Chest",     False, True),
    ("FlipperTip.R", (0.315, 0.005, 0.36), (0.37, 0.005, 0.20),   "Flipper.R", True,  True),
    ("Grip.R",       (0.37, 0.005, 0.20),  (0.37, -0.105, 0.20),  "FlipperTip.R", False, False),
    ("Flipper.L",    (-0.26, 0.005, 0.47), (-0.315, 0.005, 0.36), "Chest",     False, True),
    ("FlipperTip.L", (-0.315, 0.005, 0.36),(-0.37, 0.005, 0.20),  "Flipper.L", True,  True),
    ("Grip.L",       (-0.37, 0.005, 0.20), (-0.37, -0.105, 0.20), "FlipperTip.L", False, False),
    ("Leg.R",        (0.135, -0.02, 0.20), (0.135, -0.02, 0.075), "Body",      False, True),
    ("Foot.R",       (0.135, -0.02, 0.075),(0.135, -0.21, 0.045), "Leg.R",     True,  True),
    ("Leg.L",        (-0.135, -0.02, 0.20),(-0.135, -0.02, 0.075),"Body",      False, True),
    ("Foot.L",       (-0.135, -0.02, 0.075),(-0.135, -0.21, 0.045),"Leg.L",    True,  True),
    ("Tail",         (0, 0.19, 0.10),      (0, 0.40, 0.05),       "Body",      False, True),
    ("Cape.1",       (0, 0.31, 0.58),      (0, 0.335, 0.36),      "Chest",     False, True),
    ("Cape.2",       (0, 0.335, 0.36),     (0, 0.38, 0.08),       "Cape.1",    True,  True),
    ("Weapon_Back",  (0, 0.42, 0.40),      (0.28, 0.42, 0.84),    "Chest",     False, False),
    ("Weapon_Ground",(0.52, 0, 0.0),       (0.52, 0, 0.30),       "Root",      False, False),
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

    # soft warm key + generous ambient: illustrated look, gentle shadows
    key_data = bpy.data.lights.new("LGT_Sun_Key_Data", type="SUN")
    key_data.energy = 2.3
    key_data.angle = D(25)
    key_data.color = (1.0, 0.956, 0.878)
    key = bpy.data.objects.new("LGT_Sun_Key", key_data)
    key.rotation_euler = Euler((D(40), D(-18), D(-30)))
    bpy.context.scene.collection.objects.link(key)

    fill_data = bpy.data.lights.new("LGT_Sun_Fill_Data", type="SUN")
    fill_data.energy = 1.2
    fill_data.angle = D(60)
    fill_data.color = (0.88, 0.90, 1.0)
    fill = bpy.data.objects.new("LGT_Sun_Fill", fill_data)
    fill.rotation_euler = Euler((D(55), D(20), D(140)))
    bpy.context.scene.collection.objects.link(fill)

    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = srgb("#F2E9DA")
    bg.inputs[1].default_value = 0.85
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
    # the procedural build acts as donor for materials/weights; the shipped
    # mesh is the user's Meshy sculpt when the reference file is present
    # Character source, in priority order:
    #   default  -> Meshy part-segmented sculpt (exact shape + clean per-part
    #               flat colours), skin-weighted from the procedural donor
    #   USE_REF=1 -> fused Meshy sculpt with baked-texture colouring
    #   PROC=1    -> the procedural model itself
    mode = ("proc" if os.environ.get("PROC") == "1"
            else "ref" if os.environ.get("USE_REF") == "1"
            else "seg" if ensure_segmented_blend()
            else "proc")
    if mode == "proc":
        penguin = join_parts(build_penguin_parts(mats), "CH_Penguin")
        uv_unwrap(penguin)
    else:
        donor = join_parts(build_penguin_parts(mats), "DONOR_Penguin")
        if mode == "seg":
            penguin = build_penguin_from_segments(donor, mats)
        else:
            penguin = build_penguin_from_reference(donor, mats)
        donor_mesh = donor.data
        bpy.data.objects.remove(donor)
        bpy.data.meshes.remove(donor_mesh)

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

    grip = Vector((0.03, -0.30, 0.50))
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
