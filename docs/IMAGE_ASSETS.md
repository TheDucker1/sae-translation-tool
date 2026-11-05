# Image assets and project PNG replacements

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
- **Settings / help:** text, audio and voice pages with their sliders/toggles,
  selection highlights, voice modes/characters, header variants and authored help
  descriptions/footer. **Options page** switches pages; unrelated controls hide.
  Values affect only this composition, without changing game settings or audio.
  The fourth alternate header is viewable, but the current reference defines no
  page-content drawing for that tab; the preview states this gap explicitly.
- **Extras:** section menu, CG album/full-image viewer, movie-thumbnail gallery,
  music-player UI and battle replay list. **Extras screen** selects the view;
  category/page/cell/variant controls select CGs. Other lists expose selection and
  scrolling. Unlock/new flags and music position/mode are preview samples, without
  reading personal progress or playing movies, audio or battle replays.
- **Profiles / approach:** profile selection/confirmation, result and response UI;
  approach mission/gauge, topics/choices and result. Choose **Screen**. Profiles
  read the original scene/event/item tables; the carousel selector's focused item
  is `(selector + 3) % 10`. Scene and character ordinal controls clamp to available
  rows. Stat `-1` uses authored initial values; explicit values are preview samples.
  Approach topics use one line per topic: `Topic | Choice1 | Choice2 | Choice3`, up
  to six topics and three children. Child focus/read/used flags show their variants.
  Topics/result text may start from matching commands in the current script.
  Response view composes the response window/text; external actors/backgrounds
  are not reconstructed. Choose a context backdrop to inspect it against a scene.
- **Battle:** introduction emblems/name/caption panels, dialogue bubbles/text,
  timed-choice cards/HUD/countdown and left-win/right-win/equal result lettering.
  **Screen** selects the view. Participant IDs, captions, bubble/card types,
  multiline dialogue, choice text, read colors, timer and pulse samples affect only
  this snapshot. Introduction/choice samples can start from current-file commands.
  Visible choice cards represent rows1–3; row0 is the timeout route and has no card.
  Divider X is a display sample, independent of the logical battle score. Actors,
  Live2D poses and actual timer/input/media playback are not reconstructed.

Choose a background/CG for context in non-title previews, or leave the
neutral matte. Context backdrops are selected explicitly; they do not claim to
recover a complete story scene. Change **Sample text** to inspect text in the
layout. These controls modify only the preview snapshot, never a script, project,
game setting or save. The layout-progress control samples shared channel values;
it is not a replay of native animation timing.

Select a layer to outline its destination and inspect its asset identity,
source crop, position, tint and rotation. Double-click a texture layer to locate
it in the individual-image browser. Layouts keep texture identities separate from
pixels. Project PNG replacements resolve those same identities in the texture
browser and compositions; original/current comparison does not alter the layout.
Game reinjection is not available yet.

**UI families** records coverage and limitations for all twelve implemented screen
families. These include variants, rather than every story scene. Ending prompts
and save screens reuse the shared-dialog and save/load layouts. Coverage/diagnostics
identifies omitted title particles and text decorations or reveal effects.
Static composition does not provide menu actions or full native scene playback.

Rendering uses shared crop/anchor/scale/tint/opacity/rotation primitives and
clamped texture edges. Extras headers also use offscreen targets and the authored
RGBA multiply blend. Their contributing source layers are inspectable individually;
the generated target itself has no separate source image. Text reuses the editor's
font data and Qt rasterization; this is not a Vita/PC pixel-parity test. PVF glyphs
use full precache cells and the player's half/full-width draw rule, rather than
stretching a Latin glyph's own narrow outline to fill its destination. Cell/source
rectangles and baseline match the implementation; antialias coverage can differ.
**Refresh layouts** rereads environment
snapshots. Reload the game to import externally changed font/text settings, and
re-index images for changed source textures. Source switches invalidate pending
work; current preview textures use bounded caches and cancellable loading.
Profile/approach result content follows texture-alpha stencil coverage, and result
text retains inline color ranges. Snapshots show settled results, without executing
their reveal/voice/fade timelines or publishing gameplay state.

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
asset tooling. Extraction always uses original game pixels/bytes, even when the
project has replacements. Use the PNG authoring controls below for current pixels.

## Import edited PNGs into the project

1. Select a texture and choose **Save viewed PNG…** to create a separate new PNG.
   With **Original pixels** checked it uses original pixels; otherwise it uses
   the project replacement, if present. Existing files are never overwritten.
2. Edit that PNG externally, keeping its original dimensions. Preserve transparency
   and use8-bit color; the tool rejects16-bit PNG rather than reducing precision.
3. Choose **Import PNG…**. The replacement appears as **Project PNG** in the table
   and is used by UI compositions. **Original pixels** compares the individual
   texture; **Use original textures** compares a whole composition.
4. **Save project** retains the PNG inside the normal `.saekano.json` file. Moving
   or deleting the external editing PNG afterwards does not break that project.
   **Revert PNG** removes the override; the editor's Undo/Redo includes both import
   and revert, alongside normal text/font edits.

PNG bytes and decoded straight RGBA pixels are preserved, including partial alpha
and RGB values under fully transparent pixels. Original GXT palette/swizzle/storage
metadata stays in the provenance; a PNG is not a byte-identical GXT container.
**Export game…** encodes those pixels into the original GXT layout and merges
them with script/font edits in a separate complete patched USRDIR. It preflights
all replacements before copying; an invalid replacement cannot be silently omitted.

Atlas crops/positions/metrics remain unchanged, hence the exact-dimension rule.
Original font-atlas replacements also affect cached bitmap glyphs in composition
previews; font generation and text metrics remain separate. There is no built-in
pixel-painting canvas. Animated PNG is rejected. Individual PNGs are limited to
32MiB, with128MiB total compressed PNG data and4096 replacements per project.

Projects with textures use format version2; old version1 projects still load.
Reopening checks original asset identity/file/member hashes, PNG checksums,
dimensions and decoded pixels. A modified/mismatched source rejects the project
rather than attaching pixels to another texture. Texture-only changes refresh
image/composition caches without restarting the scenario simulator.

## Export edited textures to the game

For live UI labels/prompts/help text, use **UI text…**, not texture replacement.
These strings are now editable and flow into the same UI compositions/export.
See [UI text](UI_TEXT.md). Texture lettering remains a PNG editing task.

Restart the editor, load the original USRDIR and open your saved project. Review
the PNG replacements and compositions, then choose **Export game…** and a separate
new/empty output folder. Use the exported data copy for game testing. Original
files, personal saves, executables and launcher settings remain untouched. Export
is staged and only published after completion; cancellation/failure leaves no
partially published copy. Existing destination files are never overwritten.

The image details show **Game export constraints** for the selected texture:

- Dimensions must remain identical. UI atlas crops/destination rectangles and
  font glyph records are authored separately; replacing an image with a larger
  one does not update them. Particle grids also depend on texture dimensions.
- P8 ARGB retains at most256 distinct RGBA colors across the **whole texture**,
  including transparent pixels. P8 opaque RGB additionally requires alpha255
  everywhere. A PNG may preview correctly yet fail this stricter game constraint.
  Reduce colors deliberately in your image editor; export never quantizes.
- Original32-bit ARGB textures retain full8-bit RGBA. Export keeps original
  format, swizzle, row stride, palette placement, headers, extent and padding.
  It cannot change a P8 texture into32-bit to bypass a consumer's format limits.
- GXT must use the supported single-texture, one-mip layouts above. Original
  GPDA kind0/1 raw/gzip and FONT paths are supported. Changed type2 paths, opaque
  seek subtrees and non-GXT originals reject explicitly rather than guessing.

Nested archive names/kinds/indices and unrelated physical payloads are retained.
Changed gzip ancestors are rebuilt; resource seek offsets/sizes/checksums are
recalculated after merging all changes. Original FONT atlas edits preserve any
generated Latin atlas and its records. `saekano-export.json` records changed
texture IDs, constraints and source/output GXT/pixel/file hashes. Identical decoded
imports leave the original GXT byte-for-byte unchanged. Source changes during
preparation/copy abort publication.

These checks verify encoding and archive consistency. They do not claim every
texture consumer or rendered frame has been playtested on either platform.

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

The existing standalone and GUI-hosted MCP connections also expose texture and
UI-scene images with structured asset/layer/text metadata. Use list_textures,
get_texture and get_texture_usage, or list_ui_scenes → describe_ui_scene →
get_ui_scene; get_ui_scene_layers pages the exact snapshot with optional glyphs
and a text-only filter. See the [tool guide](TRANSLATOR_GUIDE.md) for coordinate,
state and snapshot rules. These calls do not change the GUI/project or write files;
extraction remains a separate GUI action. Extracted assets, manifests and private
inventories are local data and should not be published with the tool.
For agent authoring, write_texture_png creates a separate workspace PNG;
import_texture_png stores the edited file in the project, and
remove_texture_replacement reverts it. All writes require the current project
revision; the same Save/Undo/preview behavior applies in standalone and live GUI.
check_texture_export performs actual lossless encoding without writing files;
export_game_copy performs the same preflight and publishes a separate complete copy.
