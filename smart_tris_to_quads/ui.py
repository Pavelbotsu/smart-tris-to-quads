# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pavlo Botsula
"""Blender UI: operator, sidebar panel, Face-menu entry, preferences, shortcut."""
import math

import bmesh
import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty
from bpy.types import AddonPreferences, Operator, Panel
from mathutils.bvhtree import BVHTree

from .engine import grid_tris_to_quads
from .fullquad import full_quads


def _mesh_objects(context):
    if context.mode == 'EDIT_MESH':
        objs = getattr(context, "objects_in_mode_unique_data", None) or [context.edit_object]
    else:
        objs = context.selected_objects
    return [o for o in objs if o is not None and o.type == 'MESH']


class MESH_OT_grid_tris_to_quads(Operator):
    """Convert triangles to quads following the real grid / edge flow, so bevels and
    curved areas come out as clean quad rows instead of zig-zags and leftover triangles"""
    bl_idname = "mesh.grid_tris_to_quads"
    bl_label = "Smart Tris to Quads"
    bl_options = {'REGISTER', 'UNDO'}

    face_threshold: FloatProperty(
        name="Max Face Angle", subtype='ANGLE', unit='ROTATION',
        default=math.radians(40.0), min=0.0, max=math.radians(180.0),
        description="Two triangles bent more than this against each other are never joined")
    max_corner_dev: FloatProperty(
        name="Max Quad Distortion", subtype='ANGLE', unit='ROTATION',
        default=math.radians(70.0), min=math.radians(10.0), max=math.radians(89.0),
        description="Reject quads with a corner further than this from 90 degrees "
                    "(lower = only nice quads, higher = also very skewed ones)")
    use_sharp_angle: BoolProperty(
        name="Protect Creases", default=True,
        description="Never join across an edge sharper than the angle below "
                    "(edges between bevel rows and flat faces stay as edges)")
    sharp_angle: FloatProperty(
        name="Crease Angle", subtype='ANGLE', unit='ROTATION',
        default=math.radians(30.0), min=math.radians(1.0), max=math.radians(180.0),
        description="Edges with a face angle at or above this are protected")
    respect_marks: BoolProperty(
        name="Respect Sharp / Seams / Materials", default=True,
        description="Never join across edges marked Sharp or Seam, or between different materials")
    merge_leftovers: BoolProperty(
        name="Clean Up Leftover Fans", default=True,
        description="Where no real quad exists (fans next to a dense bevel), merge the leftover "
                    "triangles into neighbouring faces when the result still has exactly 4 "
                    "real corners. Those faces are n-gons that look like quads, with the extra "
                    "vertices on their straight sides. Turn off to keep pure quads + triangles")
    continue_loops: BoolProperty(
        name="Continue Rows Through Bevels", default=True,
        description="Rebuild dense bevels so the rows of the faces next to them carry straight on "
                    "across the bevel, instead of the bevel keeping its own dense cross-lines. "
                    "Only flat cross-edges are removed, so the bevel's shape stays the same")
    bevel_crease: FloatProperty(
        name="Bevel Edge Angle", subtype='ANGLE', unit='ROTATION',
        default=math.radians(6.0), min=math.radians(1.0), max=math.radians(60.0),
        description="Edges bent at least this much count as the long edges of a bevel")
    straight_tol: FloatProperty(
        name="Straightness", subtype='ANGLE', unit='ROTATION',
        default=math.radians(5.0), min=0.0, max=math.radians(30.0),
        description="Leftover vertices in the middle of an edge are removed only if the edge bends "
                    "less than this there (keeps curved edges curved)")
    ngon_max_verts: IntProperty(
        name="Max Verts per Merged Face", default=8, min=5, max=32,
        description="Upper limit for faces made by the clean-up step")
    rebuild_flat: BoolProperty(
        name="Rebuild Flat CAD Faces", default=True,
        description="Flat faces exported from CAD as a few huge sliver triangles are cleared and "
                    "re-cut with straight parallel lines that continue the rows around them. "
                    "Only perfectly flat areas with sliver triangles are touched, so the shape "
                    "can't change")
    full_quad: BoolProperty(
        name="Full Quad (adds points)", default=False,
        description="Finish with quads only: pair up leftover triangles and odd faces, add points "
                    "on edges / inside faces and cut every remaining face into quads. Original "
                    "vertices never move and new points sit exactly on the original surface")
    relax_new: BoolProperty(
        name="Even Out New Points", default=True,
        description="Slide the added points along the surface to make the new quads squarer")

    @classmethod
    def poll(cls, context):
        return context.mode in {'EDIT_MESH', 'OBJECT'} and bool(_mesh_objects(context))

    def draw(self, context):
        lay = self.layout
        lay.use_property_split = True
        lay.use_property_decorate = False
        col = lay.column()
        col.prop(self, "face_threshold")
        col.prop(self, "max_corner_dev")
        col.separator()
        col.prop(self, "use_sharp_angle")
        sub = col.column()
        sub.active = self.use_sharp_angle
        sub.prop(self, "sharp_angle")
        col.prop(self, "respect_marks")
        col.separator()
        col.prop(self, "merge_leftovers")
        sub = col.column()
        sub.active = self.merge_leftovers or self.continue_loops
        sub.prop(self, "ngon_max_verts")
        col.separator()
        col.prop(self, "continue_loops")
        sub = col.column()
        sub.active = self.continue_loops
        sub.prop(self, "bevel_crease")
        sub.prop(self, "straight_tol")
        col.separator()
        col.prop(self, "rebuild_flat")
        col.separator()
        col.prop(self, "full_quad")
        sub = col.column()
        sub.active = self.full_quad
        sub.prop(self, "relax_new")

    def _run(self, bm, faces, wm, base, span):
        def prog(x):
            wm.progress_update(base + span * x)

        return grid_tris_to_quads(
            bm, faces,
            face_threshold=self.face_threshold,
            max_corner_dev=self.max_corner_dev,
            sharp_angle=self.sharp_angle if self.use_sharp_angle else None,
            respect_sharp=self.respect_marks,
            respect_seams=self.respect_marks,
            respect_materials=self.respect_marks,
            merge_leftovers=self.merge_leftovers or self.continue_loops,
            continue_loops=self.continue_loops,
            bevel_crease=self.bevel_crease,
            straight_tol=self.straight_tol,
            rebuild_flat=self.rebuild_flat,
            ngon_max_verts=self.ngon_max_verts,
            progress=prog,
        )

    def execute(self, context):
        objs = _mesh_objects(context)
        edit = context.mode == 'EDIT_MESH'
        wm = context.window_manager
        wm.progress_begin(0.0, 1.0)
        tot_in = tot_left = tot_q = tot_ng = tot_lines = tot_pts = 0
        n_obj = 0
        loose_warning = False
        try:
            for i, ob in enumerate(objs):
                me = ob.data
                if edit:
                    bm = bmesh.from_edit_mesh(me)
                else:
                    bm = bmesh.new()
                    bm.from_mesh(me)
                scope_layer = None
                if self.full_quad and edit:
                    # remember the selection through all the joins and splits
                    scope_layer = bm.faces.layers.int.new("_t2q_scope")
                    for f in bm.faces:
                        f[scope_layer] = 1 if f.select else 0
                if edit:
                    faces = [f for f in bm.faces if f.select and len(f.verts) == 3]
                else:
                    faces = [f for f in bm.faces if len(f.verts) == 3]
                if not faces:
                    if scope_layer is not None:
                        bm.faces.layers.int.remove(scope_layer)
                    if not edit:
                        bm.free()
                    continue

                # STL imported without merging vertices: every triangle is an island
                shared = sum(1 for f in faces for e in f.edges if len(e.link_faces) == 2)
                if shared < 0.5 * 3 * len(faces):
                    loose_warning = True

                tris_before = sum(1 for f in bm.faces if len(f.verts) == 3)
                if self.full_quad:
                    surface = BVHTree.FromBMesh(bm)
                r = self._run(bm, faces, wm, i / len(objs), 1.0 / len(objs))
                if self.full_quad:
                    if scope_layer is not None:
                        scope = [f for f in bm.faces if f[scope_layer]]
                    else:
                        scope = list(bm.faces)
                    fq = full_quads(bm, scope, relax=self.relax_new, surface=surface)
                    tot_pts += fq["points_added"]
                    if scope_layer is not None:
                        for f in bm.faces:
                            if f[scope_layer]:
                                f.select = True
                        bm.faces.layers.int.remove(scope_layer)
                tris_after = sum(1 for f in bm.faces if f.is_valid and len(f.verts) == 3)
                tot_in += r["tris_in"]
                tot_left += max(0, tris_after - (tris_before - r["tris_in"]))
                tot_q += r["quads"]
                tot_ng += r["ngon_merges"]
                tot_lines += r.get("bevel_lines", 0)
                n_obj += 1

                if edit:
                    bmesh.update_edit_mesh(me, loop_triangles=True, destructive=True)
                else:
                    bm.to_mesh(me)
                    me.update()
                    bm.free()
        finally:
            wm.progress_end()

        if not n_obj:
            self.report({'WARNING'}, "No triangles to convert"
                        + (" (select some faces first)" if edit else ""))
            return {'CANCELLED'}

        msg = (f"{tot_in} triangles processed, {tot_left} triangles left"
               + (f", {tot_ng} merged into clean faces" if tot_ng and not self.full_quad else "")
               + (f", {tot_lines} rows carried across bevels" if tot_lines else "")
               + (f", {tot_pts} points added for full quads" if self.full_quad else ""))
        if self.full_quad:
            not_quads = 0
            for ob in objs:
                me = ob.data
                if edit:
                    not_quads += sum(1 for f in bmesh.from_edit_mesh(me).faces
                                     if f.select and len(f.verts) != 4)
                else:
                    not_quads += sum(1 for p in me.polygons if len(p.vertices) != 4)
            msg += f" ({not_quads} non-quads in result)"
        if loose_warning:
            self.report({'WARNING'}, msg + ". Most triangles aren't connected: run "
                        "Mesh > Clean Up > Merge by Distance first")
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}


class VIEW3D_PT_grid_tris_to_quads(Panel):
    bl_label = "Smart Tris to Quads"
    bl_idname = "VIEW3D_PT_grid_tris_to_quads"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tris2Quads"

    def draw(self, context):
        lay = self.layout
        col = lay.column(align=True)
        col.scale_y = 1.4
        col.operator(MESH_OT_grid_tris_to_quads.bl_idname, icon='MOD_TRIANGULATE')
        op = col.operator(MESH_OT_grid_tris_to_quads.bl_idname, text="Full Quad (adds points)",
                          icon='MESH_GRID')
        op.full_quad = True
        if context.mode == 'EDIT_MESH':
            lay.label(text="Works on the selected faces", icon='INFO')
        else:
            n = len(_mesh_objects(context))
            lay.label(text=f"Whole mesh of {n} selected object(s)", icon='INFO')
        lay.label(text="Tweak settings in the Adjust Last")
        lay.label(text="Operation panel (F9) after running.")


def _menu_func(self, context):
    self.layout.separator()
    self.layout.operator(MESH_OT_grid_tris_to_quads.bl_idname, icon='MOD_TRIANGULATE')
    op = self.layout.operator(MESH_OT_grid_tris_to_quads.bl_idname, text="Full Quad (adds points)",
                              icon='MESH_GRID')
    op.full_quad = True


_keymaps = []


def _update_keymap(self=None, context=None):
    _unregister_keymap()
    try:
        prefs = bpy.context.preferences.addons[__package__].preferences
        use_altj = prefs.replace_alt_j
    except (KeyError, AttributeError):
        use_altj = False
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new(name="Mesh", space_type='EMPTY')
    if use_altj:
        kmi = km.keymap_items.new(MESH_OT_grid_tris_to_quads.bl_idname, 'J', 'PRESS', alt=True)
    else:
        kmi = km.keymap_items.new(MESH_OT_grid_tris_to_quads.bl_idname, 'J', 'PRESS',
                                  alt=True, shift=True)
    _keymaps.append((km, kmi))


def _unregister_keymap():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()


class GridTrisToQuadsPreferences(AddonPreferences):
    bl_idname = __package__

    replace_alt_j: BoolProperty(
        name="Use Alt+J for this tool in Edit Mode",
        description="When off, the tool is on Shift+Alt+J and Blender's own Alt+J stays as it is",
        default=False, update=_update_keymap)

    def draw(self, context):
        self.layout.prop(self, "replace_alt_j")
        self.layout.label(text="Default shortcut: Shift+Alt+J (Edit Mode). Also in Face menu (Ctrl+F) and F3 search.")


_classes = (
    GridTrisToQuadsPreferences,
    MESH_OT_grid_tris_to_quads,
    VIEW3D_PT_grid_tris_to_quads,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.VIEW3D_MT_edit_mesh_faces.append(_menu_func)
    _update_keymap()


def unregister():
    _unregister_keymap()
    bpy.types.VIEW3D_MT_edit_mesh_faces.remove(_menu_func)
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
