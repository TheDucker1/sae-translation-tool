"""Pack proportional Approach labels for Saekano's fixed-cursor DrawString."""
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


def measured_width(record_width):
    return 1 + record_width * CELL // 36


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


def make_label(font, text, size):
    """Build fixed cells containing proportional Latin text at the authored size."""
    if (not getattr(font, 'pair_spacing', None) or size != CELL or font.bitmap_height != CELL
            or len(text) < 2 or not plain(text, font.format)
            or any(c in text for c in ('\r', '\n', font.format.break_char))):
        return None
    letters = [c for c in text if c.isalpha()]
    if not letters or any('LATIN' not in unicodedata.name(c, '') for c in letters):
        return None
    from .textlayout import full_width_text
    value = narrow(full_width_text(text, font)['text'], font.pair_spacing)
    if any(c not in font.cached for c in value):
        return None

    draws = []
    pen = width = 0
    previous = ''
    for char in value:
        glyph = font.glyph(ord(char))
        record_width = glyph['width']
        mask = bytes.fromhex(glyph['rgba'])[3::4]
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

    count = (width + CELL - 1) // CELL
    base_measure = count * measured_width(CELL)
    left = max(0, base_measure // 2 - width // 2)
    stride = count * CELL
    rows = [bytearray(stride) for _ in range(CELL)]
    for x, mask, record_width, ink in draws:
        for y, row in enumerate(rows):
            start = y * record_width
            for col, alpha in enumerate(mask[start:start + ink], x + left):
                if alpha > row[col]:
                    row[col] = alpha
    cells = [(CELL, b''.join(row[x:x + CELL] for row in rows)) for x in range(0, stride, CELL)]

    # MeasureString and DrawString use different widths. A transparent trailing
    # glyph fills their difference for centering, without moving any visible ink.
    remaining = width - base_measure
    while remaining > 0:
        advance = min(remaining, measured_width(255))
        record_width = next(w for w in range(1, 256) if measured_width(w) == advance)
        cells.append((record_width, None))
        remaining -= advance
    return PackedLabel(width, tuple(cells))


class ChoiceAtlas:
    def __init__(self, font, unavailable=()):
        self.font = font
        blocked = set(font.cached) | font.charset | set(unavailable)
        self.carriers = (chr(code) for code in range(FIRST_CARRIER, END_CARRIER) if chr(code) not in blocked)
        self.glyphs = {}
        self.labels = {}

    def encode(self, text, size):
        key = (text, size)
        if key not in self.labels:
            label = make_label(self.font, text, size)
            if label is None:
                return text, None
            self.labels[key] = (''.join(self.register(cell) for cell in label.cells), label.width)
        return self.labels[key]

    def register(self, cell):
        if cell not in self.glyphs:
            code = next(self.carriers, None)
            if code is None:
                raise ValueError('Approach label font ran out of unused UTF-16 glyph slots')
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
            raise ValueError('Approach label font exceeds the native atlas table capacity')
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


def preview_label(font, text, size):
    if not getattr(font, 'pair_spacing', None):
        return text, None
    preview = getattr(font, 'approach_labels', None)
    if preview is None:
        preview = font.approach_labels = PreviewChoices(font)
        font.cached = font.cached.copy()
        font.glyph_cache = font.glyph_cache.copy()
    return preview.encode(text, size)
