# Read-only image browser

Restart **Launch.cmd**, load your USRDIR, then choose **Images…**. Existing setup
is sufficient; this feature adds no packages or native build requirement.

The browser scans supported containers throughout the supplied folder, rather
than limiting itself to the selected script or scene. It lists original textures
for UI, logos, backgrounds, event pictures, characters, battle, approach, Extras,
effects, models and font atlases. The scenario preview remains a separate logical
preview; opening the browser does not insert these assets into it. Separate
**UI compositions…** previews assemble supported UI layouts from current assets.

## See assets in context

Choose **Images… → UI compositions…**. Implemented compositions include:

- **Title / menu:** press-start or menu layout, four presentation variants,
  selected row, ring angle and a layout-progress sample.
- **Gameplay / message window:** original frame, speaker plate, Skip/Auto widgets,
  advance cursor, opacity and fully revealed sample text. The sample starts from
  the selected dialogue command, or the first dialogue in the selected file.
- **In-game system menu:** settled five-row menu, selected row and chapter panel.
- **Scenario choices:** one sample-text line per entry, authored two/default-row
  placement, selection marker, opacity and previously-chosen text color.
- **Calendar / chapter banners:** month/day, automatic authored date palette or
  explicit override, and a chapter palette with two sample caption lines.
- **Shared dialogs:** measured/wrapped prompt, tiled frame/decorations, authored
  button groups, focus and opacity. Group `-1` shows no buttons.
- **Save / load:** sixty slot positions, authored clipped cards and scrollbars,
  empty/occupied/protected/new states, help icons and an optional thumbnail taken
  from the chosen context backdrop. Metadata is explicitly sample content; the
  preview does not read personal saves. Select Save or Load under **Screen mode**.
- **Backlog:** one sample-text line per retained row (up to200), selection, clipped
  scrolling rows, scrollbar and voice-icon frames. Clear Sample text for the empty
  state. Rows can start from dialogue samples in the selected file; these are not
  personal history. No voice replay or game rewind is executed.

Choose a background/CG for context in non-title previews, or leave the
neutral matte. Context backdrops are selected explicitly; they do not claim to
recover a complete story scene. Change **Sample text** to inspect text in the
layout. These controls modify only the preview snapshot, never a script, project,
game setting or save. The layout-progress control samples shared channel values;
it is not a replay of native animation timing.

Select a layer to outline its destination and inspect its asset identity,
source crop, position, tint and rotation. Double-click a texture layer to locate
it in the individual-image browser. Layouts keep texture identities separate from
pixels so future replacement previews can resolve the same identities; replacement
editing/import/reinjection is not available yet.

**UI families** tracks implemented and pending adapters. Settings/help, Extras, profiles/approach
and battle remain pending. Choosing one reports that status and clears the preview.
It does not substitute an unrelated layout. Coverage/diagnostics also identifies
omitted title particles/live submenus and text decorations or reveal effects.
Static composition does not provide menu actions or full native scene playback.

Rendering uses shared crop/anchor/scale/tint/opacity/rotation primitives and
clamped texture edges. Text reuses the editor's font data and Qt rasterization;
this is not a Vita/PC pixel-parity test. **Refresh layouts** rereads environment
snapshots. Reload the game to import externally changed font/text settings, and
re-index images for changed source textures. Source switches invalidate pending
work; current preview textures use bounded caches and cancellable loading.

List controls expose a static scroll-channel sample and an optional first visible
row (`-1` chooses automatically). Cards use their authored viewport clip; layer
inspection still shows their complete destination and clip rectangles. Save dates
and occupied-card text are samples. The new-marker particle scale is a static
sample rather than playback of its timed cycle.

## Find and inspect

- Search names, resource identities, categories or known uses. `script:000`
  finds images with a mapped literal reference in that original script.
- Filter by category or unsupported/invalid status. Click column headers to sort;
  **Source order** restores archive/member order.
- Select a row to decode it. Transparent pixels use a checkerboard. **Fit**, **1:1**,
  zoom buttons, the mouse wheel and dragging control the view.
- **Location / usage** shows the archive/member chain, exact indices, original
  names, compression and byte extents. Nested offsets belong to their decoded
  parent container; they are not absolute offsets into the outer archive.
- **Atlas regions** outlines known font glyphs and ordinary message-window sprites.
  Other textures currently display as a whole; a missing region definition does
  not mean the texture is unused. Region overlays do not alter extracted images.
- **Script uses** lists potential literal references from original scripts. Double
  click one to inspect that command in the editor. Existing project commands are
  located by original identity; removed commands report that they were removed.
- **Inventory / issues** reports scanned banks, including empty ones, traversal
  failures and dynamic resource operands. Unclassified images stay in the list.

The source folder is the one successfully loaded by **Load game**. Typing a
different folder without loading it does not change the browser source. Loading
another game folder cancels and invalidates the old index. **Re-index** refreshes
the inventory after an external source change; stale assets cannot be extracted.
Selected images decode in a worker; decoded-image and source-byte caches are
bounded. **Cancel** stops the current operation. Closing the browser preserves
the index for reopening; closing the editor cancels its remaining image work.

## Extract into a separate folder

1. Select one or more rows with the usual Shift/Ctrl selection, or filter the list.
2. Choose **Original bytes + PNG**, **Original bytes only**, or **PNG only**.
3. Choose **Extract selected…** or **Extract filtered list…** and select a separate
   empty folder. The latter extracts every filtered row, including rows offscreen.

Extraction stages its output, then publishes it only when the whole selection
succeeds. Source folders, their ancestors/descendants and occupied destinations
are rejected. Errors/cancellation discard the staging output. Existing files are
never overwritten. A corrupt or unsupported picture can still be extracted as
original bytes; requesting PNG for an undecodable selection fails the operation
instead of silently dropping it.

“Original bytes” means the image member after archive decompression, such as a
GXT texture. It is not a cropped sprite or an entire archive. `manifest.json`
records source hashes, member chains, storage offsets/extents, image hashes,
known uses/regions and output filenames. Keep it with the extraction for future
asset tooling. There is no image import, editing or reinjection in this version.

## Coverage limits

Supported pixel layouts are single-texture, single-mip Vita GXT P8 ARGB/opaque RGB
and 32-bit ARGB, linear or rectangular swizzled, including padded rows/palettes.
Standalone/nested PNG and JPEG are also recognized. Other GXT layouts remain
visible with an unsupported/invalid explanation. The index bounds source files
to 512 MiB, decompressed members to 128 MiB and decoded images to 64 megapixels;
an exceeded bound is reported, never treated as a successful scan.

Individual textures remain available alongside the limited UI compositions above.
Animated characters/Live2D, full native screen behavior, motion/pose composition,
save-generated thumbnails, movies and audio are outside this inventory. Known consumer labels and literal script uses
help locate textures but are not an exhaustive scene-use graph: runtime variables,
native bindings and indirect mode data can select additional images. The current
project's text edits do not change the original-reference index.

This version's image review/extraction interface is the GUI. The existing text
MCP interface does not yet expose the image catalog. Extracted assets, manifests
and private inventories are local data and should not be published with the tool.
