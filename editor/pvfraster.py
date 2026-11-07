"""PVF precache cell geometry; Qt supplies outline coverage, not text advances."""
import struct


def f32(value):return struct.unpack('<f',struct.pack('<f',value))[0]


class PvfCells:
    def __init__(self,head,hhea,characters,nominal=36):
        if len(head)<54 or len(hhea)<36 or not 0<nominal<=255:raise ValueError('Invalid PVF font tables or nominal size')
        units=struct.unpack_from('>H',head,18)[0]
        _,ymin,_,ymax=struct.unpack_from('>4h',head,36)
        maximum=struct.unpack_from('>H',hhea,10)[0]
        if not units or not maximum or ymin>ymax:raise ValueError('Invalid authored font metrics')
        # Match float32 point sizing, FT_Set_Char_Size's26.6 truncation and
        # positive FT_MulDiv/FT_DivFix rounding at128dpi, without a native bridge.
        points=f32(f32(nominal*f32(12.15))/f32(22))
        char_size=int(f32(points*64));scaled=(char_size*128+36)//72
        scale=((scaled<<16)+units//2)//units
        mul=lambda value:((abs(value)*scale+0x8000)>>16)*(-1 if value<0 else 1)
        self.pixel_size=scaled/64
        self.baseline=max(0,(mul(ymax)+63)//64)
        self.height=self.baseline+max(0,(-mul(ymin)+63)//64)
        advance=mul(maximum);self.raster_width=max(0,advance//64)
        columns=max(1,900//nominal);self.widths={}
        for i,c in enumerate(characters):
            column=i%columns
            self.widths[c]=((column+1)*advance)//64-(column*advance)//64-1
        if not 0<self.height<=1024 or any(not 0<w<1024 for w in self.widths.values()):raise ValueError('PVF cache cell outside raster budget')

    def raster(self,font,character):
        from PySide6.QtCore import QPointF,QRectF
        from PySide6.QtGui import QImage,QPainter,QColor,QGlyphRun
        width=self.widths.get(character)
        if width is None:return {'missing':True}
        indices=font.glyphIndexesForString(character)
        if not indices or indices[0]==0:return {'missing':True}
        # Full cells are packed for Latin too. The destination half-width is a
        # later draw operation; using a glyph's hmtx width here doubles its ink.
        image=QImage(width+1,self.height+1,QImage.Format_RGBA8888);image.fill(0)
        run=QGlyphRun();run.setRawFont(font);run.setGlyphIndexes(indices);run.setPositions([QPointF(0,self.baseline)])
        painter=QPainter(image);painter.setClipRect(QRectF(0,0,self.raster_width,self.height))
        painter.setPen(QColor('white'));painter.drawGlyphRun(QPointF(0,0),run);painter.end()
        return dict(width=image.width(),height=image.height(),source=[0,0,width,self.height],
            rgba=bytes(image.constBits()).hex(),bitmap=False)
