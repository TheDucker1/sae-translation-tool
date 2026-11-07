"""Small visual metadata/protocol contracts; no original data or private captures."""
import asyncio
import importlib.util
import os
from types import SimpleNamespace
import unittest
from typing import Any
from unittest.mock import patch

if importlib.util.find_spec('mcp') is None: raise unittest.SkipTest('Optional MCP dependencies required')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtGui import QGuiApplication, QImage, QColor
from mcp.server import MCPServer
from editor.composition import Composition, Layer
from editor.compositionstate import resolve_state
from editor.visualcontext import IMAGE_KEY, image_reply, layer_records, page_layers, VisualContext
from editor.mcp_server import tool_handler


class VisualMcpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_native_image_block_keeps_geometry_and_json_separate(self):
        image = QImage(100, 50, QImage.Format_RGBA8888); image.fill(QColor('red'))
        def get_picture() -> dict[str, Any]:
            return image_reply(image, dict(asset_id='synthetic:0'), 64, (10, 20))
        async def exercise():
            server = MCPServer('Synthetic visuals')
            server.add_tool(tool_handler(get_picture), structured_output=True)
            result = await server.call_tool('get_picture', {})
            self.assertEqual([block.type for block in result.content], ['text', 'image'])
            self.assertEqual(result.content[1].mime_type, 'image/png')
            self.assertNotIn(IMAGE_KEY, result.structured_content)
            self.assertEqual(result.structured_content['image']['source_region'], [10, 20, 100, 50])
            self.assertEqual(result.structured_content['image']['source_to_preview_scale'], [.64, .64])
            self.assertEqual(result.structured_content['image']['height'], 32)
        asyncio.run(exercise())

    def test_layer_passes_text_and_glyph_paging(self):
        label = Layer('Label', kind='text', text='AB', size=20, destination=[30, 40, 40, 20],
            glyphs=[dict(code=65, rect=[30, 40, 20, 20]), dict(code=66, rect=[50, 40, 20, 20], rgb=[0, 0, 255])])
        mask = Layer('Source', asset='synthetic:0', source=[8, 0, -8, 8], destination=[1, 2, 8, 8], clip=[0, 0, 5, 5])
        target = Layer('Pass', kind='target', target='test', children=[mask, label])
        display = Layer('Composed', asset='@target:test', source=[0, 0, 960, 544], destination=[0, 0, 960, 544], mask='@target:coverage')
        rows = layer_records(Composition('Synthetic', layers=[target, display]), SimpleNamespace(by_id={}))
        self.assertEqual(rows[1]['pass_id'], '@target:test')
        self.assertEqual(rows[1]['parent_id'], rows[0]['layer_id'])
        self.assertEqual(rows[2]['draw_order'], 1)
        self.assertEqual(rows[2]['text'], 'AB')
        self.assertEqual(len(rows[2]['color_spans']), 2)
        page = page_layers(rows, 1, 2)
        self.assertEqual(page['next_start'], 3); self.assertNotIn('glyphs', page['layers'][1])
        detailed = page_layers(rows, 2, 1, True)['layers'][0]
        self.assertEqual(detailed['glyphs'][1]['rect'], [50, 40, 20, 20])
        self.assertTrue(rows[3]['generated']); self.assertEqual(rows[3]['mask_target'], '@target:coverage')
        context = VisualContext(); context.catalog_revision = 'catalog'
        context.scenes['sample'] = (dict(project_revision='project'), rows)
        text_page = context.layers('sample', kind='text')
        self.assertEqual(text_page['total_scene_layers'], 4); self.assertEqual(text_page['total_layers'], 1)
        self.assertEqual(text_page['layers'][0]['layer_id'], rows[2]['layer_id'])

    def test_state_types_bounds_and_stale_snapshot_rejection(self):
        with self.assertRaisesRegex(ValueError, 'integer'): resolve_state(None, 'message', dict(opacity=True))
        with self.assertRaisesRegex(ValueError, 'Unknown scene parameter'): resolve_state(None, 'message', dict(pretend_state=1))
        with self.assertRaisesRegex(ValueError, 'outside'): resolve_state(None, 'message', dict(speaker=-2))
        with patch('editor.compositionstate.extras_limits', return_value=dict(selected=3, first=0)):
            with self.assertRaisesRegex(ValueError, 'outside'): resolve_state(None, 'extras', dict(selected=4))
        with self.assertRaisesRegex(ValueError, 'stale'): VisualContext().layers('old-session')


if __name__ == '__main__': unittest.main()
