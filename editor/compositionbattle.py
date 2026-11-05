"""Battle UI consumer bindings, independent of actors, controllers and media."""
from copy import deepcopy
import struct
from .composition import Composition, Layer, sprite, text_layer
from .compositioncommon import cached, plain_layer, selection_environment, add_shadow
from .compositionmodes import visual_sprite
from .scriptcodec import Reader
from .imagecodec import ImageError
from .text import color, units


def battle_environment(data):
    r = Reader(data); r.take(15); words = lambda n: [r.word('i') for _ in range(n)]
    table = lambda fn: [fn() for _ in range(r.count())]; sp = lambda: sprite(r)
    pts = lambda: table(lambda: words(2)); rects = lambda: table(lambda: words(4))
    colors = lambda: table(lambda: color(r.word()))
    e = dict(minimum=r.word('i'), thresholds=table(lambda: r.word('i')), gauge=sp(), bars=[words(4) for _ in range(2)])
    e['versus'] = [sp() for _ in range(4)]; e['name_scale'], e['caption_scale'] = r.word('f'), r.word('f')
    e['name_positions'], e['name_sizes'], e['name_offsets'] = pts(), pts(), table(lambda: r.word('i'))
    e['names'], e['caption_positions'], e['padding'], e['colors'] = table(r.string), pts(), r.word('i'), colors(); r.take(4)
    e['dialogue_positions'], e['bubble'], e['bubble_scale'] = [words(2) for _ in range(2)], sp(), r.word('f')
    e['dialogue_offsets'], e['width'] = [words(2) for _ in range(2)], r.word('i')
    e['auxiliary_sprites'] = [sp() for _ in range(5)]; e['auxiliary_points'] = table(pts)
    r.take(2 * 34 + 4 + 34 + 12); r.take(r.count() * 4); r.take(34 + 16 + 3 * 34)
    e['result_sprites'] = [sp(), sp()]; e['glyph_color'] = color(r.word())
    e['equal_rectangles'], e['equal_positions'] = rects(), pts(); e['result_sprites'].extend([sp(), sp()])
    e['upper_color'], e['lower_color'] = color(r.word()), color(r.word())
    e['upper_rectangles'], e['lower_rectangles'] = rects(), rects()
    e['upper_positions'], e['lower_positions'], e['upper_bases'], e['lower_bases'] = pts(), pts(), pts(), pts()
    e['timing'] = words(13); e['upper_scale'] = struct.unpack('<f', struct.pack('<i', e['timing'][2]))[0]
    e['gauge_duration'], e['display_per_point'], e['x_per_point'], e['scale_per_point'] = r.word('i'), r.word('i'), r.word('i'), r.word('f')
    e['result_poses'] = words(4)
    e['choice_positions'], e['choice_sprites'], e['card_scale'] = pts(), table(sp), r.word('f')
    e['choice_offsets'] = [words(2) for _ in range(2)]
    e['pulses'] = [[r.word('f'), r.word('f'), r.word('i')] for _ in range(3)]
    e['labels'], e['label_positions'], e['label_scale'] = table(r.string), pts(), r.word('f')
    e['fill_colors'], e['frame_colors'], e['hud'] = colors(), colors(), [sp() for _ in range(3)]
    e['timer_position'], e['timer_source'], e['timer_stride'], e['timer_advance'] = words(2), words(4), r.word('i'), r.word('i')
    e['choice_timing'] = words(3)
    # Later service/effect data has no consumer in these UI draw functions.
    return e


def positioned_plain(name, value, center, y, width, scale, rgba, font, *, offsets=None, tags=False):
    layer, height = plain_layer(name, value, [0, 0], width, scale, rgba, font, font_tags=tags)
    extent = text_extent(font, value, width, scale, tags=tags)
    lines = max((glyph['rect'][1] for glyph in layer.glyphs), default=0)
    offset = offsets[int(lines == 0)] if offsets else [0, 0]
    dx, dy = center + offset[0] - extent // 2, y + offset[1]
    layer.destination[0:2] = [dx, dy]
    for glyph in layer.glyphs: glyph['rect'][0] += dx; glyph['rect'][1] += dy
    return layer


def text_extent(font, value, width, scale, *, tags=False):
    text, _ = font.format.prepare(value.replace('\r\n', '\n').replace('\n', font.format.break_char), font_tags=tags)
    glyphs = font.layout(text, width, scale)
    return max((g['x'] + int(g['advance'] * scale) for g in glyphs), default=0)


def widget_sprite(out, name, entry, bubble, point, base_scale, pulse, rgba):
    """Native widget anchors unscaled geometry, then pulses about its base center."""
    shape = deepcopy(bubble); x, y = point; w, h = shape['w'], shape['h']
    ax, ay = shape['alignment'] % 3, shape['alignment'] // 3
    x -= w // 2 if ax == 1 else w if ax == 2 else 0
    y -= h // 2 if ay == 1 else h if ay == 2 else 0
    pw, ph = int(w * abs(pulse)), int(h * abs(pulse))
    shape['x'], shape['y'] = int(x + w * base_scale * .5) - pw // 2, int(y + h * base_scale * .5) - ph // 2
    return visual_sprite(out, name, f'resource.dat:16/{entry}', shape, anchored=False, scale_x=pulse, scale_y=pulse, tint=rgba)


def introduction(out, e, state, font):
    add = lambda name, entry, shape, **kw: visual_sprite(out, name, f'resource.dat:16/{entry}', shape, **kw)
    for i in range(2): add('Battle introduction emblem', 29 + i, e['versus'][i], alpha=255)
    name_size, size, panel_size = int(font.utility * e['name_scale']), int(font.utility * e['caption_scale']), int(36 * e['caption_scale'])
    for side in range(2):
        character = state.get('side_' + str(side), side); dimensions = e['name_sizes'][character]
        pos, base = e['name_positions'][side], e['caption_positions'][side]; dw, dh = dimensions
        caption = state.get('caption_' + str(side), '') or 'Introduction preview'
        width = e['padding'] + font.measure(units(caption), 0 if side else panel_size)
        name = add('Battle name panel', 23, e['versus'][3], tint=e['colors'][character])
        name.destination = [pos[0] - (dw if side else 0), pos[1] - dh // 2, dw, dh]
        bar = add('Battle caption panel', 24, e['versus'][2], tint=e['colors'][character])
        bar.destination = [base[0] - (width if side else 0), base[1] - e['versus'][2]['h'] // 2, width, e['versus'][2]['h']]
        for label, value, center, y, pixels in (
            ('Battle participant name', e['names'][character], pos[0] + (-(dw // 2) if side else dw // 2) + e['name_offsets'][character], pos[1] - name_size // 2, name_size),
            ('Battle introduction caption', caption, base[0] + (-(width // 2) if side else width // 2), base[1] - size // 2, size)):
            x = center - font.measure(units(value), pixels) // 2
            out.layers.append(text_layer(label, value, [x, y], pixels, [255] * 4, font))


def dialogue(out, e, state, font):
    for side in range(2):
        kind = state.get('bubble_' + str(side), 0)
        if kind == 3: continue
        shape = deepcopy(e['bubble']); shape['x'], shape['y'] = e['dialogue_positions'][side]
        alpha = state.get('opacity', 11) * 255 // 11
        for entry, tint in (((4, 1, 7)[kind], [255] * 3), ((5, 2, 8)[kind], [0] * 3)):
            visual_sprite(out, 'Battle dialogue bubble', f'resource.dat:16/{entry}', shape,
                          scale_x=e['bubble_scale'], scale_y=e['bubble_scale'], tint=tint + [alpha])
        value = state.get('dialogue_' + str(side), '') or 'Dialogue preview'
        parsed = font.format.ordinary(value)
        layer = positioned_plain('Battle dialogue text', parsed['body'], *e['dialogue_positions'][side],
                                 e['width'], font.scale, font.unread, font, offsets=e['dialogue_offsets'])
        add_shadow(out, layer)
    out.notes.append('Dialogue text is fully revealed; ruby/keyword visual decorations and actor animation are not composed.')


def choices(out, library, e, state, font):
    values = state.get('choices', '').splitlines() or ['Choice 1', 'Choice 2', 'Choice 3']
    if len(values) > 3: raise ImageError('Battle choices have up to three visible cards; row0 is the separate timeout route')
    shared = cached(library, 'selection', 'env/env_script_select.dat', selection_environment)
    for control, value in enumerate(values):
        kind = state.get('type_' + str(control), control)
        if kind < 3:
            low, high, _ = e['pulses'][kind]; pulse = int((low + (high - low) * state.get('pulse', 0) / 100) * 100) / 100
            for entry, rgba in (((4, 1, 7)[kind], e['fill_colors'][control]), ((6, 3, 9)[kind], e['frame_colors'][control])):
                widget_sprite(out, 'Battle choice widget', entry, e['bubble'], e['choice_positions'][control], e['card_scale'], pulse, rgba)
        layer = positioned_plain('Battle choice text', value, *e['choice_positions'][control], e['width'], font.scale,
                                 shared['text_colors'][int(state.get('visited', False))], font, offsets=e['choice_offsets'], tags=True)
        out.layers.append(layer)
        point, offset = e['choice_positions'][control], e['label_positions'][control]
        size = int(font.utility * e['label_scale']); label = e['labels'][control]
        out.layers.append(text_layer('Battle direct-button label', label,
            [point[0] + offset[0] - font.measure(units(label), size) // 2, point[1] + offset[1] - size // 2], size, [255] * 4, font))
    for entry, shape in zip((32, 11, 10), e['hud']): visual_sprite(out, 'Battle selection HUD', f'resource.dat:16/{entry}', shape)
    seconds = state.get('seconds', 30)
    for digit, value in enumerate((seconds // 10, seconds % 10)):
        source = e['timer_source'][:]; source[0] += value * e['timer_stride']
        out.layers.append(Layer('Battle timer digit', asset='resource.dat:16/25', source=source,
            destination=[e['timer_position'][0] + digit * e['timer_advance'], e['timer_position'][1], *source[2:]], rgba=[0, 0, 0, 255]))
    out.notes.append('Visible cards represent command rows1–3. Row0 is a timeout destination and has no card. Countdown/pulse are static samples.')


def result(out, e, state):
    outcome = state.get('outcome', 0)
    if not 0 <= outcome < 3: raise ImageError('Battle result outcome outside0..2')
    def emit(name, entry, shape, position, rgba, scale=1):
        shape = deepcopy(shape); shape['x'], shape['y'] = position
        return visual_sprite(out, name, f'resource.dat:16/{entry}', shape, tint=rgba, scale_x=scale, scale_y=scale)
    def glyph(entry, rectangle, position, scale=1):
        shape = deepcopy(e['result_sprites'][1]); shape['sx'], shape['sy'], shape['w'], shape['h'] = rectangle
        emit('Battle result lettering', entry, shape, position, e['glyph_color'], scale)
    if outcome == 2:
        for i, position in enumerate(e['equal_positions']):
            emit('Equal result background', 15, e['result_sprites'][0], position, e['result_sprites'][0]['rgba'])
            emit('Equal result frame', 14, e['result_sprites'][1], position, e['glyph_color'])
            glyph(20, e['equal_rectangles'][i], position)
    else:
        side = 1 if outcome == 0 else 0
        for i, position in enumerate(e['upper_positions']):
            p = [position[axis] + e['upper_bases'][side][axis] for axis in range(2)]
            emit('Upper result background', 15, e['result_sprites'][0], p, e['result_sprites'][2]['rgba'])
            emit('Upper result frame', 14, e['result_sprites'][1], p, e['upper_color'])
            glyph(22, e['upper_rectangles'][i], p, e['upper_scale'])
        for i in range(len(e['upper_positions'])):
            p = [e['lower_positions'][i][axis] + e['lower_bases'][side][axis] for axis in range(2)]
            p[1] += e['timing'][0]
            emit('Lower result background', 34, e['result_sprites'][2], p, e['result_sprites'][2]['rgba'])
            emit('Lower result frame', 33, e['result_sprites'][3], p, e['lower_color'])
            glyph(21, e['lower_rectangles'][i], p)


def battle_layout(library, state, font):
    if font is None: raise ImageError('Original font/layout data is required')
    e = cached(library, 'battle_ui', 'env/env_tukkomi.dat', battle_environment); view = state.get('view', 0)
    out = Composition('Battle UI', notes=['Static native UI layout. Choose a context backdrop; actor/Live2D poses, media and mode timelines are not reconstructed.'])
    if view in (0, 3):
        for i, bounds in enumerate(e['bars']):
            bounds = bounds[:]
            if i: bounds[1] = 544 - e['bars'][0][3]
            out.layers.append(Layer('Battle letterbox', kind='solid', destination=bounds, rgba=[0, 0, 0, 255]))
    if view != 3 or state.get('outcome', 0) == 2:
        shape = deepcopy(e['gauge']); display = state.get('display', -1)
        if display >= 0: shape['x'] = display
        visual_sprite(out, 'Battle divider gauge', 'resource.dat:16/0', shape)
    if view == 0: introduction(out, e, state, font)
    elif view == 1: dialogue(out, e, state, font)
    elif view == 2: choices(out, library, e, state, font)
    elif view == 3: result(out, e, state)
    else: raise ImageError('Unknown battle composition view')
    return out


def parameter_visible(name, view):
    if name.startswith(('side_', 'caption_')): return view == 0
    if name.startswith(('bubble_', 'dialogue_')): return view == 1
    if name in ('choices', 'seconds', 'pulse', 'visited') or name.startswith('type_'): return view == 2
    if name == 'outcome': return view == 3
    return True


ADAPTERS = {'battle': battle_layout}
PARAMETERS = {'battle': [
    ('view', 'Screen', 'enum', 0, [(0, 'Introduction'), (1, 'Dialogue'), (2, 'Timed choices'), (3, 'Results')]),
    ('display', 'Divider X (-1 authored)', 'int', -1, -1, 960),
    ('side_0', 'Left participant ID', 'int', 0, 0, 5), ('side_1', 'Right participant ID', 'int', 1, 0, 5),
    ('caption_0', 'Left introduction caption', 'text', ''), ('caption_1', 'Right introduction caption', 'text', ''),
    ('bubble_0', 'Left bubble type', 'enum', 0, [(0, 'Type0'), (1, 'Type1'), (2, 'Type2'), (3, 'Hidden')]),
    ('bubble_1', 'Right bubble type', 'enum', 0, [(0, 'Type0'), (1, 'Type1'), (2, 'Type2'), (3, 'Hidden')]),
    ('dialogue_0', 'Left dialogue', 'text', ''), ('dialogue_1', 'Right dialogue', 'text', ''),
    ('choices', 'Visible choices (one per line)', 'text', ''),
    *[('type_' + str(i), 'Card' + str(i + 1) + ' type', 'enum', i, [(0, 'Type0'), (1, 'Type1'), (2, 'Type2'), (3, 'No widget')]) for i in range(3)],
    ('seconds', 'Countdown seconds', 'int', 30, 0, 99), ('pulse', 'Pulse sample %', 'int', 0, 0, 100),
    ('visited', 'Previously read choices', 'bool', False),
    ('outcome', 'Outcome', 'enum', 0, [(0, 'Left wins'), (1, 'Right wins'), (2, 'Equal')]),
]}
