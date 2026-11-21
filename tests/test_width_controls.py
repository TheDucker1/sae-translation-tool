"""Synthetic timed-text width conversion and project transaction checks."""
from copy import deepcopy
import re
from pathlib import Path
import tempfile
import unittest

from editor.archive import Archive,describe
from editor.engine import ROOT
from editor.gameexport import prepare_archives,nested
from editor.text import TextFormat,TextPresentation
from editor.textlayout import TextLayoutService,full_width_text
from editor.textcleanup import analyze_cleanup,apply_cleanup
from test_document import fixture


def font_fixture():
    formatter=TextFormat.__new__(TextFormat)
    formatter.tokens=['《','》','《》','','“”','」']
    formatter.following=['']*27
    for index,value in {0:'『』',1:'「',2:'『』',3:'＿',8:'RUBY',9:'RT',10:'《/RUBY》',
                        11:'KEYWORD',12:'/KEYWORD',15:'SP',16:',',18:'QUE'}.items():
        formatter.following[index]=value
    formatter.mapping={};formatter.break_char='＿'
    font=TextPresentation.__new__(TextPresentation);font.format=formatter
    font.charset=set(chr(code) for code in range(0xff01,0xff5f));font.cached={};font.bitmap_height=24
    font.width=400;font.scale=1;font.utility=36;font.height=36;font.leading=0
    font.message_bounds=[0,0,400,150];font.origin=[0,0];font.ruby_scale=.5
    return font


class WidthControlChecks(unittest.TestCase):
    def setUp(self):
        self.font=font_fixture();self.service=TextLayoutService(self.font,{})

    def test_leading_keyword_keeps_native_aside_and_inline_keywords_still_pack(self):
        from unicodedata import normalize
        from editor.textlayout import script_font_text
        self.font.format.following[0]='（【'
        self.font.format.following[2]='「」'
        self.font.width=1000
        marks={'【':'龠','】':'龝'}
        self.font.pair_spacing=dict(pairs={},keyword_marks=marks,restore={v:k for k,v in marks.items()})
        self.font.asset_sha256='fixture'
        tag='【《KEYWORD = 121》Word《/KEYWORD》】'
        aside='Megumi「'+tag+' a phrase＿with a break.」'
        wire=script_font_text(self.font,aside,0x64,{},'text',authored=True)
        self.assertEqual(wire,full_width_text(aside,self.font,preserve_speaker=True)['text'])
        geometry=self.service.measure_dialogue(aside,font_authored=True)
        self.assertTrue(normalize('NFKC',geometry['body']).startswith('【Word】'))
        self.assertEqual(geometry['line_count'],2)
        result=self.service.wrap(0x64,aside,reflow=True)
        self.assertIn('《KEYWORD = 121》Word《/KEYWORD》',normalize('NFKC',result['text']))
        self.assertTrue(normalize('NFKC',result['lines'][0]).startswith('【Word】'))

        inline='Megumi「A '+tag+'.」'
        shaped=script_font_text(self.font,inline,0x64,{},'text',authored=True)
        self.assertIn('龠《KEYWORD = 121》Word《/KEYWORD》龝',normalize('NFKC',shaped))

    def test_timed_sentence_spacing_preserves_cues_and_existing_separators(self):
        from editor.textlayout import space_timed_sentences
        value='A「Câu rồi.《SP QUE,1,10》《SP QUE,2,20》Câu tiếp!《SP QUE,3,30》 Câu cuối.」'
        expected=value.replace('》Câu tiếp','》 Câu tiếp')
        self.assertEqual(space_timed_sentences(self.font.format,value),(expected,1))
        self.assertEqual(space_timed_sentences(self.font.format,expected),(expected,0))
        expected_markers=[m[1:] for m in self.font.format.ordinary(value)['markers']]
        result=self.service.wrap(0x64,value)
        self.assertEqual(result['inserted_cue_spaces'],1)
        self.assertIn('《SP QUE,2,20》 Câu',result['text'])
        self.assertEqual([m[1:] for m in self.font.format.ordinary(result['text'])['markers']],expected_markers)
        self.assertNotIn('＿',result['text'])

    def project(self,text):
        project=fixture();project.text_format=self.font.format
        args=deepcopy(project.scripts[0].commands[2].args);args['text']=text
        project.replace(0,'s0:c2',0x64,args)
        return project

    def test_surrounding_text_ruby_and_tags_keep_queue_and_style_ranges(self):
        source='Eriri「Why here...《SP QUE,1,2700》《RUBY》word《RT》reading《/RUBY》?《KEYWORD = 12》After《/KEYWORD》」'
        packet=self.service.wrap(0x64,source,width=160,full_width_latin=True)
        result=packet['text'];before=self.font.format.ordinary(source);after=self.font.format.ordinary(result)
        self.assertIn('Ｗｈｙ ｈｅｒｅ．．．《SP QUE,1,2700》',result)
        self.assertIn('《RUBY》ｗｏｒｄ《RT》ｒｅａｄｉｎｇ《/RUBY》？',result)
        self.assertIn('《KEYWORD = 12》Ａｆｔｅｒ《/KEYWORD》',result)
        self.assertEqual(re.findall('《.*?》',source),re.findall('《.*?》',result))
        self.assertEqual(before['markers'],after['markers'])
        self.assertEqual([[a+1,b+1,key] for a,b,key in before['keywords']],after['keywords'])
        self.assertEqual([i+1 for i in before['ruby'][0][:2]],after['ruby'][0][:2])
        self.assertEqual(after['ruby'][0][2],'ｒｅａｄｉｎｇ')
        self.assertEqual(len(before['body'])+1,len(after['body']))
        self.assertNotIn('＿',result);self.assertEqual(packet['inserted_breaks'],0)
        self.assertEqual(packet['hyphenations'],0);self.assertIn('wrapping_skipped',packet)
        self.assertEqual(full_width_text(result,self.font)['converted_characters'],0)

    def test_cleanup_converts_without_reflow_serializes_and_undoes(self):
        source="Eriri「Why don't you come over here...《SP QUE,1,2700》Wait, seriously? You're reading even here?」"
        for attributes in ({},{'route':1},{'completion':2},{'selector':1}):
            with self.subTest(attributes=attributes):
                project=self.project(source);project.scripts[0].commands[2].args.update(attributes)
                original=project.compile(0);args=deepcopy(project.scripts[0].commands[2].args)
                plan=analyze_cleanup(project,self.font,{},command_ids=['s0:c2'],width=160,full_width_latin=True)
                change=plan['changes'][0];measurement=plan['issues'][0]['measurement']
                self.assertEqual(change['page_count'],1);self.assertTrue(measurement['auto_edit'])
                self.assertFalse(measurement['standalone_fits'])
                self.assertEqual(measurement['text'],change['pages'][0]['text'])
                self.assertEqual(measurement['measurement'],'converted_command_text')
                self.assertEqual({k:v for k,v in change['pages'][0].items() if k!='text'},
                                 {k:v for k,v in args.items() if k!='text'})
                result=apply_cleanup(project,plan);self.assertEqual(result['inserted_commands'],0)
                encoded=describe(project.compile(0))['commands'][2]['args']['text']
                self.assertEqual(encoded,change['pages'][0]['text']);self.assertIn('Ｗａｉｔ',encoded)
                self.assertIn('《SP QUE,1,2700》',encoded);self.assertNotIn('＿',encoded)
                repeated=analyze_cleanup(project,self.font,{},command_ids=['s0:c2'],width=160,full_width_latin=True)
                self.assertFalse(repeated['changes'])
                project.undo();self.assertEqual(project.compile(0),original)

    def test_game_archive_export_contains_converted_timed_text(self):
        from test_game_export import source_fixture
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as folder:
            project,first,resource=source_fixture(Path(folder)/'original')
            project.text_format=self.font.format
            command=project.scripts[0].commands[3];args=deepcopy(command.args)
            args['text']='A「Before《SP QUE,1,2700》After」'
            project.replace(0,command.uid,0x64,args)
            plan=analyze_cleanup(project,self.font,{},command_ids=[command.uid],full_width_latin=True,hyphenate=False)
            apply_cleanup(project,plan);exported=prepare_archives(project)
            obj=nested(nested(nested(Archive(exported['resource']),4),0),0)
            actual=describe(obj.read(0,gzip=True))['commands'][3]['args']['text']
            self.assertEqual(actual,'Ａ「Ｂｅｆｏｒｅ《SP QUE,1,2700》Ａｆｔｅｒ」')
            self.assertEqual((Path(project.root)/'first.dat').read_bytes(),first)
            self.assertEqual((Path(project.root)/'resource.dat').read_bytes(),resource)

    def test_fitting_text_stays_intact_and_invalid_timed_breaks_reject(self):
        source='A「Before《SP QUE,1,2700》After」';project=self.project(source)
        plan=analyze_cleanup(project,self.font,{},command_ids=['s0:c2'])
        self.assertFalse(plan['changes']);self.assertFalse(plan['issues'])
        invalid=source.replace('Before','Before＿')
        project.scripts[0].commands[2].args['text']=invalid
        plan=analyze_cleanup(project,self.font,{},command_ids=['s0:c2'],full_width_latin=True)
        self.assertFalse(plan['changes']);self.assertIn('explicit line breaks',plan['issues'][0]['reason'])
        with self.assertRaisesRegex(ValueError,'explicit line breaks'):
            self.service.wrap(0x64,invalid,full_width_latin=True)


if __name__=='__main__':unittest.main()
