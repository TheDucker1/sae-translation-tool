"""Asset-only proportional dialogue glyphs through the existing GSF override."""
import argparse,hashlib,json,math,struct
import unicodedata
from pathlib import Path
from .text import TextPresentation,font_atlas

GENERATOR_REVISION=10
WORD_SPACE_WIDTHS = range(3, 10)
DEFAULT_WORD_SPACE_RECORD = 18
STORAGE_GLYPH=0x1d20
STORAGE_AMOUNT='7456'
VIETNAMESE_FACE = Path(__file__).with_name('assets') / 'saekano-rounded-vn' / 'SaekanoRoundedVN-Regular.ttf'


def storage_glyph(raw,font):
    """Repair the native integer-as-UTF16 append through its existing cache key."""
    indexes=raw.glyphIndexesForString(STORAGE_AMOUNT);runs=[];x=0
    if len(indexes)!=len(STORAGE_AMOUNT) or not all(indexes):raise ValueError('Original font has no storage amount digits')
    for index in indexes:
        rect=raw.boundingRect(index);left=math.floor(rect.left());ink=math.ceil(rect.right())-left
        runs.append((index,x-left));x+=ink+1
    return dict(character=STORAGE_GLYPH,source=STORAGE_AMOUNT,index=None,left=0,
        width=dialogue_width(x-1,font,1),runs=runs,fixed=False)


def relocate_storage_glyph(parts, font, alias):
    """Move the constant amount to an encodable slot; leave the native append blank."""
    amount = font.cached[chr(STORAGE_GLYPH)]
    blank = font.cached[' ']
    record = struct.Struct('<4H2B')
    records = bytearray(parts[-2])
    for offset in range(0, len(records), record.size):
        if record.unpack_from(records, offset)[0] == STORAGE_GLYPH:
            record.pack_into(records, offset, STORAGE_GLYPH, *blank)
            break
    else:
        raise ValueError('Missing native storage glyph in font cache')
    records.extend(record.pack(ord(alias), *amount))
    parts[-2] = bytes(records)


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


def vietnamese_characters():
    """Non-ASCII NFC Vietnamese letters plus the đồng sign."""
    vowels = 'aăâeêioôơuưy'
    tones = ('', '\u0300', '\u0301', '\u0309', '\u0303', '\u0323')
    letters = {
        unicodedata.normalize('NFC', vowel + tone)
        for vowel in vowels + vowels.upper()
        for tone in tones
    }
    return ''.join(sorted({letter for letter in letters if not letter.isascii()} | set('Đđ₫')))


def vietnamese_glyphs(font, baseline):
    """Fit accent stacks inside the shared GSF cell with the existing baseline."""
    from PySide6.QtGui import QFont, QRawFont

    raw = QRawFont(str(VIETNAMESE_FACE), 22, QFont.PreferNoHinting)
    if not raw.isValid():
        raise ValueError('Cannot open the bundled Saekano Rounded VN font')
    characters = vietnamese_characters()
    indexes = raw.glyphIndexesForString(characters)
    if len(indexes) != len(characters) or not all(indexes):
        raise ValueError('The bundled font is missing required Vietnamese glyphs')
    top_room = baseline - 1
    bottom_room = font.bitmap_height - baseline - 1
    if min(top_room, bottom_room) <= 0:
        raise ValueError('No room for accents in the GSF cell')

    # Keep the x-height and baseline. Compress the area above the x-height and
    # below the baseline only when this glyph would exceed the native cell.
    x_height = -raw.pathForGlyph(raw.glyphIndexesForString('x')[0]).boundingRect().top()
    anchor = min(x_height, top_room * 0.7)
    glyphs = []
    for character, index in zip(characters, indexes):
        codepoint = ord(character)
        if character in font.cached:
            raise ValueError(f'Original GSF already caches Vietnamese glyph U+{codepoint:04X}')
        path = raw.pathForGlyph(index)
        if path.isEmpty():
            raise ValueError(f'Empty Vietnamese glyph U+{codepoint:04X}')
        bounds = path.boundingRect()
        top, bottom = -bounds.top(), bounds.bottom()
        top_scale = (top_room - anchor) / (top - anchor) if top > top_room else 1
        bottom_scale = bottom_room / bottom if bottom > bottom_room else 1
        if top_scale < 1 or bottom_scale < 1:
            for i in range(path.elementCount()):
                point = path.elementAt(i)
                y = point.y
                if y < -anchor:
                    y = -anchor + (y + anchor) * top_scale
                elif y > 0:
                    y *= bottom_scale
                path.setElementPositionAt(i, point.x, y)
        fitted = path.boundingRect()
        if fitted.top() < -baseline or fitted.bottom() > font.bitmap_height - baseline:
            raise ValueError(f'Vietnamese glyph U+{codepoint:04X} exceeds the GSF cell')
        left = math.floor(fitted.left())
        ink = math.ceil(fitted.right()) - left
        glyphs.append(dict(character=codepoint, source=character, left=left,
                           width=dialogue_width(ink, font, 1), path=path, fixed=False))
    return glyphs


def word_space_record(font, pixels):
    """Convert a whole default-dialogue advance to the native ASCII-space record width."""
    def advance(width):
        return int(int(width * (font.utility / 36 if font.utility else 1) * 0.5) * font.scale)

    if pixels is None or pixels == advance(DEFAULT_WORD_SPACE_RECORD):
        return DEFAULT_WORD_SPACE_RECORD, advance(DEFAULT_WORD_SPACE_RECORD)
    for width in range(1, 256):
        if advance(width) == pixels:
            return width, pixels
    raise ValueError('The source font scale cannot represent this word-space advance')


def build(root, *, word_space_px=None):
    """Keep original atlas/records/charset and append a Latin and Vietnamese atlas.

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
    if word_space_px is not None and (type(word_space_px) is not int or word_space_px not in WORD_SPACE_WIDTHS):
        raise ValueError(f'Word space must be {WORD_SPACE_WIDTHS.start}–{WORD_SPACE_WIDTHS.stop - 1} game pixels')
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
    glyphs.append(storage_glyph(raw,font))
    # ASCII-space measurement halves the recorded width. The bitmap stays blank.
    space_width, space_advance = word_space_record(font, word_space_px)
    glyphs.append(dict(character=32,source=' ',index=None,left=0,width=space_width,fixed=False))
    vietnamese=vietnamese_glyphs(font,baseline)
    glyphs.extend(vietnamese)
    from .pairspacing import build_pairs, carrier_codes
    unavailable=set(font.cached)|font.charset|{chr(g['character']) for g in glyphs}
    unavailable.update(font.format.mapping)
    unavailable.update(font.format.mapping.values())
    unavailable.update(''.join(font.format.tokens+font.format.following))
    carriers=carrier_codes(unavailable)
    keyword_marks={}
    for char in '【】':
        index=raw.glyphIndexesForString(char)[0]
        if not index:continue
        rect=raw.boundingRect(index);left=math.floor(rect.left());ink=math.ceil(rect.right())-left
        if ink<=0 or -rect.top()>baseline or math.ceil(rect.bottom())>height-baseline:continue
        alias=next(carriers);keyword_marks[char]=alias
        compact=min(ink,7)
        glyphs.append(dict(character=ord(alias),source=char,index=index,left=left,
                           width=dialogue_width(compact,font,0),ink_scale=compact/ink,fixed=False))
    atlas_width=512;atlas_height=512;coverage=bytearray(atlas_width*atlas_height)
    records=[];glyph_records={};x=1;y=1;report=[]
    for g in glyphs:
        width=g['width']
        if x+width+1>atlas_width:x=1;y+=height+2
        if y+height+1>atlas_height:raise ValueError('Font atlas exceeded bounded capacity')
        image=QImage(width,height,QImage.Format_RGBA8888);image.fill(0)
        if 'path' in g:
            painter=QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.translate(-g['left'],baseline)
            painter.fillPath(g['path'],QColor('white'))
            painter.end()
        elif g['index'] is not None or g.get('runs'):
            runs=g.get('runs',[(g['index'],-g['left'])])
            run=QGlyphRun();run.setRawFont(raw);run.setGlyphIndexes([i for i,x in runs]);run.setPositions([QPointF(x,baseline) for i,x in runs])
            painter=QPainter(image);painter.setPen(QColor('white'));painter.translate(g.get('padding',0),0);painter.scale(g.get('ink_scale',1),1);painter.drawGlyphRun(QPointF(0,0),run);painter.end()
        pixels=bytes(image.constBits())
        for row in range(height):
            for col in range(width):coverage[(y+row)*atlas_width+x+col]=pixels[(row*width+col)*4+3]
        record = (len(parts)-2,x,y,width,height)
        glyph_records[chr(g['character'])] = record
        records.append(struct.pack('<4H2B',g['character'],*record))
        report.append(dict(codepoint=g['character'],source=g['source'],record_width=width,atlas_rect=[x,y,width,height],fixed_cursor=g['fixed']))
        x+=width+2
    scales = [font.scale]
    profile_path = root/'env/env_otaku_mode.dat'
    if profile_path.is_file():
        from .compositionmodes import profile_environment
        scales.append(profile_environment(profile_path.read_bytes())['response_scale'])
    pairing, aliases = build_pairs(font, scales, coverage, atlas_width, glyph_records, vietnamese_characters())
    pairing['keyword_marks']=keyword_marks
    pairing['restore'].update({alias:char for char,alias in keyword_marks.items()})
    records.extend(struct.pack('<4H2B', ord(char), *record) for char, record in aliases.items())
    atlas=p8_atlas(atlas_width,atlas_height,bytes(coverage));font_atlas(atlas)
    output=pack(parts[:-2]+[atlas,parts[-2]+b''.join(records),parts[-1]])
    manifest=dict(format='saekano-proportional-font',version=1,generator_revision=GENERATOR_REVISION,source_sha256=hashlib.sha256(original).hexdigest(),
        font_sha256=hashlib.sha256(output).hexdigest(),font_file='Font.gsf',executable_changes=False,
        nominal=nominal,bitmap_height=height,glyphs=report,
        scope='Proportional dialogue aliases, readable fixed-cursor Latin and precomposed Vietnamese glyphs.',
        ui_bitmap_cells=True,ui_cell_ink_width=11,
        word_space=dict(pixels=space_advance, scale='default_dialogue', record_width=space_width),
        pair_spacing=pairing,
        vietnamese=dict(face='Saekano Rounded VN',glyph_count=len(vietnamese),input_form='NFC',
            vector_sha256=hashlib.sha256(VIETNAMESE_FACE.read_bytes()).hexdigest()),
        native_storage_amount=dict(codepoint=STORAGE_GLYPH,text=STORAGE_AMOUNT,reason='Native capacity value is appended as one UTF16 unit'),
        dialogue_spacing='native_scaled_ink_plus_gap',dialogue_gap_pixels=1,
        limitations=['Simple DrawString names/UI still use fixed cursor advances.',
                    'Use matching patched font metrics when rewrapping scripts.',
                    'The ASCII space width is shared by measured text. Other text scales can round differently.',
                    'Pair spacing is limited to verified plain measured text.'])
    return output,manifest


def make_asset(root, *, word_space_px=None):
    data,manifest=build(root, word_space_px=word_space_px)
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
    if (changed[:-3]!=original[:-2] or not changed[-2].startswith(original[-2]) or changed[-1]!=original[-1]
            or len(changed[-2]) % 10):
        raise ValueError('Font asset changed protected original glyphs/charset')
    from .pairspacing import config_for
    config = config_for(asset)
    if config:
        glyphs = {chr(code): (atlas, x, y, width, height) for code, atlas, x, y, width, height in struct.iter_unpack('<4H2B', changed[-2])}
        reserved = config['restore']
        marks={alias:base for base,alias in config.get('keyword_marks',{}).items()}
        if (set(marks.values())-set('【】')
                or set(reserved) != (set(config['accents'].values()) | set(config['pairs'].values()) | marks.keys())):
            raise ValueError('Pair-spacing charset does not match its glyph mapping')
        for char, base in reserved.items():
            alias = glyphs[char]
            if char in marks:
                if marks[char]!=base or alias[0]!=len(changed)-3 or not 0<alias[3]<=36 or alias[4]!=24:
                    raise ValueError('Invalid keyword bracket glyph')
                continue
            original_glyph = glyphs[base]
            if (alias[:3] != original_glyph[:3] or not 0 < alias[3] <= original_glyph[3]
                    or alias[4] != original_glyph[4] or char.encode('shift_jis').decode('cp932') != char):
                raise ValueError('Invalid proportional text carrier glyph')
        if (any(reserved[char] != pair[0] or len(pair) != 2 for pair, char in config['pairs'].items())
                or any(glyphs[char] != glyphs[base] for base, char in config['accents'].items())):
            raise ValueError('Pair-spacing aliases changed their base glyph')
    font_atlas(changed[-3])


def effective_font(project,font):
    asset=getattr(project,'font_asset',None)
    original=getattr(font,'source_font',font)
    if asset is None:return original
    digest=asset['manifest']['font_sha256']
    if getattr(font,'asset_sha256',None)==digest:return font
    result=TextPresentation(project.root,font_asset=bytes.fromhex(asset['data_hex']));result.asset_sha256=digest
    from .pairspacing import config_for
    result.pair_spacing = config_for(asset)
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
