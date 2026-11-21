"""Pack proportional labels for Saekano's fixed-cursor DrawString."""
from dataclasses import dataclass
from functools import lru_cache
from statistics import median
import struct
import unicodedata

from .pairspacing import narrow, plain

CELL = 24
FIRST_CARRIER = 0xE000
END_CARRIER = 0xF900
ATLAS_EDGE = 512
TILES_PER_ROW = 20
ROWS_PER_ATLAS = 19  # First row is blank and holds measured centering records.


@dataclass(frozen=True)
class PackedLabel:
    width: int
    cells: tuple
    left: int
    source_ink: int
    source_left: int

    def measure(self, size):
        return sum(measured_width(width, size) for width, _ in self.cells)

    def bounds(self, size):
        return self.source_left * size // CELL, (self.source_ink * size + CELL - 1) // CELL


def measured_width(record_width, size=CELL):
    return 1 + record_width * (size or 36) // 36


@lru_cache(maxsize=512)
def ink_edges(mask, width, threshold):
    rows = []
    for y in range(CELL):
        ink = [x for x, alpha in enumerate(mask[y * width:(y + 1) * width]) if alpha >= threshold]
        rows.append((ink[0], ink[-1] + 1) if ink else None)
    return tuple(rows)


def optical_shift(left, left_width, right, right_width, advance):
    """Move the right letter in whole pixels, using solid ink and antialiasing."""
    def gaps(threshold):
        a = ink_edges(left, left_width, threshold)
        b = ink_edges(right, right_width, threshold)
        return [advance + r[0] - l[1] for l, r in zip(a, b) if l and r]

    solid = gaps(128)
    if len(solid) < 4:
        return 0
    typical = median(solid)
    clearance = min(gaps(1))
    if typical <= 1 and min(solid) <= 0:
        return 1
    return -max(0, min(2, int(typical - 2.5), clearance - 1))


def approach_metrics(root, utility):
    from .compositioncommon import selection_environment
    from .compositionmodes import approach_environment

    approach = approach_environment((root/'env/env_approach.dat').read_bytes())
    selection = selection_environment((root/'env/env_script_select.dat').read_bytes())
    parent_left = max(marker[0] - card[0] for table in (0, 1)
                      for card, marker in zip(approach['points'][table], approach['points'][table+2]))
    parent_left += approach['parent_marker']['w']
    parent_right = approach['parent_sprites'][1]['w']
    child_marker = selection['sprites'][2]
    child_left = child_marker['x'] + child_marker['w']
    child_right = selection['sprites'][0]['w']

    def interior(center, left, right):
        return 2 * min(center - left, right - center) - 4

    return dict(parent=(int(utility * approach['scale']), interior(approach['text_offset'][0], parent_left, parent_right)),
                child=(int(utility * selection['scale']), interior(selection['words'][4], child_left, child_right)))


def caption_panel_size(scale, side):
    return 0 if side else int(36 * scale)


def caption_panel(anchor, side, padding, measured):
    width = padding + measured
    left = anchor - width if side else anchor
    center = anchor - width // 2 if side else anchor + width // 2
    return left, width, center


def ui_label_placement(field, font):
    """Only pack UTF-16 strings with one verified, compatible draw contract."""
    if (not getattr(font, 'pair_spacing', None) or field.get('format_tokens')
            or field['encoding'].split(' ',1)[0] not in {'counted-utf16', 'utf-16-le'}):
        return None
    contracts = field.get('contracts', ())
    placements = set()
    for contract in contracts:
        if contract['kind'] == 'fixed' and not contract.get('format_samples'):
            align = contract.get('align', 'left')
        elif contract['kind'] == 'help_group' and contract['rectangle'] is not None:
            # Group spacing reserves the label's MeasureString width.
            align = 'right'
        else:
            return None
        placements.add((int(font.utility * contract['scale']), align))
    calibrated = {(size, align) for size, align in placements if align != 'left'}
    if len(calibrated) > 1 or not placements:
        return None
    size, align = next(iter(calibrated)) if calibrated else max(placements)
    return size, dict(align=align)


def ui_row_placement(field, font):
    if (not getattr(font, 'pair_spacing', None) or field.get('format_tokens')
            or field['encoding'].split(' ',1)[0] not in {'counted-utf16', 'utf-16-le'}):
        return None
    contracts = field.get('contracts', ())
    if not contracts or any(c['kind'] not in {'fixed_rows','profile_tips'} for c in contracts):
        return None
    if any(not c.get('separator') or 'scale' not in c for c in contracts):
        return None
    placements = {(int(font.utility*c['scale']),c['separator']) for c in contracts}
    return next(iter(placements)) if len(placements)==1 else None


def _tile_layout(ink, size, align, panel_size, panel_padding):
    """Choose transparent records that calibrate native centering and panel sizing."""
    width = (ink * size + CELL - 1) // CELL
    count = (ink + CELL - 1) // CELL
    if align == 'left':
        return width, count, 0, []
    while True:
        measure = count * measured_width(CELL, size)
        panel = count * measured_width(CELL, panel_size) if panel_size is not None else 0
        extra = []
        panel_target = width + 4 - panel_padding if panel_size is not None else 0
        while measure < width or panel < panel_target:
            record = next((n for n in range(1, 256)
                           if measure + measured_width(n, size) >= width
                           and (panel_size is None or panel + measured_width(n, panel_size) >= panel_target)), 255)
            extra.append(record)
            measure += measured_width(record, size)
            if panel_size is not None:
                panel += measured_width(record, panel_size)
        gap = max(0, measure - width if align == 'right' else measure // 2 - width // 2)
        left = (gap * CELL + size - 1) // size
        required = (left + ink + CELL - 1) // CELL
        if required <= count:
            return width, count, left, extra
        count = required


def stock_symbol_mask(glyph):
    """Sample a stock PVF symbol in the same cropped cell used by DrawString."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage,QPainter
    width,height=glyph['width'],glyph['height']
    image=QImage(bytes.fromhex(glyph['rgba']),width,height,width*4,QImage.Format_RGBA8888).copy()
    cell=QImage(CELL,CELL,QImage.Format_RGBA8888);cell.fill(0)
    painter=QPainter(cell)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.drawImage(QRectF(0,0,CELL,CELL),image,QRectF(*glyph.get('source',[0,0,width,height])))
    painter.end()
    return CELL,bytes(cell.constBits())[3::4]


def make_label(font, text, size, *, align='center', panel_size=None, panel_padding=0,
               extra_symbols=frozenset()):
    """Build fixed cells containing proportional Latin text at the authored size."""
    if (not getattr(font, 'pair_spacing', None) or not 8 <= size <= 64 or font.bitmap_height != CELL
            or len(text) < 2 or not plain(text, font.format)
            or any(c in text for c in ('\r', '\n', font.format.break_char))):
        return None
    letters = [c for c in text if c.isalpha()]
    if not letters or any('LATIN' not in unicodedata.name(c, '') for c in letters):
        return None
    from .textlayout import full_width_text
    value = narrow(full_width_text(text.replace('　',' '), font)['text'], font.pair_spacing)
    if any(c not in font.cached and (c not in extra_symbols or c not in font.charset) for c in value):
        return None

    draws = []
    pen = width = 0
    previous = ''
    for char in value:
        glyph = font.glyph(ord(char))
        if glyph.get('missing'):return None
        if char in font.cached:
            record_width = glyph['width']
            mask = bytes.fromhex(glyph['rgba'])[3::4]
        else:
            record_width,mask=stock_symbol_mask(glyph)
        ink = max((i % record_width + 1 for i, alpha in enumerate(mask) if alpha), default=0)
        if ink:
            if previous.isalpha() and char.isalpha():
                prior_x, prior_mask, prior_width, _ = draws[-1]
                pen += optical_shift(prior_mask, prior_width, mask, record_width, pen - prior_x)
            draws.append((pen, mask, record_width, ink))
            width = max(width, pen + ink)
        # Work in the 24px bitmap grid. Keep every accent and the existing font's
        # configured space advance. The native cursor will advance by tiles.
        advance = int(font.measure(char, font.utility) * CELL / font.utility)
        pen += max(advance, ink)
        previous = char if ink else ''
        if pen > 960:
            return None
    if not width:
        return None

    source_ink = width
    width, count, left, extra = _tile_layout(source_ink, size, align, panel_size, panel_padding)
    stride = count * CELL
    rows = [bytearray(stride) for _ in range(CELL)]
    for x, mask, record_width, ink in draws:
        for y, row in enumerate(rows):
            start = y * record_width
            for col, alpha in enumerate(mask[start:start + ink], x + left):
                if alpha > row[col]:
                    row[col] = alpha
    cells = [(CELL, b''.join(row[x:x + CELL] for row in rows)) for x in range(0, stride, CELL)]

    cells.extend((record_width, None) for record_width in extra)
    return PackedLabel(width, tuple(cells), left * size // CELL, source_ink, left)


class ChoiceAtlas:
    def __init__(self, font, unavailable=()):
        self.font = font
        blocked = set(font.cached) | font.charset | set(unavailable)
        self.carriers = (chr(code) for code in range(FIRST_CARRIER, END_CARRIER) if chr(code) not in blocked)
        self.glyphs = {}
        self.labels = {}
        self.geometry = {}

    def encode(self, text, size, *, align='center', panel_size=None, panel_padding=0, extra_symbols=frozenset()):
        key = (text, size, align, panel_size, panel_padding, extra_symbols)
        if key not in self.labels:
            label = make_label(self.font, text, size, align=align, panel_size=panel_size,
                               panel_padding=panel_padding, extra_symbols=extra_symbols)
            if label is None:
                return text, None
            wire = ''.join(self.register(cell) for cell in label.cells)
            self.labels[key] = (wire, label.width)
            self.geometry[wire] = label
        return self.labels[key]

    def register(self, cell):
        if cell not in self.glyphs:
            code = next(self.carriers, None)
            if code is None:
                raise ValueError('Packed font ran out of unused UTF-16 glyph slots')
            self.glyphs[cell] = code
        return self.glyphs[cell]

    def append_to(self, parts):
        if not self.glyphs:
            return
        from .fontpatch import p8_atlas
        atlas_pages = [bytearray(ATLAS_EDGE * ATLAS_EDGE)]
        records = []
        tile_number = 0
        tiles_per_atlas = TILES_PER_ROW * ROWS_PER_ATLAS
        atlas_start = len(parts) - 2
        for (width, mask), code in self.glyphs.items():
            if mask is None:
                page, x, y = 0, 1, 1
            else:
                page, tile = divmod(tile_number, tiles_per_atlas)
                if page == len(atlas_pages):
                    atlas_pages.append(bytearray(ATLAS_EDGE * ATLAS_EDGE))
                y, x = divmod(tile, TILES_PER_ROW)
                x, y = 1 + x * 25, 26 + y * 25
                atlas = atlas_pages[page]
                for row in range(CELL):
                    start = (y + row) * ATLAS_EDGE + x
                    atlas[start:start + CELL] = mask[row * CELL:(row + 1) * CELL]
                tile_number += 1
            records.append(struct.pack('<4H2B', ord(code), atlas_start + page, x, y, width, CELL))
        if len(parts) + len(atlas_pages) > 258:
            raise ValueError('Packed font exceeds the native atlas table capacity')
        parts[-2] += b''.join(records)
        parts[-2:-2] = [p8_atlas(ATLAS_EDGE, ATLAS_EDGE, bytes(page)) for page in atlas_pages]


class PreviewChoices(ChoiceAtlas):
    def register(self, cell):
        existing = cell in self.glyphs
        code = super().register(cell)
        if not existing:
            width, mask = cell
            count = width * CELL
            pixels = bytearray(b'\xff' * (4 * count))
            pixels[3::4] = mask if mask is not None else bytes(count)
            self.font.cached[code] = (-1, 0, 0, width, CELL)
            self.font.glyph_cache[ord(code)] = dict(width=width, height=CELL, rgba=pixels.hex(), bitmap=True)
        return code


def preview_label(font, text, size, **placement):
    if not getattr(font, 'pair_spacing', None):
        return text, None
    preview = getattr(font, 'approach_labels', None)
    if preview is None:
        preview = font.approach_labels = PreviewChoices(font)
        font.packed_text = {}
        font.cached = font.cached.copy()
        font.glyph_cache = font.glyph_cache.copy()
    wire, width = preview.encode(text, size, **placement)
    if width is not None:
        font.packed_text[wire] = text
    return wire, width
