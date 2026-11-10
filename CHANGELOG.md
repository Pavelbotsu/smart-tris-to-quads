# Changelog

All notable changes to Smart Tris to Quads. Versions follow `bl_info["version"]`.

<!--
How to add a release:
1. Add a new "## [x.y.z] - YYYY-MM-DD" section at the top (below this comment).
2. Group changes under: Added / Changed / Fixed / Removed.
3. `python tools/build.py --notes` prints the section; the GitHub release uses it as its text.
-->

## [4.1.0] - 2026-11-10

First public release.

### Added
- **Smart Tris to Quads**: pairs triangles along the real grid, so edge loops follow the surface
  instead of zig-zagging like stock Alt+J.
- **Continue Rows Through Bevels**: carries face rows straight across dense bevel strips.
- **Rebuild Flat CAD Faces**: redraws flat CAD faces made of huge sliver triangles.
- **Full Quad (adds points)**: finishes with quads only. Original vertices never move and new
  points sit exactly on the original surface.
- Sidebar tab (N > Tris2Quads), Face menu entry, Shift+Alt+J shortcut (optional Alt+J in the
  preferences), live settings with F9.
- Works in Blender 3.6 to 5.x; installs as an extension in Blender 4.2+.
