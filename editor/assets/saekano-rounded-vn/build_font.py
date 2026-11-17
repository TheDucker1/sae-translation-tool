"""Build Saekano Rounded VN from independently drawn vector outlines.

Requires fontTools and skia-pathops. No game font assets are used as inputs.
"""

from argparse import ArgumentParser
from pathlib import Path
import unicodedata

from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
import pathops

from outlines import DOTS, EXTRAS, LATIN, MARKS

UPM = 1024
ADVANCE = 512
STEM = 80
KAPPA = 0.55228475
TONES = ('', '\u0300', '\u0301', '\u0309', '\u0303', '\u0323')
VIETNAMESE_BASES = 'aăâeêioôơuưyAĂÂEÊIOÔƠUƯY'
UPPER_TOP = 779
LOWER_TOP = 576
SHAPES = {'\u0302', '\u0306', '\u031b'}
HORN_EDGE = {'o': 378, 'O': 402, 'u': 384, 'U': 404}


def stroke(data, width=STEM):
    """Expand the centerline into closed contours with round joins and ends."""
    words = iter(data.split())
    path = pathops.Path()
    for command in words:
        if command == 'M':
            path.moveTo(float(next(words)), float(next(words)))
        elif command == 'L':
            path.lineTo(float(next(words)), float(next(words)))
        elif command == 'C':
            path.cubicTo(*(float(next(words)) for _ in range(6)))
        elif command == 'Z':
            path.close()
        else:
            raise ValueError(f'Unknown centerline command {command}')
    path.stroke(width, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
    path.convertConicsToQuads(0.35)
    return path


def oval(x, y, radius):
    d = radius * KAPPA
    path = pathops.Path()
    path.moveTo(x + radius, y)
    path.cubicTo(x + radius, y - d, x + d, y - radius, x, y - radius)
    path.cubicTo(x - d, y - radius, x - radius, y - d, x - radius, y)
    path.cubicTo(x - radius, y + d, x - d, y + radius, x, y + radius)
    path.cubicTo(x + d, y + radius, x + radius, y + d, x + radius, y)
    path.close()
    return path


def union(paths):
    outline = pathops.Path()
    for path in paths:
        if len(outline):
            outline = pathops.op(outline, path, pathops.PathOp.UNION, clockwise=True)
        else:
            outline.addPath(path)
            outline.simplify(clockwise=True)
    return outline


def glyph_name(char):
    return f'uni{ord(char):04X}'


def bottom_y(char):
    return -153 if char == 'y' else -7


def top_y(char):
    if char.isupper():
        return UPPER_TOP
    if char in 'bdfhijkl':
        return UPPER_TOP
    return LOWER_TOP


def base_ink(char):
    width = STEM
    if char in 'MWmw%#@':
        width = 72
    elif char in '"\'~<>=+-*_' or char == chr(96):
        width = 68
    return union([stroke(line, width) for line in LATIN.get(char, ())] +
                 [oval(*dot) for dot in DOTS.get(char, ())])


class Design:
    def __init__(self):
        self.cmap = {}
        self.glyphs = {}
        self.widths = {}
        self.anchors = {}

    def add_outline(self, name, outline, width):
        pen = TTGlyphPen(None)
        bounds = BoundsPen(None)
        outline.draw(Cu2QuPen(pen, 0.85))
        outline.draw(bounds)
        self.glyphs[name] = pen.glyph()
        self.widths[name] = (width, round(bounds.bounds[0]) if bounds.bounds else 0)

    def add_char(self, char, outline, width=ADVANCE):
        name = glyph_name(char)
        self.cmap[ord(char)] = name
        self.add_outline(name, outline, width)
        return name

    def add_components(self, char, components, width):
        name = glyph_name(char)
        pen = TTGlyphPen(self.glyphs)
        for component, (dx, dy) in components:
            pen.addComponent(component, (1, 0, 0, 1, dx, dy))
        lsb = min(self.widths[part][1] + dx for part, (dx, _) in components)
        self.cmap[ord(char)] = name
        self.glyphs[name] = pen.glyph()
        self.widths[name] = (width, lsb)
        return name


def accent_positions(base, structural, tone):
    """Offset a tone beside a circumflex or above a breve."""
    top = UPPER_TOP if base.isupper() else LOWER_TOP
    offsets = []
    if structural == '\u031b':
        offsets.append((structural, (HORN_EDGE[base], top - 150)))
    elif structural:
        offsets.append((structural, (256, top)))
    if tone == '\u0323':
        offsets.append((tone, (256, bottom_y(base) - 43)))
    elif tone:
        shift_x, shift_y = 0, 0
        if structural == '\u0302':
            shift_x, shift_y = {
                '\u0300': (-114, 102), '\u0301': (114, 102),
                '\u0309': (114, 101), '\u0303': (0, 154),
            }[tone]
        if structural == '\u0306':
            shift_y = 145
        offsets.append((tone, (256 + shift_x, top + shift_y)))
    return offsets


def make_design():
    design = Design()
    design.add_outline('.notdef', union([stroke('M 96 80 L 96 672 L 416 672 L 416 80 Z', 53)]), ADVANCE)
    for code in range(32, 127):
        char = chr(code)
        design.add_char(char, base_ink(char))
        if char.isalpha():
            design.anchors[glyph_name(char)] = {
                'top': (256, top_y(char)), 'bottom': (256, bottom_y(char) - 43),
            }
    design.add_char('\u00a0', pathops.Path())
    design.add_char('…', union([oval(x, 53, 49) for x in (108, 256, 404)]))
    design.add_char('·', oval(256, 340, 53))
    for char, (width, weight, line) in EXTRAS.items():
        design.add_char(char, union([stroke(line, weight)]), width)
    design.add_char('Đ', union([base_ink('D'), stroke('M 61 387 L 234 387', 72)]))
    design.add_char('đ', union([base_ink('d'), stroke('M 275 600 L 461 600', 67)]))
    design.add_char('₫', union([base_ink('d'), stroke('M 275 600 L 461 600', 67),
                                stroke('M 100 -106 L 429 -106', 56)]))
    dotless_i = design.add_char('ı', union([stroke(line) for line in LATIN['i']]))
    design.anchors[dotless_i] = {'top': (256, LOWER_TOP), 'bottom': (256, -50)}

    for mark, (name, weight, line) in MARKS.items():
        outline = union([stroke(line, weight)]) if line else oval(0, -25, 42)
        design.cmap[ord(mark)] = name
        design.add_outline(name, outline, 0)
    for shaped in VIETNAMESE_BASES:
        for tone in TONES:
            char = unicodedata.normalize('NFC', shaped + tone)
            if len(char) != 1:
                raise ValueError(f'Expected one precomposed letter for {shaped + tone!r}')
            if ord(char) in design.cmap:
                continue
            decomposition = unicodedata.normalize('NFD', char)
            base = decomposition[0]
            structural = next((mark for mark in decomposition[1:] if mark in SHAPES), '')
            if base == 'i' and tone not in {'', '\u0323'}:
                base_name = dotless_i
            else:
                base_name = glyph_name(base)
            components = [(base_name, (0, 0))]
            components.extend((MARKS[mark][0], position)
                              for mark, position in accent_positions(base, structural, tone))
            width = 576 if structural == '\u031b' else ADVANCE
            name = design.add_components(char, components, width)
            accent_top = top_y(base)
            if structural == '\u0302':
                accent_top += 154
            elif structural == '\u0306':
                accent_top += 145
            if tone and tone != '\u0323':
                accent_top += 159
            design.anchors[name] = {'top': (256, accent_top), 'bottom': (256, bottom_y(base) - 43)}
    return design


def feature_text(design):
    lines = ['languagesystem DFLT dflt;', 'languagesystem latn dflt;', 'languagesystem latn VIT;']
    # Support shapers that pass decomposed glyph streams straight through.
    compositions = {}
    for char in {unicodedata.normalize('NFC', b + t) for b in VIETNAMESE_BASES for t in TONES}:
        nfd = unicodedata.normalize('NFD', char)
        for split in range(1, len(nfd)):
            value = unicodedata.normalize('NFC', nfd[:split]) + nfd[split:]
            if len(value) > 1 and all(ord(c) in design.cmap for c in value):
                compositions[value] = char
        if len(nfd) == 3:
            value = unicodedata.normalize('NFC', nfd[0] + nfd[2]) + nfd[1]
            if len(value) > 1 and all(ord(c) in design.cmap for c in value):
                compositions[value] = char
    lines.append('feature ccmp {')
    for value, result in sorted(compositions.items(), key=lambda pair: (-len(pair[0]), pair[0])):
        names = ' '.join(design.cmap[ord(char)] for char in value)
        lines.append(f'  sub {names} by {glyph_name(result)};')
    lines.append('} ccmp;')
    for char, (name, _, _) in MARKS.items():
        group = 'below' if char == '\u0323' else 'horn' if char == '\u031b' else 'above'
        lines.append(f'markClass {name} <anchor 0 0> @{group};')
    lines.append('feature mark {')
    for name, anchors in design.anchors.items():
        tx, ty = anchors['top']
        bx, by = anchors['bottom']
        lines.append(f'  pos base {name} <anchor {tx} {ty}> mark @above <anchor {bx} {by}> mark @below;')
    for base, edge in HORN_EDGE.items():
        lines.append(f'  pos base {glyph_name(base)} <anchor {edge} {top_y(base) - 150}> mark @horn;')
    lines.append('} mark;')
    lines.extend([
        'feature mkmk {',
        '  pos mark circumflexcomb <anchor 0 154> mark @above;',
        '  pos mark brevecomb <anchor 0 145> mark @above;',
        '  pos mark acutecomb <anchor 19 151> mark @above;',
        '  pos mark gravecomb <anchor -19 151> mark @above;',
        '  pos mark tildecomb <anchor 0 158> mark @above;',
        '  pos mark hookabovecomb <anchor 0 183> mark @above;',
        '} mkmk;',
    ])
    return '\n'.join(lines)


def build(output):
    design = make_design()
    builder = FontBuilder(UPM, isTTF=True)
    builder.setupGlyphOrder(list(design.glyphs))
    builder.setupCharacterMap(design.cmap)
    builder.setupGlyf(design.glyphs)
    builder.setupHorizontalMetrics(design.widths)
    builder.setupHorizontalHeader(ascent=1150, descent=-272, lineGap=0)
    builder.setupNameTable({
        'familyName': 'Saekano Rounded VN',
        'styleName': 'Regular',
        'uniqueFontIdentifier': 'SaekanoRoundedVN-Regular 1.001',
        'fullName': 'Saekano Rounded VN Regular',
        'psName': 'SaekanoRoundedVN-Regular',
        'version': 'Version 1.001',
        'description': 'Independently drawn rounded Latin outlines with Vietnamese coverage.',
    })
    builder.setupOS2(
        version=4,
        sTypoAscender=1150, sTypoDescender=-272, sTypoLineGap=0,
        usWinAscent=1150, usWinDescent=272,
        usWeightClass=400, usWidthClass=3, fsSelection=(1 << 7) | (1 << 6),
        sxHeight=551, sCapHeight=750, ulCodePageRange1=(1 << 0) | (1 << 8),
    )
    builder.setupPost(keepGlyphNames=True)
    builder.setupMaxp()
    addOpenTypeFeaturesFromString(builder.font, feature_text(design))
    builder.font.recalcTimestamp = False
    builder.font['head'].created = builder.font['head'].modified = 3856896000
    builder.save(output)


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('SaekanoRoundedVN-Regular.ttf'))
    build(parser.parse_args().output)
