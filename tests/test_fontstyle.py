"""Native consumer font aliases and guarded UI translation repair."""
from pathlib import Path
import tempfile
import unittest

from editor.engine import ROOT
from editor.fontstyle import FIXED,LAYOUT,match_style,translated_ui_edits
from editor.textlayout import TextLayoutService,full_width_text
from editor.fontpatch import WORD_SPACE_WIDTHS,dialogue_width,vietnamese_glyphs,word_space_record
from types import SimpleNamespace
from editor.uitext import get_catalog,prepare
from editor.uitextcodec import counted_spans,help_text
from test_ui_text import fixture
from test_width_controls import font_fixture
from test_autofit_layouts import settings_fixture


class FontStyleChecks(unittest.TestCase):
    def test_dialogue_advance_accounts_for_native_double_truncation(self):
        font=SimpleNamespace(utility=27,scale=.9200000166893005,bitmap_height=24)
        self.assertEqual(dialogue_width(11,font,1),18)
        self.assertEqual(dialogue_width(3,font,0),4)

    def test_word_space_uses_quantized_native_advance(self):
        from editor.text import TextPresentation
        font = SimpleNamespace(utility=27, scale=.9200000166893005, cached={})
        self.assertEqual(word_space_record(font, None), (18, 5))
        self.assertEqual(word_space_record(font, 5), (18, 5))
        for pixels in WORD_SPACE_WIDTHS:
            width, _ = word_space_record(font, pixels)
            font.cached[' '] = (0, 0, 0, width, 24)
            self.assertEqual(int(TextPresentation.measure(font, ' ', font.utility) * font.scale), pixels)

    def test_reviewed_pairs_keep_canonical_text_and_protected_context(self):
        from editor.pairspacing import readable, shape_profile, shape_script
        formatter = SimpleNamespace(tokens=['《', '》', '《》'], following=['', '「'])
        pairing = dict(pairs={'Ｔô': '龠'}, accents={'ô': '齟'}, restore={'龠': 'Ｔ', '齟': 'ô'})
        dialogue = 'Ｔôi「Ｔôｉ ＿Ｔ ｏ」'
        wire = shape_script(dialogue, 0x64, {}, 'text', formatter, pairing)
        self.assertEqual(wire, 'Ｔôi「龠ôｉ ＿Ｔ ｏ」')
        self.assertEqual(readable(wire, pairing), dialogue)
        timed = 'Eriri「《SP QUE,1,2700》Ｔôｉ」'
        self.assertEqual(shape_script(timed, 0x64, {}, 'text', formatter, pairing), timed)
        self.assertEqual(shape_script(dialogue, 0x64, {'selector': 1}, 'text', formatter, pairing), dialogue)
        self.assertEqual(shape_script('Ｔô', 0x3F2, {}, 'choices[0].label', formatter, pairing), 'Ｔô')
        self.assertEqual(shape_profile('Ｔôｉ', pairing).encode('cp932').decode('cp932'), '龠齟ｉ')

    def test_approach_bitmap_tiles_compensate_for_native_centering(self):
        from editor.choiceart import ChoiceAtlas, measured_width
        from editor.fontpatch import font_atlas
        from editor.text import TextPresentation
        import struct

        font = font_fixture()
        font.bitmap_height = 24
        font.pair_spacing = {'pairs': {}}
        source_widths = {'ｉ': 4, 'Ｗ': 15}
        font.cached.update({char: (0, 0, 0, width, 24) for char, width in source_widths.items()})
        font.measure = lambda text, size: TextPresentation.measure(font, text, size)
        font.glyph = lambda code: dict(width=source_widths[chr(code)], rgba='ffffffff' * (24 * source_widths[chr(code)]))
        atlas = ChoiceAtlas(font)
        wire, width = atlas.encode('iWiW', 24)
        self.assertEqual(width, 38)
        self.assertLess(len(wire), len('iWiW'))
        self.assertEqual(atlas.encode('iWiW', 24), (wire, width))
        self.assertEqual(atlas.encode('日本語', 24), ('日本語', None))
        parts = [b'', b'']
        atlas.append_to(parts)
        records = {chr(code): (x, y, w) for code, _, x, y, w, _ in struct.iter_unpack('<4H2B', parts[-2])}
        self.assertEqual(sum(measured_width(records[c][2]) for c in wire), width)
        stride, _, pixels = font_atlas(parts[0])
        ink = [i * 24 + col for i, c in enumerate(wire) for x, y, w in [records[c]]
               for col in range(w) if pixels[((y * stride + x + col) * 4) + 3]]
        self.assertEqual((min(ink), max(ink)), (0, width - 1))

    def test_approach_c_tucks_under_ink_overhang_only_with_clearance(self):
        from editor.choiceart import c_pair_reduction

        left = b'\xff\xff\0\0' * 24
        right = b'\0\xff\xff' * 24
        self.assertEqual(c_pair_reduction(left, 4, right, 3, 4), 2)
        self.assertEqual(c_pair_reduction(left, 4, right, 3, 2), 0)

    def test_vietnamese_bitmap_geometry_preserves_tall_and_deep_marks(self):
        from PySide6.QtWidgets import QApplication
        app=QApplication.instance() or QApplication([])
        font=SimpleNamespace(utility=27,scale=.9200000166893005,bitmap_height=24,cached={})
        glyphs={g['source']:g for g in vietnamese_glyphs(font,19)}
        self.assertEqual(len(glyphs),135)
        for char in 'ếệăưĐơẤẲỵ₫':
            glyph=glyphs[char]
            bounds=glyph['path'].boundingRect()
            self.assertFalse(bounds.isEmpty())
            self.assertGreater(bounds.top(),-19)
            self.assertLess(bounds.bottom(),5)
            self.assertLessEqual(bounds.right()-glyph['left'],glyph['width'])
        self.assertNotEqual(glyphs['ì']['width'],glyphs['Đ']['width'])

    def test_measured_quotes_keep_cues_and_format_operands(self):
        font=font_fixture();font.cached.update({c:(0,0,0,4,24) for c in '‘’“”'})
        text='A「If you don\'t《SP QUE,1,2700》 press "Start".」'
        result=full_width_text(text,font,preserve_speaker=True)['text']
        self.assertIn('ｄｏｎ’ｔ《SP QUE,1,2700》',result)
        self.assertIn('“Ｓｔａｒｔ”',result)
        self.assertEqual(font.format.ordinary(text)['markers'],font.format.ordinary(result)['markers'])
        proposal=match_style('Load "%ls"?',font,LAYOUT)
        self.assertEqual(proposal['text'],'Ｌｏａｄ “%ls”？')

    def test_fixed_and_measured_styles_preserve_native_syntax(self):
        font=font_fixture()
        value='Ｓｋｉｐ ｔｈｅ tutorial %02d ≪UNCHANGED≫＿① 日本語\0hidden_ASCII'
        fixed=match_style(value,font,FIXED)
        self.assertEqual(fixed['text'],'Skip the tutorial %02d ≪UNCHANGED≫＿① 日本語\0hidden_ASCII')
        measured=match_style(fixed['text'],font,LAYOUT)
        self.assertIn('Ｓｋｉｐ ｔｈｅ ｔｕｔｏｒｉａｌ %02d ≪UNCHANGED≫＿① 日本語',measured['text'])
        self.assertTrue(measured['text'].endswith('\0hidden_ASCII'))
        self.assertEqual(match_style(measured['text'],font,LAYOUT)['text'],measured['text'])
        self.assertEqual(match_style('“Quoted” ＿①',font,FIXED)['text'],'“Quoted” ＿①')

    def test_ui_apply_and_existing_repair_use_renderer_with_one_undo(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            p,_,_=fixture(Path(tmp)/'original');catalog=get_catalog(p)
            help_id='env/env_help_mgr.dat:#s0';response='resource.dat:3/1/0#s0'
            p.set_ui_texts([(help_id,catalog.fields[help_id]['original'],'Ｍｏｖｅ cursor'),
                            (response,catalog.fields[response]['original'],'A response')])
            before=p.ui_text_assets.copy();p.font_asset=dict(manifest=dict(font_sha256='synthetic'),data_hex='')
            p._ui_style_font=((p.root,'synthetic'),font_fixture())
            self.assertEqual(catalog.fields[help_id]['renderer'],FIXED)
            self.assertEqual(catalog.fields[response]['renderer'],LAYOUT)
            edits=translated_ui_edits(p);self.assertEqual(len(edits),1)
            count=len(p.undo_stack);p.set_ui_texts(edits);self.assertEqual(len(p.undo_stack),count+1)
            self.assertNotIn(help_id,p.ui_text_assets)  # Normalized text matches the original.
            p.undo();self.assertEqual(p.ui_text_assets,before)
            p.set_ui_texts([(response,'A response','New response')])
            self.assertEqual(p.ui_text_assets[response]['text'],'Ｎｅｗ ｒｅｓｐｏｎｓｅ')
            proposals,_,_=prepare(p.ui_text_assets,p.root,catalog)
            # Serializers preserve the effective rendered strings, not just GUI drafts.
            help_bytes=proposals['env/env_help_mgr.dat'][0][1]
            self.assertEqual(counted_spans(help_bytes,help_text)[0].text,'Ｍｏｖｅ cursor')
            self.assertFalse(translated_ui_edits(p)[0][2].startswith('Ｍ'))

    def test_script_choice_repairs_aliases_while_dialogue_retains_them(self):
        font=font_fixture();font.asset_sha256='synthetic'
        service=TextLayoutService(font,settings_fixture())
        result=service.wrap(0x65,'Ｓｋｉｐ ｔｈｅ tutorial',field='choices[0].label',full_width_latin=True)
        self.assertEqual(result['text'],'Skip the tutorial');self.assertTrue(result['font_style']['changed'])
        self.assertEqual(result['line_widths'][0],service.label_width(result['text'],result['scale']))
        dialogue=service.wrap(0x64,'A「Skip the tutorial」',full_width_latin=True)
        self.assertIn('Ｓｋｉｐ',dialogue['text'])


if __name__=='__main__':unittest.main()
