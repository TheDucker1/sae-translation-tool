"""Asset-only proportional dialogue glyphs through the existing GSF override."""
import argparse,hashlib,json,math,struct
from pathlib import Path
from .text import TextPresentation,font_atlas

GENERATOR_REVISION=4


def dialogue_width(ink_width,font,gap):
    """Record width whose native advance clears drawn ink by the requested gap."""
    pixels=int(font.utility*font.scale)
    if pixels<=0 or font.scale<=0:raise ValueError('Invalid dialogue font scale')
    target=math.ceil(ink_width*pixels/font.bitmap_height)+gap
    # Measurement first scales a nominal36 record at utility size and adds1,
    # then layout truncates after body scaling. Drawing instead uses bitmap24.
    for width in range(max(1,math.ceil(ink_width)),256):
        advance=int(int(1+width*font.utility/36)*font.scale)
        if advance>=target:return width
    raise ValueError('Dialogue glyph advance exceeds the GSF record width')


def sections(data):
    if data[:4]!=b'FONT' or len(data)<16:raise ValueError('Invalid GSF source')
    count,size=struct.unpack_from('<II',data,8)
    if size!=len(data) or not 2<=count<=258:raise ValueError('Invalid GSF extent')
    return [data[a:a+n] for a,n in (struct.unpack_from('<II',data,16+8*i) for i in range(count))]


def pack(parts):
    offset=16+8*len(parts);table=[]
    for part in parts:table.append(struct.pack('<II',offset,len(part)));offset+=len(part)
    return b'FONT'+struct.pack('<III',0,len(parts),offset)+b''.join(table)+b''.join(parts)


def p8_atlas(width,height,coverage):
    """Linear RGBA palette GXT, one texture, eight-pixel row alignment."""
    if width%8 or len(coverage)!=width*height:raise ValueError('Invalid atlas dimensions')
    palette=b''.join(bytes((255,255,255,a)) for a in range(256));size=len(coverage)+len(palette)
    header=struct.pack('<8I',0x00545847,0x10000003,1,64,size,0,1,0)
    texture=struct.pack('<8I',64,len(coverage),0,0,0x60000000,0x95001000,width|(height<<16),1)
    return header+texture+coverage+palette


def build(root):
    """Keep original atlas/records/charset and append a separate Latin atlas.

    Full-width aliases avoid PVF's half-width measurement factor. Source ink is
    optically cropped because the authored Latin hmtx itself is fixed-width.
    Record width is in nominal36 measurement units, image ink in bitmap24 units;
    transparent right padding reconciles existing measurement/draw scaling.
    Fixed-cursor ASCII records retain nominal36 measurement while their ink
    occupies a12px half-cell at bitmap24. The remaining pixels are transparent;
    sampling these directly avoids compressing the full PVF precache cell.
    """
    from PySide6.QtCore import QByteArray,QPointF
    from PySide6.QtGui import QRawFont,QFont,QImage,QPainter,QGlyphRun,QColor,QGuiApplication
    if QGuiApplication.instance() is None:raise ValueError('A Qt GUI application is required to rasterize the font asset')
    root=Path(root);original=(root/'Font.gsf').read_bytes();parts=sections(original)
    font=TextPresentation(root);height=font.bitmap_height;nominal=36
    if height!=24:raise ValueError('This generator requires the original24px GSF asset; do not stack font patches')
    raw=QRawFont();raw.loadFromData(QByteArray(font.font_data),22,QFont.PreferDefaultHinting)
    if not raw.isValid():raise ValueError('Cannot open the original TTC')
    codes=[(c,chr(ord(c)+0xfee0),False) for c in map(chr,range(33,127)) if c!='_']
    codes.extend((c,c,False) for c in '‘’“”…―')
    codes.extend((c,c,True) for c in map(chr,range(33,127)) if c not in font.cached)
    glyphs=[]
    for c,alias,fixed in codes:
        if alias in font.cached:raise ValueError('Source already has Latin bitmap overrides; use the original Font.gsf')
        try:
            if alias.encode('cp932').decode('cp932')!=alias:continue
        except UnicodeError:continue
        ids=raw.glyphIndexesForString(c)
        if not ids or not ids[0]:continue
        rect=raw.boundingRect(ids[0]);left=math.floor(rect.left());ink=math.ceil(rect.right())-left
        # Apostrophes sit inside words: normal letter padding makes them look
        # detached, and this Japanese font's apostrophe shape is unusually wide.
        # Tighten ink and outgoing advance without touching script spaces.
        single_quote=c in "'‘’";quote=c in "'\"‘’“”"
        ink_width=min(ink,11) if fixed else min(ink,3) if single_quote else ink
        width=nominal if fixed else dialogue_width(ink_width,font,0 if quote else 1)
        padding=(12-ink_width)/2 if fixed else 0
        glyphs.append(dict(character=ord(alias),source=c,index=ids[0],left=left,width=width,
                           ink_scale=ink_width/ink,padding=padding,fixed=fixed))
    baseline=math.ceil(max(-raw.boundingRect(g['index']).top() for g in glyphs))
    bottom=max(math.ceil(raw.boundingRect(g['index']).bottom()) for g in glyphs)
    if baseline+bottom>height:raise ValueError('Latin ink exceeds the original shared bitmap height')
    # Native ASCII-space measurement halves the recorded width. Its blank mask
    # has no ink, so a doubled metadata width supplies a normal short word space.
    glyphs.append(dict(character=32,source=' ',index=None,left=0,width=18,fixed=False))
    atlas_width=512;atlas_height=512;coverage=bytearray(atlas_width*atlas_height)
    records=[];x=1;y=1;report=[]
    for g in glyphs:
        width=g['width']
        if x+width+1>atlas_width:x=1;y+=height+2
        if y+height+1>atlas_height:raise ValueError('Latin atlas exceeded bounded capacity')
        image=QImage(width,height,QImage.Format_RGBA8888);image.fill(0)
        if g['index'] is not None:
            run=QGlyphRun();run.setRawFont(raw);run.setGlyphIndexes([g['index']]);run.setPositions([QPointF(-g['left'],baseline)])
            painter=QPainter(image);painter.setPen(QColor('white'));painter.translate(g['padding'],0);painter.scale(g['ink_scale'],1);painter.drawGlyphRun(QPointF(0,0),run);painter.end()
        pixels=bytes(image.constBits())
        for row in range(height):
            for col in range(width):coverage[(y+row)*atlas_width+x+col]=pixels[(row*width+col)*4+3]
        records.append(struct.pack('<4H2B',g['character'],len(parts)-2,x,y,width,height))
        report.append(dict(codepoint=g['character'],source=g['source'],record_width=width,atlas_rect=[x,y,width,height],fixed_cursor=g['fixed']))
        x+=width+2
    atlas=p8_atlas(atlas_width,atlas_height,bytes(coverage));font_atlas(atlas)
    output=pack(parts[:-2]+[atlas,parts[-2]+b''.join(records),parts[-1]])
    manifest=dict(format='saekano-proportional-font',version=1,generator_revision=GENERATOR_REVISION,source_sha256=hashlib.sha256(original).hexdigest(),
        font_sha256=hashlib.sha256(output).hexdigest(),font_file='Font.gsf',executable_changes=False,
        nominal=nominal,bitmap_height=height,glyphs=report,
        scope='Proportional dialogue aliases and readable fixed-cursor Latin bitmap cells from the same font face.',
        ui_bitmap_cells=True,ui_cell_ink_width=11,
        dialogue_spacing='native_scaled_ink_plus_gap',dialogue_gap_pixels=1,
        limitations=['Simple DrawString names/UI still use fixed cursor advances.',
                    'Use matching patched font metrics when rewrapping scripts.',
                    'ASCII spaces become shorter globally; Japanese glyph records and atlases are unchanged.',
                    'No kerning pairs or shaping; per-glyph optical spacing.'])
    return output,manifest


def make_asset(root):
    data,manifest=build(root)
    return dict(data_hex=data.hex(),manifest=manifest)


def validate_asset(asset,root):
    if asset is None:return
    if not isinstance(asset,dict) or set(asset)!={'data_hex','manifest'}:raise ValueError('Invalid font asset project record')
    data=bytes.fromhex(asset['data_hex']);manifest=asset['manifest']
    if (manifest.get('format')!='saekano-proportional-font' or manifest.get('version')!=1
            or hashlib.sha256(data).hexdigest()!=manifest.get('font_sha256')):raise ValueError('Font asset checksum/format mismatch')
    if hashlib.sha256((Path(root)/'Font.gsf').read_bytes()).hexdigest()!=manifest.get('source_sha256'):
        raise ValueError('Font asset belongs to a different source Font.gsf')
    original=sections((Path(root)/'Font.gsf').read_bytes());changed=sections(data)
    if changed[:-3]!=original[:-2] or not changed[-2].startswith(original[-2]) or changed[-1]!=original[-1]:
        raise ValueError('Font asset changed protected original glyphs/charset')
    font_atlas(changed[-3])


def effective_font(project,font):
    asset=getattr(project,'font_asset',None)
    original=getattr(font,'source_font',font)
    if asset is None:return original
    digest=asset['manifest']['font_sha256']
    if getattr(font,'asset_sha256',None)==digest:return font
    result=TextPresentation(project.root,font_asset=bytes.fromhex(asset['data_hex']));result.asset_sha256=digest
    result.source_font=original
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve();output=args.output.resolve()
    if output==source or output.is_relative_to(source) or source.is_relative_to(output):parser.error('Output must be separate from source USRDIR')
    if output.exists() and any(output.iterdir()):parser.error('Choose a new or empty output folder')
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    data,manifest=build(source);output.mkdir(parents=True,exist_ok=True)
    (output/'Font.gsf').write_bytes(data);(output/'font-patch.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(f'Generated asset-only font patch: {output}; {len(manifest["glyphs"])} overrides. No original files or executables modified.')


if __name__=='__main__':main()
