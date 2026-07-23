# Richard the Penguin Knight — Game Assets

Low-poly, rigged 3D assets for a stylized top-down action game in Godot 4,
built from the character concept sheet ("Richard the Penguin Knight").

## Contents

| Path | Description |
| --- | --- |
| `assets/penguin_warrior.blend` | Full Blender scene: character, sword, rig, materials, preview camera, lighting, ground plane |
| `assets/exports/penguin_warrior.glb` | Game-ready rigged penguin (mesh + armature + materials) |
| `assets/exports/greatsword.glb` | Game-ready greatsword (separate asset) |
| `assets/previews/*.png` | Readability renders from the gameplay camera, turnaround orthos, held pose, pixelated in-game look |
| `scripts/build_penguin_assets.py` | Procedural build script — regenerates everything from scratch |

## Asset specs

**CH_Penguin** — ~5,900 tris, 6 flat-colour materials (`M_Penguin_Dark`,
`M_Penguin_White`, `M_Penguin_EyeBlack`, `M_Penguin_Orange`, `M_Cape_Blue`,
`M_Gold`), colours sampled from the concept palette. Rounded plush-mascot
build: squat smooth-shaded egg body, flat oval eyes with navy pupils and thin
white rims, two-lobe bill, plumage belly lens, gathered cloth cowl, cape with
fold ripples and tapered tails, three-toed feet. 1.0 m tall, origin at the
centre of the feet on the ground plane, faces **-Y** in Blender (imports
facing **-Z** in Godot). Scale/rotation applied.

**WPN_Greatsword** — ~520 tris, 6 materials (`M_Sword_Steel`, `M_Sword_Face`,
`M_Gold`, `M_Gold_Dark`, `M_Sword_Wrap`, `M_Sword_Gem`). 2.36 m long
(~2.3× the penguin — intentionally absurd). Origin at the main grip position;
blade points **+Z** in Blender (**+Y** in Godot). Broad chipped slab blade,
dark core plate, crown mark near the tip, gold crossguard with diamond studs,
wrapped two-flipper grip, gold pommel with blue gem. In the `.blend` the sword
object is posed lying on the ground for presentation; the GLB is exported with
identity transforms.

## Rig (`RIG_Penguin`, 19 bones)

Deform chain:

```
Root
└─ Body ── Leg.L/R ── Foot.L/R,  Tail
   └─ Chest ── Head,  Cape.1 ── Cape.2
      └─ Flipper.L/R ── FlipperTip.L/R
```

Non-deform attachment bones (use with `BoneAttachment3D` in Godot):

- `Grip.R` / `Grip.L` — child of each flipper tip; two-handed sword hold
- `Weapon_Back` — child of `Chest`; diagonal back-carry slot
- `Weapon_Ground` — child of `Root`; sword planted beside the character

Every vertex is weighted (no auto-weights — regions were assigned
programmatically, so deformation is predictable). The rig supports idle,
walk/run, turning, flipper motion, two-handed swings, dashes, parries, hits,
and knockdowns; the sword stays a separate object and attaches to any of the
four attachment bones.

## Godot 4 import notes

1. Drop both `.glb` files into your project — default import settings work.
2. Character: instance `penguin_warrior.glb`, add a `BoneAttachment3D`
   targeting `Grip.R` (or `Weapon_Back`, etc.) and parent an instance of
   `greatsword.glb` under it.
3. Materials are plain Principled/flat-colour (no textures) and convert to
   `StandardMaterial3D`. For the toon look, swap in a toon `ShaderMaterial`
   per colour slot, or keep the flat colours — they read correctly at low
   internal resolutions with nearest-neighbour scaling.
4. Outlines: use an inverted-hull or screen-space shader in Godot if desired
   (no outline geometry is baked in).

## Regenerating

```bash
pip install bpy pillow
python3 scripts/build_penguin_assets.py          # full build + renders
RENDERS=0 python3 scripts/build_penguin_assets.py  # skip preview renders
```

The script rebuilds the scene deterministically, runs sanity checks
(weighting coverage, deformation smoke test, blade-geometry checks, applied
transforms), exports both GLBs, and renders the preview set.
