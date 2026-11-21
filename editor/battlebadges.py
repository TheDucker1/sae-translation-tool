"""Asset-only wordmark badges for the existing four-slot battle result."""
from hashlib import sha256
import math
from pathlib import Path
import struct

from .imagecodec import ImageError


SOURCE='env/env_tukkomi.dat'
GROUPS=(('draw','equal',20),('loss','lower',21),('win','upper',22))
DEFAULT_LABELS={'draw':'HÒA','loss':'THUA','win':'THẮNG'}
ASSETS=frozenset(f'resource.dat:16/{entry}' for _,_,entry in GROUPS)
INK={'draw':(12,26,39),'loss':(12,26,39),'win':(255,255,255)}


def ink_center(image):
    """Coverage-weighted center in source pixels, including antialiased accents."""
    width=image.width()
    alpha=bytes(image.constBits())[3::4]
    total=sum(alpha)
    if not total:raise ImageError('Battle result label has no visible ink')
    x=y=0
    for i,coverage in enumerate(alpha):
        x+=(i%width)*coverage;y+=(i//width)*coverage
    return x/total+.5,y/total+.5


def render_wordmark(label,width,height,scale):
    from PySide6.QtGui import QColor,QFont,QImage,QPainter,QPainterPath,QRawFont
    from .fontpatch import VIETNAMESE_FACE

    # A size in game pixels. The winner's native 1.4x scaling is applied later.
    for size in range(28,13,-1):
        font=QRawFont(str(VIETNAMESE_FACE),size/scale,QFont.PreferNoHinting)
        glyphs=font.glyphIndexesForString(label)
        if not font.isValid() or not glyphs or not all(glyphs):raise ImageError('The bundled font lacks a result-label glyph')
        path=QPainterPath();pen=0.0
        for index,advance in zip(glyphs,font.advancesForGlyphIndexes(glyphs)):
            glyph=font.pathForGlyph(index);glyph.translate(pen,0.0);path.addPath(glyph);pen+=advance.x()
        bounds=path.boundingRect()
        w,h=math.ceil(bounds.width())+4,math.ceil(bounds.height())+4
        if w*scale>width or h*scale>height:continue
        mask=QImage(w,h,QImage.Format_RGBA8888);mask.fill(0)
        sample=QPainter(mask);sample.setRenderHint(QPainter.Antialiasing)
        sample.translate(2-bounds.left(),2-bounds.top())
        sample.fillPath(path,QColor('white'));sample.end()
        mx,my=ink_center(mask)
        cx,cy=bounds.left()+mx-2,bounds.top()+my-2
        # A centered source crop becomes a centered native quad. Leave the same
        # safety margin at the furthest ink edge after optical placement.
        w=math.ceil(2*max(cx-bounds.left(),bounds.right()-cx))+4
        h=math.ceil(2*max(cy-bounds.top(),bounds.bottom()-cy))+4
        if w*scale<=width and h*scale<=height:break
    else:raise ImageError('Result label needs more room. Use a shorter wordmark.')
    return path,(cx,cy),w,h


def build(root,catalog,labels):
    from PySide6.QtGui import QColor,QImage,QPainter
    from .compositionbattle import battle_environment
    from .gxtwriter import encode_gxt
    from .textureassets import encode_png,make_replacement
    from unicodedata import normalize

    if set(labels)!=set(DEFAULT_LABELS):raise ImageError('Supply draw, loss and win labels')
    source=(Path(root)/SOURCE).read_bytes()
    layout=battle_environment(source)
    record=dict(source_sha256=sha256(source).hexdigest(),labels={},crops={},png_hashes={})
    textures={}
    for kind,group,entry in GROUPS:
        name=normalize('NFC',labels[kind]).strip()
        if not name or len(name)>24 or any(not (c.isalnum() or c in ' !?-.') for c in name):
            raise ImageError('Use a short single-line result label')
        identity=f'resource.dat:16/{entry}'
        asset=catalog.by_id[identity]
        scale=layout['upper_scale'] if group=='upper' else 1.0
        if not 0<scale<=4:raise ImageError('Unsupported battle wordmark scale')
        frame=layout['result_sprites'][3 if group=='lower' else 1]
        path,(cx,cy),w,h=render_wordmark(name,min(frame['w']-6,(asset.width-2)*scale),
                                       min(frame['h']-6,(asset.height-2)*scale),scale)
        image=QImage(asset.width,asset.height,QImage.Format_RGBA8888);image.fill(0)
        painter=QPainter(image);painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(1+w/2-cx,1+h/2-cy)
        painter.fillPath(path,QColor(*INK[kind]));painter.end()
        encode_gxt(catalog.read(identity),image)  # Preflight original palette and storage.
        texture=make_replacement(catalog,identity,encode_png(image))
        record['labels'][kind]=name
        record['crops'][kind]=[1,1,w,h]
        record['png_hashes'][identity]=texture['png_sha256']
        textures[identity]=texture
    patch_environment(source,record)
    return record,textures


def validate(root,record,textures):
    if record is None:return
    data=(Path(root)/SOURCE).read_bytes()
    if not isinstance(record,dict) or set(record)!={'source_sha256','labels','crops','png_hashes'}:
        raise ImageError('Invalid battle result badge record')
    if sha256(data).hexdigest()!=record['source_sha256']:
        raise ImageError('Battle result badge layout belongs to different source data')
    if any(not isinstance(record[key],dict) for key in ('png_hashes','labels','crops')):
        raise ImageError('Invalid battle result badge record')
    if set(record['png_hashes'])!=ASSETS or set(record['labels'])!=set(DEFAULT_LABELS) or set(record['crops'])!=set(DEFAULT_LABELS):
        raise ImageError('Battle result badges require all three matching wordmark textures')
    for kind,_,entry in GROUPS:
        key=f'resource.dat:16/{entry}';texture=textures.get(key)
        if not texture or texture['png_sha256']!=record['png_hashes'][key]:
            raise ImageError('Battle result badge texture no longer matches its layout')
        crop=record['crops'][kind]
        if (not isinstance(crop,list) or len(crop)!=4 or any(type(v) is not int for v in crop)
                or crop[:2]!=[1,1] or not 1<=crop[2]<texture['width'] or not 1<=crop[3]<texture['height']):
            raise ImageError('Battle result badge crop exceeds its texture')
    patch_environment(data,record)


def patch_environment(data,record):
    """Patch only fixed-size geometry cells, even after variable UI text edits."""
    from .compositionbattle import battle_environment
    offsets={}
    layout=battle_environment(data,result_offsets=offsets)
    output=bytearray(data)
    # The original shared cyan tint blends into the draw disk. Preserve each
    # wordmark's own contrasting ink through the native texture multiply.
    struct.pack_into('<I',output,offsets['glyph_color'],0xffffffff)
    for kind,group,_ in GROUPS:
        positions=layout[group+'_positions'];rectangles=layout[group+'_rectangles']
        if len(positions)!=4 or len(rectangles)!=4:
            raise ImageError('The source does not have the verified four-slot result tables')
        center=[sum(point[axis] for point in positions)//4 for axis in range(2)]
        start=offsets[group+'_positions']
        # Reveal the wordmark at the first result sound. The remaining native
        # tweens still advance, with their decorations outside the viewport.
        struct.pack_into('<ii',output,start,*center)
        for i in range(1,4):struct.pack_into('<ii',output,start+8*i,-2048,-2048)
        struct.pack_into('<4i',output,offsets[group+'_rectangles'],*record['crops'][kind])
    return bytes(output)
