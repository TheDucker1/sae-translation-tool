"""Small transaction/context/path contracts for LLM translation tools."""
import importlib.util
import unittest
if importlib.util.find_spec('mcp') is None:raise unittest.SkipTest('Optional MCP dependencies required')
from copy import deepcopy
import hashlib,json,tempfile,threading
from pathlib import Path
from editor.translation import TranslationWorkspace,GUIDE
from editor.mcp_models import TranslationEdit,CommandEdit
from editor.engine import ROOT
from test_document import fixture


def workspace_fixture(folder):
    w=object.__new__(TranslationWorkspace);w.lock=threading.RLock();w.root=folder/'original';w.root.mkdir()
    w.workspace=folder/'workspace';w.workspace.mkdir();w.project=fixture();w.project.root=str(w.root)
    w._runtime=None;w._preview_revision=None;w._disk_hashes={};w._cache={}
    w._baseline={c.uid:c for s in w.project.baseline.values() for c in s.commands}
    w.source_fingerprint=hashlib.sha256(json.dumps(w.project.fingerprints(),sort_keys=True).encode()).hexdigest()
    w.profile=dict(target_language='',style_notes='',glossary={},progress_note='')
    w._context_path=w.path('translation-context.json');w.project_file='translation.saekano.json'
    return w


class TranslationChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.local');self.w=workspace_fixture(Path(self.temp.name))
    def tearDown(self):self.temp.cleanup()

    def edit(self,uid,old,new):return TranslationEdit(script_id=0,command_id=uid,field='text',expected_text=old,translation=new)

    def test_atomic_translation_stale_controls_invalid_unicode_and_undo(self):
        w=self.w;p=w.project;rev=p.revision;before=deepcopy(p.display(0))
        c2,c4=p.scripts[0].commands[2],p.scripts[0].commands[4]
        result=w.apply_translations([self.edit(c2.uid,'True','Translated true'),self.edit(c4.uid,'False','Translated false')],rev)
        self.assertEqual(len(p.undo_stack),1);self.assertEqual(len(result['applied']),2)
        stable=p.compile(0)
        with self.assertRaisesRegex(ValueError,'Stale project'):w.apply_translations([self.edit(c2.uid,'Translated true','X')],rev)
        with self.assertRaisesRegex(ValueError,'Stale expected'):w.apply_translations([self.edit(c2.uid,'True','X')],p.revision)
        with self.assertRaisesRegex(ValueError,'control tokens'):w.apply_translations([self.edit(c2.uid,'Translated true','《SP QUE,1,10》X')],p.revision)
        with self.assertRaisesRegex(ValueError,'unicode'):w.apply_translations([self.edit(c2.uid,'Translated true','Good'),self.edit(c4.uid,'Translated false','Bad\ud800')],p.revision)
        self.assertEqual(p.compile(0),stable)
        self.assertEqual(p.display(0)[1]['args'],before[1]['args'])
        self.assertEqual(w.get_context(0,c2.uid)['command']['text_fields'][0]['original'],'True')
        w.undo(p.revision);self.assertEqual(p.display(0),before)
        w.redo(p.revision);self.assertEqual(p.compile(0),stable)
        self.assertEqual(w.get_status()['modified_text_fields'],2)

    def test_structural_batch_repairs_references_and_rejects_unsafe_delete(self):
        w=self.w;p=w.project;target=p.scripts[0].commands[6].uid;anchor=p.scripts[0].commands[2].uid
        args=w.command_template(0,0x64,target)['arguments']
        result=w.edit_commands([CommandEdit(action='insert_before',script_id=0,command_id=anchor,opcode=0x64,arguments=args)],p.revision)
        inserted=result['changes'][0]['command_id']
        self.assertEqual(p.display(0)[1]['args']['start'],3);self.assertEqual(w.command(0,inserted)[0],2)
        self.assertFalse(w.validate_project()['issues']);stable=p.compile(0)
        with self.assertRaisesRegex(ValueError,'Batch rejected'):w.edit_commands([CommandEdit(action='delete',script_id=0,command_id=target)],p.revision)
        self.assertEqual(p.compile(0),stable)
        w.edit_commands([CommandEdit(action='delete',script_id=0,command_id=target,replacement_id=p.scripts[0].commands[-1].uid)],p.revision)
        self.assertTrue(w.validate_project()['valid'])
        self.assertEqual(w.get_script_flow(0,anchor)['edges'][0]['source_id'] is not None,True)

    def test_paged_context_safe_save_profile_and_external_change_detection(self):
        w=self.w;p=w.project
        page=w.list_commands(0,limit=2);self.assertEqual([c['index'] for c in page['commands']],[2,4]);self.assertEqual(page['next_start'],5)
        self.assertEqual(w.search_text('Join')['matches'][0]['command_id'],'s0:c6')
        self.assertNotIn('.cpp',w.opcode_help(0x64)['help']);self.assertIn('apply_translations',GUIDE)
        w.configure_translation('English',style_notes='Keep character tone',glossary={'英梨々':'Eriri'})
        w.configure_translation('English',progress_note='Next: s0:c6')
        self.assertEqual(w.profile['style_notes'],'Keep character tone');self.assertEqual(w.profile['glossary'],{'英梨々':'Eriri'})
        self.assertEqual(json.loads(w._context_path.read_text(encoding='utf-8'))['profile']['progress_note'],'Next: s0:c6')
        with self.assertRaisesRegex(ValueError,'escapes'):w.save_project(p.revision,'../outside.saekano.json')
        w.save_project(p.revision);path=w.path(w.project_file);self.assertTrue(path.exists())
        w.load_project(w.project_file,p.revision);self.assertTrue(w.validate_project()['valid'])
        path.write_text('external content',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'changed outside'):w.save_project(w.project.revision)
        self.assertEqual(path.read_text(encoding='utf-8'),'external content')
        w.save_project(w.project.revision,'new-copy.saekano.json')
        self.assertEqual(w.save_project(w.project.revision)['filename'],'new-copy.saekano.json')
        with self.assertRaisesRegex(ValueError,'escapes'):w.export_game_copy('../original',w.project.revision)


if __name__=='__main__':unittest.main()
