"""PVF cache cells versus half-width drawing, without original font/game data."""
import struct
import unittest
from editor.pvfraster import PvfCells
from editor.composition import Composition,text_layer
from editor.compositionrender import FontConsumer,render_composition


class PvfPreview(unittest.TestCase):
    def test_cache_columns_and_duplicate_characters_keep_full_source_cells(self):
        head=bytearray(54);hhea=bytearray(36)
        struct.pack_into('>H',head,18,1024);struct.pack_into('>4h',head,36,0,-256,1024,768)
        struct.pack_into('>H',hhea,10,1024)
        cells=PvfCells(head,hhea,'ABCA')
        #26.6 cell advance35+21/64: successive columns are35,35,35,36
        # pixels before excluding the final column. Last duplicate replaces A.
        self.assertEqual(cells.widths,{'A':35,'B':34,'C':34})
        self.assertEqual((cells.raster_width,cells.baseline,cells.height),(35,27,36))

    def test_half_width_destination_samples_full_cell_not_glyph_advance(self):
        class CellFont:
            cached={}
            def glyph(self,code):
                # Four pixels of ink in an eight-pixel cell, with a deliberately
                # colored extra border so sampling that border is observable.
                row=bytes((255,255,255,255))*4+bytes((0,0,0,0))*4+bytes((255,0,0,255))
                return dict(width=9,height=3,source=[0,0,8,2],bitmap=False,rgba=(row*2+bytes(9*4)).hex())
        font=CellFont();layer=text_layer('Latin','AAあ',[0,0],8,[255]*4,font)
        self.assertEqual([g['rect'] for g in layer.glyphs],[[0,0,4,8],[4,0,4,8],[8,0,8,8]])
        image,issues=render_composition(Composition('Cells',layers=[layer],clear=(0,0,0,255)),{},FontConsumer(font))
        self.assertFalse(issues)
        # ASCII ink is compressed to two pixels; full-width Japanese retains4.
        self.assertEqual([image.pixelColor(x,3).red() for x in range(4)],[255,255,0,0])
        self.assertEqual([image.pixelColor(x,3).red() for x in range(8,16)],[255,255,255,255,0,0,0,0])


if __name__=='__main__':unittest.main()
