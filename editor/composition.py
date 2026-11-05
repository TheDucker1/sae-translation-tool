"""Read-only UI draw lists. Source layouts are shared across scenes, not screenshots."""
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import math
import struct
from .imageassets import stamp
from .imagecodec import ImageError
from .scriptcodec import Reader
from .text import color, units


FAMILIES = (
    ('title', 'Title / menu', 'Implemented: static menu and press-start states'),
    ('message', 'Gameplay / message window', 'Implemented: window, nameplate, widgets, text and optional backdrop'),
    ('system', 'In-game system menu', 'Implemented: settled five-row menu, selection and chapter panel'),
    ('choices', 'Scenario choices', 'Implemented: authored cards, selection, history color and sample entries'),
    ('calendar', 'Calendar / chapter banners', 'Implemented: month/day/palette and two-caption chapter banner'),
    ('dialogs', 'Shared dialogs', 'Implemented: measured prompt, tiled frame, authored button groups and focus'),
    ('slots', 'Save / load', 'Implemented: clipped cards, empty/occupied/lock/new variants and scrollbars; sample records only'),
    ('backlog', 'Backlog', 'Implemented: clipped sample dialogue rows, selection, voice icons and scrollbars'),
    ('settings', 'Settings / help', 'Implemented: text/audio/voice pages, header variants and authored help; fourth tab has no source page content'),
    ('extras', 'Extras', 'Implemented: section menu, CG album/viewer, movie thumbnails, music and replay list; preview unlock/playback flags'),
    ('profile', 'Profiles / approach', 'Implemented: profile selection/confirmation/result/response UI, approach mission/gauge/topics/choices/result; settled snapshots'),
    ('battle', 'Battle', 'Implemented: introduction, dialogue bubbles/text, timed-choice cards/HUD/countdown and win/lose/equal result lettering; static UI only'),
)
IMPLEMENTED_FAMILIES = frozenset(key for key, _, status in FAMILIES if status.startswith(('Implemented', 'Partial')))


@dataclass
class Layer:
    name: str
    kind: str = 'sprite'
    asset: str = ''
    source: list = field(default_factory=list)
    destination: list = field(default_factory=list)
    rgba: list = field(default_factory=lambda: [255, 255, 255, 255])
    rotation: tuple | None = None  # degrees, pivot x/y in logical canvas space
    text: str = ''
    size: int = 0
    glyphs: list = field(default_factory=list)
    clip: list = field(default_factory=list)
    blend: str = 'normal'
    target: str = ''
    children: list = field(default_factory=list)
    mask: str = ''  # full-canvas target; native alpha > 0 stencil coverage


def walk_layers(layers, depth=0):
    if depth > 4: raise ImageError('Composition target nesting exceeds budget')
    for layer in layers:
        yield layer
        if layer.children: yield from walk_layers(layer.children, depth + 1)


@dataclass
class Composition:
    name: str
    layers: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    clear: tuple = (53, 65, 76, 255)


def sprite(r, legacy=True):
    parameter = r.word('h' if legacy else 'i')
    alignment, x, y, sx, sy, w, h = (r.word('i') for _ in range(7))
    return dict(parameter=parameter, alignment=alignment, x=x, y=y, sx=sx, sy=sy,
                w=w, h=h, rgba=color(r.word()))


def blit(name, bank, entry, shape, *, source='resource.dat', scale=1., offset=(0, 0),
         alpha=None, tint=None, anchored=True):
    s = deepcopy(shape)
    w, h = int(abs(s['w'] * scale)), int(abs(s['h'] * scale))
    x, y = s['x'] + offset[0], s['y'] + offset[1]
    if anchored:
        ax, ay = s['alignment'] % 3, s['alignment'] // 3
        x -= w // 2 if ax == 1 else w if ax == 2 else 0
        y -= h // 2 if ay == 1 else h if ay == 2 else 0
    rgba = list(tint if tint is not None else s['rgba'])
    if alpha is not None: rgba[3] = alpha & 255
    return Layer(name, asset=f'{source}:{bank}/{entry}', source=[s['sx'], s['sy'],
                 s['w'] if scale > 0 else -s['w'], s['h'] if scale > 0 else -s['h']],
                 destination=[x, y, w, h], rgba=rgba)


def text_layer(name, text, position, size, rgba, font, *, center=False):
    size = int(size)
    if not 0 <= size <= 1024: raise ImageError('Composition text size outside supported range')
    # Native simple DrawString advances by nominal PVF cells even for cached glyphs.
    chars = units(text).split('\0', 1)[0]
    widths = [size // 2 if 0x20 <= ord(c) <= 0x7e or 0xff61 <= ord(c) <= 0xffa0 else size for c in chars]
    x, y = position
    if center: x -= sum(widths) // 2
    glyphs, cursor = [], x
    for c, width in zip(chars, widths):
        cached = font.cached.get(c) if font is not None else None
        drawn = math.ceil(cached[3] * size / font.bitmap_height) if cached and size else cached[3] if cached else width
        height = size or (font.bitmap_height if cached else 0)
        glyphs.append(dict(code=ord(c), rect=[cursor, y, drawn, height]))
        cursor += width
    extent = max((g['rect'][0] + g['rect'][2] - x for g in glyphs), default=cursor - x)
    height = max((g['rect'][3] for g in glyphs), default=size)
    return Layer(name, kind='text', destination=[x, y, extent, height],
                 rgba=list(rgba), text=text, size=size, glyphs=glyphs)


class EnvironmentLibrary:
    """Small immutable environment snapshots; changes require an explicit refresh."""
    def __init__(self, root, *, catalog=None):
        self.root = root; self.files = {}; self.decoded = {}; self.catalog = catalog
        self.members = {}; self.member_sources = {}

    def member(self, source, route):
        if self.catalog is None: raise ImageError('A source image catalog is required for archive metadata')
        self.catalog.verify(); key = (source, tuple(route))
        if key not in self.members:
            self.members[key] = self.catalog.read_member(source, route)
            self.member_sources[source + ':' + '/'.join(map(str, route))] = hashlib.sha256(self.members[key]).hexdigest()
        return self.members[key]

    def read(self, relative):
        path = self.root / relative
        if relative not in self.files:
            before = stamp(path)
            if before[0] > 32 * 1024 * 1024: raise ImageError('Layout environment exceeds 32 MiB budget')
            data = path.read_bytes()
            if stamp(path) != before: raise ImageError('Layout changed while reading; refresh compositions')
            self.files[relative] = (before, data, hashlib.sha256(data).hexdigest())
        self.verify()
        return self.files[relative][1]

    def verify(self):
        if self.catalog: self.catalog.verify()
        for relative, (before, _, _) in self.files.items():
            if stamp(self.root / relative) != before:
                raise ImageError(f'Layout source changed: {relative}. Refresh compositions; reload game for font/text changes.')

    def get(self, family):
        if family not in self.decoded:
            path = {'title': 'env/env_scene_title.dat', 'message': 'env/env_message_window.dat',
                    'system': 'env/env_system_menu.dat'}[family]
            self.decoded[family] = {'title': title_environment, 'message': message_environment,
                                    'system': system_environment}[family](self.read(path))
        self.verify()
        return self.decoded[family]

    def build(self, family, state, font):
        try:
            builders = {'title': title_layout, 'message': message_layout, 'system': system_layout}
            if family in builders:
                result = builders[family](self.get(family), state, font)
            else:
                from .compositioncommon import ADAPTERS
                from .compositionlists import ADAPTERS as LIST_ADAPTERS
                from .compositionsettings import ADAPTERS as SETTINGS_ADAPTERS
                from .compositionextras import ADAPTERS as EXTRAS_ADAPTERS
                from .compositionmodes import ADAPTERS as MODE_ADAPTERS
                from .compositionbattle import ADAPTERS as BATTLE_ADAPTERS
                result = (ADAPTERS | LIST_ADAPTERS | SETTINGS_ADAPTERS | EXTRAS_ADAPTERS | MODE_ADAPTERS | BATTLE_ADAPTERS)[family](self, state, font)
        except (KeyError, IndexError) as error:
            raise ImageError(f'{family}: source layout tables are incomplete or a selector is outside their range ({error})') from error
        result.sources = {k: v[2] for k, v in self.files.items()} | self.member_sources
        return result


class Fields:
    """Typed environment reader. Keys are configuration identities, not file offsets."""
    def __init__(self, data, *, legacy=True):
        self.r = Reader(data); self.r.take(3)
        self.legacy = legacy
        self.scalar = {}; self.color = {}; self.sprite = {}; self.point = {}; self.rect = {}
        self.ints = {}; self.colors = {}; self.sprites = {}; self.points = {}; self.rects = {}; self.strings = {}

    def read(self, kind, key):
        r = self.r
        readers = dict(scalar=lambda: r.word(), color=lambda: color(r.word()), sprite=lambda: sprite(r, self.legacy),
                       point=lambda: [r.word('i'), r.word('i')], rect=lambda: [r.word('i') for _ in range(4)],
                       string=lambda: r.string())
        if kind in readers: value = readers[kind]()
        else:
            item = dict(ints=lambda: r.word('i'), colors=readers['color'], sprites=readers['sprite'],
                        points=readers['point'], rects=readers['rect'])[kind]
            value = [item() for _ in range(r.count())]
        getattr(self, 'strings' if kind == 'string' else kind)[key] = value

    def many(self, kind, start, count, stride=4):
        for i in range(count): self.read(kind, start + i * stride)

    def signed(self, at):
        value = self.scalar[at]
        return value if value < 2**31 else value - 2**32

    def floating(self, at):
        value = struct.unpack('<f', struct.pack('<I', self.scalar[at]))[0]
        if not math.isfinite(value): raise ImageError('Nonfinite layout scale')
        return value

    def finish(self):
        if self.r.pos != len(self.r.data): raise ImageError('Unexpected environment tail')
        return self


def title_environment(data):
    e = Fields(data); rd = e.read; many = e.many
    rd('ints', 0); rd('point', 0x10); rd('scalar', 0x18)
    many('color', 0x1c, 3); many('scalar', 0x28, 2); rd('color', 0x30); rd('scalar', 0x34)
    rd('color', 0x38); many('scalar', 0x3c, 2); many('color', 0x44, 2)
    many('sprite', 0x4c, 7, 0x24); many('scalar', 0x148, 11)
    rd('colors', 0x174); rd('ints', 0x184); rd('sprite', 0x194); rd('scalar', 0x1b8)
    rd('sprite', 0x1bc); rd('colors', 0x1e0); rd('colors', 0x1f0)
    rd('sprite', 0x200); rd('sprite', 0x224); many('scalar', 0x248, 3)
    rd('sprite', 0x254); rd('sprite', 0x278); rd('point', 0x29c); rd('point', 0x2a4)
    many('scalar', 0x2ac, 5); rd('sprites', 0x2c0); rd('sprites', 0x2d0)
    many('scalar', 0x2e0, 4); rd('sprite', 0x2f0); rd('points', 0x314); rd('sprite', 0x324)
    rd('points', 0x348); rd('rects', 0x358); rd('rect', 0x368)
    e.labels = [e.r.string() for _ in range(e.r.count())]
    many('scalar', 0x388, 2); many('color', 0x390, 2); many('scalar', 0x398, 2); rd('sprite', 0x3a0)
    for at in (0x3c4, 0x3dc, 0x3f4, 0x40c): rd('rect', at); rd('point', at + 16)
    rd('ints', 0x424); rd('rects', 0x434); rd('points', 0x444); many('scalar', 0x454, 3)
    return e.finish()


def title_layout(e, state, font):
    out = Composition('Title / menu', notes=['Static source-defined state; ambient particles and live submenu owners are not drawn.'])
    out.clear = (255, 255, 255, 255)
    p = max(0, min(100, state.get('progress', 100))); a = p * 255 // 100
    character = state.get('character', 0); selected = state.get('selected', 0)
    pressing = state.get('press_start', False)
    # ResetAnimations leaves logo/menu channels at0 with Reveal100; settled main
    # menu has those channels100 with Reveal0. The slider is a layout sample,
    # not a claim to reproduce the staged controller timeline.
    reveal = p if pressing else 0
    motion = 0 if pressing else p
    a = motion * 255 // 100
    if not 0 <= character < 4: raise ImageError('Title variant must be 0–3')
    def add(label, entry, key, **kw):
        layer = blit(label, 15, entry, e.sprite[key], **kw); out.layers.append(layer); return layer
    add('Backdrop', 78, 0x4c, alpha=reveal * 255 // 100); add('Background detail', 73, 0x70, alpha=reveal * 255 // 100)
    add('Title base art', 74, 0x194)
    logo_offset = (int(e.signed(0x250) * (100 - motion) / 100), 0)
    tint = e.colors[0x1e0][character][:3] + [a]
    add('Logo ring', 65, 0x200, tint=tint, offset=logo_offset)
    add('Logo strip', 67, 0x254, alpha=a, offset=logo_offset)
    for i, scale_key in enumerate((0x2b8, 0x2b4)):
        s = deepcopy(e.sprite[0x124]); s['x'], s['y'] = e.point[0x29c]; s['alignment'] = 4
        layer = blit(f'Ambient circle {i}', 15, 69, s, scale=e.floating(scale_key), alpha=a)
        layer.rotation = (state.get('angle', 0) * (1 if i == 0 else -1), *e.point[0x2a4]); out.layers.append(layer)
    add('Logo inner ring', 66, 0x224, tint=e.colors[0x1f0][character][:3] + [a], offset=logo_offset)
    add('Logo lettering', 70, 0x278)
    portrait = (72, 81, 76, 75)[character]
    dx = int(e.signed(0x2ec) * (100 - motion) / 100)
    for label, key in (('Portrait back', 0x2d0), ('Portrait front', 0x2c0)):
        out.layers.append(blit(label, 15, portrait, e.sprites[key][character], alpha=a, offset=(dx, 0)))
    if len(e.points[0x314]) > 4 or len(e.labels) < len(e.points[0x314]): raise ImageError('Invalid title menu table')
    size = int((font.utility if font else 27) * e.floating(0x38c))
    slide = int(e.signed(0x39c) * (100 - motion) / 100)
    for i, point in enumerate(e.points[0x314]):
        s = deepcopy(e.sprite[0x2f0]); s['x'], s['y'] = point[0], point[1] - slide
        out.layers.append(blit(f'Menu row {i}', 15, 63, s, alpha=a))
        if i == selected:
            s = deepcopy(e.sprite[0x324]); pos = e.points[0x348][i]; s['x'], s['y'] = pos[0], pos[1] - slide
            out.layers.append(blit('Selection cursor', 15, 64, s, alpha=a))
        rgba = e.color[0x390 if i == selected else 0x394][:3] + [a]
        out.layers.append(text_layer(f'Menu label {i}', e.labels[i],
            [point[0] + e.signed(0x388), point[1] - slide - size // 2], size, rgba, font))
    if pressing:
        add('Press-start decoration 0', 79, 0xdc, alpha=reveal * 255 // 100)
        add('Press-start decoration 1', 80, 0xb8, alpha=reveal * 255 // 100)
        add('Press-start prompt', 77, 0x94, alpha=state.get('blink', 255))
    add('Copyright', 71, 0x3a0)
    return out


def message_environment(data):
    r = Reader(data); r.take(15)
    e = dict(frame=[sprite(r) for _ in range(2)])
    r.take(16); e['nameplate'] = [sprite(r) for _ in range(3)]
    e['cursors'] = [sprite(r) for _ in range(2)]; e['auxiliary'] = [sprite(r) for _ in range(9)]
    e['auto_duration'] = r.word('i'); e['menu_hint'] = sprite(r)
    e['menu_sprites'] = [sprite(r) for _ in range(2)]; r.take(16 + 8)
    r.take(r.count() * 4); r.take(12); e['travel'] = r.word('i')
    e['text_position'] = [r.word('i'), r.word('i')]; e['width'] = r.word('i')
    return e


def message_layout(e, state, font):
    out = Composition('Gameplay / message window', notes=['Static UI preview; optional backdrop is user-selected, not a reconstructed story scene.'])
    openness = state.get('progress', 100); alpha = state.get('opacity', 11) * 255 // 11
    slide = int(e['travel'] * (100 - openness) / 100)
    speaker = state.get('speaker', 0)
    for i, shape in enumerate(e['frame']): out.layers.append(blit(f'Message frame {i}', 1, i, shape, offset=(0, slide), alpha=alpha))
    if speaker >= 0:
        for i, shape in enumerate(e['nameplate']):
            out.layers.append(blit(f'Nameplate layer {i}', 1, 9 if i < 2 else speaker + 41, shape, offset=(0, slide), alpha=alpha))
    indices = [0, 2 if state.get('skip') else 1, 4 if state.get('skip_gesture') else 3,
               5, 6, 8 if state.get('auto') else 7]
    for i in indices:
        layer = blit(f'{"Skip" if i < 5 else "Auto"} widget {i}', 1, 3, e['auxiliary'][i],
                     offset=(0, slide), tint=[255, 255, 255, alpha])
        if i == 8:
            x, y, w, h = layer.destination; layer.rotation = (state.get('angle', 0), x + w // 2, y + h // 2)
        out.layers.append(layer)
    if state.get('cursor', True):
        for i, shape in enumerate(e['cursors']):
            out.layers.append(blit(f'Advance cursor {i}', 1, 2, shape, offset=(0, slide), alpha=alpha))
    if font is not None and state.get('text'):
        parsed = font.format.ordinary(state['text'], geometry_only=True)
        size = int(font.utility * font.scale)
        glyphs = font.layout(parsed['body'], e['width'], font.scale, ruby=parsed['ruby'])
        origin = [e['text_position'][0], e['text_position'][1] + slide]
        body = Layer('Dialogue text', kind='text', text=parsed['body'], size=size,
            destination=[*origin, e['width'], max((g['y'] for g in glyphs), default=0) + size], rgba=font.unread[:])
        body.glyphs = [dict(code=g['code'], rect=[origin[0] + g['x'], origin[1] + g['y'],
                       math.ceil(font.cached[chr(g['code'])][3] * size / font.bitmap_height) if chr(g['code']) in font.cached else
                       size // 2 if 0x20 <= g['code'] <= 0x7e or 0xff61 <= g['code'] <= 0xffa0 else size,
                       size]) for g in glyphs]
        # Fully revealed ordinary text is the preview state. Native body shadow is
        # a separate offset pass; name text is not duplicated as a body shadow.
        shadow = deepcopy(body); shadow.name = 'Dialogue shadow'; shadow.rgba = [0, 0, 0, 255]
        for g in shadow.glyphs: g['rect'][0] += 1; g['rect'][1] += 1
        out.layers.extend([shadow, body])
        if parsed['name']:
            name_size = int(font.utility * font.name_scale)
            x, y = font.name_origin
            out.layers.append(text_layer('Speaker text', parsed['name'],
                [x - font.measure(parsed['name'], name_size) // 2, y + slide - name_size // 2],
                name_size, font.name_color[:3] + [255], font))
        if parsed['ruby'] or parsed['keywords'] or parsed['markers']:
            out.notes.append('This static sample shows body/name text; ruby, keyword decoration and timed reveal are not composed yet.')
    return out


def system_environment(data):
    e = Fields(data); rd = e.read; many = e.many
    many('color', 0, 3); rd('sprite', 0xc); rd('sprite', 0x30); rd('scalar', 0x54); rd('sprite', 0x58)
    many('scalar', 0x7c, 4); rd('sprite', 0x8c); rd('point', 0xb0); many('scalar', 0xb8, 2)
    many('sprites', 0xc0, 4, 16); many('scalar', 0x100, 3); rd('ints', 0x10c); many('scalar', 0x11c, 5)
    many('sprite', 0x130, 3, 0x24); many('scalar', 0x19c, 9)
    rd('sprite', 0x1c0); rd('sprite', 0x1e4); rd('scalar', 0x208); rd('point', 0x20c)
    rd('scalar', 0x214); rd('sprite', 0x218); rd('sprite', 0x23c); many('scalar', 0x260, 3)
    rd('colors', 0x26c); rd('string', 0x27c); rd('string', 0x2b4); rd('scalar', 0x2ec)
    for at in (0x2f0, 0x314):
        rd('scalar', at); rd('ints', at + 4)
        if at == 0x2f0: rd('rects', 0x304)
    many('scalar', 0x328, 4); many('color', 0x338, 2)
    return e.finish()


def system_layout(e, state, font):
    out = Composition('In-game system menu', notes=['Settled menu snapshot; no game navigation, save actions or live contact/tween simulation.'])
    selected = state.get('selected', 0)
    if not 0 <= selected < 5: raise ImageError('System menu selection must be 0–4')
    def add(label, entry, key, **kw):
        layer = blit(label, 13, entry, e.sprite[key], **kw); out.layers.append(layer); return layer
    add('Menu controls', 3, 0x130)
    add('Close decoration', 3, 0x154, anchored=False, tint=[255] * 4)
    add('Back button', 3, 0x178, anchored=False, tint=[255] * 4)
    add('Menu backdrop', 0, 0xc); add('Menu line', 24, 0x8c)
    add('Menu overlay', 1, 0x30); add('Menu heading', 2, 0x58)
    for i, s in enumerate(e.sprites[0xc0]):
        out.layers.append(blit(f'Menu row {i}', 13, 7 + i if i == selected else 12 + i,
                               s, tint=[255] * 4, anchored=False))
        if i == selected:
            out.layers.append(blit('Selected row description', 13, 17 + i, e.sprites[0xd0][i]))
            fill = deepcopy(e.sprites[0xe0][i]); width = e.sprites[0xe0][0]['w']
            fill['sx'] += fill['w'] - width; fill['w'] = width
            out.layers.append(blit('Selection fill', 13, 22, fill, alpha=255))
            out.layers.append(blit('Selection glow', 13, 23, e.sprites[0xf0][i], alpha=255))
    chapter = state.get('chapter', 0)
    if chapter >= 0:
        if chapter >= len(e.colors[0x26c]): raise ImageError('Chapter palette outside environment table')
        add('Chapter frame', 4, 0x1c0, alpha=255)
        add('Chapter banner', 5, 0x1e4, tint=e.colors[0x26c][chapter], alpha=255)
        size = int((font.utility if font else 27) * e.floating(0x214)); x, y = e.point[0x20c]; y -= size
        label = state.get('text', '')
        if label:
            out.layers.append(text_layer('Chapter shadow', label, [x + 1, y + 1], size, [0, 0, 0, 255], font))
            out.layers.append(text_layer('Chapter text', label, [x, y], size, [255] * 4, font))
        for i in range(e.signed(0x268)):
            s = deepcopy(e.sprite[0x23c if i == 0 else 0x218]); s['x'] += e.signed(0x260) * i
            out.layers.append(blit(f'Chapter indicator {i}', 13, 6, s, alpha=255))
    return out
