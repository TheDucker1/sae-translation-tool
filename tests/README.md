# Focused synthetic checks

These checks exercise editor reference repair, transactions, archive export,
translator context and command help using synthetic fixtures. No original game
assets or captured native evidence are distributed. Some optional checks skip
when the locally supplied game data or MCP dependencies are unavailable.

After setup, create the ignored scratch directory once:

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
```

Run the affected module, for example:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_document.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_game_export.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_image_assets.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_composition.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_composition_extras -v
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_composition_modes -v
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_composition_battle -v
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_visual_mcp -v
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_texture_projects -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_texture_export.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_ui_text.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_pvf_preview.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_width_controls.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_autofit_layouts.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_fontstyle.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_autofit_ui.py -v
```

Translator/MCP checks require `requirements-mcp.txt`. Run a focused check when
changing its boundary; do not replay a game or run unrelated suites for every edit.

Width-control checks cover visible text and ruby around intact timed tags,
conversion-only overflow reports, queue indices, one Undo and archive export.
Auto-fit layout checks distinguish all seven text consumers across files,
fixed label advances, native space padding, curved fill masks and explicit reflow.
Font-style checks distinguish fixed-cursor labels from measured text, preserve
syntax/hidden data and check existing UI repair, typed serialization and Undo.
They also catch native advance double-truncation and quote conversion around
timed cues, printf operands and protected UI controls.
Unified Auto-fit checks cover combined script/UI Apply and Undo, checked UI-only
selection, stale plans and rejection of invalid UI text before any batch commit.

The image module uses tiny synthetic GPDA/GXT/font fixtures for pixel layouts,
member provenance, extraction boundaries and asynchronous GUI source switching.
It requires PySide6 but no game files or optional MCP package.

Composition checks use tiny synthetic pixels to distinguish atlas edge clamping,
flips, anchor/scale, tint, layer blending and pivot rotation, plus layout-source
snapshot invalidation. They do not replay menu controllers or game scenarios.
The focused list-rendering case also checks clipped reversed source rectangles
and natural-size cached help icons without any original assets or save data.
Extras checks distinguish native catalogue token/category padding and offscreen
RGBA multiplication (including alpha and quad coverage) from normal source-over.
Mode checks distinguish binary stencil alpha from opacity/luminance and retain
native three-row description splitting and approach topic capacity.
Battle checks distinguish unscaled widget anchoring followed by a centered pulse,
and text advance extents from the rasterized glyph rectangles used to draw them.
Visual MCP checks cover native image blocks with separate structured geometry,
offscreen/text/glyph/filter paging and strict state/stale-snapshot handling. They
require optional MCP dependencies and working local sockets for Python asyncio.
Texture project checks use tiny PNG/GXT fixtures for exact transparent RGBA/PNG
bytes, save/reopen/Undo, corrupt/mismatched inputs and bitmap-atlas cache refresh.
Texture export checks cover palette/alpha limits, rectangular swizzle, stride/gap/
tail retention, combined nested GPDA/gzip/script/FONT merge and seek repair,
texture-only export, no-overwrite and preflight failure before publication.
No original game assets are required.

UI text checks cover UTF16 lengths/non-BMP text, native quote/CRLF table handling,
CP932/placeholder/protected-field rejection, atomic batches and source fingerprints,
mixed script/UI Undo/reopen, effective environment reads, combined texture/script/
catalogue/environment export with seek repair, and human/agent draft conflicts.

PVF preview checks distinguish full sampled cache cells from half-width draw
advances, fractional packed-column widths, duplicate charset entries and cropped
sampling borders. They use synthetic font tables/pixels, not original fonts.
