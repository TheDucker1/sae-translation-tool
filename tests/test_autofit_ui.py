"""Unified script/UI cleanup is one revision-guarded transaction."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import hashlib
import struct
from unittest.mock import patch

from editor.engine import ROOT
from editor.textcleanup import analyze_cleanup,apply_cleanup,public_plan
from editor.uitext import get_catalog
from editor.fontpatch import pack
from test_image_assets import gxt
from test_ui_text import fixture
from test_width_controls import font_fixture
from test_autofit_layouts import settings_fixture


class AutoFitUiChecks(unittest.TestCase):
    def test_tip_layout_and_wrapping_share_existing_transaction(self):
        from test_composition_modes import profile_environment_fixture
        from test_ui_text import global_fixture
        from editor.compositionmodes import profile_environment
        from editor.composition import EnvironmentLibrary
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            p,_,_,_=self.setup_project(Path(tmp)/'original');root=Path(p.root)
            (root/'env/env_otaku_mode.dat').write_bytes(profile_environment_fixture(8))
            (root/'env/env_global.dat').write_bytes(global_fixture())
            (root/'env/env_game_utility.dat').write_bytes(bytes(3)+struct.pack('<i',27))
            p._ui_text_catalog=None;c=get_catalog(p);identity='first.dat:3/0#s1'
            font=font_fixture();font.charset.update(map(chr,range(32,127)));font.utility=27;p._ui_style_font=((p.root,p.font_asset['manifest']['font_sha256']),font)
            p.set_ui_texts([(identity,c.fields[identity]['original'],'A hostess plots her rise.')])
            before=p.ui_text_assets.copy();history=len(p.undo_stack)
            with patch('editor.fontpatch.effective_font',return_value=font):
                plan=analyze_cleanup(p,font,settings_fixture(),command_ids=[])
            self.assertFalse(plan['issues']);self.assertEqual(len(plan['ui_changes']),3)  # Also repairs the existing help label.
            tip=next(item for item in plan['ui_changes'] if item['field_id']==identity)
            self.assertEqual(tip['after_text'],'A hostess plots＿her rise.')
            apply_cleanup(p,plan);self.assertEqual(len(p.undo_stack),history+1)
            lib=EnvironmentLibrary(root,ui_text_assets=p.ui_text_assets,ui_text_catalog=c)
            self.assertEqual(profile_environment(lib.read('env/env_otaku_mode.dat'))['columns'],16)
            p.undo();self.assertEqual(p.ui_text_assets,before);p.redo()
            self.assertEqual(p.ui_text_assets[identity]['text'],tip['after_text'])

    def setup_project(self,root):
        p,_,_=fixture(root);catalog=get_catalog(p);key='env/env_help_mgr.dat:#s0'
        p.set_ui_texts([(key,catalog.fields[key]['original'],'Ｍｏｖｅ now')])
        font=font_fixture();p.text_format=font.format
        chars=struct.pack('<I',4)+b'\xff\xfeA\0'
        original=pack([gxt(8,2),b'',chars]);generated=pack([gxt(8,2),gxt(8,2),b'',chars])
        (root/'Font.gsf').write_bytes(original);digest=hashlib.sha256(generated).hexdigest()
        p.font_asset=dict(data_hex=generated.hex(),manifest=dict(format='saekano-proportional-font',version=1,
            source_sha256=hashlib.sha256(original).hexdigest(),font_sha256=digest,generator_revision=3))
        p._ui_style_font=((p.root,digest),font)
        command=next(c for c in p.scripts[0].commands if c.opcode==0x64)
        args=deepcopy(command.args);args['text']='A「Hello」';p.replace(0,command.uid,0x64,args)
        with patch('editor.fontpatch.effective_font',return_value=font):
            plan=analyze_cleanup(p,font,settings_fixture(),command_ids=[command.uid])
        return p,key,command.uid,plan

    def test_combined_apply_and_ui_only_selection_have_atomic_undo(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            p,key,uid,plan=self.setup_project(Path(tmp)/'original')
            self.assertEqual(len(plan['ui_changes']),1);self.assertEqual(len(plan['changes']),1)
            self.assertEqual(public_plan(plan,limit=1)['ui_changes'][0]['field_id'],key)
            before=p.compile(0);before_ui=p.ui_text_assets.copy();history=len(p.undo_stack)
            result=apply_cleanup(p,plan)
            self.assertEqual(result['ui_fields'],[key]);self.assertEqual(len(p.undo_stack),history+1)
            self.assertEqual(p.ui_text_assets[key]['text'],'Move now');self.assertNotEqual(p.compile(0),before)
            p.undo();self.assertEqual(p.compile(0),before);self.assertEqual(p.ui_text_assets,before_ui)
            with patch('editor.fontpatch.effective_font',return_value=font_fixture()):
                plan=analyze_cleanup(p,font_fixture(),settings_fixture(),command_ids=[uid])
            result=apply_cleanup(p,plan,[key]);self.assertFalse(result['changes'])
            self.assertEqual(p.compile(0),before);self.assertEqual(result['ui_fields'],[key])

    def test_bad_ui_rejects_the_entire_script_and_font_batch(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            p,key,uid,plan=self.setup_project(Path(tmp)/'original')
            before=(p.revision,p.compile(0),p.ui_text_assets.copy(),p.font_asset,len(p.undo_stack))
            plan['ui_changes'][0]['after_text']='Unexpected %ls'
            with self.assertRaisesRegex(ValueError,'placeholders'):apply_cleanup(p,plan)
            self.assertEqual((p.revision,p.compile(0),p.ui_text_assets,p.font_asset,len(p.undo_stack)),before)
            plan['revision']='stale'
            with self.assertRaisesRegex(ValueError,'Stale cleanup'):apply_cleanup(p,plan)


if __name__=='__main__':unittest.main()
