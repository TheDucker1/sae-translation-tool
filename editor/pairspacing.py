"""Asset-only proportional pair spacing using the native GSF rectangle and advance."""
from functools import lru_cache
from itertools import product
from math import ceil
import re
from string import ascii_letters
import struct
import unicodedata

REVIEW_LETTERS = str.maketrans('ａｅｉｏｒｕ', 'aeioru')


def reviewed_pair(left, right):
    """Keep the shapes that looked better in Vietnamese rendered specimens."""
    right = right.translate(REVIEW_LETTERS)
    vowel_shape = unicodedata.normalize('NFC', ''.join(
        ch for ch in unicodedata.normalize('NFD', right) if ch not in '\u0300\u0301\u0303\u0309\u0323'))
    return (left == 'Ｔ' and vowel_shape in 'aăâoôơuưr'
            or left == 'Ｖ' and vowel_shape in 'aăâeêoôơư'
            or left == 'ư' and vowel_shape == 'ơ')


def carrier_codes(unavailable):
    """Use standard two-byte Shift-JIS kanji with identical CP932 decoding."""
    for code in range(0x9FFF, 0x4DFF, -1):
        char = chr(code)
        if char in unavailable:
            continue
        try:
            raw = char.encode('shift_jis')
        except UnicodeEncodeError:
            continue
        if len(raw) == 2 and raw[0] >= 0xE0 and raw.decode('cp932') == char:
            yield char


def build_pairs(font, scales, coverage, stride, records, vietnamese):
    """Evaluate every supported letter pair against solid ink and preserve the full mask."""
    letters = {chr(ord(char) + 0xFEE0) for char in ascii_letters} | (set(vietnamese) - {'₫'})
    letters = sorted(letters & records.keys())
    scales = tuple(sorted(set(scales)))
    silhouettes = {}
    ink_columns = {}
    for char in letters:
        _, x, y, width, height = records[char]
        mask = [coverage[row * stride + x:row * stride + x + width] for row in range(y, y + height)]
        solid = [[i for i, alpha in enumerate(row) if alpha >= 128] for row in mask]
        silhouettes[char] = [(row[0], row[-1] + 1) if row else None for row in solid]
        ink_columns[char] = max((i + 1 for row in mask for i, alpha in enumerate(row) if alpha), default=width)

    def advance(width, scale):
        return int(int(1 + width * font.utility / 36) * scale)

    variants = {}
    for char in letters:
        width = records[char][3]
        variants[char] = [candidate for candidate in range(width - 1, ink_columns[char] - 1, -1)
                          if all(1 <= advance(width, scale) - advance(candidate, scale) <= 2 for scale in scales)]

    @lru_cache(maxsize=None)
    def outline(char, width, scale):
        stretch = ceil(width * int(font.utility * scale) / font.bitmap_height) / width
        return [(row[0] * stretch, row[1] * stretch) if row else None for row in silhouettes[char]]

    @lru_cache(maxsize=None)
    def incoming(char, scale):
        widths = [records[char][3], *variants[char]]
        return [min(row[0] for row in rows) if rows[0] else None
                for rows in zip(*(outline(char, width, scale) for width in widths))]

    def clearance(left, width, right, scale):
        pen = advance(width, scale)
        return min((pen + start - edge[1] for edge, start in zip(outline(left, width, scale), incoming(right, scale))
                    if edge and start is not None), default=0)

    selected = {}
    for left, right in product(letters, repeat=2):
        if not variants[left] or min(clearance(left, records[left][3], right, s) for s in scales) < 3.4:
            continue
        for width in variants[left]:
            if min(clearance(left, width, right, s) for s in scales) >= 1.7:
                selected[left + right] = (left, width)
                break

    unavailable = set(records) | set(font.cached) | font.charset | set(font.format.mapping) | set(font.format.mapping.values())
    unavailable.update(''.join(font.format.tokens + font.format.following))
    geometry_passed = len(selected)
    selected = {pair: variant for pair, variant in selected.items() if reviewed_pair(*pair)}
    carriers = carrier_codes(unavailable)
    accents = {char: next(carriers) for char in vietnamese}
    names = {variant: next(carriers) for variant in sorted(set(selected.values()))}
    shapes = {alias: records[char] for char, alias in accents.items()}
    for (char, width), alias in names.items():
        atlas, x, y, _, height = records[char]
        shapes[alias] = (atlas, x, y, width, height)
    restore = {alias: char for char, alias in accents.items()}
    restore.update({alias: char for (char, _), alias in names.items()})
    report = dict(scales=list(scales), pairs_checked=len(letters) ** 2, pairs_geometry_passed=geometry_passed, pairs_approved=len(selected),
                  variants=len(names), cp932_aliases=len(accents))
    return dict(summary=report, pairs={pair: names[value] for pair, value in selected.items()},
                accents=accents, restore=restore), shapes


def config_for(asset):
    return asset['manifest'].get('pair_spacing') if asset else None


def public_pair_spacing(config):
    """Group approved pairs by actual variant, in readable text for MCP clients."""
    grouped = {}
    for pair, alias in sorted(config['pairs'].items()):
        grouped.setdefault(alias, []).append(unicodedata.normalize('NFKC', pair))
    details = [dict(glyph=unicodedata.normalize('NFKC', config['restore'][alias]), pairs=pairs)
               for alias, pairs in grouped.items()]
    return dict(config['summary'], scales=list(config['summary']['scales']), variant_details=details)


def narrow(text, config):
    if not config:
        return text
    pairs = config['pairs']
    return ''.join(pairs.get(text[i:i+2], char) for i, char in enumerate(text))


def plain(text, formatter):
    return '\0' not in text and not any(char in text for char in formatter.tokens[2])


def script_enabled(opcode, args, field=''):
    if opcode == 0x64:
        return not (args.get('selector') or args.get('completion'))
    return opcode == 0x3F2 and field != 'choices[0].label'


def shape_script(text, opcode, args, field, formatter, config, *, keyword_markup=False):
    if not config or formatter is None or not script_enabled(opcode, args, field):
        return text
    if not plain(text, formatter):
        marks=config.get('keyword_marks')
        if opcode==0x64 and keyword_markup and marks and '\0' not in text:
            # Only the wrapper of a native keyword directive uses the compact bracket.
            opening,closing=map(re.escape,(formatter.tokens[0][0],formatter.tokens[1][0]))
            tag,end=map(re.escape,(formatter.following[11],formatter.following[12]))
            pattern=rf'【(?={opening}{tag}\s*=\s*\d+{closing})|(?<={opening}{end}{closing})】'
            if not re.search(pattern,text,flags=re.IGNORECASE) or formatter.ordinary(text,geometry_only=True)['markers']:
                return text
            return re.sub(pattern,lambda match:marks.get(match[0],match[0]),text,flags=re.IGNORECASE)
        return text
    quote = text.find(formatter.following[1]) if opcode == 0x64 else -1
    if quote > 0:
        return text[:quote] + narrow(text[quote:], config)
    return narrow(text, config)


def shape_profile(text, config):
    if not config:
        return text
    if any(char in text for char in '《》'):
        raise ValueError('Profile responses require plain text')
    return narrow(text, config).translate(str.maketrans(config['accents']))


def readable(text, config):
    return ''.join(config['restore'].get(c, c) for c in text) if config else text


def remove_unused_font_records(parts, config, used):
    reserved = {ord(char) for char in config['restore'].keys() - used}
    records = parts[-2]
    parts[-2] = b''.join(records[i:i+10] for i in range(0, len(records), 10)
                        if struct.unpack_from('<H', records, i)[0] not in reserved)
