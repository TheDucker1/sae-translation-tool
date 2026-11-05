"""Small native-layout export fixtures; no gameplay/rendering regression."""
import gzip
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import struct
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from editor import scriptcodec as codec
from editor.archive import Archive,describe
from editor.document import Project
from editor.engine import ROOT
from editor.packing import Member,pack_members,repack,payload,content_crc
from editor.gameexport import prepare_archives,export_game,ExportError,ExportCancelled,table_rows
from editor.seekwriter import relocate
from editor.editview import template
from test_document import fixture


def pack(entries):return pack_members([Member(name.encode('cp932'),0,data) for name,data in entries])


def seekmap(data):
    rows=[]
    def walk(name,data,at=0,depth=0):
        archive=Archive(data) if bytes(data[:4])==b'GPDA' else None
        line='\t'*depth+f'{name}  {at} {len(data)} {content_crc(data)}'
        if archive:line+=f' 0 {len(archive.entries)} '
        rows.append(line+'\r\n')
        if archive:
            for i,e in enumerate(archive.entries):walk(e.name.strip(),payload(archive,i),at+e.offset,depth+1)
    walk('resource.dat',data)
    return ''.join(rows).encode('cp932')


def source_fixture(root):
    p=fixture();data0=codec.parse(p.compile(0));records=data0[1]
    for index,voice in ((2,10),(4,20),(6,10)):
        a=deepcopy(p.scripts[0].commands[index].args);a['voice']=voice
        records[index]=codec.RawRecord(0x64,codec.encode_text(0x64,a),records[index].post,0)
    # The non-text approach-entry history row has a nonzero authored length;
    # preserve it rather than deriving it from the scene ID.
    records.insert(0,codec.RawRecord(0x3ee,struct.pack('<i',0),0,0))
    # Shift the original condition/jump command references for this fixture.
    for i,r in enumerate(records):
        b=bytearray(r.payload)
        for _,offset in codec.reference_sites(r.opcode,b):struct.pack_into('<i',b,offset,struct.unpack_from('<i',b,offset)[0]+1)
        records[i]=codec.RawRecord(r.opcode,bytes(b),r.post,0)
    blob0=codec.assemble(data0[0],records,data0[2])
    a=template(0x64,'');a.update(text='Other original voice',voice=30)
    blob1=codec.assemble(b'',[codec.RawRecord(0x64,codec.encode_text(0x64,a),9,0),codec.RawRecord(0x2bf,struct.pack('<i',-1),0,0)],b'')
    bundle=dict(scripts=[dict(id=i,**describe(b)) for i,b in enumerate((blob0,blob1))])
    p=Project.from_import(bundle,[dict(id=0,name='first'),dict(id=1,name='second')],str(root))
    numbered=[]
    for sid,blob,ids in ((0,blob0,[10,20]),(1,blob1,[30])):
        volumes=pack([(f'voice{id}.vol',f'VOL{id}'.encode()) for id in ids])
        obj=pack([('script.obj.gz ',gzip.compress(blob,mtime=0)),('script.dat.gz ',gzip.compress(volumes,mtime=0))])
        numbered.append((f'{sid}.dat ',pack([('object.dat ',obj)])))
    scripts=pack(numbered);resource=pack([(f'part{i}.dat ',pack([])) for i in range(4)]+[('script.dat ',scripts)])
    counts=struct.pack('<III',2,9,2);branches=struct.pack('<IIII',1,0,0,12)
    reads=struct.pack('<I',4)+b''.join(struct.pack('<II',sid,i) for sid,indices in ((0,[3,5,7]),(1,[0])) for i in indices)
    tables=pack([('zz1.tmp',counts),('zz2.tmp',branches),('zz3.tmp',reads)])
    first=pack([(f'part{i}',b'untouched') for i in range(4)]+[('script.dat ',tables),('seekmap.dat ',gzip.compress(seekmap(resource),mtime=0))])
    root.mkdir();(root/'first.dat').write_bytes(first);(root/'resource.dat').write_bytes(resource)
    (root/'env').mkdir();(root/'env/setting.dat').write_bytes(b'original setting')
    (root/'voice.awb').write_bytes(b'original audio')
    return p,first,resource


class GameExport(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.local');self.folder=Path(self.temp.name)
        self.p,self.first,self.resource=source_fixture(self.folder/'original')
    def tearDown(self):self.temp.cleanup()

    def test_archive_noop_padding_and_relocation(self):
        a=Archive(pack_members([Member(b'first ',0,b'one'),Member(b'gim ',2,b'x',b'x'+b'physical tail')],reserved=123))
        self.assertEqual(repack(a,{}),bytes(a.data));new=Archive(repack(a,{0:b'changed'*1000}))
        self.assertEqual(bytes(payload(new,1,True)),bytes(payload(a,1,True)))
        self.assertEqual(new.entries[1].kind,2);self.assertEqual(new.entries[1].name,'gim ')
        self.assertEqual(struct.unpack_from('<I',new.data,8)[0],123)
        self.assertGreater(new.entries[1].offset,a.entries[1].offset)
        result=prepare_archives(self.p)
        self.assertEqual((result['first'],result['resource']),(self.first,self.resource))

    def edit(self):
        p=self.p;old=p.scripts[0].commands[5];target=p.scripts[0].commands[7].uid
        p.replace(0,old.uid,0x65,dict(duration=0,choices=[dict(target={'$ref':target},label='One',preview=-1,extras=[]),dict(target={'$ref':target},label='Two',preview=-1,extras=[])]))
        inserted=template(0x64,target);inserted.update(voice=30,text='Added translation')
        p.add(0,7,0x64,inserted)
        # Delete an original voiced message with an explicit inbound replacement.
        victim=p.scripts[0].commands[3].uid;p.delete(0,victim,p.scripts[0].commands[4].uid)
        p.add(0,8,0x3ec,dict(chapter=0,texts=['Added chapter','Subtitle']))
        self.assertFalse(p.validate())

    def test_complete_export_metadata_voices_checksums_and_source_preservation(self):
        self.edit();p=self.p;destination=self.folder/'patched';report=export_game(p,destination)
        self.assertTrue(report['requires_fresh_progress']);self.assertTrue(report['changed_scripts'][0]['voice_companion_rebuilt'])
        first=Archive((destination/'first.dat').read_bytes());resource=Archive((destination/'resource.dat').read_bytes())
        scripts=Archive(resource.read(4));obj=Archive(Archive(scripts.read(0)).read(0))
        self.assertEqual(obj.read(0,gzip=True),p.compile(0));self.assertEqual(scripts.read(1),Archive(Archive(self.resource).read(4)).read(1))
        vol=Archive(obj.read(1,gzip=True));self.assertEqual([vol.read(i) for i in range(len(vol.entries))],[b'VOL30',b'VOL10'])
        tables=Archive(first.read(4));self.assertEqual(table_rows(tables.read(0),1)[0][0],(10,))
        branches=table_rows(tables.read(1),3)[0]
        self.assertEqual(branches,[(0,0,12),(0,4,2)])
        self.assertEqual(table_rows(tables.read(2),2)[0],[(0,6),(0,7),(1,0)])
        seek=first.read(5,gzip=True)
        # Independent pass treats output as its own source: all absolute ranges
        # and changed checksums must agree with the actual rebuilt hierarchy.
        paths={() ,(4,),(4,0),(4,0,0),(4,0,0,0),(4,0,0,1)}
        checked,_=relocate(seek,resource.data,resource.data,paths);self.assertEqual(checked,seek)
        self.assertEqual((Path(p.root)/'first.dat').read_bytes(),self.first)
        self.assertEqual((Path(p.root)/'resource.dat').read_bytes(),self.resource)
        self.assertEqual((destination/'env/setting.dat').read_bytes(),b'original setting')
        (destination/'voice.awb').write_bytes(b'modified copy')
        self.assertEqual((Path(p.root)/'voice.awb').read_bytes(),b'original audio')
        self.assertTrue((destination/'saekano-export.json').is_file())

    def test_invalid_source_destination_voice_and_cancel_do_not_publish(self):
        p=self.p;self.edit()
        for destination in (Path(p.root),Path(p.root)/'child'):
            with self.assertRaisesRegex(ExportError,'separate'):export_game(p,destination)
        occupied=self.folder/'occupied';occupied.mkdir();(occupied/'keep').write_text('keep')
        with self.assertRaisesRegex(ExportError,'empty'):export_game(p,occupied)
        cancelled=False
        def progress(message):
            nonlocal cancelled
            if message.startswith('Exporting'):cancelled=True
        destination=self.folder/'cancelled'
        with self.assertRaises(ExportCancelled):export_game(p,destination,progress,lambda:cancelled)
        self.assertFalse(destination.exists());self.assertFalse(list(self.folder.glob('.saekano-export-*')))
        command=next(c for c in p.scripts[0].commands if c.opcode==0x64);args=deepcopy(command.args);args['voice']=999
        p.replace(0,command.uid,0x64,args)
        with self.assertRaisesRegex(ExportError,'no original envelope'):export_game(p,self.folder/'badvoice')
        p.undo()
        original=p.scripts[0].original;p.scripts[0].original+='00'
        with self.assertRaisesRegex(ExportError,'changed since project import'):export_game(p,self.folder/'wrongsource')
        p.scripts[0].original=original
        choice=next(c for c in p.scripts[0].commands if c.opcode==0x65)
        p.delete(0,choice.args['choices'][0]['target']['$ref'])
        with self.assertRaisesRegex(ExportError,'validation'):export_game(p,self.folder/'invalid')

    def test_gui_export_worker_publishes_and_restores_controls(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QEventLoop,QTimer
        from editor.ui import Window
        app=QApplication.instance() or QApplication([]);w=Window();w.project=self.p;w.preview_revision=self.p.revision
        self.edit();w.preview_revision=self.p.revision;errors=[];w.problem=errors.append
        destination=self.folder/'gui-patched'
        try:
            with patch('editor.ui.QFileDialog.getExistingDirectory',return_value=str(destination)),patch('editor.ui.QMessageBox.information') as info:
                w.export_game();self.assertIsNotNone(w.export_worker);self.assertFalse(w.centralWidget().isEnabled())
                loop=QEventLoop();w.export_worker.finished.connect(loop.quit);QTimer.singleShot(5000,loop.quit);loop.exec();app.processEvents()
                self.assertIsNone(w.export_worker);self.assertFalse(errors);self.assertTrue(w.centralWidget().isEnabled())
                info.assert_called_once();self.assertTrue((destination/'saekano-export.json').is_file())
        finally:
            if w.export_worker is not None:w.export_worker.requestInterruption();w.export_worker.wait(5000);app.processEvents()
            self.p.saved_revision=self.p.revision;w.close();app.processEvents()


if __name__=='__main__':unittest.main()
