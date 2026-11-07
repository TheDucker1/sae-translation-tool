# Proportional dialogue font assets

The optional font feature generates a bitmap override from your supplied game
font. It works through the existing asset-loading path on Vita/Vita3K and the PC
player; it does not modify an executable. Generated fonts are local game-derived
outputs and are not included in this repository.

## Use

1. Load the original USRDIR and open your translation project.
2. **Auto-fit text…** -> choose the scope -> check **Proportional dialogue font
   asset** -> **Analyze again**.
3. Review text/page proposals and the font update notice. **Apply** commits the
   selected text and font together. Ordinary text-form Apply and MCP translations
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
again to repair existing choice/topic/caption strings. The dialogue aliases stay
in their measured layouts. In UI text…, use Match font in draft before Apply or
Repair font in translated UI for existing environment/help/catalogue edits.
New UI translations match verified consumers on Apply automatically. Save and
export a new copy after either repair.

These repairs select compatible text aliases. Fixed-cursor UI remains monospaced.
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

Generator revision 2 tightens apostrophe masks and removes excess quote padding.
It preserves literal spaces in the script; it does not guess which spaces the
translator intended or introduce pair-specific kerning.

## Limits

- Dialogue, multiline battle text and result text use the variable glyph widths.
  Speaker names and some simple UI labels retain fixed cursor spacing. Those
  paths cannot be made proportional by this font asset alone.
- Original Japanese glyph records/atlas are retained. ASCII word spaces become
  shorter globally, which can affect spacing/centering elsewhere.
- This uses per-glyph optical spacing, not kerning pairs or complex shaping.
  Non-ASCII Latin extensions are not generally supported by the script encoding.
- Existing authored breaks stay hard unless Reflow existing line breaks is enabled.
  Timed text can use verified space padding with intact directive times. Queued
  and append messages must fit one message; inherited buffers need display context.
- Inspect appearance, clipping and positioning in the target game. The editor's
  placeholder preview does not certify native pixel or animation parity.

MCP: use `analyze_text_cleanup(proportional_latin=true)`, review `font_changed`
and `font_asset`, then call `apply_text_cleanup` with the current revision.
`get_status` reports selected font hashes/revision. The public plan omits the
embedded font bytes. Source data, personal saves and executable files stay unchanged.
