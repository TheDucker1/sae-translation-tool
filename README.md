# Saekano Script Studio — v0.2 alpha

A Python/Qt translation and asset editor for Saekano. Edit scenario text and UI
strings, inspect script flow, replace textures, improve Latin font readability,
preview changes, and export a separate patched game-data copy.

The scenario simulator uses placeholder art and silent logical services. Separate
UI composition previews render supported screens with the current game assets,
translated labels and selected font. These are static snapshots, not a playable
game or a claim of complete visual/timing parity.

Supply your own USRDIR. Original data stays read-only; no original game assets,
font files, translated projects or native captures are included.

## New in v0.2

- **Image assets:** searchable texture inventory, transparency/atlas inspection,
  extraction, same-size PNG replacements, and lossless GXT reinjection on export.
- **UI translation:** edit environment/help text, menus, prompts and catalogues
  alongside scenario text, with shared project saves and Undo/Redo.
- **Visual review:** composed UI screens with inspectable layers, source-bound
  field previews, and previews of unapplied Auto-fit proposals.
- **Font and fitting:** generated proportional dialogue glyphs and readable
  fixed-cell UI glyphs from the supplied font. Auto-fit normalizes text before
  measuring each consumer's layout, including battle bubbles and profile tips.
- **Agent tools:** GUI-shared and standalone MCP access to UI text, textures,
  rendered images, composition geometry and the same editing/export operations.

Older projects remain supported. Overlong platform save metadata now loads
unchanged with an actionable warning; its native capacity is enforced on game
export rather than preventing the project from opening.

## Setup and launch

Developed with Python 3.14 on Windows. From the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Then double-click **Launch.cmd**, choose your USRDIR and click **Load game**.
Alternatively:

```powershell
.\.venv\Scripts\python.exe run.py --usrdir "C:\path\to\USRDIR"
```

Setup installs the pinned PySide6 dependency. No Visual Studio, CMake, custom DLL
or Impacto checkout is required. Restart after application updates.

## Scenario text workflow

1. Load the game files and select a script. Inspect dialogue, choices, command
   help and script/file flow charts. Exact arguments and debug state are under
   **Advanced**.
2. Edit, add, replace or delete a text command. Targets use stable identities;
   structural edits repair typed references. Deleting an incoming target requires
   a replacement or leaves a validation error. Undo/Redo restores transactions.
3. **Save project** writes an editable `.saekano.json` project outside the original
   data. It does not overwrite a game script. Reopening checks source fingerprints.
4. Preview, step or replay to review context. **Preview here** needs a recorded
   route or an explicitly fresh/sandbox state; arbitrary jumps cannot recover all
   earlier story variables. Passing validation does not prove every route works.
5. **Export game…** writes a complete patched USRDIR into a new/empty folder,
   including script metadata, UI translations, texture replacements and the
   selected font asset. Original data and occupied destinations are never
   overwritten. Select the new data folder manually in
   your game/emulator setup. No launcher setting or executable is modified.

Editable families: dialogue, ordinary choices, chapter captions, battle choices,
approach topics/options, approach results and battle-introduction captions. Other
commands retain the logical state/control flow needed for translation preview;
native menu interaction remains outside the scenario simulator. Read-only UI
composition previews and non-script image inspection are available separately below.

Structural changes can invalidate existing game saves/history. Export reports
when fresh progress is required; it does not migrate personal saves.

## Image assets

**Load game → Images…** opens the image browser across the full source data
tree. Search/filter textures, view transparency and known atlas regions, inspect
archive/member locations and literal script uses, and extract original image
members and/or PNGs into a separate empty folder with a provenance manifest.
Images are decoded on selection. **Import PNG…** stores same-size lossless texture
replacements in the editor project, with Undo/Redo and current/original comparison.
Save the project to retain them. **Export game…** now merges texture, script and
font edits into a separate patched USRDIR. GXT encoding is lossless and retains
original dimensions/formats: P8 textures allow at most 256 RGBA colors; opaque
originals must stay opaque. Invalid replacements fail before copying files.
**UI compositions…** assembles title/menu, gameplay message-window, system-menu,
choices, calendar/chapter, shared-dialog, save/load, backlog, settings/help and
Extras, profile/approach and battle layouts with preview states and inspectable
layers. The coverage checklist records each family's limits.
See [the image-browser guide](docs/IMAGE_ASSETS.md) for usage and coverage limits.

## UI text and screen previews

**UI text…** discovers and edits environment/catalogue labels, prompts,
settings/help, save messages, Extras titles, keywords and profile items/responses.
These share project saves, Undo/Redo and separate game export. Protected
resource/control fields and retained strings without a drawn consumer are
identified explicitly.

Use **Preview field…** to review a field's current text or unsaved draft in its
supported screen. In **Auto-fit text…**, **Preview selected UI…** renders the
checked proposals before Apply. Both use the effective project text, font and
textures; they do not modify the project merely to produce a preview.

Platform save metadata has its own limits. An overlong field remains editable
and can be saved in the project; Validation and the UI text browser identify the
field to shorten before export. These limits do not apply to scenario dialogue.
See [the UI text guide](docs/UI_TEXT.md).

## Wrapping and readability

Multiline text fields accept Enter as a native break. **Wrap words** uses the
loaded font/layout; single-line labels have **Check fit**. Preserve native control
tags and speaker/quotation delimiters. Timed dialogue with explicit breaks is
unsupported and rejected by editing, preview and export.

For older translations, **Auto-fit text…** analyzes the current file by default.
Choose **Whole project** for all scripts and keep **Include translated UI text**
enabled to review UI changes too. Auto-fit detects each command's consumer,
uses its authored geometry and reports overflow. Review the proposals, then
**Apply**. Enable **Reflow existing line breaks** when repairing
old narrow wrapping; explicit breaks otherwise remain in place.
Analyze alone does not change text; save/export does not implicitly run Auto-fit.
Safe ordinary dialogue can be paginated with repeated speakers and repaired
references. Timed, queued and retained-buffer cases report limitations instead
of silently rewriting their synchronization.

Optional **Full-width Latin** widens supported glyphs. For proportional dialogue,
choose **Proportional dialogue + readable UI font asset**: this generates a
bitmap override from the supplied game font, then fits text using the final
metrics. The font is retained by project save/Undo/preview/export. Older embedded
fonts can receive a reviewed font-only update even when no text changes are
needed. No executable changes or native build are required.

Speaker names and some UI labels still use fixed cursor spacing. ASCII spaces
become shorter globally; pair kerning and complex shaping are not implemented.
See [font asset usage and limitations](docs/FONT_ASSET.md).

## Optional MCP access

Install the optional dependencies:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-mcp.ps1
```

For an agent sharing the GUI, load the game/project, open **MCP…**, choose a
separate writable workspace, then **Start MCP** and **Copy connection configuration**.
Use the generated localhost URL and per-start bearer token in your MCP host.
GUI and agent edits share the same project/Undo; stale revisions, conflicting
text and busy dialogs reject writes. Keep the editor running. Closing the panel
leaves the server running; **Stop MCP** or editor exit stops it.

For an independent stdio session:

```powershell
.\.venv\Scripts\python.exe run_mcp.py --usrdir "C:\path\to\USRDIR" --workspace .local\translation-mcp --print-config
```

Add the generated entry to your MCP host. The host starts the server. The
[configuration template](mcp-config.example.json) uses placeholders, not working
machine-specific paths. Standalone and GUI sessions exchange saved project files;
they do not share live in-memory edits.

An agent should begin with `get_translation_guide` and `get_status`, or the
`translate_script` prompt. Tools expose readable dialogue flow, opcode help,
original/current text, reference-aware edits, validation, preview and explicit
save/export. No model service or API key is built in.
Visual tools also expose textures and all supported UI compositions as native MCP
images plus structured geometry, layer/pass order, asset provenance and text.
Start with `list_textures` or `list_ui_scenes`, then `describe_ui_scene` and
`get_ui_scene`. `get_ui_scene_layers(kind="text")` reads UI strings/styles directly.
These calls inspect snapshots without changing the human's GUI or project.
Use `list_ui_text` / `get_ui_text` for editable fields and
`get_ui_text_preview(field_id, plan_id)` to render a field with an optional
unapplied Auto-fit plan. `get_status` and `validate_project` expose platform
metadata export blockers without preventing older projects from loading.
`write_texture_png`, `import_texture_png` and `remove_texture_replacement` support
texture authoring through the same workspace and revision rules. Use
`check_texture_export` for a read-only GXT preflight, then `export_game_copy` only
when a patched game-data copy is requested. No launcher or executable changes.
See the [translator/tool guide](docs/TRANSLATOR_GUIDE.md).

## Development

Application code is in `editor/`; `run.py` and `run_mcp.py` are the entry points.
Small synthetic checks and run instructions are in [tests](tests/README.md).
Local game-data verification, research, personal projects, generated font/data
outputs, environments and development history are excluded from Git.

Engine behavior and portions of the Python implementation were adapted from
Impacto. See [third-party notices](THIRD_PARTY_NOTICES.md).
