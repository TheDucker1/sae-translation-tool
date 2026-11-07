"""Consequential battle geometry; synthetic fixtures only."""
import unittest
from types import SimpleNamespace
from editor.composition import Composition
from editor.compositionbattle import widget_sprite, positioned_plain


class BattleCompositionTests(unittest.TestCase):
    def test_widget_anchors_before_base_scale_and_centered_pulse(self):
        shape = dict(parameter=0, alignment=4, x=0, y=0, sx=2, sy=3, w=8, h=4, rgba=[255] * 4)
        out = Composition('Test')
        layer = widget_sprite(out, 'Card', 4, shape, [10, 20], .5, 1., [128, 255, 64, 255])
        self.assertEqual(layer.destination, [4, 17, 8, 4])
        self.assertEqual(layer.source, [2, 3, 8, 4])
        self.assertEqual(shape['alignment'], 4)

    def test_text_centers_advance_extent_not_drawn_glyph_width(self):
        font = SimpleNamespace(utility=20, height=20, leading=0, cached={},
            format=SimpleNamespace(break_char='\n', prepare=lambda value, **kw: (value, [])),
            layout=lambda *args: [dict(code=65, x=0, y=0, index=0, line=0, advance=8),
                                  dict(code=66, x=8, y=0, index=1, line=0, advance=6)])
        layer = positioned_plain('Text', 'AB', 100, 70, 200, 1., [0, 0, 0, 255], font, offsets=[[1, 2], [3, 4]])
        # Logical width14 differs from the rendered10-pixel glyph rectangles.
        self.assertEqual(layer.destination[:2], [96, 74])
        self.assertEqual(layer.glyphs[1]['rect'][:2], [104, 74])


if __name__ == '__main__': unittest.main()
