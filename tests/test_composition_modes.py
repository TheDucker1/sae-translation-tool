"""Focused mode UI checks without original assets or personal state."""
import unittest
from PySide6.QtGui import QImage, QColor
from editor.composition import Composition, Layer
from editor.compositionrender import render_composition
from editor.compositionmodes import description_lines, approach_topics


class ModeCompositionTests(unittest.TestCase):
    def test_stencil_uses_nonzero_alpha_not_luminance_or_opacity(self):
        mask = QImage(2, 1, QImage.Format_RGBA8888)
        mask.setPixelColor(0, 0, QColor(0, 0, 0, 1)); mask.setPixelColor(1, 0, QColor(255, 255, 255, 0))
        coverage = Layer('Coverage', asset='mask', source=[0, 0, 2, 1], destination=[0, 0, 2, 1])
        target = Layer('Stencil', kind='target', target='mask', rgba=[0] * 4, children=[coverage])
        content = Layer('Content', kind='solid', destination=[0, 0, 2, 1], rgba=[0, 255, 0, 255], mask='@target:mask')
        image, issues = render_composition(Composition('Test', layers=[target, content], clear=(255, 0, 0, 255)), {'mask': mask})
        self.assertFalse(issues)
        self.assertEqual(image.pixelColor(0, 0).getRgb(), (0, 255, 0, 255))
        self.assertEqual(image.pixelColor(1, 0).getRgb(), (255, 0, 0, 255))

    def test_native_description_rows_and_topic_capacity(self):
        self.assertEqual(description_lines('abcdefghij', '/', 3), ['abc', 'def', 'ghij'])
        self.assertEqual(description_lines('ab/cd', '/', 3), ['ab', 'cd'])
        with self.assertRaises(ValueError): description_lines('a/b/c/d', '/', 3)
        self.assertEqual(approach_topics(' Topic | First | Second '), [['Topic', 'First', 'Second']])
        with self.assertRaises(ValueError): approach_topics('Topic only')
        with self.assertRaises(ValueError): approach_topics('Topic | 1 | 2 | 3 | 4')


if __name__ == '__main__': unittest.main()
