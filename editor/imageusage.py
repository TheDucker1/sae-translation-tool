"""Source-derived resource namespaces and static uses, not simulated scene rendering."""
import re
import struct
from .scriptcodec import Reader


BANKS = {
    ('first.dat', 1): ('Shared UI', 'Shared dialogs, common buttons and loading UI'),
    ('first.dat', 2): ('Startup logos', 'Startup logo sequence'),
    ('first.dat', 6): ('Shared particles', 'Shared particle/effect textures'),
    ('resource.dat', 0): ('Live2D textures', 'Model texture atlases; not a rendered model'),
    ('resource.dat', 1): ('Main gameplay UI', 'Message window, dates, chapter, approach and scenario UI'),
    ('resource.dat', 2): ('Extras thumbnails', 'CG, movie and battle replay galleries'),
    ('resource.dat', 3): ('Profiles / approach', 'Profiles, approach character packs and interface'),
    ('resource.dat', 5): ('Backgrounds', 'Scenario background image slots'),
    ('resource.dat', 6): ('Character pose textures', 'Pose main image and eye/mouth overlays; not a composed character'),
    ('resource.dat', 7): ('Battle face banks', 'Battle group / costume / side face textures'),
    ('resource.dat', 8): ('Effects', 'Effect texture packs; not a rendered animation'),
    ('resource.dat', 9): ('Event CG', 'Scenario event-image slots'),
    ('resource.dat', 10): ('Free images', 'Scenario free-image slots'),
    ('resource.dat', 11): ('Rule images', 'Transition/wipe rule textures'),
    ('resource.dat', 12): ('Rule masks', 'Rule-mask resource bank'),
    ('resource.dat', 13): ('System UI', 'Save/load, backlog, settings, help and system screens'),
    ('resource.dat', 15): ('Title UI', 'Title screen and title submenus'),
    ('resource.dat', 16): ('Battle UI', 'Battle interface and presentation'),
}


def family(source, route):
    if source.lower().endswith('.gsf'):
        return 'Font atlases', 'Cached font glyph atlas; not a scene picture'
    category, consumer = BANKS.get((source, route[0] if route else -1),
                                  ('Unclassified images', 'Usage has not been mapped'))
    if source == 'resource.dat' and len(route) > 1:
        bank, entry = route[:2]
        if bank in (5, 9, 10, 11): consumer += f'; resource ID {entry}'
        elif bank == 6 and len(route) == 3:
            consumer += f'; pose ID {entry}; ' + ('main texture' if route[2] == 2 else f'face atlas {route[2] - 3}')
        elif bank == 7 and len(route) >= 5:
            consumer += f'; group {entry}, costume {route[2]}, side {route[3]}, texture {route[4]}'
        elif bank == 0 and len(route) >= 4:
            consumer += f'; model {entry}, texture {route[-1]}'
        elif bank == 2:
            consumer += '; ' + {0: 'CG gallery', 1: 'Movie gallery', 2: 'Battle replay gallery'}.get(entry, 'unmapped gallery')
        elif bank == 3:
            consumer += '; ' + {0: 'Portrait bank', 1: 'Scene definitions', 2: 'Character/approach texture pack', 3: 'Common interface'}.get(entry, 'unmapped profile bank')
        elif bank == 1:
            consumer += '; ' + {0: 'message frame base', 1: 'message frame overlay', 2: 'message cursors',
                3: 'skip/auto widgets', 4: 'date base/labels', 5: 'calendar months', 6: 'calendar days',
                9: 'nameplate layers', 24: 'approach gauge frame', 25: 'approach gauge fill',
                50: 'chapter banner'}.get(entry, f'UI entry {entry}')
    return category, consumer


def static_references(descriptions, cancelled=lambda: False):
    """Index literal resource operands only. Never invent values for dynamic operands."""
    from .imagecodec import checkpoint
    result, dynamic = {}, []
    def add(route, row):
        if all(isinstance(v, int) and v >= 0 for v in route):
            result.setdefault(tuple(route), []).append(row)
    for sid, script in descriptions.items():
        checkpoint(cancelled)
        for command in script['commands']:
            op, a = command['opcode'], command['args']
            row = dict(script=sid, command=command['index'], opcode=op)
            if 'decode_error' in a:
                continue
            if op == 0xcb and a['category'] in (0, 1, 2):
                if re.fullmatch(r'-?[0-9]+', a['texture']):
                    add(((5, 9, 10)[a['category']], int(a['texture'])), dict(row, use='Draw image'))
                else:
                    dynamic.append(dict(row, use='Dynamic image resource', operand=a['texture']))
            elif op == 0x191:
                add((11, a['rule']), dict(row, use='Rule wipe'))
                if a['background_kind'] in (2, 3, 4):
                    add(((5, 9, 10)[a['background_kind'] - 2], a['color_or_image']), dict(row, use='Wipe background'))
            elif op == 0x1f9:
                if a['source'] == 0:
                    add((6, a['value']), dict(row, use=f"Actor {a['character']} pose"))
                else:
                    dynamic.append(dict(row, use='Dynamic pose resource', operand=a['value'], source=a['source']))
            elif op == 0x438 and a['selector'] == 2:
                add((0, a['target'], 1), dict(row, use='Live2D texture pack'))
            elif op == 0x3ef:
                for side in (0, 1):
                    add((7, a[f'side{side}_group'], a[f'side{side}_entry'], side),
                        dict(row, use=f'Battle side {side} face bank'))
    return result, dynamic


def message_regions(data):
    """Authored rectangles + native texture bindings for the ordinary message UI."""
    r = Reader(data)
    r.take(15)
    result = {}
    def read(label, entries):
        at = r.pos
        parameter = r.word('h')
        alignment, x, y, sx, sy, w, h = (r.word('i') for _ in range(7))
        tint = r.word()
        for entry in entries:
            result.setdefault(('resource.dat', (1, entry)), []).append(dict(
                label=label, rect=[sx, sy, w, h], destination=[x, y], alignment=alignment,
                parameter=parameter, tint=tint, definition='env/env_message_window.dat', offset=at))
    read('Message frame 0', [0]); read('Message frame 1', [1])
    r.take(16)
    read('Nameplate layer 0', [9]); read('Nameplate layer 1', [9])
    read('Speaker nameplate', range(41, 50))
    for i in range(2):
        read(f'Message cursor {i}', [2])
    for i in range(9):
        read(f'{"Skip" if i < 5 else "Auto"} widget state {i}', [3])
    # The menu fields are retained in the environment but their texture bindings
    # are not inferred from parameter IDs. Only proven consumer bindings above.
    return result


def font_regions(data, sections):
    result = {}
    at, size = sections[-2]
    if size % 10:
        raise ValueError('Font glyph table is not a multiple of 10 bytes')
    for offset in range(at, at + size, 10):
        code, atlas, x, y, width, height = struct.unpack_from('<4H2B', data, offset)
        if atlas >= len(sections) - 2:
            raise ValueError('Glyph refers outside font atlas table')
        result.setdefault(atlas, []).append(dict(label=f'U+{code:04X} {chr(code)}',
            rect=[x, y, width, height], definition='Font glyph table', offset=offset))
    return result
