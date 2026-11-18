# Dialogue and UI font assets

The optional font feature generates a bitmap override from your supplied game
font. It works through the existing asset-loading path on Vita/Vita3K and the PC
player; it does not modify an executable. Generated fonts are local game-derived
outputs and are not included in this repository.

## Use

1. Load the original USRDIR and open your translation project.
2. **Auto-fit text…** -> choose the scope -> check **Proportional dialogue + readable
   UI font asset** and keep **Include translated UI text** enabled -> **Analyze again**.
3. Review script/UI proposals and the font update notice. **Apply** commits the
   selected script/UI text and font together in one Undo. Text-form Apply and MCP translations
   then use the selected font's aliases and fitting metrics.
4. Save the project and export to a new/empty folder. The selected `Font.gsf` is
   included automatically. Select that exported data manually in your player or
   separate modded game-data installation. Do not replace an executable.

The font is embedded in the editable project with source/output hashes. Reopening
checks the source; Undo/Redo restores font selection and text together. An export
never changes an older export or the player's selected folder automatically.

The older **Full-width Latin** option alone uses wider fixed cells. The
proportional-font option additionally supplies variable-width bitmap glyphs and
uses them when fitting. Speaker text stays unchanged during that conversion.

The active game font has two cursor behaviours. Dialogue, battle text, results
and verified dialog/profile-response layouts use measured advances. Choices,
help, menu labels and profile descriptions use fixed half/full cells even when
the bitmap glyph has a different width. Full-width proportional aliases on those
fixed paths caused widely separated letters and incorrect centering.

With a proportional font selected, text-form Apply, MCP translation edits and
Auto-fit now restore ordinary Latin in fixed-cursor script labels. Run Auto-fit
again to repair existing choice/topic/caption and translated environment/help/
catalogue strings together. The dialogue aliases stay in their measured layouts.
New UI translations match verified consumers on Apply automatically. Save and
export a new copy after either repair.

Font generator revision3 supplies readable bitmap Latin letters for fixed-cursor
UI, using the same original font face as dialogue. ASCII retains the native cursor
width, while the bitmap supplies correctly sized letter ink. These letters avoid
the PVF precache-cell compression. Their advances and proportional dialogue glyphs
are preserved. Auto-fit proposes the font upgrade even when text stays identical.
Fixed-cursor UI remains monospaced; lettering baked into textures has its own artwork.
The selected font's shorter ASCII-space measurement can still cause a small
centering difference in fixed UI. Assets cannot supply proportional cursor steps
to that active DrawString path. Unverified consumers are labeled explicitly and
retain their text during repair. Input glyphs, placeholders, native separators,
hidden suffixes and original untouched fields are preserved.

## Existing font updates

With a saved font project, keep the proportional option checked and analyze again.
If a newer generator revision is available, the dialog reports a font update.
Apply can update only the font even when no script text changes. Save/export a
new copy afterward. Uncheck the option and reanalyze to keep the embedded older
font; use Undo to reverse an applied change.

Generator revision2 tightened apostrophe masks; revision3 added readable UI bitmaps.
Revision4 recalculates dialogue advances from actual draw size and native double
truncation, targeting about one pixel of clearance at the authored default size.
The previous padding added too much tracking on top of the engine's implicit
cached-glyph pixel. Measured text also selects supported narrow quote glyphs for
ASCII apostrophes/double quotes, including contractions. UI bitmaps are preserved.
Run Auto-fit with the font option checked to review the revision4 upgrade. Enable
Reflow existing line breaks to repack older wrapping if desired, then Apply/Save
and export a new copy. Explicit authored breaks remain hard by default.
It preserves literal spaces in the script; it does not guess which spaces the
translator intended or introduce pair-specific kerning.

Revision5 adds one bitmap cache entry for the storage-space error prompt. The
native program appends its capacity value as a single UTF16 codepoint rather
than decimal text. That existing runtime codepoint now draws **7456** using the
original font's digits. The original charset and glyph records remain intact;
no marker is inserted into translated strings. Auto-fit measures the same glyph
inside the combined prompt and proposes the font update through normal Apply,
Undo, save and separate export. Other dialogue/UI advances are unchanged.

## Vietnamese glyphs

Revision 6 bakes 135 additional glyphs from the bundled Saekano Rounded VN face,
including precomposed Vietnamese letters and the đồng sign (`₫`). It fits
stacked marks and descenders into the 24 px bitmap cell. Auto-fit measures the
new records in dialogue and other measured layouts. Fixed-cell UI still uses its
native cursor steps.

Revision 9 makes the horn on `ơ` and `ư` rise with less sideways overhang.
Upgrade through Auto-fit to use the revised outlines and retain your saved word
spacing selection.

Run **Auto-fit text…** with the font asset option enabled, apply the font upgrade,
and export through **Export game…**. Use NFC (precomposed) Vietnamese in game
text. The OpenType accent positioning in the vector face is available to desktop
font renderers. The native cache displays individual glyphs by codepoint.

Scenario strings use UTF-16. Revision 8 supports NFC Vietnamese in profile event
responses inside `resource.dat → 3 → 1 → <scene>`. The editor stores the actual
translation. Export substitutes standard CP932 kanji codes whose font records
point to the Vietnamese glyphs. Export checks for collisions with game text.

## Reviewed pair spacing

Revision 8 checks glyph clearance and renders the qualifying shapes for visual
review. The reviewed adjustments reuse narrower `T`, `V`, and `ư` records across
selected pairs. Auto-fit and preview use these metrics for plain dialogue,
visible battle choices, and profile responses. Export substitutes only the
approved pairs and includes the glyph aliases used by the exported text. The
project and MCP retain editable letters and spaces.

Apply the revision 8 font proposal through Auto-fit before editing Vietnamese
profile responses. Speaker names, fixed-cursor UI, tagged and timed script text
keep their existing spacing path. Use the normal file-separate export workflow.

The original companion outline source is bundled alongside the TTF in
[`editor/assets/saekano-rounded-vn`](../editor/assets/saekano-rounded-vn/).
Rebuild the vector face with `python build_font.py` from that folder using
Python 3.13, `fonttools==4.68.0` and `skia-pathops==0.9.2`. The editor only
needs its existing Qt dependency to bake the font.

## Word spacing

Revision 7 adds **Word space** to Auto-fit when the font asset option is enabled.
Choose 3–9 game pixels at the default dialogue scale. **Keep current** retains
the saved font's choice. Older projects open normally and get the original
generated advance when upgraded. Other text scales may round differently.

Analyze again after changing the width. Measure and preview the proposed font
before applying it. Turn on **Reflow existing line breaks** to revisit earlier
wrapping. Apply, Undo, project saves and game export all carry the chosen font.
The native layout advances by whole pixels, so a single space cannot advance
by 5.5 px at a given scale.

## Proportional fixed-cursor text

With revision 8 or later selected, translated Latin and Vietnamese ordinary
choices, Approach topics, and Approach subchoices can use proportional bitmap
strips on the fixed-cursor cards.
Eligible plain labels use the configured font's letter and space widths. The
editor packs the ink into 24 px strips and adds transparent glyphs to give the
native centering function the measured width it needs. Preview and game export
use the same strips. Project text stays editable. Export adds the bitmap glyphs
and their lookup codes while retaining the original choice conditions and targets.
Chapter and battle introduction captions use the same strips at their authored
sizes. Battle Auto-fit measures each panel using the same width calculation as
the game and keeps its caption inside the panel.
Eligible plain UTF-16 UI strings also use packed labels or rows. These include
right-aligned help, title labels, dialog buttons, and profile names and tips.
The editor retains native row boundaries and measures serialized cells for tips.
Packed labels also adjust the gaps within words using the 24 px ink
masks. They tighten visibly open pairs and give touching strokes some room.
The review used attested Vietnamese syllables in lowercase and initial-capital
contexts, including `ươi`, `ười`, and the different tone marks. Word spacing
uses the selected font's space glyph.

Use `format_text` to check the width against the usable card interior. Preview
the labels in **Scenario choices** or **Profiles / approach → Approach topics /
choices**.

With a project font patch selected, translated dialogue, battle choices and
Approach results select proportional Latin glyphs alongside Vietnamese glyphs.
The same choice of glyphs is applied by Auto-fit, the scenario renderer, archive
export and sampled UI previews including backlog. Measured UI assets such as
dialogs, profile responses, and the profile result format follow their recorded
consumer layout even when reopened from older projects. Native breaks and
embedded directives or format operands are retained.

Generator revision 10 adds narrower variants of the original keyword brackets.
They apply around native keyword tags in authored, untimed dialogue. Preview
shows keyword color, underlining and ruby readings. Auto-fit preserves the
configured word spacing when it proposes the upgrade.

## Limits

- Dialogue, multiline battle text and result text use the variable glyph widths.
  Speaker names and other simple UI labels use the engine's fixed cursor spacing.
- Original Japanese glyph records/atlas are retained. The ASCII-space glyph is
  shared across measured text. Changing its width can also affect centering in
  fixed-cursor UI.
- The cached asset format supplies per-glyph advances. Pair spacing uses a
  reviewed subset of narrower glyph records. Other measured pairs use their
  base widths. Coverage beyond Latin and Vietnamese depends on the source font
  and on the storage encoding of each field.
- Existing authored breaks stay hard unless Reflow existing line breaks is enabled.
  Timed text can use verified space padding with intact directive times. Queued
  and append messages must fit one message; inherited buffers need display context.
- Inspect appearance, clipping and positioning in the target game. The editor's
  placeholder preview does not certify native pixel or animation parity.

MCP: use `analyze_text_cleanup(proportional_latin=true)`, review `font_changed`
and `font_asset`, then call `apply_text_cleanup` with the current revision.
Use `word_space_px` to request a specific width. The plan and `get_status`
report the proposed and applied values as `font_asset.word_space`. The public
plan reports the pair audit and shared glyph counts in `font_asset.pair_spacing`.
