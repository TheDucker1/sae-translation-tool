"""Read-only profile/approach UI snapshots; no mode controllers or personal state."""
from copy import deepcopy
from .archive import Archive
from .composition import Composition, Layer, blit, sprite, text_layer
from .compositioncommon import cached, plain_layer, selection_environment, dialog_layout
from .imagecodec import ImageError
from .scriptcodec import Reader
from .text import color, units
from . import profileflow


def profile_environment(data):
    r = Reader(data); r.take(15)
    sp = lambda: sprite(r, False)
    words = lambda n: [r.word('i') for _ in range(n)]
    table = lambda fn: [fn() for _ in range(r.count())]
    e = dict(intro=r.word('i'), background=[sp() for _ in range(3)], wave=r.word('i'))
    for name in ('frame', 'before', 'header', 'stretch'): e[name] = sp()
    e['stretch_size'] = words(2); e['early'], e['late'] = sp(), sp(); r.take(4)
    e['after'] = [sp() for _ in range(4)]; e['statbar'] = sp(); e['stat_colors'] = table(lambda: color(r.word()))
    e['portrait'], e['portrait_area'], e['name'] = sp(), words(4), sp()
    e['navigation'] = [sp() for _ in range(2)]
    e['navigation_travel'], e['navigation_duration'] = r.word('f'), r.word('i')
    e['arrow_travel'], e['arrow_duration'] = r.word('f'), r.word('i')
    e['arrows'] = [[sp() for _ in range(2)] for _ in range(2)]; e['event_buttons'] = [words(4) for _ in range(2)]
    e['itemframe'], e['positions'], e['selector'], e['categories'] = sp(), table(lambda: words(2)), sp(), table(sp)
    e['label_offset'], e['label_scale'] = words(2), r.word('f'); r.take(12); e['carousel'] = r.word('i')
    e['description_positions'] = table(lambda: words(2)); e['description_scale'], e['columns'] = r.word('f'), r.word()
    e['footer'] = sp(); r.take(36); e['result_progress'] = r.word('i'); r.take(8); r.string()
    table(lambda: (r.string(), r.word())); r.string(); r.take(4); e['reflection'] = sp()
    e['labels'] = [table(r.string) for _ in range(3)]; e['format'] = r.string()
    e['marker'], e['marker_positions'], e['secondary'], e['marker_step'] = sp(), table(lambda: words(2)), r.word('i'), words(2)
    e['stat_duration'] = r.word('i')
    e['response_window'], e['response_origin'], e['response_width'], e['response_scale'] = sp(), words(2), r.word('i'), r.word('f')
    from .uitextcodec import ui_string
    e['confirmation'] = ui_string(r,'dialog prompt'); e['response_rectangles'] = [words(4) for _ in range(2)]
    e['response_cursors'] = [sp() for _ in range(2)]; e['cursor_duration'], e['cursor_travel'] = r.word('i'), r.word('f')
    e['stats'] = table(lambda: table(lambda: r.word('i')))
    if len(e['stats']) > 4 or any(len(row) > 3 for row in e['stats']): raise ImageError('Profile stats exceed native capacity')
    if r.pos != len(data): raise ImageError('Unexpected profile environment tail')
    return e


def approach_environment(data):
    r = Reader(data); r.take(15); words = lambda n: [r.word('i') for _ in range(n)]
    table = lambda fn: [fn() for _ in range(r.count())]; sp = lambda: sprite(r)
    e = dict(sprites=[sp() for _ in range(6)], particle_positions=[words(2) for _ in range(2)], labels=table(sp))
    e['parent_sprites'] = [sp() for _ in range(2)]; e['text_offset'], e['parent_marker'], e['hit'] = words(2), sp(), words(4)
    e['arrows'] = [table(sp), table(sp)]; e['arrow_hits'] = table(lambda: words(4))
    e['points'] = [table(lambda: words(2)) for _ in range(2)]; e['selected_offset'] = r.word('i')
    e['points'].extend(table(lambda: words(2)) for _ in range(4))
    e['colors'] = [color(r.word())]; e['scale'] = r.word('f'); e['colors'].extend(color(r.word()) for _ in range(2))
    e['rectangles'], e['offset'] = [words(4) for _ in range(2)], words(2)
    e['distance'], e['scroll_duration'] = words(2)
    for name in ('fill', 'frame', 'content', 'mask'): e[name] = sp()
    e['text_origin'], e['text_width'], e['text_scale'] = words(2), r.word('i'), r.word('f')
    e['icon'] = sp(); middle = sp(); sp(); success, failure = sp(), sp(); sp()
    e['outcomes'] = [failure, middle, success]; e['gauge_timing'] = words(4); e['mission_timing'] = words(6)
    e['result_timing'] = words(9); e['cursor_positions'] = [words(2) for _ in range(2)]; e['fade'] = r.word('i')
    e['overlay'] = r.word('i'); e['character_colors'] = table(lambda: color(r.word()))
    # Remaining data belongs to particle/services settings; these UI consumers stop here.
    return e


def profile_catalogue(library, ordinal):
    key = ('profile_items', ordinal)
    if key not in library.decoded:
        text = library.member('first.dat', (3, ordinal)).decode('utf-16-le')
        rows = []
        for row in profileflow.rows(text, '\t'):
            if not row or row[0] != 'ON': continue
            if len(row) < 5: raise ImageError('Truncated profile item row')
            rows.append(dict(id=profileflow.number(row[1]), category=profileflow.number(row[2]),
                             name=row[3].split('\0', 1)[0], description=row[4].split('\0', 1)[0]))
        if len(rows) != 30: raise ImageError('Profile catalogue requires thirty authored rows')
        library.decoded[key] = rows
    return library.decoded[key]


def profile_scene(library, scene):
    key = ('profile_scene', scene)
    if key not in library.decoded:
        result = []
        for row in profileflow.rows(library.member('resource.dat', (3, 1, scene)).decode('cp932'), ','):
            if not row or row[0] != 'ON': continue
            if len(row) < 3: raise ImageError('Truncated profile scene row')
            if row[1] == 'CHARA': result.append(dict(id=profileflow.number(row[2]), events=[]))
            elif row[1] == 'DATA':
                if not result or len(row) < 12: raise ImageError('Truncated profile event')
                result[-1]['events'].append(dict(values=list(map(profileflow.number, row[2:7])),
                    response=row[10].split('\0', 1)[0], presentation=list(map(profileflow.number, row[8:10]))))
        if not 1 <= len(result) <= 4 or any(not 0 <= c['id'] < 4 or len(c['events']) != 10 for c in result):
            raise ImageError('Profile scene requires 1–4 characters with ten events each')
        library.decoded[key] = result
    return library.decoded[key]


def description_lines(text, separator, columns):
    if not separator or columns <= 0: raise ImageError('Invalid profile description layout')
    out = []
    for part in units(text).split('\0', 1)[0].split(units(separator)):
        for _ in range(2):
            if len(part) <= columns: break
            out.append(part[:columns]); part = part[columns:]
        out.append(part)
    if len(out) > 3: raise ImageError('Profile description exceeds three owner lines')
    return out


def visual_sprite(out, name, asset, shape, *, scale_x=1., scale_y=1., **kw):
    layer = blit(name, 0, 0, shape, **kw); layer.asset = asset
    w, h = int(shape['w'] * abs(scale_x)), int(shape['h'] * abs(scale_y))
    x, y = shape['x'] + kw.get('offset', (0, 0))[0], shape['y'] + kw.get('offset', (0, 0))[1]
    if kw.get('anchored', True):
        ax, ay = shape['alignment'] % 3, shape['alignment'] // 3
        x -= w // 2 if ax == 1 else w if ax == 2 else 0
        y -= h // 2 if ay == 1 else h if ay == 2 else 0
    layer.destination = [x, y, w, h]
    layer.source[2] = shape['w'] if scale_x > 0 else -shape['w']
    layer.source[3] = shape['h'] if scale_y > 0 else -shape['h']
    out.layers.append(layer); return layer


def mode_result(out, library, e, state, font, text, *, profile=None):
    """Settled shared result pass. Alpha-test stencil uses binary texture coverage."""
    character, category = state['character_id'], state['category']
    if not 0 <= character < len(e['character_colors']) or not 0 <= category < 3:
        raise ImageError('Result character/category outside authored tables')
    add = lambda name, entry, shape, **kw: visual_sprite(out, name, f'resource.dat:1/{entry}', shape, **kw)
    out.layers.append(Layer('Result shade', kind='solid', destination=[0, 0, 960, 544], rgba=[0, 0, 0, e['overlay']]))
    if profile is not None: add('Profile result reflection', 22, profile['reflection'], scale_y=-1, alpha=255)
    add('Result banner', 22, e['sprites'][0], alpha=255)
    mask = add('Character-colored result mask', 10, e['mask'], tint=e['character_colors'][character][:3] + [255])
    coverage = deepcopy(mask); coverage.name = 'Result stencil coverage'; coverage.rgba = [255] * 4
    out.layers.append(Layer('Result stencil target', kind='target', target='result-mask', rgba=[0] * 4, children=[coverage]))
    content = add('Result masked content', 13, e['content'], alpha=255)
    content.mask = '@target:result-mask'
    add('Result frame', 11, e['frame'], alpha=255)
    visual_sprite(out, 'Character result icon', f'resource.dat:3/2/{character}/{category}', e['icon'], alpha=255)
    add('Result completed progress', 12, e['fill'], alpha=255)
    if text:
        layer, _ = plain_layer('Result text', text, e['text_origin'], e['text_width'], e['text_scale'], [0, 0, 0, 255], font, font_tags=True)
        out.layers.append(layer)
    if state.get('cursor', True):
        for shape, p in zip(library.get('message')['cursors'], e['cursor_positions']):
            shape = deepcopy(shape); shape['x'], shape['y'] = p
            add('Result advance cursor', 2, shape)
    add('Result outcome', 14 + category, e['outcomes'][category], alpha=255)


def profile_layout(library, state, font):
    if font is None: raise ImageError('Original font/layout data is required')
    e = cached(library, 'profile_ui', 'env/env_otaku_mode.dat', profile_environment)
    view = state.get('view', 0)
    if view >= 3: return approach_layout(library, state, font)
    scene = profile_scene(library, state.get('scene', 0)); ordinal = state.get('ordinal', 0)
    if not 0 <= ordinal < len(scene): raise ImageError('Profile character ordinal outside selected scene')
    character = scene[ordinal]; cid = character['id']; rows = profile_catalogue(library, ordinal)
    selector = state.get('event', 0)
    if not 0 <= selector < 10 or any(not 0 <= event['values'][0] < len(rows) for event in character['events']):
        raise ImageError('Profile selector/event row outside authored table')
    selected_event = character['events'][(selector + 3) % 10]
    phase = 12 if view == 1 else 5 if state.get('character_focus', False) else 6
    out = Composition('Profiles / approach', notes=['Settled profile UI; scene/selector and stat controls are preview samples. No mode, saves or media run.'])
    add = lambda name, entry, shape, **kw: visual_sprite(out, name, f'resource.dat:3/3/{entry}', shape, **kw)
    if view == 2:
        add('Profile response window', 1, e['response_window'])
        text, _ = plain_layer('Profile response text', selected_event['response'], e['response_origin'],
                              e['response_width'], e['response_scale'], [0, 0, 0, 255], font)
        out.layers.append(text)
        if state.get('cursor', True):
            for shape in e['response_cursors']: add('Profile response cursor', 0, shape)
        out.notes.append('Response pose/background are external scene presentation; choose a context backdrop. This view composes the response UI only.')
        return out
    add('Profile backdrop', 2, e['background'][0]); wave = state.get('wave', 0)
    remaining = e['background'][1]['w'] - wave
    for i in (1, 2):
        shape = deepcopy(e['background'][i]); shape.update(sx=wave, w=remaining); add('Profile wave first part', 21 + i, shape)
        shape = deepcopy(e['background'][i]); shape['x'] = remaining; add('Profile wave wrapped part', 21 + i, shape)
    if phase >= 12:
        for point in e['marker_positions'][:3]:
            shape = deepcopy(e['marker']); shape['x'], shape['y'] = point; add('Profile result stat marker', 17, shape)
    shape = deepcopy(e['stretch']); source = shape['w'], shape['h']; shape['w'], shape['h'] = e['stretch_size']
    add('Profile stretched header', 24, shape).source[2:] = list(source)
    for name, entry, shape in (('Profile header', 24, e['header']), ('Profile phase overlay', 24, e['early' if phase <= 5 else 'late']),
                               ('Profile frame', 3, e['frame']), ('Profile footer', 11, e['footer'])): add(name, entry, shape)
    start = len(out.layers); gray = 200 if phase <= 5 else 255
    for i, point in enumerate(e['positions'][:8]):
        shape = deepcopy(e['itemframe']); shape['x'], shape['y'] = point
        add(f'Profile item frame {i}', 18, shape, tint=[gray, gray, gray, 255])
    add('Profile event selector', 19, e['selector'], offset=e['positions'][3], alpha=128 if phase <= 5 else 255)
    for i, point in enumerate(e['positions'][:8]):
        index = character['events'][(selector + i) % 10]['values'][0]; row = rows[index]
        if not 0 <= row['category'] < len(e['categories']): raise ImageError('Profile item category outside sprite table')
        add(f'Profile event category {i}', 16, e['categories'][row['category']], offset=point)
        x, y = point; dx, dy = e['label_offset']; tint = 128 if phase <= 5 else 0
        out.layers.append(text_layer(f'Profile event label {i}', row['name'], [x + dx, y + dy],
                                    int(font.utility * e['label_scale']), [tint] * 3 + [255], font))
    for layer in out.layers[start:]: layer.clip = [500, 96, 460, 300]
    if phase in (6, 7):
        for i, shapes in enumerate(e['arrows']): add('Profile event arrow', 10, shapes[1], scale_y=1 if not i else -1, tint=[255] * 4)
    # Same global prefix, then the separate profile-description separator.
    separator = profile_separator(library)
    row = rows[selected_event['values'][0]]; tint = 128 if phase <= 5 else 0
    for value, point in zip(description_lines(row['description'], separator, e['columns']), e['description_positions']):
        out.layers.append(text_layer('Profile description', value, point, int(font.utility * e['description_scale']), [tint] * 3 + [255], font))
    add('Profile portrait backing', 9, e['before'])
    visual_sprite(out, 'Selected profile portrait', f'resource.dat:3/0/{cid}', e['portrait'])
    for entry, shape in zip((20, 7, 8, 5), e['after']): add('Profile HUD frame', entry, shape)
    for i, rgba in enumerate(e['stat_colors']):
        stat = state.get('stat_' + str(i), -1)
        if stat == -1: stat = e['stats'][cid][i]
        shape = deepcopy(e['statbar']); shape['x'] += e['after'][i + 1]['x']; shape['y'] += e['after'][i + 1]['y']
        add('Profile stat fill', 6, shape, scale_x=min(1., stat / 100), tint=rgba)
    add('Profile character name', 12 + cid, e['name'])
    if phase <= 5:
        for i, shape in enumerate(e['navigation']): add('Profile character navigation', 4, shape, scale_x=1 if not i else -1, tint=[255] * 4)
    if view == 1:
        result_env = cached(library, 'approach_ui', 'env/env_approach.dat', approach_environment)
        meta = dict(environment=e, catalog=[profile_catalogue(library, n) for n in range(4)])
        text = profileflow.result_text(meta, ordinal, cid, selected_event)
        mode_result(out, library, result_env, dict(state, character_id=cid, category=selected_event['values'][1]), font, text, profile=e)
    elif state.get('confirmation', False):
        modal = dialog_layout(library, dict(text=e['confirmation'], group=1, selected=1, progress=100), font)
        out.layers.extend(modal.layers); out.notes.extend(modal.notes)
    return out


def profile_separator(library):
    key = 'profile_separator'
    if key not in library.decoded:
        r = Reader(library.read('env/env_global.dat')); r.take(3)
        for _ in range(4): r.string()
        r.take(8)
        for _ in range(9): r.string()
        r.take(30 * 4)
        for stride, extra in ((24, 32), (24, 16), (4, 0)):
            r.take(r.count() * stride); r.take(extra)
        for _ in range(r.count()): r.string()
        r.string(); r.take(8); r.string(); r.string(); library.decoded[key] = r.string()
    return library.decoded[key]


def approach_topics(value):
    result = [[field.strip() for field in line.split('|')] for line in value.splitlines() if line.strip()]
    if not result: result = [['Topic ' + str(i + 1), 'Choice 1', 'Choice 2'] for i in range(3)]
    if len(result) > 6 or any(not 2 <= len(row) <= 4 for row in result):
        raise ImageError('Use up to six lines: Topic | Choice1 | Choice2 | Choice3 (one to three choices)')
    return result


def approach_layout(library, state, font):
    e = cached(library, 'approach_ui', 'env/env_approach.dat', approach_environment); view = state['view']; cid = state.get('approach_character', 0)
    out = Composition('Approach UI', notes=['Settled approach UI with preview-local gauge, choices, history and result. Scene actors/particles and mode timing are not simulated.'])
    add = lambda name, entry, shape, **kw: visual_sprite(out, name, f'resource.dat:1/{entry}', shape, **kw)
    add('Approach gauge frame', 24, e['sprites'][3]); fill = deepcopy(e['sprites'][4]); height = int(fill['h'] * state.get('gauge', 50) / 100)
    fill['sy'] -= height - fill['h']; fill['h'] = height; add('Approach gauge fill', 25, fill)
    if view == 3:
        for name, entry, shape in (('Approach mission banner', 22, e['sprites'][0]), ('Mission left', 32, e['sprites'][1]),
                                   ('Mission right', 32, e['sprites'][2]), ('Mission character', 26 + cid, e['labels'][cid])): add(name, entry, shape, alpha=255)
    elif view == 4: approach_choices(out, library, e, state, font)
    elif view == 5:
        text = state.get('result_text', '').strip() or 'Approach result preview'
        mode_result(out, library, e, dict(state, character_id=cid, category=2 if state.get('success', True) else 0), font, text)
    return out


def approach_choices(out, library, e, state, font):
    shared = cached(library, 'selection', 'env/env_script_select.dat', selection_environment)
    topics = approach_topics(state.get('topics', '')); count = len(topics); selected = state.get('selected', 0)
    children = state.get('child_focus', False); child = state.get('child', 0); weight = .5 if children else 1.
    if not 0 <= selected < count or children and not 0 <= child < len(topics[selected]) - 1:
        raise ImageError('Approach topic/child selection outside preview entries')
    visited, used = state.get('visited', False), state.get('used', False)
    def label(name, value, point, size, rgba, baseline=False):
        x, y = point; x -= font.measure(units(value), size) // 2
        out.layers.append(text_layer(name, value, [x, y - size if baseline else y], size, rgba, font))
    def put(name, entry, shape, point, **kw):
        shape = deepcopy(shape); shape['x'], shape['y'] = point
        return visual_sprite(out, name, f'resource.dat:1/{entry}', shape, **kw)
    def parent(index, point, focused):
        x, y = point; x += e['selected_offset'] if focused else 0
        shape = e['parent_sprites'][1]
        put('Approach topic card', 31 if focused else 30, shape, [x, y], alpha=int(shape['rgba'][3] * weight))
        rgba = shared['text_colors'][int(visited)][:3] + [int(255 * weight)]
        label('Approach topic', topics[index][0], [x + e['text_offset'][0], y + e['text_offset'][1]], int(font.utility * e['scale']), rgba, True)
    def marker(point):
        put('Approach topic marker', 37, e['parent_marker'], point, tint=e['arrows'][0][0]['rgba'][:3] + [int(255 * weight)])
    if count >= 5:
        for i in range(2):
            shape = deepcopy(e['arrows'][i][0]); shape['alignment'] = e['arrows'][i][0]['alignment']
            layer = put('Approach carousel arrow', 39, shape, e['points'][5][i], tint=e['arrows'][0][0]['rgba'][:3] + [int(255 * weight)])
            if i: layer.source[3] *= -1
        start = len(out.layers)
        for i in range(6): parent((selected - 2 + i) % count, [e['offset'][0], e['offset'][1] + e['distance'] * i], i == 2)
        marker(e['points'][3][1])
        for layer in out.layers[start:]: layer.clip = e['rectangles'][1][:]
    else:
        table = 0 if count == 3 else 1
        for i in range(count):
            parent(i, e['points'][table][i], i == selected)
            if i == selected: marker(e['points'][table + 2][i])
    if children:
        values = topics[selected][1:]; points = shared['points'][0 if len(values) == 2 else 1]
        for i, value in enumerate(values):
            x, y = points[i]; shape = deepcopy(shared['sprites'][0]); shape['alignment'] = e['arrows'][0][0]['alignment']
            put('Approach choice card', 18 if i == child else 19, shape, [x, y], tint=e['colors'][1] if used else [255] * 4)
            if i == child:
                mark = deepcopy(shared['sprites'][2]); mark['alignment'] = 0
                put('Approach child marker', 20, mark, [x + mark['x'], y + mark['y']])
            rgba = e['colors'][2] if visited and used else shared['text_colors'][int(visited)]
            label('Approach choice text', value, [x + shared['words'][4], y + shared['words'][5]], int(font.utility * shared['scale']), rgba)


def preview_limits(library, state):
    view = state['view']
    if view < 3:
        count = len(Archive(library.member('resource.dat', (3, 1))).entries)
        scene = profile_scene(library, min(state['scene'], count - 1))
        return dict(scene=count - 1, ordinal=len(scene) - 1)
    if view == 4:
        topics = approach_topics(state.get('topics', '')); selected = min(state['selected'], len(topics) - 1)
        return dict(selected=len(topics) - 1, child=len(topics[selected]) - 2)
    return {}


def parameter_visible(name, view):
    if name in ('scene', 'ordinal', 'event'): return view < 3
    if name in ('wave', 'stat_0', 'stat_1', 'stat_2'): return view < 2
    if name in ('character_focus', 'confirmation'): return view == 0
    if name == 'approach_character': return view >= 3
    if name == 'gauge': return view >= 3
    if name in ('topics', 'child_focus', 'child', 'visited', 'used'): return view == 4
    if name in ('success', 'result_text'): return view == 5
    return True


ADAPTERS = {'profile': profile_layout}
PARAMETERS = {'profile': [
    ('view', 'Screen', 'enum', 0, [(0, 'Profile selection'), (1, 'Profile result'), (2, 'Profile response UI'),
                                (3, 'Approach mission / gauge'), (4, 'Approach topics / choices'), (5, 'Approach result')]),
    ('scene', 'Profile scene ID', 'int', 0, 0, 999), ('ordinal', 'Scene character ordinal', 'int', 0, 0, 3),
    ('event', 'Carousel selector', 'int', 0, 0, 9), ('character_focus', 'Character selection focus', 'bool', False),
    ('confirmation', 'Show confirmation', 'bool', False), ('wave', 'Backdrop wave offset', 'int', 0, 0, 959),
    ('stat_0', 'Stat1 (-1 authored)', 'int', -1, -1, 100), ('stat_1', 'Stat2 (-1 authored)', 'int', -1, -1, 100),
    ('stat_2', 'Stat3 (-1 authored)', 'int', -1, -1, 100),
    ('approach_character', 'Approach character pack', 'int', 0, 0, 3), ('gauge', 'Approach gauge', 'int', 50, 0, 100),
    ('topics', 'Topics: topic | choices', 'text', ''), ('child_focus', 'Child choice focus', 'bool', False),
    ('child', 'Selected child', 'int', 0, 0, 2), ('visited', 'Previously read', 'bool', False), ('used', 'Previously used children', 'bool', False),
    ('success', 'Successful result', 'bool', True), ('result_text', 'Result sample text', 'text', ''),
]}
