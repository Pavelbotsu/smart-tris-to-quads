from build123d import *
import math

parts = {}

# 1. Bracket: filleted block with a pocket, holes, chamfered rim
with BuildPart() as bracket:
    Box(80, 50, 20)
    fillet(bracket.edges().filter_by(Axis.Z), radius=6)
    with Locations((0, 0, 10)):
        Box(50, 28, 12, mode=Mode.SUBTRACT)
    with Locations((-30, 0, 0), (30, 0, 0)):
        Cylinder(4, 30, mode=Mode.SUBTRACT)
top = [e for e in bracket.part.edges() if abs(e.center().Z - 10) < 0.01]
pb = bracket.part
for r in (1.5, 1.0, 0.6):
    try:
        pb = bracket.part.fillet(r, top)
        print('bracket top fillet', r, 'ok')
        break
    except Exception:
        print('bracket top fillet', r, 'failed')
parts["bracket"] = pb

# 2. Panel with grooves (panel lines) meeting at a T, groove edges rounded
with BuildPart() as panel:
    Box(120, 80, 8)
    with Locations(Location((8, 0, 3.5), (0, 0, 57))):
        Box(130, 5, 3, mode=Mode.SUBTRACT)
    with Locations((-38, -4, 3.5)):
        Box(58, 4, 3, mode=Mode.SUBTRACT)
inner = [e for e in panel.part.edges()
         if abs(e.center().Z - 4) < 0.01 and abs(e.center().X) < 59.5 and abs(e.center().Y) < 39.5]
p2 = panel.part
for r in (1.2, 0.8, 0.5):
    try:
        p2 = panel.part.fillet(r, inner)
        print("panel groove fillet", r, "ok")
        break
    except Exception as ex:
        print("panel fillet", r, "failed")
for r in (6, 4):
    try:
        p2 = p2.fillet(r, [e for e in p2.edges() if e.geom_type == GeomType.LINE
                            and abs(e.length - 8) < 1e-3 and abs(abs(e.center().X) - 60) < 1e-3 and abs(abs(e.center().Y) - 40) < 1e-3])
        print("panel corner fillet", r, "ok")
        break
    except Exception as ex:
        print("panel corner fillet", r, "failed", ex)
parts["panel"] = p2

# 3. Knob: cylinder, fillet on top, chamfer at bottom, hex hole
with BuildPart() as knob:
    Cylinder(20, 18)
    fillet(knob.edges().group_by(Axis.Z)[-1], radius=5)
    try:
        chamfer(knob.edges().group_by(Axis.Z)[0], length=1.5)
    except Exception as ex:
        print('knob chamfer skipped', ex)
    with BuildSketch(Plane.XY.offset(-9)):
        RegularPolygon(6, 6)
    extrude(amount=10, mode=Mode.SUBTRACT)
parts["knob"] = knob.part

with BuildPart() as rb:
    Box(60, 40, 20)
    fillet(rb.edges(), radius=4)
    with Locations((0, 0, 10)):
        Box(30, 16, 8, mode=Mode.SUBTRACT)
inner_top = [e for e in rb.part.edges() if abs(e.center().Z - 10) < 0.01 and abs(e.center().X) < 16 and abs(e.center().Y) < 9]
p3 = rb.part
for r in (2.0, 1.0):
    try:
        p3 = rb.part.fillet(r, inner_top)
        print("roundbox pocket fillet", r, "ok")
        break
    except Exception:
        print("roundbox pocket fillet", r, "failed")
parts["roundbox"] = p3

for name, p in parts.items():
    for q, (tol, ang) in {"medium": (0.05, 0.25), "fine": (0.01, 0.1)}.items():
        export_stl(p, f"{name}_{q}.stl", tolerance=tol, angular_tolerance=ang)
        print(name, q, "exported")
