"""Discriminating reference/codec/transaction checks; no story regression."""
import struct,tempfile,json,unittest
from pathlib import Path
from copy import deepcopy
from editor.document import Project,EditError
from editor.engine import ROOT
from editor.editview import template
from editor import scriptcodec as codec


def fixture():
    message=lambda t:dict(route=0,selector=0,voice=-1,speaker=-1,text=t,completion=0,lane=0)
    rows=[(0,dict(bank=0,index=6,operation=0,operand_kind=2,operand=6)),
          (1,dict(condition='?L6==6',start=2,alternate=4,resume=6)),
          (0x64,message('True')),(0x2be,dict(target=6)),
          (0x64,message('False')),(0x2be,dict(target=6)),
          (0x64,message('Join')),(0x2bf,dict(script=-1))]
    records=[];commands=[]
    for i,(op,a) in enumerate(rows):
        if op in {0x64}:payload=codec.encode_text(op,a)+b'\x80\x01'
        elif op==0:payload=struct.pack('<5I',*(a[k] for k in ('bank','index','operation','operand_kind','operand')))
        elif op==1:payload=codec.string(a['condition'])+struct.pack('<3i',2,4,6)
        else:payload=struct.pack('<i',next(iter(a.values())))
        records.append(codec.RawRecord(op,payload,6+i,0));commands.append(dict(args=a))
    blob=codec.assemble(b'opaque-header',records,b'opaque-tail')
    other=codec.assemble(b'', [codec.RawRecord(0x2bf,struct.pack('<i',0),111,0)], b'')
    return Project.from_import(dict(scripts=[dict(id=0,data_hex=blob.hex(),commands=commands),dict(id=1,data_hex=other.hex(),commands=[dict(args=dict(script=0))])]),[dict(id=0,name='first'),dict(id=1,name='second')])


class DocumentChecks(unittest.TestCase):
    def test_nested_choice_result_operands_relocate_at_their_actual_byte_sites(self):
        for opcode in (0x65,0x3f2,0x3f6,0x3f8,0x3fa):
            p=fixture();header,records,tail=codec.parse(p.compile(0));args=template(opcode,'s0:c6') if opcode!=0x3fa else dict(win=6,lose=6,draw=6)
            for path in codec.reference_paths(opcode,args):codec.put(args,path,6)
            if opcode==0x3f6:args['parents'][0]['children']*=3
            records[2]=codec.RawRecord(opcode,codec.encode_text(opcode,args) if opcode!=0x3fa else struct.pack('<3i',6,6,6),222,0)
            commands=[dict(args=r['args']) for r in p.display(0)];commands[2]=dict(args=args)
            p=Project.from_import(dict(scripts=[dict(id=0,data_hex=codec.assemble(header,records,tail).hex(),commands=commands)]),[dict(id=0,name='nested')])
            p.add(0,6,0x64,template(0x64,'s0:c6'));self.assertEqual(p.validate(),[],hex(opcode))
            record=codec.parse(p.compile(0))[1][2]
            sites=codec.reference_sites(opcode,record.payload);self.assertTrue(sites)
            for path,offset in sites:self.assertEqual(struct.unpack_from('<i',record.payload,offset)[0],7,(hex(opcode),path))

    def test_insert_fixes_every_typed_target_but_not_equal_operands(self):
        p=fixture();original=p.scripts[0].original;join=p.scripts[0].commands[6].uid
        p.add(0,2,0x64,template(0x64,join))
        self.assertEqual(p.validate(),[])
        rows=p.display(0)
        self.assertEqual(rows[1]['args']['start'],3)
        self.assertEqual(rows[1]['args']['alternate'],5)
        self.assertEqual(rows[1]['args']['resume'],7)
        self.assertEqual([c['args']['target'] for c in rows if c['opcode']==0x2be],[7,7])
        self.assertEqual(rows[0]['args']['operand'],6);self.assertEqual(rows[0]['args']['index'],6)
        header,records,tail=codec.parse(p.compile(0));oldheader,oldrecords,oldtail=codec.parse(bytes.fromhex(original))
        self.assertEqual((header,tail),(oldheader,oldtail));self.assertEqual(records[3].post,oldrecords[2].post)
        self.assertEqual(p.compile(1).hex(),p.scripts[1].original)

    def test_delete_never_retargets_implicitly_and_undo_is_atomic(self):
        p=fixture();original=p.compile(0);victim=p.scripts[0].commands[6].uid
        self.assertEqual(len(p.inbound(victim)),3)
        p.delete(0,victim)
        self.assertTrue(any('Unresolved' in d.message for d in p.validate()))
        with self.assertRaises(EditError):p.revision_request(0)
        p.undo();self.assertEqual(p.compile(0),original);self.assertEqual(p.validate(),[])
        victim=p.scripts[0].commands[2].uid;replacement=p.scripts[0].commands[3].uid
        p.delete(0,victim,replacement);self.assertEqual(p.validate(),[])
        self.assertEqual(p.display(0)[1]['args']['start'],2)

    def test_replace_identity_reopen_and_corruption_checks(self):
        p=fixture();base=fixture();uid=p.scripts[0].commands[6].uid
        p.replace(0,uid,0x3ec,dict(chapter=0,texts=['Longer chapter title','Subtitle']))
        self.assertEqual(p.validate(),[]);self.assertEqual(len(p.inbound(uid)),3)
        changed=p.compile(0);self.assertEqual(codec.parse(changed)[1][6].opcode,0x3ec)
        p.undo();self.assertEqual(p.compile(0).hex(),p.scripts[0].original);p.redo();self.assertEqual(p.compile(0),changed)
        with tempfile.TemporaryDirectory(dir=ROOT/'.local') as folder:
            self.assertTrue(Path(folder).resolve().is_relative_to(ROOT.resolve()))
            path=Path(folder)/'edit.saekano.json';p.save(path);loaded=Project.load(path,base)
            self.assertEqual(loaded.compile(0),changed);self.assertEqual(loaded.scripts[0].commands[6].uid,uid)
            data=json.loads(path.read_text());self.assertEqual(len(data['scripts']),1)
            data['fingerprints']['0']='incorrect';path.write_text(json.dumps(data))
            with self.assertRaises(EditError):Project.load(path,base)
        loaded.scripts[0].commands[0].args['operand']=999
        self.assertTrue(any('Unencoded' in d.message for d in loaded.validate()))

    def test_utf16_lengths_counts_bounds_and_exact_roundtrip(self):
        p=fixture();self.assertEqual(p.compile(0).hex(),p.scripts[0].original)
        reader=codec.Reader(codec.string('A😀'));self.assertEqual(reader.word(),3)
        with self.assertRaises(codec.CodecError):codec.string('\ud800')
        uid=p.scripts[0].commands[2].uid;a=deepcopy(p.scripts[0].commands[2].args);a['voice']=2**40
        p.replace(0,uid,0x64,a);self.assertTrue(p.validate())
        p.undo();uid=p.add(0,2,0x65,dict(duration=0,choices=[]));self.assertTrue(any('must not be empty' in d.message for d in p.validate()))


if __name__=='__main__':unittest.main()
