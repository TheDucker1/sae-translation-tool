"""Shared choices, calendar/chapter and modal compositions from authored layouts."""
from copy import deepcopy
import math
from .composition import Composition, Layer, sprite, blit, text_layer
from .imagecodec import ImageError
from .scriptcodec import Reader
from .text import color, glyph_draw_width, units, unicode_text
from .pairspacing import readable
from .textlayout import script_font_text
from . import environments


def cached(library, key, path, decoder):
    if key not in library.decoded: library.decoded[key] = decoder(library.read(path))
    library.verify()
    return library.decoded[key]


def quad(name, asset, source, destination, rgba=(255, 255, 255, 255)):
    return Layer(name, asset=asset, source=list(source), destination=list(destination), rgba=list(rgba))


def plain_layer(name, value, origin, width, scale, rgba, font, *, font_tags=False, glyphs=None):
    """Reuse the Python line formatter with native line-height and glyph-cell drawing."""
    if font is None: raise ImageError('Load original font/layout data before composing text')
    value = value.replace('\r\n', '\n').replace('\n', font.format.break_char)
    text, ranges = font.format.prepare(value, font_tags=font_tags)
    if glyphs is None:glyphs = font.layout(text, width, scale)
    size = int(font.utility * scale)
    if not 0 < size <= 1024: raise ImageError('Text scale outside composition range')
    height = (max((g['line'] for g in glyphs), default=-1) + 1) * int(font.height * scale + font.leading)
    layer = Layer(name, kind='text', text=unicode_text(readable(text, getattr(font, 'pair_spacing', None))), size=size,
                  destination=[*origin, width, height], rgba=list(rgba))
    for index, g in enumerate(glyphs):
        drawn = glyph_draw_width(font,chr(g['code']),size)
        glyph = dict(code=g['code'], rect=[origin[0] + g['x'], origin[1] + g['y'], drawn, size])
        for start, end, rgb in ranges:
            if start <= index < end: glyph['rgb'] = rgb; break
        layer.glyphs.append(glyph)
    return layer, height


def add_shadow(out, layer):
    shadow = deepcopy(layer); shadow.name += ' shadow'; shadow.rgba = [0, 0, 0, layer.rgba[3]]
    for glyph in shadow.glyphs: glyph['rect'][0] += 1; glyph['rect'][1] += 1
    out.layers.extend([shadow, layer])


def dialogue_annotations(out,font,body,glyphs,parsed,origin,scale):
    from .presentation import ruby_positions
    keywords={i for start,end,_ in parsed['keywords'] for i in range(start,end)}
    if keywords:
        color=font.keyword_colors[0][:3]+[body.rgba[3]]
        underline=Layer('Keyword underline',kind='text',destination=body.destination.copy(),rgba=color,size=body.size)
        for index,glyph in enumerate(body.glyphs):
            if index not in keywords:continue
            glyph['rgb']=color[:3]
            pos=glyph['rect'][:2]
            mark=text_layer('',font.format.break_char,pos,body.size,color,font)
            underline.glyphs.extend(mark.glyphs)
        add_shadow(out,underline)
    for _,reading,x,y,size in ruby_positions(font,glyphs,origin,scale,parsed['ruby']):
        value=unicode_text(reading)
        out.layers.append(text_layer('Ruby shadow',value,[x+1,y+1],size,font.ruby_shadow[:3]+[body.rgba[3]],font))
        out.layers.append(text_layer('Ruby reading',value,[x,y],size,body.rgba,font))


def selection_environment(data):
    r = Reader(data); r.take(3); font_id = r.word('H'); scalars = [r.word('i') for _ in range(4)]
    colors = [color(r.word()) for _ in range(3)]; shapes = [sprite(r, False) for _ in range(3)]
    points = [[[r.word('i'), r.word('i')] for _ in range(r.count())] for _ in range(2)]
    words = [r.word('i') for _ in range(6)]; scale = r.word('f'); text_colors = [color(r.word()) for _ in range(2)]
    if not math.isfinite(scale) or scale <= 0: raise ImageError('Invalid choice text scale')
    return dict(font=font_id, scalars=scalars, colors=colors, sprites=shapes, points=points, words=words,
                scale=scale, text_colors=text_colors)


def choice_label_layer(name, value, center, y, size, rgba, font):
    from .choiceart import preview_label
    wire, ink_width = preview_label(font, value, size)
    advance = font.measure(units(wire), size) if font else len(wire) * size // 2
    layer = text_layer(name, wire, [center - advance // 2, y], size, rgba, font)
    if ink_width is not None:
        layer.text = value
        layer.destination[0] = center - ink_width // 2
        layer.destination[2] = ink_width
    return layer


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
        value = script_font_text(font, value, 0x65, {}, f'choices[{i}].label', authored=True)
        out.layers.append(choice_label_layer(f'Choice label {i}', value, x + e['words'][4], y + e['words'][5], size, rgb, font))
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
        from .choiceart import preview_label
        for i, value in enumerate(texts):
            value = script_font_text(font, value, 0x3EC, {}, f'texts[{i}]', authored=True)
            x, y = e['chapter']['positions'][i]
            wire, width = preview_label(font, value, size, align='left')
            layer = text_layer(f'Chapter caption {i}', wire, [x, y - size // 2], size, [0, 0, 0, 255], font)
            if width is not None:
                layer.text = value
                layer.destination[2] = width
            out.layers.append(layer)
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
    value = state.get('text', '')
    if getattr(font, 'asset_sha256', None):
        from .fontstyle import LAYOUT, match_style
        value = match_style(value, font, LAYOUT)['text']
    prompt, height = plain_layer('Dialog prompt', value, [0, 0], settings[6], e['scales'][1], e['colors'][0][:3] + [alpha], font)
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
    def emit(name, entry, src, dst):
        layer=quad(name, f'first.dat:1/{entry}', src, dst, [255, 255, 255, alpha])
        out.layers.append(layer)
        return layer
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
    frame_clip=[x,y,width,frame_height]
    for r in range(pattern_rows + 1):
        h = frame_height % pattern[5] - e['vectors'][1][1] if r == pattern_rows else pattern[5]
        for c in range(columns):
            emit(f'Pattern {r}:{c}', 9, [pattern[2], pattern[3], pattern[4], h], [at_x, at_y, pattern[4], h]).clip=frame_clip
            at_x += pattern[4]
        w = width % pattern[4] - e['vectors'][1][0]
        emit(f'Pattern remainder {r}', 9, [pattern[2], pattern[3], w, h], [at_x, at_y, w, h]).clip=frame_clip
    strip, ornament = e['rectangles'][1], e['decoration']
    emit('Separator strip', 0, strip[2:], [x + strip[0], y + strip[1], width - e['offset'][0], e['offset'][1]])
    emit('Dialog ornament', 1, ornament[2:], [x + ornament[0], y + ornament[1], ornament[4], ornament[5]])
    add_shadow(out, prompt)
    if labels:
        from .choiceart import preview_label
        positions = e['buttons'][len(labels) - 1]
        if len(positions) < len(labels): raise ImageError('Missing dialog button positions')
        baseline = top + height + settings[5]; focus = e['focus']
        for i, pair in enumerate(labels):
            bx, by = x + positions[i][0], baseline + positions[i][1]
            entries = (3, 5) if i == state.get('selected', 0) else (4,)
            for entry in entries: emit(f'Button {i} layer {entry}', entry, focus[2:], [bx - focus[4] // 2, by - focus[5] // 2, focus[4], focus[5]])
            value=pair[1]
            if value in {'OK','ＯＫ'}:
                value,_=preview_label(font,value,button_size)
            measured = font.measure(units(value), button_size)
            out.layers.append(text_layer(f'Button label {i}', value, [bx - measured // 2, by - button_size // 2],
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
