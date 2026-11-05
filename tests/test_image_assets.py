"""Small synthetic checks. No original game data or private inventory required."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from editor.imagecodec import inspect_gxt, decode_gxt, ImageError, ImageCancelled
from editor.imageassets import build_catalog, extract_images
from editor.packing import Member, pack_members


def gxt(width=3, height=2, *, rgba=False, swizzled=False, opaque=False, pixels=None):
    stride = width if swizzled else (width + 7) & ~7
    count = stride * height
    if pixels is None:
        pixels = (bytes((0, 0, 255, 90)) * count if rgba else bytes(range(count)))
    palette = b'' if rgba else b''.join(bytes((i, 0, 255 - i, 20 + i % 200)) for i in range(256))
    header = bytearray(64)
    struct.pack_into('<4s7I', header, 0, b'GXT\0', 0x10000003, 1, 64,
                     len(pixels) + len(palette), 0, 0 if rgba else 1, 0)
    struct.pack_into('<6IHHI', header, 32, 64, len(pixels), 0, 0,
                     0 if swizzled else 0x60000000,
                     0x0c001000 if rgba else 0x95005000 if opaque else 0x95001000,
                     width, height, 1)
    return bytes(header) + pixels + palette


class ImageAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pixels_stride_alpha_and_rectangular_swizzle(self):
        blob = gxt()
        image = decode_gxt(blob + b'archive padding')
        self.assertEqual(image.pixelColor(2, 1).getRgb(), (245, 0, 10, 30))
        self.assertEqual(decode_gxt(gxt(opaque=True)).pixelColor(2, 1).alpha(), 255)
        self.assertEqual(decode_gxt(gxt(rgba=True)).pixelColor(0, 1).getRgb(), (255, 0, 0, 90))
        # A hand-ordered 4x2 Morton stream maps rows to [0,2,4,6], [1,3,5,7].
        swizzled = decode_gxt(gxt(4, 2, swizzled=True, pixels=bytes(range(8))))
        self.assertEqual([[swizzled.pixelColor(x, y).blue() for x in range(4)] for y in range(2)],
                         [[0, 2, 4, 6], [1, 3, 5, 7]])
        tall = decode_gxt(gxt(2, 4, swizzled=True, pixels=bytes(range(8))))
        self.assertEqual([[tall.pixelColor(x, y).blue() for x in range(2)] for y in range(4)],
                         [[0, 2], [1, 3], [4, 6], [5, 7]])
        rgba = decode_gxt(gxt(4, 2, rgba=True, swizzled=True,
                              pixels=b''.join(bytes((i, 0, 100, 255)) for i in range(8))))
        self.assertEqual(rgba.pixelColor(3, 1).getRgb(), (100, 0, 7, 255))
        bad = bytearray(blob); struct.pack_into('<I', bad, 52, 0x1234)
        with self.assertRaisesRegex(ImageError, 'format'): inspect_gxt(bad)
        with self.assertRaises(ImageCancelled): decode_gxt(blob, lambda: True)

    def fixture(self, root):
        texture = gxt()
        compressed = gzip.compress(texture, mtime=0)
        nested = pack_members([Member(b'ui.gxt ', 1, compressed),
                               Member(b'unknown.gxt', 0, b'unknown format')])
        # Kind0 gzip (character archives), and type2 whose physical gzip extends
        # beyond its logical size. These cannot be read as ordinary raw members.
        archive = pack_members([Member(b'poses.dat', 0, gzip.compress(nested)),
                                Member(b'special.gxt', 2, compressed[:10], compressed)])
        (root / 'resource.dat').write_bytes(archive)
        return texture, archive

    def test_inventory_provenance_and_transactional_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory); root = parent / 'USRDIR'; root.mkdir()
            texture, archive = self.fixture(root)
            source_hash = hashlib.sha256(archive).hexdigest()
            c = build_catalog(root)
            self.assertEqual(len(c.assets), 3)
            self.assertEqual(c.assets[0].chain[0]['compression'], 'gzip')
            self.assertEqual(c.assets[0].chain[1]['offset_space'], 'decoded parent container')
            self.assertEqual(c.assets[0].name, 'ui.gxt ')
            self.assertEqual(c.assets[1].status, 'Unsupported / invalid')
            self.assertEqual(c.read(c.assets[2].id), texture)
            result = extract_images(c, [c.assets[0].id, c.assets[2].id], parent / 'images')
            manifest = json.loads((Path(result['path']) / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(len(manifest['images']), 2)
            first = manifest['images'][0]
            self.assertEqual((parent / 'images' / first['files']['raw']).read_bytes(), texture)
            self.assertTrue((parent / 'images' / first['files']['png']).is_file())
            with self.assertRaisesRegex(ImageError, 'empty'): extract_images(c, [c.assets[0].id], parent / 'images')
            with self.assertRaisesRegex(ImageError, 'separate'): extract_images(c, [c.assets[0].id], root / 'extracted')
            with self.assertRaises(ImageCancelled): extract_images(c, [c.assets[0].id], parent / 'cancelled', cancelled=lambda: True)
            with self.assertRaises(ImageError): extract_images(c, [c.assets[0].id, c.assets[1].id], parent / 'bad')
            self.assertFalse((parent / 'cancelled').exists()); self.assertFalse((parent / 'bad').exists())
            self.assertFalse(list(parent.glob('.saekano-images-*')))
            self.assertEqual(hashlib.sha256((root / 'resource.dat').read_bytes()).hexdigest(), source_hash)
            (root / 'resource.dat').write_bytes(archive + b'changed')
            with self.assertRaisesRegex(ImageError, 'changed'): c.read(c.assets[0].id)

    def test_font_regions_and_original_script_uses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            texture = gxt()
            glyph = struct.pack('<4H2B', ord('A'), 0, 0, 0, 2, 2)
            charset = struct.pack('<I', 4) + b'\xff\xfeA\0'
            at = 40
            header = struct.pack('<4sIII', b'FONT', 0, 3, at + len(texture) + len(glyph) + len(charset))
            header += struct.pack('<6I', at, len(texture), at + len(texture), len(glyph), at + len(texture) + len(glyph), len(charset))
            (root / 'Font.gsf').write_bytes(header + texture + glyph + charset)
            bank = pack_members([Member(b'bg.gxt', 0, texture)])
            (root / 'resource.dat').write_bytes(pack_members([Member(None, 0, b'') for _ in range(5)] + [Member(b'bg', 0, bank)]))
            descriptions = {12: dict(commands=[dict(index=6, opcode=0xcb, args=dict(category=0, texture='0')),
                                                dict(index=7, opcode=0xcb, args=dict(category=0, texture='?L1'))])}
            c = build_catalog(root, descriptions)
            self.assertEqual(c.by_id['Font.gsf:0'].regions[0]['label'], 'U+0041 A')
            self.assertEqual(c.by_id['resource.dat:5/0'].references[0]['command'], 6)
            self.assertEqual(c.dynamic_references[0]['command'], 7)

    def test_browser_selection_filter_and_source_invalidation(self):
        from editor.imageview import ImageBrowser
        def wait_idle(browser):
            deadline = time.monotonic() + 5
            while browser.job is not None and time.monotonic() < deadline:
                self.app.processEvents(); time.sleep(.005)
            self.app.processEvents()
            self.assertIsNone(browser.job, 'Image worker did not finish')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self.fixture(root)
            other = root / 'other'; other.mkdir(); (other / 'single.gxt').write_bytes(gxt())
            browser = ImageBrowser()
            try:
                browser.set_source(root, {}); browser.show(); wait_idle(browser)
                self.assertEqual(browser.model.rowCount(), 4)
                browser.search.setText('special'); self.app.processEvents()
                self.assertEqual(browser.proxy.rowCount(), 1)
                browser.table.selectRow(0); wait_idle(browser)
                self.assertIsNotNone(browser.canvas.image_item)
                browser.search.clear()
                browser.rebuild(); browser.set_source(other, {})
                wait_idle(browser)
                self.assertEqual([a.id for a in browser.catalog.assets], ['single.gxt:'])
                self.assertTrue(all(k == 'single.gxt:' for k in browser.cache))
            finally:
                browser.shutdown(); browser.close(); self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
