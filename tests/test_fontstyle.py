"""Native consumer font aliases and guarded UI translation repair."""
from pathlib import Path
import tempfile
import unittest

from editor.engine import ROOT
from editor.fontstyle import FIXED,LAYOUT,match_style,translated_ui_edits
from editor.textlayout import TextLayoutService,full_width_text
from editor.fontpatch import dialogue_width
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
