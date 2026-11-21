"""Exercise the coupled native template, catalogue, font packing and preview."""
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from editor.choiceart import ChoiceAtlas
from editor.composition import Composition, EnvironmentLibrary
from editor.keywordnotice import KEYWORD_ENV, SCRIPT_ENV, TEMPLATE_FIELD, environment
from editor.scriptcodec import string
from editor.uitext import build_catalog, make_record, prepare
from editor.uitextcodec import keyword_text
from test_width_controls import font_fixture


class KeywordNoticeChecks(unittest.TestCase):
    def test_complete_notice_packs_across_the_runtime_format_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'env').mkdir()
            panel = struct.pack('<h8i', 0, 3, 664, 350, 1, 1, 328, 72, -1)
            empty = bytes(4)
            script = (bytes(3+16+34) + empty*2 + bytes(68) + empty + panel + bytes(20) +
                      string('「%ls」を取得') + struct.pack('<iif',18,15,.72) +
                      bytes(24) + empty + bytes(60) + string('')*4)
            names = bytes(3) + empty + struct.pack('<2i',2,111) + string('keyword') + struct.pack('<i',112) + string('story')
            (root/SCRIPT_ENV).write_bytes(script)
            (root/KEYWORD_ENV).write_bytes(names)
            catalog = build_catalog(root)
            first_name = KEYWORD_ENV + ':#s0'
            records = {TEMPLATE_FIELD:make_record(catalog,TEMPLATE_FIELD,'Đã nhận «%ls»'),
                       first_name:make_record(catalog,first_name,'Từ khóa')}
            font=font_fixture()
            font.pair_spacing=dict(pairs={},accents={},restore={})
            font.glyph_cache={}
            font.charset.update('≪≫')
            font.cached.update((c,(0,0,0,12,24)) for c in ' Đãậừó≪≫' + ''.join(font.charset))
            font.glyph=lambda code:dict(width=12,height=24,rgba='ffffffff'*12*24,bitmap=True)
            atlas=ChoiceAtlas(font)
            changes,_,_=prepare(records,root,catalog,font=font,pairing=font.pair_spacing,pack_label=atlas.encode)
            self.assertEqual(environment(changes[SCRIPT_ENV][0][1])['template'],'%ls')
            exported = dict(keyword_text(changes[KEYWORD_ENV][0][1]))
            self.assertEqual(list(exported),[111,112])
            self.assertTrue(all(wire in atlas.geometry for wire in exported.values()))
            self.assertEqual(catalog.fields[first_name]['contracts'][0]['scene']['state'],{'keyword':111})
            self.assertEqual(records[first_name]['text'],'Từ khóa')

            library=EnvironmentLibrary(root,ui_text_assets=records,ui_text_catalog=catalog,font=font,pairing=font.pair_spacing)
            with patch.object(library,'get',return_value={}), patch('editor.composition.message_layout',return_value=Composition('Preview')):
                preview=library.build('message',{'keyword':111},font)
            self.assertEqual(preview.layers[0].asset,'resource.dat:1/8')
            layer=preview.layers[-1]
            self.assertEqual(layer.text,'Đã nhận «Từ khóa»')
            self.assertEqual(layer.destination[:2],[682,353])
            self.assertEqual(len(layer.glyphs),len(exported[111]))
