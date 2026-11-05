"""Documentation coverage and read-only UI checks, not an engine replay suite."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
import json
from editor.engine import Session,ROOT
from editor.opcodes import CATALOG,ENGINE,markdown


class OpcodeReferenceChecks(unittest.TestCase):
    def test_catalog_scope_sources_and_conditional_documentation(self):
        names=json.loads((ROOT/'editor/opcode_names.json').read_text(encoding='utf-8'))
        self.assertEqual(set(CATALOG),{int(k,16) for k in names})
        self.assertEqual(sum(o.used for o in CATALOG.values()),55)
        for op in CATALOG.values():
            for text in (op.name,op.behavior,op.wire,op.lifecycle,op.preview):self.assertTrue(text)
            for source in op.sources:self.assertIsInstance(source,str);self.assertTrue(source)
            self.assertEqual(len([p.key for p in op.fields]),len({p.key for p in op.fields}))
            for p in op.fields:self.assertTrue(p.type);self.assertTrue(p.meaning)
        self.assertIn('selector-specific',CATALOG[0x438].wire)
        self.assertIn('Intentional expected-behavior correction',CATALOG[0x202].rules)
        self.assertIn('not used',markdown(CATALOG[0x2bd]))

    @unittest.skipUnless((ROOT.parent/'GAMEFILE/USRDIR/resource.dat').is_file(),'Local game data required')
    def test_actual_used_types_and_decoded_field_roots(self):
        b=Session();scripts=b.call('open',path=str(ROOT.parent/'GAMEFILE/USRDIR'))['scripts']
        used={int(op) for s in scripts for op in s['opcodes']}
        self.assertEqual(used,{o.code for o in CATALOG.values() if o.used})
        remaining=set(used)
        # Greedy representative files: inspect once per needed family, not a
        # scene-by-scene run or a playback regression campaign.
        while remaining:
            s=max(scripts,key=lambda s:len(remaining & {int(op) for op in s['opcodes']}))
            commands=b.call('script',id=s['id'])['commands']
            for c in commands:
                if c['opcode'] not in remaining:continue
                self.assertNotIn('decode_error',c['args'])
                roots={p.key.split('[')[0].split('.')[0] for p in CATALOG[c['opcode']].fields}
                derived={'duration'} if c['opcode']==0x65 else set()
                self.assertFalse(set(c['args'])-roots-derived,(hex(c['opcode']),set(c['args'])-roots))
                remaining.remove(c['opcode'])

    def test_browser_and_selected_help_do_not_execute(self):
        from PySide6.QtWidgets import QApplication
        from editor.opcodeview import OpcodeReference,help_markdown
        app=QApplication.instance() or QApplication([]);panel=OpcodeReference()
        command={'index':10,'opcode':0x202,'args':{'character':3},'offset':42,'size':10}
        panel.show_command(command)
        self.assertEqual(panel.code,0x202)
        self.assertIn('overread',panel.document.toPlainText())
        self.assertIn('Selected instance',panel.document.toPlainText())
        self.assertNotIn('Implementation sources',panel.document.toPlainText())
        self.assertNotIn('.cpp',panel.document.toPlainText())
        self.assertNotIn(str(ENGINE),help_markdown(command))
        self.assertNotIn('Wire order',panel.document.toPlainText())
        self.assertNotIn('```json',help_markdown(command))
        panel.technical.setChecked(True)
        self.assertIn('Wire order',panel.document.toPlainText())
        self.assertIn('"character": 3',panel.document.toPlainText())
        self.assertNotIn('.cpp',panel.document.toPlainText())
        panel.technical.setChecked(False)
        self.assertIn('Add, edit, replace and delete',markdown(CATALOG[0x64]))
        panel.follow.setChecked(False);panel.search.setText('live2d')
        shown=[panel.list.item(i) for i in range(panel.list.count()) if not panel.list.item(i).isHidden()]
        self.assertTrue(any('0438' in item.text() for item in shown))
        panel.list.setCurrentItem(next(item for item in shown if '0438' in item.text()))
        self.assertIn('selector',panel.document.toPlainText().lower())
        self.assertNotIn('Selected instance',panel.document.toPlainText())
        self.assertIn('Unknown opcode',help_markdown(dict(index=0,opcode=0xffff,args={})))
        panel.show();app.processEvents();self.assertFalse(panel.grab().isNull());panel.close()


if __name__=='__main__':unittest.main()
