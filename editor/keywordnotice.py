"""The HUD formats one keyword into a fixed-cell reward notification."""
import re

from .environments import keyword_notice
from .scriptcodec import Reader
from .text import fixed_extent, units


SCRIPT_ENV = 'env/env_script.dat'
KEYWORD_ENV = 'env/env_keyword.dat'
TEMPLATE_FIELD = SCRIPT_ENV + ':#s0'
QUOTES = str.maketrans('«»', '≪≫')
PACKING = dict(align='left', extra_symbols=frozenset('≪≫'))


def environment(data):
    return keyword_notice(Reader(data))


def format_notice(template, name):
    value = re.sub(r'%ls|%%', lambda match: name if match[0] == '%ls' else '%', template)
    if any(char in value for char in '\0\r\n'):
        raise ValueError('Keyword notifications use one line')
    return value


def drawable(value, font):
    # The original face has double-angle brackets but no Latin guillemets.
    return ''.join(char.translate(QUOTES) if char not in font.cached and char not in font.charset else char
                   for char in value)


def geometry(layout, font):
    panel = layout['panel']
    left = panel['x'] - (0, panel['width'] // 2, panel['width'])[panel['alignment'] % 3]
    x = panel['x'] + layout['offset'][0]
    y = panel['y'] + layout['offset'][1]
    size = int(font.utility * layout['scale'])
    return x, y - size // 2, size, min(960, left + panel['width']) - x


def pack_notice(value, layout, font, encode=None):
    value = drawable(value, font)
    _, _, size, available = geometry(layout, font)
    wire, width = encode(value, size, **PACKING) if encode else (value, None)
    if width is None:
        width = fixed_extent(units(wire), size, font)
    if width > available:
        raise ValueError(f'Keyword notification needs {width}px but has {available}px')
    if len(units(wire)) >= 128:
        raise ValueError('Keyword notification exceeds the native 127-unit text buffer')
    return wire, width


def export_overrides(catalog, records, font, encode):
    if not encode or TEMPLATE_FIELD not in catalog.fields or KEYWORD_ENV + ':' not in catalog.nodes:
        return {}
    node = catalog.nodes[KEYWORD_ENV + ':']
    names = [node['id'] + '#s' + str(i) for i in range(len(node['spans']))]
    if not any(key in records for key in [TEMPLATE_FIELD, *names]):
        return {}
    layout = environment(catalog.source(SCRIPT_ENV))
    template = records.get(TEMPLATE_FIELD, {}).get('text', layout['template'])
    overrides = {TEMPLATE_FIELD: '%ls'}
    for key in names:
        name = records.get(key, {}).get('text', catalog.fields[key]['original'])
        # The catalogue names are consumed by the queue for this notification.
        # Bake the phrase together so the format boundary cannot add a cell gap.
        overrides[key], _ = pack_notice(format_notice(template, name), layout, font, encode)
    return overrides


def draw(out, library, font, keyword_id):
    from .choiceart import preview_label
    from .composition import blit, text_layer
    from .uitextcodec import keyword_text

    layout = environment(library.read(SCRIPT_ENV))
    names = dict(keyword_text(library.read(KEYWORD_ENV)))
    value = format_notice(layout['template'], names[keyword_id])
    wire, _ = pack_notice(value, layout, font, lambda text,size,**kw: preview_label(font,text,size,**kw))
    panel = layout['panel']
    shape = dict(panel, w=panel['width'], h=panel['height'], rgba=panel['color'])
    out.layers.append(blit('Keyword notification panel', 1, 8, shape))
    x, y, size, _ = geometry(layout, font)
    shadow = text_layer('Keyword notification shadow', wire, [x+1,y+1], size, [255,255,255,255], font)
    shadow.text = value
    out.layers.append(shadow)
    label = text_layer('Keyword notification', wire, [x,y], size, [0,0,0,255], font)
    label.text = value
    out.layers.append(label)
