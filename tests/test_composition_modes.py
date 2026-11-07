"""Focused mode UI checks without original assets or personal state."""
import unittest
from PySide6.QtGui import QImage, QColor
from editor.composition import Composition, Layer
from editor.compositionrender import render_composition
from editor.compositionmodes import description_lines, approach_topics,profile_environment


def profile_environment_fixture(columns=18):
    """Synthetic profile schema with strings on both sides of its scalar setting."""
    import struct
    from editor.scriptcodec import string
    z=lambda n:bytes(n)
    u=lambda n:struct.pack('<I',n)
    f=lambda n:struct.pack('<f',n)
    sp=z(36);empty=u(0)
    return b''.join((z(15),u(0),sp*3,u(0),sp*4,z(8),sp*2,z(4),sp*4,sp,empty,
        sp,z(16),sp,sp*2,z(16),sp*4,z(32),sp,empty,sp,empty,z(8),f(.9),z(12),u(0),
        u(3),z(24),f(.7),u(columns),sp,z(36),u(0),z(8),string('Before'),empty,string('Other'),z(4),sp,
        empty,empty,empty,string('Format'),sp,empty,u(0),z(8),u(0),sp,z(8),u(100),f(1),
        string('Confirm'),z(32),sp*2,u(0),f(0),empty))


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

    def test_profile_tip_pixels_counts_and_hard_breaks(self):
        from editor.uifit import wrap_tip
        e=profile_environment(profile_environment_fixture());self.assertEqual(e['columns'],18)
        p=wrap_tip('A hostess plots her rise. Wildly misleading epic.','/',36,324,18)
        self.assertEqual(p['lines'],['A hostess plots her rise. Wildly','misleading epic.'])
        self.assertTrue(all(n<=324 for n in p['line_widths']))
        self.assertEqual(wrap_tip('One/Two','/',36,324,18)['lines'],['One','Two'])
        self.assertEqual(wrap_tip('One/Two','/',36,324,18,reflow=True)['lines'],['One Two'])
        mixed=wrap_tip('日本語 abc 日本語 abc 日本語 abc','/',36,180,18)
        self.assertTrue(all(n<=180 for n in mixed['line_widths']))
        with self.assertRaisesRegex(ValueError,'three'):wrap_tip('word '*100,'/',36,324,18)


if __name__ == '__main__': unittest.main()
