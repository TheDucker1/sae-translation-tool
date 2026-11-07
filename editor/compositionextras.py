"""Source-derived Extras snapshots. Unlock/playback state is preview-local."""
from copy import deepcopy
from .composition import Composition, Layer, Fields, sprite, blit, text_layer
from .compositioncommon import cached, quad
from .compositionlists import backdrop_sprite, button_help, help_environment, new_marker
from .imagecodec import ImageError
from .text import units, color


def extras_environment(data):
    e = Fields(data); r = e.r; rd, many = e.read, e.many
    words = lambda n: [r.word('i') for _ in range(n)]
    table = lambda fn: [fn() for _ in range(r.count())]
    colors = words(3); header = words(2); shared = [sprite(r) for _ in range(2)]; stretch = words(2)
    shared.extend(sprite(r) for _ in range(4)); cancel = words(4); counters = [words(2) for _ in range(2)]
    from .uitextcodec import ui_string
    shared_scale = r.word('f'); value, fade = words(2); prompt = ui_string(r,'dialog prompt'); backdrop = sprite(r)
    headers, buttons = [sprite(r) for _ in range(4)], [sprite(r) for _ in range(4)]
    marker = sprite(r); offset = r.word('i'); rects = table(lambda: table(lambda: words(4)))
    labels = table(r.string); text_scale = r.word('f'); text_position = words(2); columns = r.word()
    if columns > 20: raise ImageError('CG catalogue image columns exceed native budget')
    e.common = dict(colors=colors, header=header, shared=shared, stretch=stretch, cancel=cancel, counters=counters,
        scale=shared_scale, value=value, fade=fade, prompt=prompt, backdrop=backdrop, headers=headers, buttons=buttons,
        marker=marker, offset=offset, rects=rects, labels=labels, text_scale=text_scale, text_position=text_position, columns=columns)
    rd('sprites', 0xd228); rd('scalar', 0xd238); rd('rect', 0xd23c)
    many('sprite', 0xd24c, 3, 36); rd('point', 0xd2b8); rd('point', 0xd2c0); many('scalar', 0xd2c8, 2)
    rd('sprite', 0xd2d0); rd('scalar', 0xd2f4); rd('rect', 0xd2f8); rd('point', 0xd308)
    rd('scalar', 0xd310); rd('point', 0xd314); rd('sprite', 0xd31c); rd('point', 0xd340)
    rd('sprite', 0xd348); rd('point', 0xd36c); rd('sprite', 0xd374); rd('sprite', 0xd398)
    rd('point', 0xd3bc); rd('point', 0xd3c4); rd('string', 0xd3cc); rd('point', 0xd404)
    rd('scalar', 0xd40c); rd('point', 0xd410); rd('scalar', 0xd418); rd('sprite', 0xd41c)
    rd('string', 0xd440); rd('scalar', 0xd478); rd('sprite', 0xd47c); rd('scalar', 0xd4a0)
    rd('sprite', 0xd4a4); rd('scalar', 0xd4c8); many('sprite', 0xd4cc, 3, 36); rd('scalar', 0xd538)
    rd('sprite', 0xd53c); rd('sprite', 0xd560); rd('point', 0xd584); many('sprite', 0xd58c, 4, 36)
    rd('point', 0xd61c); rd('sprite', 0xd624); many('sprites', 0xd648, 3, 16)
    rd('rect', 0xd678); rd('rect', 0xd688); rd('point', 0xd698); many('scalar', 0xd6a0, 2)
    rd('sprite', 0xd6a8); many('scalar', 0xd6cc, 2); rd('sprite', 0xd6d4); rd('sprite', 0xd6f8)
    e.album_rectangles = table(lambda: words(4)); rd('point', 0xd72c); many('scalar', 0xd734, 2)
    rd('point', 0xd73c); rd('scalar', 0xd744); rd('sprite', 0xd748); rd('point', 0xd76c)
    rd('scalar', 0xd774); rd('point', 0xd778); rd('point', 0xd780); rd('scalar', 0xd788)
    e.music = table(lambda: dict(zip(('flags', 'wave', 'history', 'duration', 'title'), words(4) + [r.string()])))
    many('string', 0xd79c, 3, 56); rd('scalar', 0xd844); rd('string', 0xd848); many('scalar', 0xd880, 3)
    e.movies = table(lambda: [r.string(), r.string()]); rd('string', 0xd89c); rd('sprite', 0xd8d4)
    rd('scalar', 0xd8f8); many('sprite', 0xd8fc, 3, 36); rd('rect', 0xd968); rd('point', 0xd978)
    rd('scalar', 0xd980); rd('rect', 0xd984); rd('rect', 0xd994); rd('scalar', 0xd9a4)
    rd('point', 0xd9a8); rd('point', 0xd9b0); many('scalar', 0xd9b8, 2)
    rd('sprite', 0xd9c0); rd('scalar', 0xd9e4); many('sprite', 0xd9e8, 4, 36)
    rd('point', 0xda78); rd('scalar', 0xda80); rd('sprite', 0xda84); rd('sprite', 0xdaa8); many('scalar', 0xdacc, 4)
    rd('rect', 0xdadc); rd('point', 0xdaec); rd('point', 0xdaf4); rd('sprite', 0xdafc); rd('sprite', 0xdb20)
    rd('point', 0xdb44); many('sprite', 0xdb4c, 4, 36); rd('point', 0xdbdc); rd('rect', 0xdbe4)
    rd('point', 0xdbf4); many('scalar', 0xdbfc, 2); rd('sprite', 0xdc04); many('scalar', 0xdc28, 2)
    rd('sprite', 0xdc30); rd('point', 0xdc54); many('scalar', 0xdc5c, 2); rd('sprite', 0xdc64); many('scalar', 0xdc88, 2)
    e.battle_rectangles = table(lambda: words(4)); many('point', 0xdca0, 3, 8); many('scalar', 0xdcb8, 2)
    rd('point', 0xdcc0); rd('scalar', 0xdcc8); rd('point', 0xdccc); many('scalar', 0xdcd4, 2); rd('sprite', 0xdcdc)
    e.replays = table(lambda: [r.string() for _ in range(4)]); rd('sprite', 0xdd10); rd('scalar', 0xdd34)
    many('sprite', 0xdd38, 8, 36); many('scalar', 0xde58, 2); many('string', 0xde60, 6, 56)
    return e


def catalogue_rows(text):
    """Native row boundaries are CRLF; quoted delimiters and doubled quotes survive."""
    row, token, i = [], '', 0
    while i < len(text):
        c = text[i]; i += 1
        if c == '"':
            while i < len(text):
                q = text[i]; i += 1
                if q != '"': token += q
                elif i < len(text) and text[i] == '"': token += '"'; i += 1
                else: break
        elif c in ',\r\n':
            row.append(token); token = ''
            if c == '\r' and i < len(text) and text[i] == '\n':
                i += 1; yield row; row = []
        else: token += c
    if row or token: yield row + [token]


def native_number(text):
    value = 0
    for c in text:
        if '0' <= c <= '9': value = (value * 10 + ord(c) - 48) & 0xffffffff
    if '-' in text: value = -value & 0xffffffff
    return value if value < 2**31 else value - 2**32


def cg_catalogue(library, e):
    key = 'extras_cg_catalogue'
    if key in library.decoded: return library.decoded[key]
    blob = library.member('resource.dat', (2, 0, 0, 0))
    if not blob.startswith(b'\xff\xfe') or len(blob) % 2: raise ImageError('Expected UTF16LE CG catalogue with BOM')
    entries, cards, groups = [], [], [[] for _ in range(6)]; previous = -1
    columns = e.common['columns']
    for fields in catalogue_rows(blob[2:].decode('utf-16-le')):
        fields += [''] * max(0, columns + 6 - len(fields))
        if fields[0] != 'ON' or not fields[1] or not fields[2]: continue
        images = [native_number(x) for x in fields[3:3 + columns] if x and native_number(x) >= 0]
        a, b, category = fields[3 + columns:6 + columns]
        if native_number(fields[2]) < 0 or not a or not b or min(native_number(a), native_number(b)) < 0: continue
        category = native_number(category)
        if not previous <= category < 6 or category < 0 or not images: raise ImageError('CG catalogue categories/variants are invalid')
        if category != previous:
            while len(cards) % 9: cards.append(None)
            previous = category
        index = len(entries); entries.append(dict(title=fields[1], images=images, thumbnail=native_number(b), category=category))
        cards.append(index); groups[category].append(index)
    while len(cards) % 9: cards.append(None)
    pages = [[cards[i:i + 9] for i in range(0, len(cards), 9) if any(v in group for v in cards[i:i + 9] if v is not None)] for group in groups]
    result = dict(entries=entries, pages=pages); library.decoded[key] = result; return result


def extras_help(library):
    key = 'extras_help'
    if key in library.decoded: return library.decoded[key]
    data = library.read('env/env_help_mgr.dat')
    # Walk the same counted prefix as the established help decoder.
    from .scriptcodec import Reader
    r = Reader(data); r.take(3 + 8 + 32 + 4)
    rect = lambda: [r.word('i') for _ in range(4)]
    items = lambda: [[r.word('i'), r.string()] for _ in range(r.count())]
    r.take(16); items(); r.take(16)
    for _ in range(r.count()): items()
    r.take(16)
    for _ in range(r.count()): items()
    root_rect, root_items = rect(), items(); album_rects, album_rows = [], []
    for _ in range(2): album_rects.append(rect()); album_rows.append([items() for _ in range(r.count())])
    movie_rows = [items() for _ in range(r.count())]; battle_rect = rect(); battle_rows = [items() for _ in range(r.count())]
    result = dict(root=(root_items, root_rect), cg=(album_rows[0], album_rects[0]), music=(album_rows[1], album_rects[1]),
                  movies=(movie_rows[0], root_rect), replay=(battle_rows[0], battle_rect))
    library.decoded[key] = result; return result


def number(value, width=0): return str(value).zfill(width).translate(str.maketrans('0123456789', '０１２３４５６７８９'))


class ExtrasDraw:
    def __init__(self, library, state, font):
        self.lib, self.state, self.font = library, state, font
        self.e = cached(library, 'extras', 'env/env_omake.dat', extras_environment); self.c = self.e.common
        self.out = Composition('Extras', notes=['Preview unlock/new/playing flags are synthetic. No personal unlock state, audio, movie decoding or replay execution.'])
    def sprite(self, name, entry, shape, **kw):
        layer = blit(name, 15, entry, shape, **kw); self.out.layers.append(layer); return layer
    def add(self, key, entry, **kw): return backdrop_sprite(self.out, self.e, key, 15, entry, **kw)
    def text(self, name, value, point, size, rgb=(0, 0, 0, 255), center=False, right=False):
        x, y = point
        if center or right: x -= self.font.measure(units(value), size) // (2 if center else 1)
        self.out.layers.append(text_layer(name, value, [x, y], size, rgb, self.font))
    def size(self, key): return int(self.font.utility * self.e.floating(key))
    def fill(self, entry):
        layer = self.sprite('Section stretched fill', entry, self.c['shared'][1]); shape = deepcopy(self.c['shared'][1])
        shape['w'], shape['h'] = self.c['stretch']; dest = blit('', 15, entry, shape).destination
        layer.destination = dest; self.sprite('Section header', entry, self.c['shared'][0])
    def footer(self, kind, count=None):
        items, rect = extras_help(self.lib)[kind]
        if kind == 'music': items = items[(4 if self.state.get('music_mode', 0) == 1 else 2 if self.state.get('music_mode', 0) == 2 else 0) + int(self.state.get('playing', False))]
        viewing = kind == 'cg' and self.state.get('image_view', False) and self.state.get('unlocked', True)
        if kind == 'cg': items = items[int(viewing)]
        button_help(self.out, self.lib, self.font, items=items, rectangle=rect)
        if kind != 'root':
            panel = kind in ('cg', 'replay') and not viewing
            shared = deepcopy(self.c['shared'][4 if panel else 3]); shared['alignment'] = 0
            self.out.layers.append(blit('Extras help strip', 1, 7 if panel else 6, shared, source='first.dat'))
        if not viewing:
            self.out.layers.append(blit('Extras back button', 1, 2, self.c['shared'][5], source='first.dat', tint=[255] * 4))
        if count is not None and not viewing:
            for index, value in enumerate((count, count if self.state.get('unlocked', True) else 0)):
                p = self.c['counters'][index][:]; size = int(self.font.utility * self.c['scale'])
                for digit in range(2):
                    self.text('Extras counter', number(value % 10), p, size, right=True); p[0] -= self.c['value']; value //= 10
    def shade(self): self.out.layers.append(Layer('Extras child shade', kind='solid', destination=[0, 0, 960, 544], rgba=[255, 255, 255, 128]))


def root_layout(d):
    selected = d.state.get('selected', 0)
    if not 0 <= selected < 4: raise ImageError('Extras root selection outside four sections')
    back = blit('Extras target backdrop', 15, 46, d.c['backdrop'])
    header = blit('Extras target section header', 15, (47, 48, 49, 55)[selected], d.c['headers'][selected]); header.blend = 'multiply'
    d.out.layers.append(Layer('Extras offscreen header target', kind='target', target='extras-header', destination=[0, 0, 960, 544], rgba=[0, 0, 0, 255], children=[back, header]))
    d.sprite('Extras backdrop', 46, d.c['backdrop'])
    result = deepcopy(back); result.name = 'Composed Extras header'; result.asset = '@target:extras-header'; d.out.layers.append(result)
    d.fill(59)
    for i, entry in ((2, 8), (3, 6)):
        s = deepcopy(d.c['shared'][i]); s['alignment'] = 0
        d.out.layers.append(blit('Shared Extras decoration', 1, entry, s, source='first.dat'))
    d.footer('root')
    for i, entry in enumerate((50, 52, 53, 54)):
        shape = deepcopy(d.c['buttons'][i]); shape['x'] += d.c['offset'] if i == selected else 0
        d.sprite(f'Extras menu section {i}', entry, shape, tint=[255 if i == selected else 128] * 3 + [255])
        if i == selected:
            marker = deepcopy(d.c['marker']); marker['alignment'] = 0; marker['y'] += d.c['buttons'][i]['y']
            d.sprite('Selected section marker', 51, marker)
            d.text('Selected section description', d.c['labels'][i], d.c['text_position'], int(d.font.utility * d.c['text_scale']), right=True)


def cg_layout(d):
    cat = cg_catalogue(d.lib, d.e); category = d.state.get('category', 0); local_page = d.state.get('page', 0)
    pages = cat['pages'][category]
    if not 0 <= local_page < len(pages): raise ImageError('CG page outside selected category')
    cards = pages[local_page]; selected = d.state.get('selected', 0); unlocked = d.state.get('unlocked', True)
    if not 0 <= selected < 9 or cards[selected] is None: raise ImageError('Selected CG cell has no catalogue entry')
    d.shade(); d.fill(58); d.add(0xd24c, 14)
    all_pages = [p for group in cat['pages'] for p in group]; page_index = sum(len(group) for group in cat['pages'][:category]) + local_page
    for i in range(len(all_pages)):
        if i == page_index:
            s = deepcopy(d.e.sprite[0xd2d0]); s['x'] += d.e.sprite[0xd24c]['x'] + i * d.e.signed(0xd2f4); s['y'] += d.e.sprite[0xd24c]['y']; d.sprite('Selected CG page', 15, s)
        p, step = d.e.point[0xd2b8], d.e.point[0xd2c0]; size = d.size(0xd2cc)
        for digit, value in enumerate(((i + 1) // 10, (i + 1) % 10)):
            d.text('CG page number', number(value), [p[0] + i * step[0] + digit * d.e.signed(0xd2c8), p[1] - size // 2], size, center=True)
    d.add(0xd270, 1); d.add(0xd294, 1).source[2] *= -1
    for i, entry in enumerate((4, 13, 8, 6, 7, 11)):
        s = deepcopy(d.e.sprites[0xd228][i]); s['x'] += d.e.signed(0xd238) if i == category else 0
        d.sprite(f'CG category {i}', entry, s, tint=[255 if i == category else 128] * 3 + [255])
        if i == category: d.sprite('CG category selection', 3, s)
    start = len(d.out.layers); origin, pitch = d.e.point[0xd314], d.e.point[0xd340]
    for cell, index in enumerate(cards):
        if index is None: continue
        entry = cat['entries'][index]; x, y = origin[0] + cell % 3 * pitch[0], origin[1] + cell // 3 * pitch[1]
        for key, texture in ((0xd31c, 12),): d.add(key, texture, offset=(x, y))
        if unlocked:
            layer = d.add(0xd348, 0, offset=(x, y)); layer.asset = f'resource.dat:2/0/1/0/{entry["thumbnail"]}'
        else: d.add(0xd374, 9, offset=(x, y))
        d.add(0xd398, 10, offset=(x, y)); face = d.e.sprite[0xd398]
        if len(entry['images']) > 1:
            size = d.size(0xd40c)
            for value, key in ((number(len(entry['images']) if unlocked else 0), 0xd3bc), (number(len(entry['images'])), 0xd3c4), (d.e.strings[0xd3cc], 0xd404)):
                p = d.e.point[key]; d.text('CG variants', value, [x + face['x'] + p[0], y + face['y'] + p[1] - size], size, [255] * 4)
        p = d.e.point[0xd410]; d.text('CG ordinal', number(index + 1, 3), [x + face['x'] + p[0], y + face['y'] + p[1] - d.size(0xd418)], d.size(0xd418), [255] * 4, right=True)
        if cell == selected: d.add(0xd41c, 5, offset=(x, y))
        if unlocked and d.state.get('new', False):
            p = d.e.point[0xd36c]; new_marker(d.out, d.lib, [x + p[0], y + p[1]])
    for layer in d.out.layers[start:]: layer.clip = list(d.e.rect[0xd2f8])
    if d.state.get('image_view', False) and unlocked:
        images = cat['entries'][cards[selected]]['images']; variant = d.state.get('variant', 0)
        if not 0 <= variant < len(images): raise ImageError('CG variant outside selected entry')
        d.out.layers.append(quad('Selected full CG', f'resource.dat:9/{images[variant]}', [0, 0, 960, 544], [0, 0, 960, 544]))
        for i in range(len(images)):
            d.add(0xd47c, 18 if i == variant else 17, offset=(i * d.e.signed(0xd4a0), 0))
    d.footer('cg', sum(len(entry['images']) for entry in cat['entries']))


def list_window(d, count, visible, pitch):
    selected = d.state.get('selected', 0)
    if not count or not 0 <= selected < count: raise ImageError('Extras selection outside authored catalogue')
    first = d.state.get('first', -1)
    if first == -1: first = min(max(0, count - visible), max(0, selected - visible + 1))
    if not 0 <= first <= max(0, count - visible): raise ImageError('First Extras row outside catalogue')
    shift = int(pitch * d.state.get('scroll', 0) / 100)
    return selected, first, shift


def scroll_bar(d, count, selected, keys, extent_key, width_key):
    a, b, c, top, mid, bottom = keys; extent = d.e.point[extent_key]
    for key in (a, b, c):
        backdrop_sprite(d.out, d.e, key, 1, 10, source='first.dat', extent=extent if key == b else None)
    height = extent[1] / count
    offset = int((extent[1] - 12) * selected / (count - 1)) if height < 12 and count > 1 else int(height * selected)
    height = max(height, 12); y = offset + d.e.sprite[b]['y']; width = d.e.point[width_key][0]
    h1, h2 = d.e.sprite[top]['h'], d.e.sprite[bottom]['h']; middle = int(height - h1 - h2)
    for key, at, h in ((top, y, h1), (mid, y, middle), (bottom, y + d.e.sprite[mid]['y'] + middle, h1)):
        backdrop_sprite(d.out, d.e, key, 1, 11, source='first.dat', offset=(0, at), extent=[width, h])


def movies_layout(d):
    selected, first, shift = list_window(d, len(d.e.movies), 1, d.e.point[0xd978][0]); unlocked = d.state.get('unlocked', True)
    d.shade(); d.add(0xd8d4, 19, alpha=d.e.signed(0xd8f8)); d.add(0xd8fc, 20, alpha=d.e.signed(0xd8f8)); d.fill(60)
    start = len(d.out.layers); pitch = d.e.point[0xd978][0]
    for i in range(max(0, first - 1), min(len(d.e.movies), first + 2)):
        x = d.e.signed(0xd9a4) + (i - first) * pitch - shift
        if unlocked:
            layer = d.add(0xda0c, 0, offset=(x, 0)); layer.asset = f'resource.dat:2/1/1/{i}'
            if d.state.get('new', False):
                anchor = d.e.sprite[0xda30]; new_marker(d.out, d.lib, [anchor['x'] + x, anchor['y']])
        else: d.add(0xd9e8, 21, offset=(x, 0))
    for layer in d.out.layers[start:]: layer.clip = list(d.e.rect[0xd968])
    for i, key in enumerate((0xd920, 0xd944)):
        if (i == 0 and selected) or (i == 1 and selected < len(d.e.movies) - 1):
            layer = d.add(key, 56)
            if i: layer.source[2] *= -1
    d.add(0xda54, 14); s = deepcopy(d.e.sprite[0xd9c0]); base = d.e.sprite[0xda54]
    s['x'] += base['x']; s['y'] += base['y']; s['sx'] += selected * d.e.signed(0xd9e4); d.sprite('Selected movie page', 15, s)
    size = d.size(0xd9bc)
    for i in range(len(d.e.movies)):
        p, step = d.e.point[0xd9a8], d.e.point[0xd9b0]
        for j, value in enumerate(((i + 1) // 10, (i + 1) % 10)):
            d.text('Movie ordinal', number(value), [p[0] + i * step[0] + j * d.e.signed(0xd9b8), p[1] - size // 2], size, center=True)
    d.text('Movie title', d.e.movies[selected][1] if unlocked else d.e.strings[0xd89c], d.e.point[0xda78], d.size(0xda80), center=True)
    for i, key in enumerate((0xda84, 0xdaa8)):
        layer = backdrop_sprite(d.out, d.e, key, 1, 1, source='first.dat')
        if i: layer.source[2] *= -1
    d.footer('movies'); d.out.notes.append('Movie gallery thumbnails are shown; live movie frames/playback are outside this image preview.')


def music_layout(d):
    selected, first, shift = list_window(d, len(d.e.music), 6, d.e.point[0xd698][1]); unlocked = d.state.get('unlocked', True)
    playing = d.state.get('playing', False) and unlocked; track = d.e.music[selected]
    d.shade(); d.add(0xd4a4, 19, alpha=d.e.signed(0xd4c8)); d.add(0xd4cc, 23, alpha=d.e.signed(0xd4c8)); d.fill(61); d.add(0xd4f0, 26)
    d.text('Playing track title', track['title'] if playing else d.e.strings[0xd80c], d.e.point[0xd76c], d.size(0xd774), center=True)
    duration = max(0, track['duration']); elapsed = d.state.get('elapsed', 0)
    if playing and not 0 <= elapsed <= duration: raise ImageError('Music position outside selected track duration')
    for seconds, point in ((elapsed if playing else d.e.signed(0xd844), 0xd778), (duration if playing else d.e.signed(0xd844), 0xd780)):
        a, b = (seconds // 60, seconds % 60) if playing else (seconds, seconds)
        value = d.e.strings[0xd848].replace('%02d', str(b).zfill(2)).replace('%d', str(a))
        value = d.font.format.normalize(units(value))
        from .text import unicode_text
        d.text('Music time', unicode_text(value), d.e.point[point], d.size(0xd788))
    if playing and duration:
        layer = d.add(0xd514, 27, anchored=False, tint=[255] * 4); layer.destination[2] = int(d.e.signed(0xd538) * elapsed / duration)
    start = len(d.out.layers); pitch = d.e.point[0xd698][1]
    y = d.e.signed(0xd6a4) + pitch * (selected - first) - shift; d.add(0xd6f8, 22, offset=(0, y), anchored=False)
    for i in range(max(0, first - 1), min(len(d.e.music), first + 7)):
        y = d.e.signed(0xd6a4) + pitch * (i - first) - shift
        d.add(0xd6d4, 24, offset=(0, y), anchored=False)
        d.add(0xd6a8, 25, offset=(0, y), anchored=False, tint=color(d.e.scalar[0xd6cc if unlocked else 0xd6d0]))
        p = d.e.point[0xd72c]; size = d.size(0xd738)
        for j, value in enumerate(((i + 1) // 10, (i + 1) % 10)):
            d.text('Track ordinal', number(value), [p[0] + j * d.e.signed(0xd734), p[1] + y - size // 2], size, center=True)
        if unlocked and d.state.get('new', False):
            s = d.e.sprite[0xd748]; new_marker(d.out, d.lib, [s['x'], s['y'] + y])
        p = d.e.point[0xd73c]
        d.text('Track title', d.e.music[i]['title'] if unlocked else d.e.strings[0xd7d4], [p[0], p[1] + y], d.size(0xd744))
    for layer in d.out.layers[start:]: layer.clip = list(d.e.rect[0xd688])
    scroll_bar(d, len(d.e.music), selected, (0xd53c, 0xd560, 0xd58c, 0xd5b0, 0xd5d4, 0xd5f8), 0xd584, 0xd61c)
    d.add(0xd624, 30)
    d.sprite('Music play state', 31 if playing else 32, d.e.sprites[0xd648][int(playing)])
    d.sprite('Music control', 37, d.e.sprites[0xd658][0]); d.sprite('Music mode', (36, 34, 28)[d.state.get('music_mode', 0)], d.e.sprites[0xd668][0])
    d.footer('music', len(d.e.music))


def replay_layout(d):
    selected, first, shift = list_window(d, len(d.e.replays), 4, d.e.point[0xdbf4][1]); unlocked = d.state.get('unlocked', True)
    d.shade(); d.add(0xdd10, 40, alpha=d.e.signed(0xd8f8)); d.add(0xdd38, 41, alpha=d.e.signed(0xdd34)); d.fill(62)
    scroll_bar(d, len(d.e.replays), selected, (0xdafc, 0xdb20, 0xdb4c, 0xdb70, 0xdb94, 0xdbb8), 0xdb44, 0xdbdc)
    d.add(0xddc8, 57); d.add(0xde10, 57).source[3] *= -1
    start = len(d.out.layers); pitch = d.e.point[0xdbf4][1]
    for row in range(max(0, first - 1), min(len(d.e.replays), first + 5)):
        y = d.e.signed(0xdc00) + pitch * (row - first) - shift
        d.add(0xdc30, 42, offset=(0, y), anchored=False)
        d.add(0xdc64, 39, offset=(0, y), anchored=False, tint=color(d.e.scalar[0xdc88 if row == selected and not shift else 0xdc8c]))
        entry = d.e.replays[row]
        def txt(value, point, scale, rgb=(0, 0, 0, 255)):
            p = d.e.point[point]; d.text('Replay text', value, [p[0], p[1] + y], d.size(scale), rgb)
        if unlocked:
            txt(entry[0], 0xdca0, 0xdcb8); txt(d.e.strings[0xded0], 0xdca8, 0xdcbc, [0, 0, 255, 255])
            txt(entry[1], 0xdcb0, 0xdcb8); txt(entry[2], 0xdcc0, 0xdcc8)
        else: txt(d.e.strings[0xdf40], 0xdcc0, 0xdcc8)
        d.add(0xdc04, 43, offset=(0, y), anchored=False, tint=color(d.e.scalar[0xdc28 if unlocked else 0xdc2c]))
        p = d.e.point[0xdc54]; size = d.size(0xdc60)
        for j, value in enumerate(((row + 1) // 10, (row + 1) % 10)):
            d.text('Replay ordinal', number(value), [p[0] + j * d.e.signed(0xdc5c), p[1] + y - size // 2], size, center=True)
        if unlocked and d.state.get('new', False):
            s = d.e.sprite[0xdcdc]; new_marker(d.out, d.lib, [s['x'], s['y'] + y])
    for layer in d.out.layers[start:]: layer.clip = list(d.e.rect[0xdbe4])
    d.add(0xdd5c, 45); p = d.e.point[0xdccc][:]
    if unlocked:
        layer = d.add(0xdd80, 0); layer.asset = f'resource.dat:2/2/1/{selected}'
        separator = d.e.strings[0xdf08]
        if not separator: raise ImageError('Missing replay description separator')
        lines = d.e.replays[selected][3].split(separator)
    else:
        d.add(0xdda4, 44); lines = [d.e.strings[0xdf78]]
    for line in lines:
        d.text('Replay description', line, p, d.size(0xdcd8)); p[1] += d.e.signed(0xdcd4)
    d.footer('replay', len(d.e.replays))


def extras_layout(library, state, font):
    if font is None: raise ImageError('Original font/layout data is required')
    d = ExtrasDraw(library, state, font); view = state.get('view', 0)
    if view == 0: root_layout(d)
    elif view in (1, 2, 3, 4):
        root_state = dict(state, selected=view - 1); saved = d.state
        # Rebuild the retained root target for the selected child, then retain
        # only its background pass. Child owners supply their own chrome.
        d.state = root_state; root_layout(d); d.out.layers = d.out.layers[:3]; d.state = saved
        (cg_layout, movies_layout, music_layout, replay_layout)[view - 1](d)
    else: raise ImageError('Unknown Extras composition view')
    return d.out


ADAPTERS = {'extras': extras_layout}
PARAMETERS = {'extras': [
    ('view', 'Extras screen', 'enum', 0, [(0, 'Section menu'), (1, 'CG album'), (2, 'Movie gallery'), (3, 'Music player'), (4, 'Battle replay list')]),
    ('unlocked', 'Preview unlocked content', 'bool', True), ('new', 'Preview new markers', 'bool', False),
    ('first', 'First row (-1 automatic)', 'int', -1, -1, 999), ('scroll', 'Scroll channel %', 'int', 0, 0, 100),
    ('category', 'CG category', 'int', 0, 0, 5), ('page', 'Page in CG category', 'int', 0, 0, 99),
    ('image_view', 'View selected full CG', 'bool', False), ('variant', 'CG image variant', 'int', 0, 0, 19),
    ('playing', 'Preview playing state', 'bool', False), ('elapsed', 'Preview position (seconds)', 'int', 0, 0, 9999),
    ('music_mode', 'Music mode', 'enum', 0, [(0, 'Mode0'), (1, 'Mode1'), (2, 'Mode2')]),
]}


def preview_limits(library, state):
    e = cached(library, 'extras', 'env/env_omake.dat', extras_environment); view = state['view']
    if view == 0: return dict(selected=3, first=0)
    if view == 1:
        cat = cg_catalogue(library, e); pages = cat['pages'][state['category']]
        if not pages: raise ImageError('Selected CG category has no authored entries')
        page = min(state['page'], len(pages) - 1); cards = pages[page]; cells = [i for i, v in enumerate(cards) if v is not None]
        selected = min(state['selected'], max(cells)); images = cat['entries'][cards[selected]]['images']
        return dict(selected=max(cells), first=0, page=len(pages) - 1, variant=len(images) - 1)
    count, visible = (len(e.movies), 1) if view == 2 else (len(e.music), 6) if view == 3 else (len(e.replays), 4)
    result = dict(selected=count - 1, first=max(0, count - visible))
    if view == 3: result['elapsed'] = max(0, e.music[min(state['selected'], count - 1)]['duration'])
    return result


def parameter_visible(name, view):
    if name in ('category', 'page', 'image_view', 'variant'): return view == 1
    if name in ('playing', 'elapsed', 'music_mode'): return view == 3
    if name in ('first', 'scroll'): return view in (2, 3, 4)
    if name in ('unlocked', 'new'): return view != 0
    return True
