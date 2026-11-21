"""Read-only save/load and backlog list consumers; no personal saves are accessed."""
from copy import deepcopy
import math
from .composition import Composition, Layer, Fields, blit, sprite, text_layer
from .compositioncommon import cached, quad, plain_layer, add_shadow
from .imagecodec import ImageError
from .scriptcodec import Reader
from .pairspacing import narrow, readable
from .text import color, glyph_draw_width, units, unicode_text
from .uitextcodec import format_ui_numbers


def slot_environment(data):
    e = Fields(data); rd, many = e.read, e.many
    e.string_tables = {}
    many('color', 0, 3); many('scalar', 0xc, 2); rd('string', 0x14)
    many('scalar', 0x4c, 3); many('sprite', 0x58, 3, 36); rd('rect', 0xc4)
    rd('sprite', 0xd4); rd('sprite', 0xf8); rd('point', 0x11c); rd('sprite', 0x124)
    rd('rect', 0x148); rd('point', 0x158); many('scalar', 0x160, 2); many('sprite', 0x168, 8, 36)
    rd('point', 0x288); rd('scalar', 0x290); rd('point', 0x294); rd('point', 0x29c)
    rd('scalar', 0x2a4); rd('point', 0x2a8); rd('scalar', 0x2b0); rd('point', 0x2b4)
    many('scalar', 0x2bc, 2); rd('point', 0x2c4); many('scalar', 0x2cc, 2)
    rd('sprite', 0x2d4); rd('sprite', 0x2f8); rd('rect', 0x31c); rd('scalar', 0x32c)
    rd('sprite', 0x330); rd('sprite', 0x354); rd('point', 0x378); many('sprite', 0x380, 4, 36)
    rd('point', 0x410); many('color', 0x418, 2); rd('colors', 0x420); rd('colors', 0x430)
    many('scalar', 0x440, 2); rd('point', 0x448); rd('rect', 0x450); many('scalar', 0x460, 2)
    e.r.ui_role='fixed UI label';many('string', 0x468, 6, 56)
    e.string_tables[0x5b8] = [e.r.string() for _ in range(e.r.count())]
    e.r.ui_role='dialog prompt';many('string', 0x5c8, 11, 56);e.r.ui_role='UI text'
    return e.finish()


def backdrop_sprite(out, e, key, bank, entry, *, offset=(0, 0), extent=None, source='resource.dat', **kw):
    shape = deepcopy(e.sprite[key])
    if extent is not None:
        sw, sh = shape['w'], shape['h']; shape['w'], shape['h'] = extent
        layer = blit(f'{out.name} sprite {key:X}', bank, entry, shape, offset=offset, source=source, **kw)
        layer.source[2:] = [sw, sh]
    else:
        layer = blit(f'{out.name} sprite {key:X}', bank, entry, shape, offset=offset, source=source, **kw)
    out.layers.append(layer)
    return layer


def help_environment(data):
    r = Reader(data); r.take(3 + 8 + 32 + 4)
    rect = lambda: [r.word('i') for _ in range(4)]
    items = lambda: [[r.word('i'), r.string()] for _ in range(r.count())]
    common_rect, common = rect(), items(); option_rect = rect(); options = [items() for _ in range(r.count())]
    slot_rect = rect(); slots = [items() for _ in range(r.count())]
    return dict(common_rect=common_rect, common=common, option_rect=option_rect, options=options, slot_rect=slot_rect, slots=slots)


def global_ui_environment(data):
    r = Reader(data); r.take(3)
    for _ in range(4): r.string()
    r.take(8)
    for _ in range(9): r.string()
    r.take(24 * 4)
    base = [r.word('i') for _ in range(6)]
    particles = [[r.word('i') for _ in range(6)] for _ in range(r.count())]
    r.take(8 * 4)
    r.take(r.count() * 24); r.take(16); r.take(r.count() * 4)
    keys = [r.string() for _ in range(r.count())]; separator = r.string(); scale = r.word('f'); gap = r.word('i')
    return dict(base=base, particles=particles, keys=keys, separator=separator, scale=scale, gap=gap)


def button_help(out, library, font, mode=None, *, items=None, rectangle=None):
    if font is None: return
    e = cached(library, 'help', 'env/env_help_mgr.dat', help_environment)
    style = cached(library, 'global_ui', 'env/env_global.dat', global_ui_environment)
    rows, authored_rectangle = (e['common'], e['common_rect']) if mode is None else (e['slots'][mode], e['slot_rect'])
    if items is not None: rows = items
    if rectangle is None: rectangle = authored_rectangle
    size = int(font.utility * style['scale']); gap = style['gap']; x, y, width, height = rectangle
    cursor = 0; half = (font.utility - size) >> 1
    for i, (key, label) in enumerate(rows):
        prefix = 0; value = ''
        if key != -1:
            if not 0 <= key < len(style['keys']): raise ImageError('Help key outside authored table')
            value = style['keys'][key]
            prefix = font.measure(units(value), font.utility) + font.measure(units(style['separator']), size)
        next_cursor = cursor + prefix + font.measure(units(label), size) + gap
        at = x + width - next_cursor; draw_prefix = 0
        if key != -1:
            out.layers.append(text_layer(f'Help key {i}', value, [at, y + height // 2 - half], 0, [255] * 4, font))
            draw_prefix = font.measure(units(value), 0)
        out.layers.append(text_layer(f'Help label {i}', label,
            [at + draw_prefix, y + height // 2 + half - (size >> 1)], size, [0, 0, 0, 255], font))
        cursor = next_cursor


def new_marker(out, library, position, scale=10):
    e = cached(library, 'global_ui', 'env/env_global.dat', global_ui_environment)
    if len(e['particles']) < 4: raise ImageError('Missing new-marker particle definitions')
    for i, part in enumerate([e['base']] + e['particles'][:4]):
        s = dict(parameter=0, alignment=0 if i == 0 else 4, x=part[0] + position[0], y=part[1] + position[1],
                 sx=part[2], sy=part[3], w=part[4], h=part[5], rgba=[255] * 4)
        layer = blit(f'New marker part {i}', 1, 18, s, source='first.dat', scale=1 if i == 0 else scale / 10)
        out.layers.append(layer)


REVIEW_LATIN = str.maketrans({**{c: c - 0xfee0 for c in range(0xff01, 0xff5f)}, 0x3000: ' '})


def slot_review_line(name, value, position, size, rgba, font, *, right=None, center=False):
    """Set a single proportional reference line in the original card geometry."""
    from .choiceart import preview_label
    pairing = getattr(font, 'pair_spacing', None)
    value = readable(value, pairing).replace(font.format.break_char, ' ').translate(REVIEW_LATIN)
    value = ' '.join(value.partition('\0')[0].split())

    def packed_line(value):
        wire, width = preview_label(font, value, size, align='center' if center else 'left', allow_numbers=True)
        if width is None or (right is not None and width > right - position[0]): return None
        origin = list(position)
        if center: origin[0] -= font.measure(units(wire), size) // 2
        return text_layer(name, wire, origin, size, rgba, font)

    if layer := packed_line(value): return layer
    chars = units(value)
    # Fullwidth aliases in the patched atlas contain the designed Latin masks.
    # Keep ASCII when the active font does not supply a patched bitmap for it.
    shaped = narrow(''.join(chr(ord(c) + 0xfee0) if '!' <= c <= '~'
                            and chr(ord(c) + 0xfee0) in font.cached else c for c in chars), pairing)

    def dimensions(char):
        width = glyph_draw_width(font, char, size)
        return width, max(width if not char.isspace() else 0, font.measure(char, size), 1)

    widths = [dimensions(char) for char in shaped]
    x, y = position
    if right is not None and sum(advance for _, advance in widths) > right - x:
        ellipsis = '…'
        end_width = dimensions(ellipsis)
        remain = right - x - end_width[1]
        if remain < 0: return Layer(name, kind='text', destination=[x, y, 0, size], rgba=rgba, size=size)
        end = 0
        for _, advance in widths:
            if advance > remain: break
            remain -= advance; end += 1
        word_end = chars.rfind(' ', 0, end + 1)
        if word_end > 0: end = word_end
        if end < len(chars) and '\udc00' <= chars[end] <= '\udfff': end -= 1
        chars, shaped, widths = chars[:end] + ellipsis, shaped[:end] + ellipsis, widths[:end] + [end_width]
        if layer := packed_line(unicode_text(chars)): return layer

    extent = sum(advance for _, advance in widths)
    if center: x -= extent // 2
    cursor = x
    layer = Layer(name, kind='text', text=unicode_text(chars), destination=[x, y, extent, size], rgba=rgba, size=size)
    for char, (width, advance) in zip(shaped, widths):
        if not char.isspace(): layer.glyphs.append(dict(code=ord(char), rect=[cursor, y, width, size]))
        cursor += advance
    return layer


def slot_cards(out, e, library, font, state, first, selected, shift):
    mode, alpha = state.get('mode', 1), state.get('highlight', 255)
    review = state.get('spacing_review', False)
    pitch = e.sprite[0x168]['h'] + e.signed(0x164)
    start = len(out.layers)
    clip = e.rect[0x148]
    for row in range(max(0, first - 1), min(60, first + 5)):
        y = e.signed(0x160) + pitch * (row - first) - shift
        x = e.sprite[0x168]['x']; focused = row == selected and shift == 0
        palette = list(e.colors[0x420 if mode == 0 else 0x430][row % 2])
        palette[3] = alpha if focused else 128
        def card(entry, key, tint=None, aligned=False):
            shape = deepcopy(e.sprite[key]); shape['y'] += y
            if key not in (0x168, 0x18c): shape['x'] += x
            layer = blit(f'Slot {row + 1} part {key:X}', 13, entry, shape, tint=tint, anchored=aligned)
            out.layers.append(layer); return layer
        card(64, 0x168, palette); card(71, 0x18c, palette[:3] + [128]); card(65, 0x1d4)
        occupied = row == selected and state.get('occupied', True)
        if not occupied:
            card(72, 0x1b0); card(68, 0x1f8 if mode == 0 else 0x21c, palette[:3] + [255 if row == selected else 128])
        else:
            if state.get('context_image') and state.get('thumbnail', True):
                s = e.sprite[0x1b0]
                out.layers.append(quad('Sample thumbnail (chosen backdrop)', state['context_image'], [0, 0, 960, 544],
                                       [x + s['x'], y + s['y'], s['w'], s['h']]))
            values = ((0x468, (2026, 11, 5), 0x294, 0x2a4), (0x4a0, (12, 34), 0x29c, 0x2a4),
                      (0x4d8, (9, 1), 0x2a8, 0x2b0))
            card_right = x + e.sprite[0x1d4]['x'] + e.sprite[0x1d4]['w']
            text_right = {0x468: x + e.point[0x29c][0], 0x4a0: card_right, 0x4d8: x + e.point[0x2b4][0]}
            for field, args, point, scale in values:
                value = format_ui_numbers(e.strings[field], args); px, py = e.point[point]
                name = f'Slot {row + 1} sample metadata {field:X}'
                position, size = [x + px, y + py], math.floor(font.utility * e.floating(scale) + .5)
                packed=getattr(font,'packed_text',{})
                prefix=max((wire for wire in packed if value.startswith(wire)),key=len,default='')
                logical = packed[prefix] + value[len(prefix):] if prefix else value
                if review:
                    layer = slot_review_line(name, logical, position, size, [0, 0, 0, 255], font,
                                             right=text_right[field] - 4)
                else:
                    layer = text_layer(name, value, position, size, [0, 0, 0, 255], font)
                    layer.text = logical
                out.layers.append(layer)
            title,_,dialogue=state.get('text','').partition('\n')
            title=title or 'Preview chapter';dialogue=dialogue or 'Preview dialogue'
            packed_title = False
            if state.get('script_sample',False):
                from .choiceart import preview_label
                from .compositioncommon import calendar_environment
                from .textlayout import script_font_text
                chapter=cached(library,'calendar','env/env_script.dat',calendar_environment)
                title=script_font_text(font,title,0x3ec,{},'texts[1]',authored=True)
                title, packed_width = preview_label(font,title,int(font.utility*chapter['chapter']['scale']),align='left')
                packed_title = packed_width is not None
                wire=script_font_text(font,dialogue,0x64,{},'text',authored=True)
                parsed=font.format.ordinary(wire,geometry_only=True)
                if review:
                    dialogue = parsed['name'] + parsed['body']
                else:
                    glyphs=font.layout(parsed['body'],1000,e.floating(0x2cc),ruby=parsed['ruby'])
                    units_text=parsed['name']+''.join(chr(glyph['code']) for glyph in glyphs)
                    capacity=e.signed(0x2d0)
                    if capacity<=0:raise ImageError('Invalid slot dialogue capacity')
                    if len(units_text)>capacity:units_text=units_text[:capacity-1]+units(e.strings[0x580])
                    dialogue=unicode_text(units_text)
            if not review or packed_title:
                maximum = e.signed(0x2c0)
                if maximum <= 0: raise ImageError('Invalid slot title capacity')
                if len(units(title)) > maximum: title = unicode_text(units(title)[:maximum - 1]) + e.strings[0x580]
            for value, point, scale, label in ((title, 0x2b4, 0x2bc, 'chapter'),
                    (dialogue, 0x2c4, 0x2cc, 'dialogue')):
                px, py = e.point[point]
                name = f'Slot sample {label}'
                position, size = [x + px, y + py], math.floor(font.utility * e.floating(scale) + .5)
                if review and (label == 'dialogue' or not packed_title):
                    end = x + e.sprite[0x2d4]['x'] if label == 'dialogue' else card_right
                    layer = slot_review_line(name, value, position, size, [0, 0, 0, 255], font, right=end - 4)
                else:
                    layer = text_layer(name, value, position, size, [0, 0, 0, 255], font)
                    layer.text = readable(layer.text, getattr(font, 'pair_spacing', None))
                out.layers.append(layer)
        card(70, 0x240, e.color[0x418 if focused else 0x41c])
        number = format_ui_numbers('%02d', (row + 1,))
        size = math.floor(font.utility * e.floating(0x290) + .5); px, py = e.point[0x288]
        name = f'Slot number {row + 1}'
        rgba = [0, 0, 0, 255] if focused else [255] * 4
        if review:
            out.layers.append(slot_review_line(name, number, [x + px, y + py - size // 2], size, rgba, font, center=True))
        else:
            out.layers.append(text_layer(name, number, [x + px - font.measure(units(number), size) // 2, y + py - size // 2], size, rgba, font))
        if occupied and state.get('new', True):
            s = e.sprite[0x264]; new_marker(out, library, [x + s['x'], y + s['y']], state.get('marker_scale', 10))
        tint = [255, 255, 255, 255 if occupied and state.get('locked', False) else 128]
        card(66, 0x2d4, tint, True); card(67, 0x2f8, tint, True)
    for layer in out.layers[start:]: layer.clip = list(clip)


def slots_layout(library, state, font):
    if font is None: raise ImageError('Original font/layout data is required')
    e = cached(library, 'slots', 'env/env_saveload.dat', slot_environment)
    mode, selected = state.get('mode', 1), state.get('selected', 0)
    if mode not in (0, 1) or not 0 <= selected < 60: raise ImageError('Save/load mode or selection outside native limits')
    first = state.get('first', -1)
    if first == -1: first = min(56, selected // 4 * 4)
    if not 0 <= first <= 56: raise ImageError('First visible slot must be0–56')
    shift = int(e.point[0x158][1] * state.get('scroll', 0) / 100)
    review = state.get('spacing_review', False)
    out = Composition('Save / load · spacing review' if review else 'Save / load', notes=[
        'Spacing review uses proportional glyph advances and fits the full source dialogue to one line. It is an editor reference and does not affect game export.' if review
        else 'Game layout uses the fixed cursor and native saved-dialogue length. Authored chapter and date prefix use their packed glyphs when available.',
        'The selected row contains sample data. Personal saves are never read.',
        'Scroll and marker scale are static channel samples, not controller animation playback.'])
    out.layers.append(Layer('Save/load shade', kind='solid', destination=[0, 0, 960, 544], rgba=[0, 0, 0, 128 if mode == 0 else 200]))
    add = lambda key, bank, entry, **kw: backdrop_sprite(out, e, key, bank, entry, **kw)
    add(0x124, 13, 69); add(0xf8, 13, 63 if mode == 0 else 62, extent=e.point[0x11c]); add(0xd4, 13, 63 if mode == 0 else 62)
    slot_cards(out, e, library, font, state, first, selected, shift)
    for key in (0x330, 0x354, 0x380): add(key, 1, 10, source='first.dat', extent=e.point[0x378] if key == 0x354 else None)
    height = e.point[0x378][1]; step = height // 59; thumb = max(step, 12)
    offset = int((height - 12) * selected / 59) if step < 12 else step * selected
    origin = e.sprite[0x354]['y'] + offset; width = e.point[0x410][0]
    top, bottom = e.sprite[0x3a4]['h'], e.sprite[0x3ec]['h']; middle = thumb - top - bottom
    add(0x3a4, 1, 11, source='first.dat', offset=(0, origin), extent=[width, top])
    add(0x3c8, 1, 11, source='first.dat', offset=(0, origin), extent=[width, middle])
    add(0x3ec, 1, 11, source='first.dat', offset=(0, origin + e.sprite[0x3c8]['y'] + middle), extent=[width, top])
    add(0x7c, 1, 6, source='first.dat', anchored=False); button_help(out, library, font, mode)
    add(0xa0, 1, 2, source='first.dat', anchored=False, tint=[255] * 4)
    return out


def backlog_environment(data):
    e = Fields(data, legacy=False); rd, many = e.read, e.many
    rd('point', 0xbe08); rd('scalar', 0xbe10); rd('point', 0xbe14); many('color', 0xbe1c, 3)
    rd('sprite', 0xbe28); rd('rect', 0xbe4c); many('sprite', 0xbe5c, 3, 36)
    rd('point', 0xbec8); rd('sprite', 0xbed0); many('point', 0xbef4, 5, 8); rd('scalar', 0xbf1c)
    e.rows = [[e.r.word('i') for _ in range(4)] for _ in range(e.r.count())]
    rd('sprite', 0xbf30); rd('sprite', 0xbf54); rd('point', 0xbf78); many('sprite', 0xbf80, 4, 36)
    many('scalar', 0xc010, 2); rd('sprite', 0xc018); rd('sprite', 0xc03c); rd('point', 0xc060)
    many('sprite', 0xc068, 4, 36); rd('point', 0xc0f8); rd('point', 0xc100)
    e.voices = [sprite(e.r, False) for _ in range(e.r.count())]
    rd('scalar', 0xc118); rd('sprite', 0xc11c); rd('sprite', 0xc140); rd('rect', 0xc164)
    many('scalar', 0xc174, 12); many('color', 0xc1a4, 3); rd('ints', 0)
    from .uitextcodec import ui_string
    e.question = ui_string(e.r,'dialog prompt'); e.text_colors = [color(e.r.word()) for _ in range(e.r.count())]
    if not 0 < e.floating(0xc180) <= 16 or not 1 <= e.signed(0xc188) <= 3 or len(e.voices) < 2:
        raise ImageError('Invalid backlog layout capacity or text scale')
    return e.finish()


def backlog_layout(library, state, font):
    if font is None: raise ImageError('Original font/layout data is required')
    e = cached(library, 'backlog', 'env/env_backlog.dat', backlog_environment)
    entries = state.get('text', '').splitlines(); count = len(entries)
    if count > 200: raise ImageError('Backlog sample exceeds native200-record capacity')
    selected = state.get('selected', 0) if count else -1
    if count and not 0 <= selected < count: raise ImageError('Selected backlog row outside sample entries')
    visible = e.signed(0xc188); first = state.get('first', -1)
    if first == -1: first = min(max(0, count - visible), max(0, selected - visible + 1))
    if not 0 <= first <= max(0, count - visible): raise ImageError('First backlog row outside sample list')
    pitch = e.point[0xc100][1]
    if pitch <= 0: raise ImageError('Backlog row pitch must be positive')
    shift = int(pitch * state.get('scroll', 0) / 100)
    out = Composition('Backlog', notes=['Sample dialogue rows only; personal history and voice audio are not accessed.',
        'One sample-text line per retained row. Scroll/voice icon are static channel samples, not a live history controller.'])
    shade = e.color[0xc1a4][:]
    out.layers.append(Layer('Backlog shade', kind='solid', destination=[0, 0, 960, 544], rgba=shade))
    add = lambda key, bank, entry, **kw: backdrop_sprite(out, e, key, bank, entry, **kw)
    add(0xbe28, 1, 33); add(0xc11c, 1, 6, source='first.dat'); button_help(out, library, font)
    add(0xc140, 1, 2, source='first.dat', tint=[255] * 4, anchored=False)
    for i, key in enumerate((0xbf80, 0xbfc8)):
        layer = add(key, 1, 38, scale=1 if i == 0 else -1)
        if i == 1:
            # ResolveUiSprite takes independent axes. Only the vertical source
            # coordinate reverses for the lower arrow.
            layer.source[2] = abs(layer.source[2])
    if count:
        start = len(out.layers)
        selected_y = e.point[0xbef4][1] + e.point[0xbf04][1] + pitch * (selected - first) - shift
        add(0xbe80, 1, 34, offset=(0, selected_y))
        frame_y = selected_y + e.sprite[0xbe80]['y']
        middle = e.point[0xbec8][1] - e.sprite[0xbed0]['h']
        add(0xbea4, 1, 34, offset=(0, frame_y), extent=[e.sprite[0xbea4]['w'], middle])
        add(0xbed0, 1, 34, offset=(0, frame_y + e.sprite[0xbea4]['y'] + middle))
        for row in range(max(0, first - 1), min(count, first + visible + 1)):
            y = e.point[0xbef4][1] + pitch * (row - first) - shift
            add(0xbe5c, 1, 35, offset=(0, y))
            root_y = y + e.sprite[0xbe5c]['y'] + e.sprite[0xbe5c]['h']
            x = e.point[0xbef4][0] + e.point[0xbf04][0]
            from .textlayout import script_font_text
            wire = script_font_text(font, entries[row], 0x64, {}, 'text', authored=True)
            parsed = font.format.ordinary(wire, geometry_only=True)
            scale = e.floating(0xc180); size = int(font.utility * scale)
            rgb = e.text_colors[3 if state.get('read_color', False) and len(e.text_colors) > 3 else 0]
            if parsed['name']:
                name = unicode_text(parsed['name']); measured = font.measure(parsed['name'], size)
                out.layers.append(text_layer(f'Backlog speaker {row}', name,
                    [x - measured // 2, root_y + e.point[0xbefc][1] - size // 2], size, rgb, font))
            body, _ = plain_layer(f'Backlog dialogue {row}', unicode_text(parsed['body']),
                [x, root_y + e.point[0xbf04][1]], e.signed(0xbf1c), scale, rgb, font)
            add_shadow(out, body)
            if parsed['ruby'] or parsed['keywords']: out.notes.append('Ruby/keyword decorations in sampled backlog rows are not composed yet.')
            if state.get('voice', True):
                frame = state.get('voice_frame', 0)
                if not 0 <= frame < len(e.voices): raise ImageError('Voice icon frame outside authored table')
                shape = deepcopy(e.voices[frame]); shape['y'] += root_y
                out.layers.append(blit(f'Backlog voice icon {row}', 1, 36, shape))
        for layer in out.layers[start:]: layer.clip = list(e.rect[0xbe4c])
    add(0xbf54, 1, 40, extent=e.point[0xbf78]); add(0xbf30, 1, 40)
    add(0xc018, 1, 10, source='first.dat'); add(0xc03c, 1, 10, source='first.dat', extent=e.point[0xc060])
    add(0xc068, 1, 10, source='first.dat')
    if count:
        track = e.point[0xc060][1]; height = track / count
        position = int((track - 12) * selected / (count - 1)) if height < 12 and count > 1 else int(height * selected)
        height = max(12, int(height)); y = e.sprite[0xc03c]['y'] + position
        middle = height - e.sprite[0xc08c]['h'] - e.sprite[0xc0d4]['h']; width = e.point[0xc0f8][0]
        add(0xc08c, 1, 11, source='first.dat', offset=(0, y), extent=[width, e.sprite[0xc08c]['h']])
        add(0xc0b0, 1, 11, source='first.dat', offset=(0, y), extent=[width, middle])
        add(0xc0d4, 1, 11, source='first.dat', offset=(0, y + e.sprite[0xc0b0]['y'] + middle), extent=[width, e.sprite[0xc0d4]['h']])
    out.notes = list(dict.fromkeys(out.notes))
    return out


ADAPTERS = {'slots': slots_layout, 'backlog': backlog_layout}
PARAMETERS = {
    'slots': [('mode', 'Screen mode', 'enum', 1, [(0, 'Save'), (1, 'Load')]),
              ('script_sample','Sample from script text','bool',False),
              ('spacing_review','Proportional spacing review (editor only)','bool',False),
              ('first', 'First row (-1 automatic)', 'int', -1, -1, 56),
              ('scroll', 'Scroll channel %', 'int', 0, 0, 100), ('highlight', 'Highlight alpha', 'int', 255, 0, 255),
              ('occupied', 'Selected slot occupied', 'bool', True), ('locked', 'Selected slot protected', 'bool', False),
              ('new', 'Selected slot new', 'bool', True), ('marker_scale', 'New particle scale /10', 'int', 10, 0, 100),
              ('thumbnail', 'Use backdrop thumbnail', 'bool', True)],
    'backlog': [('first', 'First row (-1 automatic)', 'int', -1, -1, 199), ('scroll', 'Scroll channel %', 'int', 0, 0, 100),
                ('read_color', 'Read-message color', 'bool', False), ('voice', 'Show voice icons', 'bool', True),
                ('voice_frame', 'Voice icon frame', 'int', 0, 0, 1)],
}
