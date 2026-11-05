"""Authored Options pages and help descriptions, without changing game settings."""
from copy import deepcopy
from .composition import Composition, Fields, blit, text_layer
from .compositioncommon import cached
from .compositionlists import backdrop_sprite, button_help, help_environment
from .imagecodec import ImageError
from .text import units


def settings_environment(data):
    e = Fields(data, legacy=False); r = e.r; rd, many = e.read, e.many
    e.point_rows = {}; e.rect_rows = {}; e.string_rows = {}; e.string_grids = {}
    def table(read): return [read() for _ in range(r.count())]
    point = lambda: [r.word('i'), r.word('i')]
    rect = lambda: [r.word('i') for _ in range(4)]
    strings = lambda: table(r.string)
    many('color', 0, 3); many('scalar', 0xc, 6)
    many('sprite', 0x24, 3, 36); rd('points', 0x90); rd('sprite', 0xa0); rd('points', 0xc4)
    rd('sprite', 0xd4); rd('sprites', 0xf8); e.rect_rows[0x108] = table(lambda: table(rect))
    rd('sprite', 0x118); e.point_rows[0x13c] = table(lambda: table(point)); e.string_rows[0x14c] = table(strings)
    rd('points', 0x15c); many('point', 0x16c, 6, 8)
    rd('sprite', 0x19c); e.point_rows[0x1c0] = table(lambda: table(point)); e.string_rows[0x1d0] = table(strings)
    rd('points', 0x1e0); many('point', 0x1f0, 10, 8); rd('sprites', 0x240)
    many('sprite', 0x250, 6, 36); many('scalar', 0x328, 3); many('sprite', 0x334, 3, 36)
    for at in (0x3a0, 0x3b0, 0x3c0): rd('ints', at)
    rd('scalar', 0x3d0); rd('ints', 0x3d4); e.string_grids[0x3e4] = table(lambda: table(strings))
    many('sprite', 0x3f4, 4, 36); rd('sprites', 0x484); rd('rect', 0x494)
    many('scalar', 0x4a4, 3); rd('point', 0x4b0); many('sprite', 0x4b8, 3, 36)
    many('rect', 0x524, 3, 16); rd('sprite', 0x554); rd('sprite', 0x578); rd('point', 0x59c)
    e.save_question = r.string()
    return e.finish()


def settings_layout(library, state, font):
    if font is None: raise ImageError('Original font/layout data is required')
    e = cached(library, 'settings', 'env/env_option.dat', settings_environment)
    page, alternate, row = state.get('page', 0), state.get('alternate', False), state.get('selected', 0)
    if not 0 <= page < (4 if alternate else 3): raise ImageError('Page outside selected three/four-tab header')
    if page < 3 and not 0 <= row <= (6, 5, 1)[page]: raise ImageError('Selected row outside authored page')
    out = Composition('Settings / help', notes=['Static Options visual state only. No system settings, audio channels, voice banks or saved options are changed.',
        'Contact rectangles are transparent; native input/revert/save controllers are not executed.'])
    add = lambda key, bank, entry, **kw: backdrop_sprite(out, e, key, bank, entry, **kw)
    add(0x24, 13, 25, anchored=False); add(0x48, 13, 36, anchored=False)
    variant = int(alternate); shape = deepcopy(e.sprite[0x6c]); shape['x'], shape['y'] = e.points[0x90][variant]
    out.layers.append(blit('Options heading', 13, 37, shape, anchored=False))
    add(0x578, 1, 17, source='first.dat', extent=e.point[0x59c]); add(0x554, 1, 17, source='first.dat')
    textures = (39, 41, 43, 45) if alternate else (40, 42, 44, 45)
    out.layers.append(blit('Selected Options tab', 13, textures[page], e.sprites[0xf8][variant], anchored=False))
    shape = deepcopy(e.sprite[0xa0]); point = e.points[0xc4][variant]
    shape['x'], shape['y'] = point[0] - state.get('arrow_offset', 0), point[1]
    out.layers.append(blit('Previous tab arrow', 13, 32 if state.get('arrow_left') else 31, shape, anchored=False))
    add(0xd4, 13, 34 if state.get('arrow_right') else 33, anchored=False, offset=(state.get('arrow_offset', 0), 0))
    add(0x4b8, 1, 8, source='first.dat', anchored=False); add(0x4dc, 1, 6, source='first.dat', anchored=False)
    add(0x500, 1, 2, source='first.dat', anchored=False, tint=[255] * 4)
    help_env = cached(library, 'help', 'env/env_help_mgr.dat', help_environment)
    hint = int(page == 1 and row == 3)
    button_help(out, library, font, items=help_env['options'][hint], rectangle=help_env['option_rect'])
    if page == 3:
        out.notes.append('The current source supplies this fourth header/tab but no page-content draw handler. No content is fabricated.')
        return out
    alpha = state.get('highlight', 255)
    description = 0
    if page < 2:
        audio = page == 1; numeric = 5 if audio else 3
        positions = e.points[0x1e0 if audio else 0x15c]
        shape = deepcopy(e.sprite[0x3f4]); shape['x'], shape['y'] = positions[row]; shape['rgba'][3] = alpha
        out.layers.append(blit('Selected Options row', 13, 27, shape, anchored=False))
        add(0x19c if audio else 0x118, 13, 35 if audio else 38, anchored=False)
        for i in range(numeric):
            key = f'audio_{i}' if audio else ('text_speed', 'auto_speed', 'window_opacity')[i]
            value = state.get(key, 5 if audio else 2 if i < 2 else 8)
            maximum = e.signed(0x18) - 1 if audio or i == 2 else e.signed(0x14) - 1
            if not 0 <= value <= maximum: raise ImageError(f'{key} exceeds authored slider range0–{maximum}')
            s = deepcopy(e.sprite[0x460] if audio else e.sprites[0x484][value] if i < 2 else e.sprite[0x43c])
            at = (0x1f0 if audio else 0x16c) + i * 16
            s['x'] = e.point[at][0] + e.point[at + 8][0] * value; s['y'] = e.point[at][1]
            out.layers.append(blit(f'{"Audio" if audio else "Text"} slider {i}', 13, 30, s, anchored=False))
        for i in range(1 if audio else 4):
            enabled = state.get('audio_toggle' if audio else f'text_toggle_{i}', True)
            index = 0 if enabled else 1
            point = e.point_rows[0x1c0][0][index] if audio else e.point_rows[0x13c][i][index]
            s = deepcopy(e.sprite[0x418]); s['x'], s['y'] = point
            out.layers.append(blit(f'{"Audio" if audio else "Text"} toggle {i}', 13, 26, s, anchored=False))
            if row == numeric + i: description = index
        label = e.string_rows[0x1d0 if audio else 0x14c][row][description]
    else:
        character, mode, progress = state.get('voice_character', 0), state.get('voice_mode', 0), state.get('pulse', 0)
        if not 0 <= character < 9 or not 0 <= mode < 5 or not 0 <= progress <= 8: raise ImageError('Invalid voice-page selector')
        shape = deepcopy(e.sprites[0x240][row]); shape['rgba'][3] = alpha
        out.layers.append(blit('Selected voice group', 13, 29 if row else 28, shape, anchored=False))
        add(0x250, 13, 58 if row else 59, anchored=False); add(0x334, 13, 48 if row else 47, anchored=False)
        for i, texture in enumerate((54, 49, 60, 56, 52)):
            shape = deepcopy(e.sprite[0x274 + i * 36]); scale = 1.
            if i == mode:
                offset = progress - progress // 4 * (progress % 4) * 2
                scale += e.floating(0x330) * offset / 10; shape['y'] -= offset
            out.layers.append(blit(f'Voice mode {i}', 13, texture + int(i == mode), shape, scale=scale))
        add(0x358, 13, 46, anchored=False)
        for i in range(9):
            s = deepcopy(e.sprite[0x418])
            s['x'], s['y'] = e.ints[0x3c0][i % 3], e.ints[0x3d4][i // 3]
            if not state.get(f'voice_{i}', True): s['x'] += e.signed(0x3d0)
            out.layers.append(blit(f'Voice character toggle {i}', 13, 26, s, anchored=False))
        s = deepcopy(e.sprite[0x37c]); s['x'], s['y'] = e.ints[0x3a0][character % 3], e.ints[0x3b0][character // 3]
        out.layers.append(blit('Selected voice character', 13, 51, s, anchored=False))
        index = character if row else 0
        description = int(not state.get(f'voice_{index}', True)) if row else mode
        label = e.string_grids[0x3e4][row][index][description]
    size = int(font.utility * e.floating(0x4ac)); x, y = e.point[0x4b0]
    out.layers.append(text_layer('Options row help description', label,
        [x - font.measure(units(label), size), y], size, [0, 0, 0, 255], font))
    return out


ADAPTERS = {'settings': settings_layout}
PARAMETERS = {'settings': [
    ('page', 'Options page', 'enum', 0, [(0, 'Text'), (1, 'Audio'), (2, 'Voice'), (3, 'Fourth header only')]),
    ('alternate', 'Four-tab header', 'bool', False), ('highlight', 'Highlight alpha', 'int', 255, 0, 255),
    ('arrow_offset', 'Arrow offset', 'int', 0, 0, 100), ('arrow_left', 'Left arrow active', 'bool', False),
    ('arrow_right', 'Right arrow active', 'bool', False),
    ('text_speed', 'Message speed', 'int', 2, 0, 4), ('auto_speed', 'Auto-play wait', 'int', 2, 0, 4),
    ('window_opacity', 'Window opacity', 'int', 8, 0, 10),
    *[(f'text_toggle_{i}', label, 'bool', True) for i, label in enumerate(
        ('Skip unread messages', 'Continue Auto after choices', 'Continue Skip after choices', 'Color read messages'))],
    *[(f'audio_{i}', ('BGM', 'SE', 'UI sound', 'Voice', 'Ducking')[i] + ' level', 'int', 5, 0, 10) for i in range(5)],
    ('audio_toggle', 'Voice cut enabled', 'bool', True), ('voice_mode', 'Voice mode', 'int', 0, 0, 4),
    ('voice_character', 'Voice character', 'int', 0, 0, 8), ('pulse', 'Mode pulse sample', 'int', 0, 0, 8),
    *[(f'voice_{i}', f'Character {i} voice enabled', 'bool', True) for i in range(9)],
]}


def parameter_visible(name, page):
    if name.startswith('text_') or name in ('auto_speed', 'window_opacity'): return page == 0
    if name.startswith('audio_'): return page == 1
    if name.startswith('voice_') or name == 'pulse': return page == 2
    return True
