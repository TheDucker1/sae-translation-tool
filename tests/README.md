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
```

Translator/MCP checks require `requirements-mcp.txt`. Run a focused check when
changing its boundary; do not replay a game or run unrelated suites for every edit.

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
