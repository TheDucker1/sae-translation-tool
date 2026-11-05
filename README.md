# Saekano Script Studio — v0.1 alpha

A Python/Qt editor for basic Saekano scenario-text translation. Read scripts,
inspect command help and flow, edit text, check references, preview logical
progression, and export a separate patched game-data copy.

This is an alpha translation tool. Preview uses placeholder art and silent logical
services; it is not a full game or a claim of visual/timing parity. No original
game data, font files, translated projects or native captures are included.
Supply your own USRDIR. The original data stays read-only.

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

## Basic text workflow

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
   including script metadata and selected font assets. Original data and occupied
   destinations are never overwritten. Select the new data folder manually in
   your game/emulator setup. No launcher setting or executable is modified.

Editable families: dialogue, ordinary choices, chapter captions, battle choices,
approach topics/options, approach results and battle-introduction captions. Other
commands retain the logical state/control flow needed for translation preview;
native menu interaction remains outside the scenario simulator. Read-only UI
composition previews and non-script image inspection are available separately below.

Structural changes can invalidate existing game saves/history. Export reports
when fresh progress is required; it does not migrate personal saves.

## Image assets

**Load game → Images…** opens a read-only inventory across the full source data
tree. Search/filter textures, view transparency and known atlas regions, inspect
archive/member locations and literal script uses, and extract original image
members and/or PNGs into a separate empty folder with a provenance manifest.
Images are decoded on selection; no image editing or reinjection is included.
**UI compositions…** assembles title/menu, gameplay message-window, system-menu,
choices, calendar/chapter and shared-dialog layouts with selectable preview states
and inspectable layers.
Additional UI families are tracked explicitly as pending.
See [the image-browser guide](docs/IMAGE_ASSETS.md) for usage and coverage limits.

## Wrapping and readability

Multiline text fields accept Enter as a native break. **Wrap words** uses the
loaded font/layout; single-line labels have **Check fit**. Preserve native control
tags and speaker/quotation delimiters. Timed dialogue with explicit breaks is
unsupported and rejected by editing, preview and export.

For older translations, **Auto-fit text…** analyzes the current file by default.
Choose **Whole project** for all scripts, review the proposals, then **Apply**.
Analyze alone does not change text; save/export does not implicitly run Auto-fit.
Safe ordinary dialogue can be paginated with repeated speakers and repaired
references. Timed, queued and retained-buffer cases report limitations instead
of silently rewriting their synchronization.

Optional **Full-width Latin** widens supported glyphs. For proportional dialogue,
choose **Proportional dialogue font asset**: this generates an asset-only bitmap
font override, then fits text using those widths. The font is retained by project
save/Undo/preview/export. Older embedded fonts can receive a reviewed font-only
update even when no text changes are needed.

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
See the [translator/tool guide](docs/TRANSLATOR_GUIDE.md).

## Development

Application code is in `editor/`; `run.py` and `run_mcp.py` are the entry points.
Small synthetic checks and run instructions are in [tests](tests/README.md).
Local game-data verification, research, personal projects, generated font/data
outputs, environments and development history are excluded from Git.

Engine behavior and portions of the Python implementation were adapted from
Impacto. See [third-party notices](THIRD_PARTY_NOTICES.md).
