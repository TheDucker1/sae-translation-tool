"""Discoverable, bounded state for the same UI adapters used by the GUI."""
from copy import deepcopy
from .composition import FAMILIES
from .compositioncommon import PARAMETERS as COMMON, cached, dialog_environment, calendar_environment
from .compositionlists import PARAMETERS as LISTS, backlog_environment
from .compositionsettings import PARAMETERS as SETTINGS, settings_environment, parameter_visible as settings_visible
from .compositionextras import PARAMETERS as EXTRAS, preview_limits as extras_limits, parameter_visible as extras_visible
from .compositionmodes import PARAMETERS as MODES, preview_limits as mode_limits, parameter_visible as mode_visible
from .compositionbattle import PARAMETERS as BATTLE, battle_environment, parameter_visible as battle_visible
from .imagecodec import ImageError

PARAMETERS = COMMON | LISTS | SETTINGS | EXTRAS | MODES | BATTLE
FAMILY_NAMES = {key: (label, coverage) for key, label, coverage in FAMILIES}


def field(name, label, kind, default, *bounds):
    result = dict(name=name, label=label, type={'text': 'string', 'int': 'integer', 'bool': 'boolean', 'enum': 'integer'}[kind], default=default, active=True)
    if kind == 'int': result.update(minimum=bounds[0], maximum=bounds[1])
    if kind == 'text': result.update(max_length=4096)
    if kind == 'enum': result['choices'] = [dict(value=v, label=text) for v, text in bounds[0]]
    return result


def controls(family):
    if family not in FAMILY_NAMES: raise ImageError('Unknown UI scene family; call list_ui_scenes')
    rows = []
    def add(*args): rows.append(field(*args))
    if family in ('title', 'system', 'choices', 'dialogs', 'slots', 'backlog', 'settings', 'extras', 'profile', 'test'):
        add('selected', 'Selected row/cell (zero-based)', 'int', 0, -1 if family in ('choices', 'dialogs') else 0, 999)
    if family == 'title':
        add('character', 'Title presentation variant', 'int', 0, 0, 3); add('press_start', 'Press-start layout', 'bool', False)
    if family in ('title', 'message', 'choices', 'dialogs'): add('progress', 'Layout channel sample % (not a timeline)', 'int', 100, 0, 100)
    if family in ('title', 'message'): add('angle', 'Ring/Auto angle in degrees', 'int', 0, 0, 359)
    if family == 'message':
        add('speaker', 'Speaker plate ID (-1 hides it)', 'int', 0, -1, 8)
        for name in ('skip', 'skip_gesture', 'auto'): add(name, name.replace('_', ' ').title() + ' active', 'bool', False)
    if family in ('message', 'battle'): add('opacity', 'Window opacity', 'int', 11, 0, 11)
    if family in ('message', 'profile'): add('cursor', 'Advance cursor', 'bool', True)
    if family in ('system', 'calendar'): add('chapter', 'Chapter palette', 'int', 0, -1 if family == 'system' else 0, 999)
    defaults = dict(message='', system='Chapter preview', choices='Choice 1\nChoice 2', calendar='Chapter preview\nSubtitle preview',
                    dialogs='Preview prompt', slots='Preview chapter\nPreview dialogue', backlog='Sample dialogue1\nSample dialogue2\nSample dialogue3')
    if family in defaults: add('text', 'Sample text (preview only)', 'text', defaults[family])
    if family != 'title':
        rows.append(dict(name='context_image', label='Explicit backdrop texture ID (background/CG)', type='string_or_null', default=None, max_length=256, active=True))
    rows.extend(field(*spec) for spec in PARAMETERS.get(family, ()))
    return {row['name']: row for row in rows}


def validate_values(schema, state):
    for name, value in state.items():
        if name not in schema: raise ImageError(f'Unknown scene parameter: {name}; call describe_ui_scene')
        f = schema[name]; kind = f['type']
        if kind == 'boolean' and type(value) is not bool: raise ImageError(name + ' requires a boolean')
        if kind == 'integer':
            if type(value) is not int: raise ImageError(name + ' requires an integer')
            if 'minimum' in f and not f['minimum'] <= value <= f['maximum']: raise ImageError(f'{name} outside {f["minimum"]}..{f["maximum"]}')
            if 'choices' in f and value not in [x['value'] for x in f['choices']]: raise ImageError(name + ' is outside its authored choices')
        if kind in ('string', 'string_or_null'):
            if value is None and kind == 'string_or_null': continue
            if not isinstance(value, str) or len(value) > f['max_length']: raise ImageError(name + ' requires bounded text')
            value.encode('utf-8')


def resolve_state(library, family, supplied=None):
    schema = controls(family); original_schema = deepcopy(schema); supplied = supplied or {}
    if not isinstance(supplied, dict): raise ImageError('Scene state must be an object')
    validate_values(schema, supplied)
    state = {name: deepcopy(spec['default']) for name, spec in schema.items()}; state.update(supplied)
    limits = {}
    if family=='test':
        from .compositiontest import test_environment
        limits['selected']=len(cached(library,'developer_test','env/env_test.dat',test_environment)['labels'])-1
    if family == 'title': limits['selected'] = len(library.get('title').points[0x314]) - 1
    if family == 'system': limits['selected'] = 4
    if family == 'slots': limits['selected'] = 59
    if family == 'choices': limits['selected'] = (len(state['text'].splitlines()) or 2) - 1
    if family in ('system', 'calendar'): limits['chapter'] = len(library.get('system').colors[0x26c]) - 1
    if family == 'calendar':
        e = cached(library, 'calendar', 'env/env_script.dat', calendar_environment)
        limits['palette'] = min(len(e['labels']), len(e['colors'])) - 1
    if family == 'dialogs':
        e = cached(library, 'dialogs', 'env/env_dialog.dat', dialog_environment)
        limits['group'] = len(e['groups']) - 1
        if state['group'] > limits['group']: raise ImageError('Dialog button group outside authored table')
        limits['selected'] = len(e['groups'][state['group']]) - 1 if state['group'] >= 0 else -1
    if family == 'backlog':
        e = cached(library, 'backlog', 'env/env_backlog.dat', backlog_environment)
        count = len(state['text'].splitlines()); limits.update(selected=max(0, count - 1), first=max(0, count - e.signed(0xc188)), voice_frame=len(e.voices) - 1)
    if family == 'settings':
        e = cached(library, 'settings', 'env/env_option.dat', settings_environment); page = state['page']
        limits['selected'] = (6, 5, 1, 0)[page]
        if page == 3: state['alternate'] = True  # Same dependency as the GUI.
        for name in schema:
            schema[name]['active'] = settings_visible(name, page)
            if name in ('text_speed', 'auto_speed', 'window_opacity') or name.startswith('audio_') and name != 'audio_toggle':
                limits[name] = e.signed(0x14 if name in ('text_speed', 'auto_speed') else 0x18) - 1
    if family == 'extras':
        limits.update(extras_limits(library, state))
        for name in schema: schema[name]['active'] = extras_visible(name, state['view'])
    if family == 'profile':
        limits.update(mode_limits(library, state))
        for name in schema: schema[name]['active'] = mode_visible(name, state['view'])
        schema['selected']['active'] = state['view'] == 4; schema['cursor']['active'] = state['view'] in (1, 2, 5)
    if family == 'battle':
        e = cached(library, 'battle_ui', 'env/env_tukkomi.dat', battle_environment)
        limit = min(len(e[name]) for name in ('names', 'name_sizes', 'name_offsets', 'colors')) - 1
        limits.update(side_0=limit, side_1=limit)
        for name in schema: schema[name]['active'] = battle_visible(name, state['view'])
        schema['opacity']['active'] = state['view'] == 1
    for name, maximum in limits.items():
        spec = schema[name]; spec['maximum'] = maximum
        if name not in supplied:
            state[name] = max(spec['minimum'], min(maximum, state[name])); spec['default'] = state[name]
    # Inactive values are retained as in the GUI; active selectors must be valid.
    validate_values({k: v if v['active'] else original_schema[k] for k, v in schema.items()}, state)
    context = state.get('context_image')
    if context:
        a = library.catalog.by_id.get(context)
        if a is None or a.source != 'resource.dat' or len(a.route) != 2 or a.route[0] not in (5, 9) or a.status != 'Ready':
            raise ImageError('context_image must identify a ready original background or CG from list_textures')
    return state, list(schema.values())
