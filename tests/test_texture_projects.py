"""Project-only PNG authoring checks using tiny synthetic GXT/PNG fixtures."""
import base64
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
import zlib

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtGui import QGuiApplication, QImage
from editor.document import Project
from editor.engine import ROOT
from editor.imageassets import build_catalog
from editor.textureassets import decode_png, png_bytes, write_png
from editor.composition import Composition, Layer
from editor.compositionrender import AssetResolver, TextureLoader, FontConsumer, render_composition
from editor.gameexport import export_game, ExportError
from tests.test_image_assets import gxt
from tests.test_document import fixture


def chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)


def png(width, height, pixels, depth=8):
    rows = b''.join(b'\0' + pixels[i * width * 4:(i + 1) * width * 4] for i in range(height))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, depth, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'tEXt', b'Note\0keep exactly') + chunk(b'IEND', b'')


class TextureProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.local'); self.folder = Path(self.temp.name)
        self.root = self.folder / 'original'; self.root.mkdir(); (self.root / 'texture.gxt').write_bytes(gxt(rgba=True))
        self.catalog = build_catalog(self.root); self.identity = self.catalog.assets[0].id
        self.project = fixture(); self.project.root = str(self.root)
        self.pixels = bytes((17, 36, 87, 0, 255, 7, 4, 1, 12, 35, 79, 128, 4, 5, 6, 255, 23, 68, 90, 255, 8, 9, 10, 255))
        self.png = png(3, 2, self.pixels)

    def tearDown(self): self.temp.cleanup()

    def test_exact_rgba_png_bytes_roundtrip_undo_and_separate_copy(self):
        image=decode_png(self.png);self.assertEqual(bytes(image.constBits()), self.pixels)
        p = self.project; key = p.scenario_key(); p.set_texture(self.identity, self.png, self.catalog)
        self.assertEqual(key, p.scenario_key()); self.assertEqual(png_bytes(p.texture_assets[self.identity]), self.png)
        p.undo(); self.assertFalse(p.texture_assets); p.redo()
        path = self.folder / 'project.saekano.json'; p.save(path)
        self.assertEqual(json.loads(path.read_text())['version'], 2)
        loaded = Project.load(path, p)
        self.assertEqual(png_bytes(loaded.texture_assets[self.identity]), self.png)
        image=decode_png(png_bytes(loaded.texture_assets[self.identity]));self.assertEqual(bytes(image.constBits()), self.pixels)
        copy_path = self.folder / 'copy.png'; write_png(copy_path, self.png, self.root)
        self.assertEqual(copy_path.read_bytes(), self.png)
        with self.assertRaises(FileExistsError): write_png(copy_path, self.png, self.root)
        with self.assertRaises(ValueError): write_png(self.root / 'forbidden.png', self.png, self.root)
        loaded.remove_texture(self.identity); loaded.save(path)
        self.assertEqual(json.loads(path.read_text())['version'], 1)

    def test_invalid_png_dimension_precision_and_source_fail_atomically(self):
        p = self.project; revision = p.revision
        for bad in (self.png[:-1] + b'X', png(2, 2, self.pixels[:16]), png(3, 2, self.pixels, depth=16)):
            with self.assertRaises(ValueError): p.set_texture(self.identity, bad, self.catalog)
            self.assertEqual(p.revision, revision); self.assertFalse(p.texture_assets); self.assertFalse(p.undo_stack)
        p.set_texture(self.identity, self.png, self.catalog); path = self.folder / 'saved.saekano.json'; p.save(path)
        data = json.loads(path.read_text()); data['texture_assets'][self.identity]['png_base64'] = base64.b64encode(b'bad').decode()
        broken = self.folder / 'broken.saekano.json'; broken.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'checksum'): Project.load(broken, p)
        original = self.root / 'texture.gxt'; changed = bytearray(original.read_bytes()); changed[-1] ^= 1; original.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, 'source'): Project.load(path, p)

    def test_shared_resolver_and_bitmap_glyph_cache_follow_replacement_changes(self):
        p = self.project; p.set_texture(self.identity, self.png, self.catalog); record = p.texture_assets[self.identity]
        image=AssetResolver(self.catalog, p.texture_assets).image(self.identity);self.assertEqual(bytes(image.constBits()), self.pixels)
        original = QImage(3, 2, QImage.Format_RGBA8888); original.fill(0xff00ff00)
        font = SimpleNamespace(cached={'A': (0, 0, 0, 3, 2)}, bitmap_height=2,
            glyph=lambda code: dict(width=3, height=2, rgba=bytes(original.constBits()).hex(), bitmap=True))
        consumer = FontConsumer(font); composition = Composition('Glyph', layers=[Layer('Text', kind='text',
            glyphs=[dict(code=65, rect=[0, 0, 3, 2])])], clear=(0, 0, 0, 0))
        resolver = AssetResolver(self.catalog, {'Font.gsf:0': record}); textures, errors = TextureLoader(resolver).load(composition)
        self.assertFalse(errors); image, issues = render_composition(composition, textures, consumer)
        self.assertFalse(issues); self.assertEqual(image.pixelColor(2, 1).getRgb(), (8, 9, 10, 255))
        image, issues = render_composition(composition, {}, consumer)
        self.assertFalse(issues); self.assertEqual(image.pixelColor(2, 1).getRgb(), (0, 255, 0, 255))

    def test_game_export_refuses_project_only_textures_before_writing(self):
        self.project.set_texture(self.identity, self.png, self.catalog); destination = self.folder / 'game-export'
        with self.assertRaisesRegex(ExportError, 'project-only'): export_game(self.project, destination)
        self.assertFalse(destination.exists())


if __name__ == '__main__': unittest.main()
