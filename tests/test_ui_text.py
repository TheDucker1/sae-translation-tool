"""Non-script UI text boundaries/transactions/merged export using synthetic data."""
import gzip,json,os,struct,tempfile
from pathlib import Path
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QWidget
from editor.archive import Archive
from editor.document import Project
from editor.engine import ROOT
from editor.scriptcodec import string,Reader
from editor.uitextcodec import Span,counted_spans,table_spans,rewrite,encode_span,save_text
from editor.uitext import build_catalog,get_catalog,effective_node,prepare
from editor.packing import Member,pack_members,repack,payload
from editor.gameexport import export_game,ExportError,prepare_archives
from editor.seekwriter import relocate
from editor.composition import EnvironmentLibrary
from editor.textureassets import encode_png
from editor.imageassets import build_catalog as image_catalog
from test_game_export import source_fixture,seekmap
from test_image_assets import gxt
from test_texture_export import rgba_image


def pack(data):return pack_members([Member(str(i).encode(),0,v) for i,v in enumerate(data)])
def word(n):return struct.pack('<I',n)

def global_fixture():
    return (bytes(3)+string('Global')*4+bytes(8)+string('UI')*9+bytes(120)+word(0)+bytes(32)
        +word(0)+bytes(16)+word(0)+word(2)+string('①')+string('②')+string(' ')+struct.pack('<fi',.7,8)+string('Yes')+string('No')+string('＿'))
def items(texts):return word(len(texts))+b''.join(word(i)+string(v) for i,v in enumerate(texts))
def rows(values):return word(len(values))+b''.join(items(v) for v in values)
def help_fixture():
    rect=struct.pack('<4i',0,516,960,28)
    return bytes(47)+rect+items(['Move cursor','Confirm'])+rect+rows([['Apply settings'],['Switch tabs']])+rect+rows([['Save'],['Load']])+rect+items(['Extras'])+(rect+rows([['Select']]))*2+rows([['Play']])+rect+rows([['Replay']])+rows([['Calendar']])+items(['Choose'])+items(['Start'])+rows([['Skip']])


def fixture(root):
    p,first,resource=source_fixture(root)
    (root/'env/env_help_mgr.dat').write_bytes(help_fixture())
    (root/'env/env_save_manager.dat').write_bytes(bytes(3)+b''.join(string('Saved: %ls' if i==0 else f'Save message {i}') for i in range(56)))
    items_text='// header\r\nON\t0\t1\t"Item"\t"A quoted ""description"""\r\n'.encode('utf-16-le')
    first=repack(Archive(first),{1:pack([gxt()]),3:pack([items_text]*4)})
    response='ON,CHARA,0\r\nON,DATA,0,0,0,0,0,original.obj,0,0,"A response",0\r\n'.encode('cp932')
    cg='\ufeffON,"CG title",0,0,0,0,0\r\n'.encode('utf-16-le')
    resource=repack(Archive(resource),{0:pack([gxt()]),2:pack([pack([pack([cg])])]),3:pack([pack([]),pack([response])])})
    first=repack(Archive(first),{5:gzip.compress(seekmap(resource),mtime=0)})
    (root/'first.dat').write_bytes(first);(root/'resource.dat').write_bytes(resource)
    return p,first,resource


class UiText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_overlong_platform_metadata_loads_unchanged_but_blocks_export(self):
        from types import SimpleNamespace
        from editor.translation import TranslationWorkspace
        from editor.uitextview import UiTextBrowser
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            folder=Path(tmp);p,_,_=fixture(folder/'original');root=Path(p.root)
            (root/'env/env_global.dat').write_bytes(global_fixture());c=get_catalog(p)
            key='env/env_global.dat:#s1';text='A'*30+'😀'  # 31 characters,32 UTF16 units.
            p.set_ui_texts([(key,c.fields[key]['original'],text)])
            workspace=folder/'workspace';workspace.mkdir()
            saved=workspace/'old.saekano.json';p.save(saved);original_bytes=saved.read_bytes()
            loaded=Project.load(saved,p)
            self.assertEqual(loaded.ui_text_assets[key]['text'],text)
            self.assertEqual(loaded.ui_metadata_issues()[0]['actual_units'],32)
            self.assertFalse(loaded.validate())  # Scenario validity is independent of platform publication.
            help_id='env/env_help_mgr.dat:#s0'
            loaded.set_ui_texts([(help_id,c.fields[help_id]['original'],'Move')])
            copy=workspace/'copy.saekano.json';loaded.save(copy)
            self.assertEqual(Project.load(copy,p).ui_text_assets[key]['text'],text)
            self.assertEqual(saved.read_bytes(),original_bytes)
            owner=QWidget();owner.project=loaded;browser=UiTextBrowser(owner)
            try:
                browser.set_project(loaded);browser.search.setText(key);browser.table.selectRow(0);browser.selected()
                self.assertIn('Export blocked',browser.note.text());self.assertIn(key,browser.note.text())
            finally:browser.close();owner.close()
            ws=TranslationWorkspace.__new__(TranslationWorkspace)
            ws.initialize(loaded,SimpleNamespace(original={},descriptions={}),workspace)
            result=ws.load_project('old.saekano.json',loaded.revision)
            self.assertEqual(result['ui_metadata_issues'][0]['field_id'],key)
            self.assertFalse(ws.validate_project()['export_ready'])
            target=folder/'export'
            with self.assertRaisesRegex(ExportError,r'env_global.dat:#s1.*32 UTF16.*31'):export_game(ws.project,target)
            self.assertFalse(target.exists())
            ws.project.set_ui_texts([(key,text,'A'*31)])
            self.assertFalse(ws.project.ui_metadata_issues());prepare(ws.project.ui_text_assets,root,c)
            # Recovery never weakens provenance checking.
            damaged=json.loads(original_bytes);damaged['ui_text_assets'][key]['span_sha256']='0'*64
            bad=folder/'damaged.saekano.json';bad.write_text(json.dumps(damaged),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'fingerprint'):Project.load(bad,p)

    def test_typed_tip_columns_preserve_original_rows_and_export_bytes(self):
        from test_composition_modes import profile_environment_fixture
        from editor.compositionmodes import profile_environment,description_lines,profile_separator
        from editor.uitextcodec import counted_spans
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            folder=Path(tmp);p,_,_=fixture(folder/'original');root=Path(p.root)
            raw=profile_environment_fixture(8);(root/'env/env_otaku_mode.dat').write_bytes(raw)
            (root/'env/env_global.dat').write_bytes(global_fixture())
            (root/'env/env_game_utility.dat').write_bytes(bytes(3)+struct.pack('<i',27))
            # The normal parser registers the scalar after strings, preserving IDs.
            c=get_catalog(p);self.assertFalse(c.issues)
            setting=next(f for f in c.fields.values() if f['role']=='Profile tips column limit')
            before=(p.revision,p.ui_text_assets)
            with self.assertRaisesRegex(ValueError,'column limit'):
                p.set_ui_texts([(setting['field_id'],'8','17')])
            self.assertEqual((p.revision,p.ui_text_assets),before)
            label=next(f for f in c.fields.values() if f['source'].endswith('env_otaku_mode.dat') and f['original']=='Before')
            p.set_ui_texts([(setting['field_id'],'8','16'),(label['field_id'],'Before','A much longer label')])
            self.assertEqual(c.fields['first.dat:3/0#s1']['fit_policy'],'profile_tips')
            self.assertEqual(c.fields['env/env_help_mgr.dat:#s0']['fit_policy'],'consumer_checked')
            library=EnvironmentLibrary(root,ui_text_assets=p.ui_text_assets,ui_text_catalog=c)
            env=library.read('env/env_otaku_mode.dat');self.assertEqual(profile_environment(env)['columns'],16)
            self.assertIn('A much longer label',[s.text for s in counted_spans(env,profile_environment)])
            changes,_,_=prepare(p.ui_text_assets,p.root,c)
            self.assertEqual(changes['env/env_otaku_mode.dat'][0][1],env)
            separator=profile_separator(library)
            from editor.uitextcodec import table_spans
            rewritten=changes['first.dat'][0][1]
            original=c.nodes['first.dat:3/0']['spans'][1].text
            current=table_spans(rewritten,'utf-16-le','\t','profile_items')[1].text
            self.assertEqual(description_lines(original,separator,8),description_lines(current,separator,16))
            saved=folder/'tips.saekano.json';p.save(saved);loaded=Project.load(saved,p)
            self.assertEqual(loaded.ui_text_assets,p.ui_text_assets)
            p.undo();self.assertFalse(p.ui_text_assets);p.redo()
            compiled=prepare_archives(p)
            self.assertEqual(compiled['files']['env/env_otaku_mode.dat'],env)

    def test_counted_and_quoted_native_roundtrip_and_protected_syntax(self):
        data=bytes(3)+b''.join(string('Saved: %ls' if i==0 else 'Other') for i in range(56))
        spans=counted_spans(data,save_text);result=rewrite(data,spans,{0:'Translated, %ls 😀'})
        updated=counted_spans(result,save_text)
        self.assertEqual(updated[0].text,'Translated, %ls 😀');self.assertEqual(updated[1].text,'Other')
        self.assertEqual(result[updated[1].start:],data[spans[1].start:])
        for wrong in ('Missing token','%ls %q'):
            with self.assertRaisesRegex(ValueError,'format'):encode_span(spans[0],wrong)
        with self.assertRaisesRegex(ValueError,'Protected'):encode_span(Span(0,4,'KEY',editable=False),'Oops')
        for encoding,separator,kind,text in (
            ('utf-16-le','\t','profile_items','ON\t0\t1\t"Name"\t"Description"\r\n'),
            ('cp932',',','profile_responses','ON,DATA,0,0,0,0,0,script,0,0,"Response",0\r\n')):
            raw=text.encode(encoding);sp=table_spans(raw,encoding,separator,kind)
            changed=rewrite(raw,sp,{0:'New "quoted", value\ncontinued'})
            self.assertEqual(table_spans(changed,encoding,separator,kind)[0].text,'New "quoted", value\ncontinued')
            if encoding=='cp932':
                with self.assertRaises(UnicodeError):rewrite(raw,sp,{0:'Emoji 😀'})

    def test_project_atomic_batch_source_guard_mixed_undo_and_version3(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            folder=Path(tmp);p,first,resource=fixture(folder/'original');c=get_catalog(p)
            self.assertFalse(c.issues);key='env/env_help_mgr.dat:#s0';original=c.fields[key]['original'];revision=p.revision
            with self.assertRaises(ValueError):p.set_ui_texts([(key,original,'Move'),('env/env_save_manager.dat:#s0','Saved: %ls','No token')])
            self.assertEqual(p.revision,revision);self.assertFalse(p.ui_text_assets)
            p.set_ui_texts([(key,original,'Move the cursor')]);command=next(c for c in p.scripts[0].commands if c.opcode==0x64)
            args=dict(command.args,text='A translated line');p.replace(0,command.uid,command.opcode,args)
            p.undo();self.assertEqual(p.ui_text_assets[key]['text'],'Move the cursor')
            p.undo();self.assertFalse(p.ui_text_assets);p.redo();p.redo()
            path=folder/'saved.saekano.json';p.save(path);self.assertEqual(json.loads(path.read_text())['version'],3)
            loaded=Project.load(path,p);self.assertEqual(loaded.ui_text_assets,p.ui_text_assets)
            library=EnvironmentLibrary(Path(p.root),ui_text_assets=p.ui_text_assets,ui_text_catalog=c)
            text=counted_spans(library.read('env/env_help_mgr.dat'),__import__('editor.uitextcodec',fromlist=['help_text']).help_text)[0].text
            self.assertEqual(text,'Move the cursor')
            (Path(p.root)/'env/env_help_mgr.dat').write_bytes(help_fixture()+b'changed')
            with self.assertRaisesRegex(ValueError,'fingerprint|source'):Project.load(path,p)

    def test_combined_export_reloads_ui_tables_textures_scripts_and_seek(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            folder=Path(tmp);p,first,resource=fixture(folder/'original');c=get_catalog(p)
            keys=['env/env_help_mgr.dat:#s0','first.dat:3/0#s0','first.dat:3/0#s1','resource.dat:3/1/0#s0','resource.dat:2/0/0/0#s0']
            texts=['Move cursor translated','New item','A longer "description"','Translated response','Translated CG title']
            p.set_ui_texts([(k,c.fields[k]['original'],v) for k,v in zip(keys,texts)])
            ic=image_catalog(p.root);p.set_texture('resource.dat:0/0',encode_png(rgba_image(3,2)),ic)
            command=next(c for c in p.scripts[0].commands if c.opcode==0x64);p.replace(0,command.uid,command.opcode,dict(command.args,text='Script translated'))
            output=folder/'patched';report=export_game(p,output);self.assertEqual(report['changed_ui_text'],5);self.assertEqual(report['changed_textures'],1)
            indexed=build_catalog(output);self.assertFalse(indexed.issues)
            for k,value in zip(keys,texts):self.assertEqual(indexed.fields[k]['original'],value)
            new_resource=(output/'resource.dat').read_bytes();seek=Archive((output/'first.dat').read_bytes()).read(5,gzip=True)
            changes,_,_=prepare(p.ui_text_assets,p.root,c)
            from editor.textureexport import changed_paths
            paths=changed_paths(changes['resource.dat'])|{(),(0,),(0,0),(4,),(4,0),(4,0,0),(4,0,0,0)}
            self.assertEqual(relocate(seek,new_resource,new_resource,paths)[0],seek)
            self.assertEqual((Path(p.root)/'first.dat').read_bytes(),first);self.assertEqual((Path(p.root)/'resource.dat').read_bytes(),resource)
            with self.assertRaisesRegex(ExportError,'empty'):export_game(p,output)

    def test_gui_field_edit_and_conflict_preserves_draft(self):
        from editor.uitextview import UiTextBrowser
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as tmp:
            p,_,_=fixture(Path(tmp)/'original');owner=QWidget();owner.project=p
            def guard(project,revision):
                if project is not owner.project or revision!=owner.project.revision:raise ValueError('Stale UI revision')
            owner.guard_edit_snapshot=guard;browser=UiTextBrowser(owner);browser.set_project(p)
            try:
                browser.search.setText('Move cursor');self.app.processEvents();browser.table.selectRow(0);browser.selected()
                key=browser.identity;browser.edit.setPlainText('Move now');browser.commit();self.assertEqual(p.ui_text_assets[key]['text'],'Move now')
                browser.edit.setPlainText('Human draft');p.set_ui_texts([(key,'Move now','Agent edit')]);browser.set_project(p)
                self.assertEqual(browser.edit.toPlainText(),'Human draft');browser.commit();self.assertIn('Stale',browser.note.text())
                self.assertEqual(p.ui_text_assets[key]['text'],'Agent edit')
            finally:browser.close();owner.close()


if __name__=='__main__':unittest.main()
