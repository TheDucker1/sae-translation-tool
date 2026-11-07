"""Small consumer contracts: final font metrics, native constraints and operands."""
import unittest
from types import SimpleNamespace
from editor.uicontracts import Contracts,FieldText
from editor.uifitting import ConsumerLayout,fixed_check,substitute,field_fit
from editor.fontstyle import match_style,FIXED,LAYOUT
from editor.scriptcodec import Reader,string,STRING_OBSERVER
from test_width_controls import font_fixture


class UiFittingChecks(unittest.TestCase):
    def font(self):
        font=font_fixture();font.charset.update(map(chr,range(32,127)));return font

    def test_normalize_before_fixed_measurement_and_no_fake_newlines(self):
        font=self.font();c=dict(scale=1,point=[0,0],left=0,right=180)
        with self.assertRaisesRegex(ValueError,'Shorten'):fixed_check('Ｈｅｌｌｏ ｗｏｒｌｄ',c,font)
        text=match_style('Ｈｅｌｌｏ ｗｏｒｌｄ',font,FIXED)['text']
        c['right']=200;self.assertEqual(fixed_check(text,c,font)[0]['width'],198)
        with self.assertRaisesRegex(ValueError,'single-line'):fixed_check('Hello＿world',c,font)

    def test_measured_wrapping_uses_native_height_and_preserves_text(self):
        font=self.font();contract=dict(width=320,scale=1,height=108)
        value=match_style('Hello there, reader.',font,LAYOUT)['text']
        result=ConsumerLayout(font,contract).wrap(0x3f8,value)
        self.assertGreater(result['line_count'],1)
        self.assertEqual(result['text'].replace('＿','').replace(' ',''),value.replace(' ',''))
        with self.assertRaisesRegex(ValueError,'height'):ConsumerLayout(font,dict(contract,height=36)).wrap(0x3f8,value)

    def test_format_measurement_uses_values_and_preserves_placeholder(self):
        font=self.font();c=dict(scale=1,point=[0,0],left=0,right=100,format_samples=[[2099]])
        self.assertEqual(fixed_check('%04d',c,font)[0]['text'],'2099')
        expanded,pairs=substitute('Load "%ls"?',['a slot'])
        self.assertEqual(expanded,'Load "a slot"?');self.assertEqual(pairs[6],(6,9))
        template='Ｈｅｌｌｏ %ls ａｎｄ ｗｅｌｃｏｍｅ ｂａｃｋ.'
        result=ConsumerLayout(font,dict(width=320,scale=1,height=180),['Ａｌｉｃｅ']).wrap(0x3f8,template)
        self.assertEqual(result['text'].count('%ls'),1);self.assertIn('＿',result['text'])

    def test_help_is_checked_as_a_whole_row(self):
        font=self.font();contract=dict(kind='help_group',rectangle=[0,0,100,30],members=[dict(key=-1,field_id='a'),dict(key=-1,field_id='b')],keys=[],separator='',scale=1,gap=5,group='row')
        c=SimpleNamespace(fields={x:dict(original='Short',contracts=[contract]) for x in ('a','b')})
        with self.assertRaisesRegex(ValueError,'Combined button help'):field_fit('a','Short',c,{},font,reflow=False,hyphenate=False)

    def test_panel_uses_fill_coverage_and_excludes_cursor(self):
        from editor.uipanel import inscribed_rows
        alpha=bytearray(100*80)
        for y in range(5,65):
            for x in range(5,95 if y<35 else 85):alpha[y*100+x]=255
        font=SimpleNamespace(utility=20,height=20,leading=10)
        c=dict(panel_shape=dict(sx=0,sy=0,w=100,h=80),origin=[10,10],
            width=90,height=100,scale=1,excludes=[[70,40,10,20]])
        regions=inscribed_rows(alpha,100,80,c,font,(0,0,100,80))
        self.assertEqual([r['panel_capacity'] for r in regions],[1,2])
        self.assertEqual(regions[0]['width'],83)
        self.assertEqual(regions[1]['row_widths'],[83,58])

    def test_composed_dialog_wraps_without_serializing_runtime_glyph(self):
        font=self.font();marker=chr(0x1d20)
        c=dict(kind='composed_dialog',width=360,height=216,scale=1,
            members=['prefix','suffix'],joiner=marker,runtime_display='7456')
        catalog=SimpleNamespace(fields={key:dict(original='',contracts=[c]) for key in c['members']})
        working=dict(prefix='You need at least ',suffix=' KB of free space. Delete content and retry.')
        with self.assertRaisesRegex(ValueError,'font asset upgrade'):
            field_fit('prefix',working['prefix'],catalog,working,font,reflow=True,hyphenate=False)
        font.cached[marker]=(0,0,0,72,24)
        result,checks=field_fit('prefix',working['prefix'],catalog,working,font,reflow=True,hyphenate=False)
        self.assertNotIn(marker,result+working['suffix']);self.assertIn('＿',result+working['suffix'])
        self.assertEqual(checks[0]['runtime_display'],'7456')
        self.assertEqual((result+working['suffix']).replace('＿','').replace(' ',''),
            'You need at least  KB of free space. Delete content and retry.'.replace(' ',''))

    def test_storage_amount_is_one_cache_record_with_four_digit_ink(self):
        from editor.fontpatch import storage_glyph
        font=self.font();font.bitmap_height=24
        class Raw:
            def glyphIndexesForString(self,text):return list(map(ord,text))
            def boundingRect(self,index):return SimpleNamespace(left=lambda:1,right=lambda:9)
        glyph=storage_glyph(Raw(),font)
        self.assertEqual(glyph['character'],0x1d20);self.assertEqual(glyph['source'],'7456')
        self.assertEqual([i for i,x in glyph['runs']],list(map(ord,'7456')))
        self.assertGreater(glyph['width'],35)

    def test_composed_cleanup_rejects_partial_selection_before_mutation(self):
        from editor.textcleanup import apply_cleanup
        p=SimpleNamespace(revision='revision');contract=dict(kind='composed_dialog',members=['a','b'])
        plan=dict(revision=p.revision,changes=[],ui_changes=[dict(field_id=x,contracts=[contract]) for x in ('a','b')])
        with self.assertRaisesRegex(ValueError,'both composed'):apply_cleanup(p,plan,['a'])
        self.assertEqual(p.revision,'revision')

    def test_help_group_names_and_indirect_test_caption_consumers(self):
        from pathlib import Path
        import struct,tempfile
        from editor.engine import ROOT
        from editor.uitext import get_catalog
        from test_ui_text import fixture,global_fixture
        from editor.composition import EnvironmentLibrary
        from editor.compositionstate import resolve_state
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as folder:
            root=Path(folder)/'source';project,_,_=fixture(root)
            (root/'env/env_global.dat').write_bytes(global_fixture())
            (root/'env/env_test.dat').write_bytes(bytes(3)+struct.pack('<I',2)+string('Asset test')+string('Debug')+bytes(20))
            c=get_catalog(project);font=self.font();font.bitmap_height=24
            self.assertFalse(any(v['family']=='help' for v in c.consumer_issues))
            slots=[f for f in c.fields.values() if f['source'].endswith('env_help_mgr.dat') and f['role'].startswith('Save / load')]
            self.assertTrue(slots);self.assertTrue(all(f['contracts'][0]['scene']['family']=='slots' for f in slots))
            field=c.fields['env/env_test.dat:#s1']
            self.assertEqual(field['fit_policy'],'consumer_checked');self.assertEqual(field['contracts'][0]['scene']['family'],'test')
            lib=EnvironmentLibrary(root,ui_text_catalog=c);state,_=resolve_state(lib,'test',dict(selected=1))
            scene=lib.build('test',state,font)
            captions=[v for v in scene.layers if v.name.startswith('Test caption ') and 'shadow' not in v.name]
            self.assertEqual([v.text for v in captions],['Asset test','Debug'])
            self.assertEqual(captions[1].glyphs[0]['rect'][:2],[100,106])

    def test_observer_provenance_is_scoped_and_stable(self):
        raw=string('')+string('Same')+string('Same');seen=[]
        def observe(r,a,b,v):seen.append(a);return FieldText(v,'field:'+str(a))
        token=STRING_OBSERVER.set(observe)
        try:
            r=Reader(raw);values=[r.string() for _ in range(3)]
        finally:STRING_OBSERVER.reset(token)
        self.assertEqual([v.field_id for v in values],['field:'+str(i) for i in seen])
        self.assertIs(type(Reader(raw).string()),str)

    def test_proposed_preview_is_revision_guarded_and_does_not_apply(self):
        from pathlib import Path
        import tempfile
        from editor.engine import ROOT
        from editor.uitext import get_catalog
        from editor.uipreview import preview_snapshot
        from test_ui_text import fixture
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as folder:
            project,_,_=fixture(Path(folder)/'source');c=get_catalog(project);key='env/env_help_mgr.dat:#s0'
            c.fields[key]['contracts']=[dict(kind='fixed',scene=dict(family='title',state={}))]
            original=c.fields[key]['original'];revision=project.revision
            plan=dict(revision=revision,ui_changes=[dict(field_id=key,before_text=original,after_text='New label')])
            view,recipe,_,text=preview_snapshot(project,key,plan=plan)
            self.assertEqual(text,'New label');self.assertEqual(recipe['family'],'title')
            self.assertEqual(view.ui_text_assets[key]['text'],'New label');self.assertFalse(project.ui_text_assets)
            self.assertEqual(project.revision,revision);self.assertFalse(project.undo_stack)
            plan['revision']='stale'
            with self.assertRaisesRegex(ValueError,'Stale'):preview_snapshot(project,key,plan=plan)


if __name__=='__main__':unittest.main()
