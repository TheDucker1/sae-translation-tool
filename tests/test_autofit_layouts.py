"""Mixed consumer layouts, timed padding and curved bubble fit checks."""
from copy import deepcopy
from types import SimpleNamespace
import struct
import unittest
from unittest.mock import patch

from editor import scriptcodec as codec
from editor.archive import describe
from editor.document import Project
from editor.engine import TEXT_OPS,text_fields
from editor.gameexport import prepare_archives,nested
from editor.archive import Archive
from editor.engine import ROOT
from pathlib import Path
import tempfile
from editor.templates import template
from editor.textcleanup import analyze_cleanup,apply_cleanup
from editor.textlayout import TextLayoutService,field_path
from editor.textregions import BattleTextRegions
from test_document import fixture
from test_width_controls import font_fixture


def settings_fixture():
    return dict(
        selection=dict(scale=.75,points=[[[100,100],[200,200]],[[100,100],[200,200],[300,300]]],words=[0,0,0,0,100,0]),
        chapter_text=dict(scale=.5,positions=[[20,100],[40,140]]),
        approach=dict(scale=.75,points=[[[200,200]],[[300,300]]],offset=[250,250],text_offset=[0,0],
                      result_scale=.75,result_origin=[100,100],result_width=220),
        battle=dict(width=180,positions=[[200,250],[700,250]],line_offsets=[[0,-40],[0,-18]],
                    bubble=dict(width=280,height=180,alignment=4,sx=0,sy=0),bubble_scale=1,
                    choice_positions=[[200,150],[500,150],[800,150]],choice_offsets=[[0,-40],[0,-18]],
                    card_scale=1,pulses=[[1,1,0]]*3,text_scale=.5,text_positions=[[100,100],[850,100]],padding=10))


class AutoFitLayouts(unittest.TestCase):
    def setUp(self):self.font=font_fixture();self.settings=settings_fixture()

    def test_all_text_families_and_files_use_their_own_consumers(self):
        p=fixture();wanted=[]
        for opcode in sorted(TEXT_OPS):
            args=template(opcode,'s0:c6')
            if opcode==0x3f2:args['choices'].append(deepcopy(args['choices'][0]))
            for field,_ in text_fields(dict(opcode=opcode,args=args)):codec.put(args,field_path(field),'Hi')
            wanted.append(p.add(0,6,opcode,args))
        # Put battle ownership in another file to catch accidental batch-global state.
        _,records,tail=codec.parse(p.compile(1))
        battle=codec.RawRecord(0x3ef,struct.pack('<6i',0,0,0,1,0,50),0,0)
        message=template(0x64,'');message['text']='Hi'
        blob=codec.assemble(b'',[battle,codec.RawRecord(0x64,codec.encode_text(0x64,message),0,0),*records],tail)
        imported=Project.from_import(dict(scripts=[dict(id=0,**describe(p.compile(0))),dict(id=1,**describe(blob))]),[dict(id=0,name='story'),dict(id=1,name='battle')])
        imported.text_format=self.font.format
        plan=analyze_cleanup(imported,self.font,self.settings,full_width_latin=True)
        self.assertFalse(plan['issues'],plan['issues'])
        changes={c['opcode']:c for c in plan['changes'] if c['script_id']==0}
        self.assertEqual(set(changes),TEXT_OPS)
        ordinary=changes[0x64]['details'][0]
        battle_change=next(c for c in plan['changes'] if c['script_id']==1)
        self.assertEqual((ordinary['dialogue_mode'],ordinary['width']),('ordinary',400))
        self.assertEqual((battle_change['details'][0]['dialogue_mode'],battle_change['details'][0]['width']),('battle',180))
        self.assertEqual(changes[0x3f8]['details'][0]['width'],220)
        self.assertTrue(all(d['field']!='choices[0].label' for d in changes[0x3f2]['details']))
        apply_cleanup(imported,plan);self.assertFalse(imported.validate())

    def test_fixed_cursor_labels_are_checked_with_a_proportional_font(self):
        p=fixture();args=template(0x65,'s0:c6');args['choices'][0]['label']='Short label'
        args['choices'].append({**deepcopy(args['choices'][0]),'label':'Hi'})
        uid=p.add(0,6,0x65,args);p.font_asset={'synthetic':True}
        font=deepcopy(self.font);font.cached={c:(0,0,0,2,36) for c in 'Shortlabel'}
        with patch('editor.fontpatch.effective_font',return_value=font):
            plan=analyze_cleanup(p,font,self.settings,command_ids=[uid],label_width=60,full_width_latin=True)
        self.assertTrue(plan['issues']);self.assertIn('Single-line',plan['issues'][0]['reason'])
        self.assertNotIn('proportional dialogue font asset cannot',plan['issues'][0]['reason'])
        self.assertEqual(plan['changes'][0]['pages'][0]['choices'][0]['label'],'Short label')
        self.assertEqual(plan['changes'][0]['pages'][0]['choices'][1]['label'],'Ｈｉ')

    def test_timed_padding_reproduces_words_without_changing_directives(self):
        text='A「One two three four《SP QUE,1,2700》 five six seven eight.」'
        service=TextLayoutService(self.font,self.settings)
        packet=service.wrap(0x64,text,width=180)
        self.assertEqual(packet['break_strategy'],'spaces');self.assertNotIn('＿',packet['text'])
        self.assertIn('《SP QUE,1,2700》',packet['text'])
        parsed=self.font.format.ordinary(packet['text'])
        actual=self.font.layout(parsed['body'],self.font.width)
        lines=[''.join(chr(g['code']) for g in actual if g['line']==i).strip() for i in range(packet['line_count'])]
        self.assertEqual(lines,packet['lines'])
        self.assertEqual(self.font.format.ordinary(text)['markers'][0][1:],parsed['markers'][0][1:])
        self.assertEqual(service.wrap(0x64,packet['text'],width=180)['text'],packet['text'])

    def test_padded_timed_message_exports_and_undoes(self):
        from test_game_export import source_fixture
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as folder:
            p,_,original=source_fixture(Path(folder)/'original');p.text_format=self.font.format
            command=p.scripts[0].commands[3];args=deepcopy(command.args)
            args['text']='A「One two three four《SP QUE,1,2700》 five six.」'
            p.replace(0,command.uid,0x64,args);before=p.compile(0)
            plan=analyze_cleanup(p,self.font,self.settings,command_ids=[command.uid])
            self.assertFalse(plan['issues'],plan['issues']);self.assertEqual(plan['changes'][0]['details'][0]['break_strategy'],'spaces')
            result=apply_cleanup(p,plan);self.assertEqual(result['inserted_commands'],0)
            exported=prepare_archives(p)
            obj=nested(nested(nested(Archive(exported['resource']),4),0),0)
            actual=describe(obj.read(0,gzip=True))['commands'][3]['args']['text']
            self.assertNotIn('＿',actual);self.assertIn('《SP QUE,1,2700》',actual)
            self.assertEqual(actual,plan['changes'][0]['pages'][0]['text'])
            self.assertEqual((Path(p.root)/'resource.dat').read_bytes(),original)
            p.undo();self.assertEqual(p.compile(0),before)

    def test_curved_mask_capacity_and_explicit_reflow(self):
        regions=BattleTextRegions(SimpleNamespace(root='',texture_assets={}),self.font,self.settings)
        w,h=280,140
        self.settings['battle']['bubble']['height']=h
        alpha=bytes(255 if ((x-w/2)/(w/2-2))**2+((y-h/2)/(h/2-2))**2<=1 else 0 for y in range(h) for x in range(w))
        regions.masks=[(w,h,alpha)]*3
        rectangle=regions.rectangle()
        self.assertLessEqual(rectangle['capacity'],2)
        self.assertGreater(rectangle['width'],0)
        service=TextLayoutService(self.font,self.settings,regions=regions)
        spec=service.dimensions(0x64,dialogue_mode='battle')
        self.assertEqual(spec['width_source'],'bubble_contour')
        old='A「One＿two＿three.」'
        preserved=service.wrap(0x64,old)
        repaired=service.wrap(0x64,old,reflow=True)
        self.assertEqual(preserved['line_count'],3);self.assertEqual(repaired['line_count'],1)
        self.assertEqual(repaired['text'],'A「One two three.」')


if __name__=='__main__':unittest.main()
