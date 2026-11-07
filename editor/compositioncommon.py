"""Shared choices, calendar/chapter and modal compositions from authored layouts."""
from copy import deepcopy
import math
from .composition import Composition, Layer, sprite, blit, text_layer
from .imagecodec import ImageError
from .scriptcodec import Reader
from .text import color, units, unicode_text
from . import environments


def cached(library, key, path, decoder):
    if key not in library.decoded: library.decoded[key] = decoder(library.read(path))
    library.verify()
    return library.decoded[key]


def quad(name, asset, source, destination, rgba=(255, 255, 255, 255)):
    return Layer(name, asset=asset, source=list(source), destination=list(destination), rgba=list(rgba))


def plain_layer(name, value, origin, width, scale, rgba, font, *, font_tags=False):
    """Reuse the Python line formatter with native line-height and glyph-cell drawing."""
    if font is None: raise ImageError('Load original font/layout data before composing text')
    value = value.replace('\r\n', '\n').replace('\n', font.format.break_char)
    text, ranges = font.format.prepare(value, font_tags=font_tags)
    glyphs = font.layout(text, width, scale)
    size = int(font.utility * scale)
    if not 0 < size <= 1024: raise ImageError('Text scale outside composition range')
    height = (max((g['line'] for g in glyphs), default=-1) + 1) * int(font.height * scale + font.leading)
    layer = Layer(name, kind='text', text=unicode_text(text), size=size,
                  destination=[*origin, width, height], rgba=list(rgba))
    for index, g in enumerate(glyphs):
        c = chr(g['code']); cached_glyph = font.cached.get(c)
        drawn = math.ceil(cached_glyph[3] * size / font.bitmap_height) if cached_glyph else (
            size // 2 if 0x20 <= g['code'] <= 0x7e or 0xff61 <= g['code'] <= 0xffa0 else size)
        glyph = dict(code=g['code'], rect=[origin[0] + g['x'], origin[1] + g['y'], drawn, size])
        for start, end, rgb in ranges:
            if start <= index < end: glyph['rgb'] = rgb; break
        layer.glyphs.append(glyph)
    return layer, height


def add_shadow(out, layer):
    shadow = deepcopy(layer); shadow.name += ' shadow'; shadow.rgba = [0, 0, 0, layer.rgba[3]]
    for glyph in shadow.glyphs: glyph['rect'][0] += 1; glyph['rect'][1] += 1
    out.layers.extend([shadow, layer])


def selection_environment(data):
    r = Reader(data); r.take(3); font_id = r.word('H'); scalars = [r.word('i') for _ in range(4)]
    colors = [color(r.word()) for _ in range(3)]; shapes = [sprite(r, False) for _ in range(3)]
    points = [[[r.word('i'), r.word('i')] for _ in range(r.count())] for _ in range(2)]
    words = [r.word('i') for _ in range(6)]; scale = r.word('f'); text_colors = [color(r.word()) for _ in range(2)]
    if not math.isfinite(scale) or scale <= 0: raise ImageError('Invalid choice text scale')
    return dict(font=font_id, scalars=scalars, colors=colors, sprites=shapes, points=points, words=words,
                scale=scale, text_colors=text_colors)


def choices_layout(library, state, font):
    e = cached(library, 'selection', 'env/env_script_select.dat', selection_environment)
    entries = state.get('text', '').splitlines()
    if not entries: entries = ['Choice 1', 'Choice 2']
    points = e['points'][0 if len(entries) == 2 else 1]
    if len(entries) > len(points): raise ImageError(f'Choice count exceeds authored capacity {len(points)}')
    selected = state.get('selected', 0)
    if selected < -1 or selected >= len(entries): raise ImageError('Selected choice is outside sample entries')
    alpha = state.get('progress', 100) * 255 // 100
    out = Composition('Scenario choices', notes=['Settled choice cards; one sample-text line per entry. Selection is preview state, not a branch action.'])
    size = int((font.utility if font else 27) * e['scale'])
    for i, value in enumerate(entries):
        is_selected = i == selected; x, y = points[i]
        card = deepcopy(e['sprites'][0 if is_selected else 1]); card.update(alignment=0, x=x, y=y)
        out.layers.append(blit(f'Choice card {i}', 1, 18 if is_selected else 19, card, tint=[255, 255, 255, alpha]))
        if is_selected:
            marker = deepcopy(e['sprites'][2]); marker['alignment'] = 0
            out.layers.append(blit('Selected choice marker', 1, 20, marker, offset=(x, y), alpha=alpha))
        rgb = e['text_colors'][int(state.get('visited', False))][:3] + [alpha]
        center_x = x + e['words'][4]; text_x = center_x - (font.measure(units(value), size) // 2 if font else len(value) * size // 4)
        out.layers.append(text_layer(f'Choice label {i}', value, [text_x, y + e['words'][5]], size, rgb, font))
    return out


def calendar_environment(data):
    r = Reader(data); r.take(19)
    base = sprite(r); labels = [sprite(r) for _ in range(r.count())]
    colors = [color(r.word()) for _ in range(r.count())]; month = sprite(r); day = sprite(r)
    ranges = [[r.word('i'), r.word('i')] for _ in range(r.count())]
    return dict(base=base, labels=labels, colors=colors, month=month, day=day, ranges=ranges,
                chapter=environments.chapter_text(data))


def calendar_layout(library, state, font):
    e = cached(library, 'calendar', 'env/env_script.dat', calendar_environment)
    out = Composition('Calendar / chapter banners', notes=['Static calendar and optional chapter banner, independent of story date and transition state.'])
    if state.get('show_date', True):
        month, day = state.get('month', 9), state.get('day', 1)
        if not 1 <= month <= 12 or not 1 <= day <= 31: raise ImageError('Calendar month/day outside native ranges')
        normalize = lambda m: m + (12 if m < 9 else 0)
        palette = state.get('palette', -1)
        if palette == -1:
            palette = next((i for i, (a, b) in enumerate(e['ranges']) if normalize(a) <= normalize(month) <= normalize(b)), None)
        if palette is None or not 0 <= palette < min(len(e['labels']), len(e['colors'])):
            raise ImageError('No authored calendar palette for this month; choose an explicit palette')
        out.layers.append(blit('Calendar base', 1, 4, e['base'], tint=e['colors'][palette]))
        out.layers.append(blit('Season label', 1, 4, e['labels'][palette]))
        m, d = deepcopy(e['month']), deepcopy(e['day'])
        m['sx'] += (month + 3 if month < 9 else month - 9) * m['w']
        d['sx'] += (day - 1) % 10 * d['w']; d['sy'] += (day - 1) // 10 * (d['h'] + 1)
        out.layers.append(blit(f'Month {month}', 1, 5, m)); out.layers.append(blit(f'Day {day}', 1, 6, d))
    if state.get('show_banner', True):
        menu = library.get('system'); chapter = state.get('chapter', 0)
        if not 0 <= chapter < len(menu.colors[0x26c]): raise ImageError('Chapter palette outside environment table')
        out.layers.append(blit('Chapter banner', 1, 50, menu.sprite[0x1e4], tint=menu.colors[0x26c][chapter]))
        size = int((font.utility if font else 27) * e['chapter']['scale'])
        texts = state.get('text', '').splitlines()[:2]
        for i, value in enumerate(texts):
            x, y = e['chapter']['positions'][i]
            out.layers.append(text_layer(f'Chapter caption {i}', value, [x, y - size // 2], size, [0, 0, 0, 255], font))
    return out


def dialog_environment(data):
    r = Reader(data); r.take(3)
    words = lambda n: [r.word('i') for _ in range(n)]
    header = words(2); parts = [words(6) for _ in range(r.count())]; focus = words(6)
    buttons = [[words(2) for _ in range(r.count())] for _ in range(3)]
    vectors = [words(2) for _ in range(2)]; rectangles = [words(6) for _ in range(2)]
    offset, decoration, extent, settings = words(2), words(6), words(2), words(10)
    scales = [r.word('f') for _ in range(2)]; separator = r.string(); colors = [color(r.word()) for _ in range(4)]
    groups = [[[r.string(), r.string()] for _ in range(r.count())] for _ in range(r.count())]
    final = color(r.word())
    return dict(header=header, parts=parts, focus=focus, buttons=buttons, vectors=vectors,
                rectangles=rectangles, offset=offset, decoration=decoration, extent=extent,
                settings=settings, scales=scales, separator=separator, colors=colors, groups=groups, final=final)


def dialog_layout(library, state, font):
    e = cached(library, 'dialogs', 'env/env_dialog.dat', dialog_environment)
    p, settings = e['parts'], e['settings']
    if len(p) < 9 or p[0][5] <= 0 or settings[4] < 0: raise ImageError('Invalid dialog tile layout')
    group = state.get('group', 0)
    if group < -1 or group >= len(e['groups']): raise ImageError(f'Button group must be -1 or 0–{len(e["groups"]) - 1}')
    labels = e['groups'][group] if group >= 0 else []
    if len(labels) > 3: raise ImageError('Dialog supports at most three buttons')
    alpha = state.get('progress', 100) * 255 // 100
    prompt, height = plain_layer('Dialog prompt', state.get('text', ''), [0, 0], settings[6], e['scales'][1], e['colors'][0][:3] + [alpha], font)
    button_size = int(font.utility * e['scales'][0])
    content_height = height + settings[0] * 2 + (button_size + settings[5] if labels else 0)
    body = (content_height + p[0][5] - 1) // p[0][5] * p[0][5]
    width, frame_height = settings[3], body + p[0][5] + p[6][5]
    x, y = 480 - width // 2, 272 - frame_height // 2
    top = 272 - body // 2 + (body - content_height) // 2 + settings[0]
    px, py = x + settings[1], top + settings[2]
    prompt.destination[:2] = [px, py]
    for glyph in prompt.glyphs: glyph['rect'][0] += px; glyph['rect'][1] += py
    out = Composition('Shared dialog', notes=['Measured static modal with authored button group; no confirmation/save action is executed.'])
    out.layers.append(Layer('Modal shade', kind='solid', destination=[0, 0, 960, 544], rgba=[0, 0, 0, 90]))
    def emit(name, entry, src, dst): out.layers.append(quad(name, f'first.dat:1/{entry}', src, dst, [255, 255, 255, alpha]))
    rows = body // p[0][5]
    if (settings[4] + 2) * (rows + 2) > 100000: raise ImageError('Dialog exceeds tile budget')
    def row(first, at_y):
        at_x = x
        indices = [first] + [first + 1] * settings[4] + [first + 2]
        for j, index in enumerate(indices):
            part = p[index]; emit(f'Frame tile {first}:{j}', 0, part[2:], [at_x, at_y, part[4], part[5]])
            at_x += p[0][4] if first == 3 and j == 0 else part[4]
    row(0, y); at_y = y + p[2][5]
    for i in range(rows): row(3, at_y); at_y += p[5][5]
    row(6, at_y)
    pattern = e['rectangles'][0]
    if pattern[4] <= 0 or pattern[5] <= 0: raise ImageError('Invalid dialog pattern dimensions')
    columns, pattern_rows = width // pattern[4], frame_height // pattern[5]
    if (columns + 1) * (pattern_rows + 1) > 100000: raise ImageError('Dialog pattern exceeds tile budget')
    at_x, at_y = x + e['vectors'][0][0], y + e['vectors'][0][1]
    for r in range(pattern_rows + 1):
        h = frame_height % pattern[5] - e['vectors'][1][1] if r == pattern_rows else pattern[5]
        for c in range(columns):
            emit(f'Pattern {r}:{c}', 9, [pattern[2], pattern[3], pattern[4], h], [at_x, at_y, pattern[4], h]); at_x += pattern[4]
        w = width % pattern[4] - e['vectors'][1][0]
        emit(f'Pattern remainder {r}', 9, [pattern[2], pattern[3], w, h], [at_x, at_y, w, h])
    strip, ornament = e['rectangles'][1], e['decoration']
    emit('Separator strip', 0, strip[2:], [x + strip[0], y + strip[1], width - e['offset'][0], e['offset'][1]])
    emit('Dialog ornament', 1, ornament[2:], [x + ornament[0], y + ornament[1], ornament[4], ornament[5]])
    add_shadow(out, prompt)
    if labels:
        positions = e['buttons'][len(labels) - 1]
        if len(positions) < len(labels): raise ImageError('Missing dialog button positions')
        baseline = top + height + settings[5]; focus = e['focus']
        for i, pair in enumerate(labels):
            bx, by = x + positions[i][0], baseline + positions[i][1]
            entries = (3, 5) if i == state.get('selected', 0) else (4,)
            for entry in entries: emit(f'Button {i} layer {entry}', entry, focus[2:], [bx - focus[4] // 2, by - focus[5] // 2, focus[4], focus[5]])
            measured = font.measure(units(pair[1]), button_size)
            out.layers.append(text_layer(f'Button label {i}', pair[1], [bx - measured // 2, by - button_size // 2],
                                         button_size, e['colors'][1][:3] + [alpha], font))
    return out


ADAPTERS = {'choices': choices_layout, 'calendar': calendar_layout, 'dialogs': dialog_layout}

# These fields belong to preview state only. The view creates only controls used
# by the selected family, rather than accumulating disabled fields for every port.
PARAMETERS = {
    'choices': [('visited', 'Previously chosen text', 'bool', False)],
    'calendar': [('month', 'Month', 'int', 9, 1, 12), ('day', 'Day', 'int', 1, 1, 31),
                 ('palette', 'Date palette (-1 auto)', 'int', -1, -1, 99),
                 ('show_date', 'Show calendar', 'bool', True), ('show_banner', 'Show chapter banner', 'bool', True)],
    'dialogs': [('group', 'Authored button group', 'int', 0, -1, 99)],
}
