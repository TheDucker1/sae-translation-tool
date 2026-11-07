"""Consequential Extras primitives only; no original assets/unlock state required."""
import unittest
from types import SimpleNamespace
from PySide6.QtGui import QImage, QColor
from editor.composition import Composition, Layer, walk_layers
from editor.compositionrender import render_composition
from editor.compositionextras import catalogue_rows, native_number, cg_catalogue


class ExtrasCompositionTests(unittest.TestCase):
    def test_native_token_rows_and_numeric_wrap(self):
        text = 'ON,"A, ""B""\r\nC",1\r\nNEXT,x\ny\r\n'
        self.assertEqual(list(catalogue_rows(text)), [['ON', 'A, "B"\r\nC', '1'], ['NEXT', 'x', 'y']])
        self.assertEqual(native_number('-1x2'), -12)
        self.assertEqual(native_number('4294967296'), 0)

    def test_catalogue_pads_category_boundaries_not_resource_ids(self):
        blob = b'\xff\xfe' + 'ON,First,0,5,0,3,0\r\nON,Second,0,7,0,8,2\r\n'.encode('utf-16-le')
        class Library:
            decoded = {}
            def member(self, source, route):
                self_route = (source, tuple(route))
                if self_route != ('resource.dat', (2, 0, 0, 0)): raise AssertionError(self_route)
                return blob
        result = cg_catalogue(Library(), SimpleNamespace(common={'columns': 1}))
        self.assertEqual(result['entries'][1]['thumbnail'], 8)
        self.assertEqual(result['entries'][1]['images'], [7])
        self.assertEqual(result['pages'][0], [[0] + [None] * 8])
        self.assertEqual(result['pages'][1], [])
        self.assertEqual(result['pages'][2], [[1] + [None] * 8])

    def test_target_multiply_includes_alpha_and_only_quad_coverage(self):
        base = QImage(2, 1, QImage.Format_RGBA8888)
        base.setPixelColor(0, 0, QColor(200, 100, 50, 255)); base.setPixelColor(1, 0, QColor(0, 0, 100, 255))
        mask = QImage(1, 1, QImage.Format_RGBA8888); mask.fill(QColor(128, 255, 0, 128))
        a = Layer('Target backdrop', asset='base', source=[0, 0, 2, 1], destination=[0, 0, 2, 1])
        b = Layer('Target multiply', asset='mask', source=[0, 0, 1, 1], destination=[0, 0, 1, 1], blend='multiply')
        target = Layer('Offscreen', kind='target', target='test', rgba=[0, 0, 0, 255], children=[a, b])
        display = Layer('Result', asset='@target:test', source=[0, 0, 2, 1], destination=[0, 0, 2, 1])
        composition = Composition('test', layers=[target, display], clear=(0, 0, 0, 0))
        image, issues = render_composition(composition, {'base': base, 'mask': mask})
        self.assertFalse(issues)
        pixel = image.pixelColor(0, 0).getRgb()
        for actual, expected in zip(pixel, (100, 100, 0, 128)): self.assertAlmostEqual(actual, expected, delta=1)
        self.assertEqual(image.pixelColor(1, 0).getRgb(), (0, 0, 100, 255))
        self.assertEqual([layer.name for layer in walk_layers(composition.layers)], ['Offscreen', 'Target backdrop', 'Target multiply', 'Result'])


if __name__ == '__main__': unittest.main()
