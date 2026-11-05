"""Lossless GXT and combined texture/script/font export, synthetic fixtures only."""
import gzip
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from editor.archive import Archive
from editor.engine import ROOT
from editor.fontpatch import pack as font_pack, sections
from editor.gameexport import prepare_archives, export_game, ExportError, ExportCancelled
from editor.gxtwriter import encode_gxt
from editor.imageassets import build_catalog
from editor.imagecodec import decode_gxt, inspect_gxt, ImageError, ImageCancelled
from editor.packing import Member, pack_members, member, repack, payload
from editor.seekwriter import relocate
from editor.textureassets import encode_png
from editor.textureexport import patch_tree, changed_paths, prepare_textures
from test_game_export import source_fixture, seekmap
from test_image_assets import gxt


def rgba_image(w, h, opaque=False):
    pixels = b''.join(bytes((i % 251, (i * 5) % 251, 177, 255 if opaque else (0, 1, 128, 255)[i % 4])) for i in range(w * h))
    return QImage(pixels, w, h, w * 4, QImage.Format_RGBA8888).copy()


class TextureExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_gxt_lossless_all_original_layouts_and_constraints(self):
        for w, h, raw, swizzled, opaque in ((3, 2, False, False, False), (4, 2, False, True, False),
                (2, 4, False, True, False), (3, 2, True, False, False), (4, 2, True, True, False),
                (3, 2, False, False, True)):
            with self.subTest(w=w, h=h, raw=raw, swizzled=swizzled, opaque=opaque):
                original = gxt(w, h, rgba=raw, swizzled=swizzled, opaque=opaque) + b'TAIL untouched'
                image = rgba_image(w, h, opaque); encoded = encode_gxt(original, image)
                decoded = decode_gxt(encoded)
                self.assertEqual(bytes(decoded.constBits()), bytes(image.constBits()))
                self.assertEqual(encoded[:64], original[:64]); self.assertEqual(len(encoded), len(original))
                self.assertTrue(encoded.endswith(b'TAIL untouched'))
                info = inspect_gxt(original); bpp = 4 if raw else 1
                if not swizzled:
                    for y in range(h):
                        start = info.pixel_offset + (y * info.stride + w) * bpp
                        end = info.pixel_offset + (y + 1) * info.stride * bpp
                        self.assertEqual(encoded[start:end], original[start:end])
                self.assertEqual(encode_gxt(original, decode_gxt(original)), original)
                with self.assertRaises(ImageCancelled): encode_gxt(original, image, lambda: True)
        # Palette alignment gap is storage, not another palette or pixel row.
        original = bytearray(gxt()); info = inspect_gxt(original)
        gap = b'Z' * ((-info.palette_offset) % 64)
        original[info.palette_offset:info.palette_offset] = gap
        struct.pack_into('<I', original, 16, struct.unpack_from('<I', original, 16)[0] + len(gap))
        result = encode_gxt(original, rgba_image(3, 2))
        self.assertEqual(result[info.palette_offset:info.palette_offset + len(gap)], gap)
        with self.assertRaisesRegex(ImageError, 'dimensions'): encode_gxt(gxt(), rgba_image(2, 2))
        with self.assertRaisesRegex(ImageError, 'transparency'): encode_gxt(gxt(opaque=True), rgba_image(3, 2))
        with self.assertRaisesRegex(ImageError, 'exceeds256'): encode_gxt(gxt(257, 1, pixels=bytes(264)), rgba_image(257, 1))

    def fixture(self, root):
        p, first, resource = source_fixture(root)
        tex = gxt(); leaf = lambda name: Member(name, 1, gzip.compress(tex, mtime=0))
        bank = pack_members([leaf(b'one.gxt '), leaf(b'two.gxt '), Member(b'keep ', 0, b'untouched', b'untouched PHYSICAL')])
        compressed_bundle = pack_members([Member(b'pose.dat ', 0, gzip.compress(bank, mtime=0))])
        resource = repack(Archive(resource), {0:bank, 1:compressed_bundle})
        first = repack(Archive(first), {1:bank, 5:gzip.compress(seekmap(resource), mtime=0)})
        (root / 'first.dat').write_bytes(first); (root / 'resource.dat').write_bytes(resource)
        glyph = struct.pack('<4H2B', ord('A'), 0, 0, 0, 2, 2)
        original_font = font_pack([tex, glyph, struct.pack('<I', 4) + b'\xff\xfeA\0'])
        (root / 'Font.gsf').write_bytes(original_font)
        catalog = build_catalog(root)
        for key in ('resource.dat:0/0', 'resource.dat:0/1', 'resource.dat:1/0/1', 'first.dat:1/0', 'Font.gsf:0'):
            p.set_texture(key, encode_png(rgba_image(3, 2)), catalog)
        return p, catalog, first, resource, original_font

    def test_combined_textures_scripts_font_seek_and_separate_copy(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.local') as tmp:
            parent = Path(tmp); root = parent / 'original'
            p, catalog, first, resource, original_font = self.fixture(root)
            # A generated-font asset appends an atlas/records; original atlas edit
            # must survive alongside it rather than replacing that generated font.
            original_parts = sections(original_font)
            generated = font_pack(original_parts[:-2] + [gxt(8, 2), original_parts[-2], original_parts[-1]])
            sha = lambda b: hashlib.sha256(b).hexdigest()
            p.font_asset = dict(data_hex=generated.hex(), manifest=dict(format='saekano-proportional-font',version=1,
                source_sha256=sha(original_font),font_sha256=sha(generated)))
            command = next(c for c in p.scripts[0].commands if c.opcode == 0x64)
            args = dict(command.args); args['text'] = 'A longer translated line'; p.replace(0, command.uid, command.opcode, args)
            self.assertFalse(p.validate())
            destination = parent / 'patched'; report = export_game(p, destination)
            self.assertEqual(report['changed_textures'], 5); self.assertEqual(len(report['changed_scripts']), 1)
            output = build_catalog(destination)
            expected_image = rgba_image(3, 2)
            for identity in p.texture_assets:
                image = output.decode(identity)
                self.assertEqual(bytes(image.constBits()), bytes(expected_image.constBits()))
            new_resource = (destination / 'resource.dat').read_bytes()
            new_first = Archive((destination / 'first.dat').read_bytes())
            textures, _, _ = prepare_textures(p.texture_assets, root, catalog=catalog)
            paths = changed_paths(textures['resource.dat']) | {(), (4,), (4, 0), (4, 0, 0), (4, 0, 0, 0)}
            seek = new_first.read(5, gzip=True)
            checked, _ = relocate(seek, new_resource, new_resource, paths); self.assertEqual(checked, seek)
            untouched = lambda data: payload(Archive(Archive(data).read(0)), 2, True)
            self.assertEqual(bytes(untouched(new_resource)), bytes(untouched(resource)))
            font_parts = sections((destination / 'Font.gsf').read_bytes())
            self.assertEqual(font_parts[1:], sections(generated)[1:])
            self.assertEqual((root / 'Font.gsf').read_bytes(), original_font)
            self.assertEqual((root / 'first.dat').read_bytes(), first); self.assertEqual((root / 'resource.dat').read_bytes(), resource)
            self.assertEqual((destination / 'voice.awb').read_bytes(), b'original audio')
            with self.assertRaisesRegex(ExportError, 'empty'): export_game(p, destination)

    def test_texture_only_export_and_preflight_fail_before_publication(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.local') as tmp:
            parent = Path(tmp); root = parent / 'original'
            p, catalog, first, resource, _ = self.fixture(root)
            prepared = prepare_archives(p)
            self.assertEqual(prepared['report']['changed_scripts'], [])
            self.assertNotEqual(prepared['first'], first); self.assertNotEqual(prepared['resource'], resource)
            self.assertEqual(Archive(prepared['first']).read(4), Archive(first).read(4))
            # Authoring can keep >256 colors, but game export must refuse it.
            (root / 'extra.gxt').write_bytes(gxt(257, 1, pixels=bytes(264))); catalog = build_catalog(root)
            p.set_texture('extra.gxt:', encode_png(rgba_image(257, 1)), catalog)
            dest = parent / 'refused'
            with self.assertRaisesRegex(ExportError, 'extra.gxt:.*exceeds256'): export_game(p, dest)
            self.assertFalse(dest.exists()); self.assertFalse(list(parent.glob('.saekano-export-*')))
            p.remove_texture('extra.gxt:')
            cancelled = False
            def progress(message):
                nonlocal cancelled
                if message.startswith('Encoding texture'): cancelled = True
            with self.assertRaises(ExportCancelled): export_game(p, dest, progress, lambda: cancelled)
            self.assertFalse(dest.exists())
            def mutate_source(message):
                if message.startswith('Exporting voice'):
                    path = root / 'Font.gsf'; path.write_bytes(path.read_bytes() + b'changed during copy')
            with self.assertRaisesRegex(ExportError, 'Source changed during export'): export_game(p, dest, mutate_source)
            self.assertFalse(dest.exists()); self.assertFalse(list(parent.glob('.saekano-export-*')))
            # Type2 reading is not permission to guess its native write semantics.
            special = pack_members([Member(b'bad.gxt', 2, gzip.compress(gxt(), mtime=0))])
            chain = [dict(container='GPDA', index=0)]
            with self.assertRaisesRegex(ImageError, 'kind'): patch_tree(special, [(chain, gxt())])


if __name__ == '__main__': unittest.main()
