"""Focused synthetic composition checks: sampling, geometry/blend and source guards."""
from pathlib import Path
import tempfile
import unittest
from PySide6.QtGui import QImage, QColor
from editor.composition import Layer, Composition, blit, text_layer, EnvironmentLibrary
from editor.compositionrender import clamped_crop, render_composition, FontConsumer
from editor.imagecodec import ImageError


class CompositionTests(unittest.TestCase):
    def pixels(self):
        image = QImage(2, 1, QImage.Format_RGBA8888)
        image.setPixelColor(0, 0, QColor(200, 0, 0, 255))
        image.setPixelColor(1, 0, QColor(0, 0, 100, 255))
        return image

    def test_atlas_edge_clamp_and_flip(self):
        source = self.pixels()
        crop = clamped_crop(source, -1, 0, 4, 2)
        self.assertEqual([crop.pixelColor(i, 1).getRgb() for i in range(4)],
                         [(200, 0, 0, 255), (200, 0, 0, 255), (0, 0, 100, 255), (0, 0, 100, 255)])
        layout = Composition('flip', layers=[Layer('flipped', asset='x', source=[2, 0, -2, 1], destination=[0, 0, 2, 1])])
        image, issues = render_composition(layout, {'x': source})
        self.assertFalse(issues)
        self.assertEqual(image.pixelColor(0, 0).getRgb(), (0, 0, 100, 255))
        self.assertEqual(image.pixelColor(1, 0).getRgb(), (200, 0, 0, 255))

    def test_anchor_tint_blend_and_rotation(self):
        shape = dict(alignment=8, x=10, y=10, sx=0, sy=0, w=4, h=2, rgba=[255] * 4)
        layer = blit('anchor', 1, 3, shape, scale=.5)
        self.assertEqual(layer.destination, [8, 9, 2, 1])
        first = Layer('base', asset='x', source=[0, 0, 1, 1], destination=[2, 1, 1, 1], rgba=[128, 255, 255, 255])
        first.rotation = (90, 2, 2)
        layout = Composition('rotate', layers=[first])
        image, issues = render_composition(layout, {'x': self.pixels()})
        self.assertFalse(issues)
        self.assertEqual(image.pixelColor(2, 2).red(), 100)
        layout.layers.append(Layer('overlay', asset='x', source=[1, 0, 1, 1], destination=[2, 2, 1, 1], rgba=[255, 255, 255, 128]))
        image, _ = render_composition(layout, {'x': self.pixels()})
        self.assertAlmostEqual(image.pixelColor(2, 2).red(), 50, delta=1)
        self.assertAlmostEqual(image.pixelColor(2, 2).blue(), 50, delta=1)

    def test_layout_snapshot_detects_external_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / 'layout.dat'; path.write_bytes(b'initial')
            library = EnvironmentLibrary(root); self.assertEqual(library.read('layout.dat'), b'initial')
            path.write_bytes(b'external change')
            with self.assertRaisesRegex(ImageError, 'Layout source changed'): library.verify()

    def test_clipped_signed_source_and_cached_icon_natural_size(self):
        layer = Layer('flipped clipped row', asset='x', source=[2, 0, -2, 1], destination=[0, 0, 2, 1], clip=[1, 0, 1, 1])
        layout = Composition('mask', layers=[layer]); layout.clear = (5, 6, 7, 255)
        image, issues = render_composition(layout, {'x': self.pixels()})
        self.assertFalse(issues)
        self.assertEqual(image.pixelColor(0, 0).getRgb(), (5, 6, 7, 255))
        self.assertEqual(image.pixelColor(1, 0).getRgb(), (200, 0, 0, 255))
        class IconFont:
            cached = {'\ue000': (0, 0, 0, 2, 1)}
            bitmap_height = 1
            def glyph(self, code):
                return dict(width=2, height=1, bitmap=True, rgba='c80000ff000064ff')
        font = IconFont()
        layout.layers = [text_layer('Original-size help icon', '\ue000', [0, 0], 0, [255] * 4, font)]
        image, issues = render_composition(layout, {}, FontConsumer(font))
        self.assertFalse(issues)
        self.assertEqual(image.pixelColor(0, 0).getRgb(), (200, 0, 0, 255))
        self.assertEqual(image.pixelColor(1, 0).getRgb(), (0, 0, 100, 255))


if __name__ == '__main__': unittest.main()
