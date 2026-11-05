"""Focused LLM reading/reference contracts; no gameplay/rendering regression."""
import importlib.util
import unittest
if importlib.util.find_spec('mcp') is None:raise unittest.SkipTest('Optional MCP dependencies required')
import json,struct,tempfile
from pathlib import Path
from editor import scriptcodec as codec
from editor.archive import describe
from editor.document import Project
from editor.engine import ROOT
from editor.text import TextFormat
from editor.mcp_server import create_server
from mcp import Client
from test_translation_workspace import workspace_fixture


def story_fixture(folder):
    w=workspace_fixture(folder);p=w.project;head,records,tail=codec.parse(p.compile(0))
    records[2:2]=[codec.RawRecord(0x258,codec.string('007')+struct.pack('<i',70),0,0),codec.RawRecord(0xc8,struct.pack('<i',100),0,0)]
    for i,r in enumerate(records):
        b=bytearray(r.payload)
        for _,offset in codec.reference_sites(r.opcode,b):
            value=struct.unpack_from('<i',b,offset)[0]
            if value>=2:struct.pack_into('<i',b,offset,value+2)
        records[i]=codec.RawRecord(r.opcode,bytes(b),r.post,0)
    w.project=Project.from_import(dict(scripts=[dict(id=0,**describe(codec.assemble(head,records,tail)))]),[dict(id=0,name='Story')])
    w._baseline={c.uid:c for c in w.project.baseline[0].commands}
    return w


class DialogueViewChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.local');self.w=story_fixture(Path(self.temp.name))
    def tearDown(self):self.temp.cleanup()

    def test_dialogue_state_media_targets_paging_and_reference_discovery(self):
        w=self.w;view=w.get_dialogue_flow(0,limit=30)
        cue=next(c for c in view['cards'] if c['kind']=='presentation_cues')
        self.assertEqual((cue['index'],cue['last_index'],cue['command_count']),(2,3,2))
        self.assertEqual(cue['opcodes'],{'0258':1,'00C8':1});self.assertNotIn('volume',json.dumps(cue))
        self.assertEqual(cue['detail_request']['arguments']['script_id'],0)
        self.assertIn('L[6] = 6',view['transcript']);self.assertIn('true: ?L6==6',view['transcript'])
        self.assertIn('false: ?L6==6',view['transcript']);self.assertIn('s0:c8',view['transcript'])
        self.assertTrue(view['potential_only']);self.assertIn('True',view['transcript'])
        context=w.get_context(0,'s0:c2',neighbours=0)
        self.assertNotIn('arguments',context['command']);self.assertEqual(context['state_cues'][0]['kind'],'presentation_cues')
        self.assertEqual(w.get_context(0,'s0:c2',neighbours=0,details=True)['command']['arguments']['volume'],70)
        first=w.get_dialogue_flow(0,limit=2);second=w.get_dialogue_flow(0,start=first['next_start'],limit=2)
        self.assertEqual(second['cards'][0]['command_id'],cue['command_id'])
        # A jump into the middle of a cue group must expose that exact target,
        # not make it appear to start at the preceding audio command.
        w.project.retarget(0,'s0:c5',('target',),'s0:c3')
        split=w.get_dialogue_flow(0,limit=30);cues=[c for c in split['cards'] if c['kind']=='presentation_cues']
        self.assertEqual([(c['index'],c['last_index']) for c in cues],[(2,2),(3,3)])
        jump=next(c for c in split['cards'] if c['command_id']=='s0:c5')
        self.assertEqual(jump['outgoing'][0]['target_id'],'s0:c3')
        self.assertIn(0x64,[row['opcode'] for row in w.list_opcodes(query='dialogue')['opcodes']])
        self.assertEqual(w.list_opcodes(limit=100)['matches'],55)
        self.assertIn('speaker',w.opcode_help(0x64)['help']);self.assertNotIn('.cpp',w.opcode_help(0x64)['help'])

    @unittest.skipUnless((ROOT.parent/'GAMEFILE/USRDIR/env/env_string_format.dat').is_file(),'Original format needed')
    def test_readable_speaker_ruby_and_unchanged_editable_source(self):
        w=self.w;w.project.text_format=TextFormat((ROOT.parent/'GAMEFILE/USRDIR/env/env_string_format.dat').read_bytes())
        c=w.project.scripts[0].commands[4];args=dict(c.args);raw='Alice「《RUBY》世界《RT》せかい《/RUBY》へ＿ようこそ」';args['text']=raw
        w.project.replace(0,c.uid,0x64,args)
        row=next(card for card in w.get_dialogue_flow(0)['cards'] if card['command_id']==c.uid)['lines'][0]
        self.assertEqual(row['speaker'],'Alice');self.assertEqual(row['text'],'「世界へ\nようこそ」')
        self.assertNotIn('RUBY',row['text']);self.assertNotIn('せかい',row['text'])
        context=w.get_context(0,c.uid,neighbours=0)
        self.assertEqual(context['command']['text_fields'][0]['current'],raw)
        self.assertEqual(context['command']['text_fields'][0]['display']['speaker'],'Alice')
        self.assertEqual(w.project.scripts[0].commands[4].args['text'],raw)


class DialogueProtocolChecks(unittest.IsolatedAsyncioTestCase):
    async def test_new_read_views_and_reference_tools_over_mcp(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as folder:
            w=story_fixture(Path(folder))
            async with Client(create_server(w)) as client:
                tools={t.name for t in (await client.list_tools()).tools}
                self.assertTrue({'get_dialogue_flow','list_opcodes','opcode_help'}<=tools)
                result=await client.call_tool('get_dialogue_flow',{'script_id':0})
                self.assertFalse(result.is_error);self.assertIn('L[6]',result.structured_content['transcript'])
                catalog=await client.call_tool('list_opcodes',{'query':'dialogue'})
                self.assertFalse(catalog.is_error);self.assertTrue(catalog.structured_content['opcodes'])
                help_result=await client.call_tool('opcode_help',{'opcode':100})
                self.assertFalse(help_result.is_error);self.assertIn('speaker',help_result.structured_content['help'])
                detailed=await client.call_tool('get_context',{'script_id':0,'command_id':'s0:c2','details':True})
                self.assertEqual(detailed.structured_content['command']['arguments']['volume'],70)


if __name__=='__main__':unittest.main()
