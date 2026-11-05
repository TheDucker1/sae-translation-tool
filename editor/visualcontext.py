"""Read-only visual context shared by MCP transports; uses existing Python UI code."""
from collections import OrderedDict
from copy import copy, deepcopy
import base64
import hashlib
import json
from pathlib import Path
import threading
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from .composition import FAMILIES, EnvironmentLibrary, Layer
from .compositionstate import resolve_state
from .compositionrender import AssetResolver, TextureLoader, FontConsumer, render_composition
from .imageassets import build_catalog, stamp
from .imagecodec import ImageError
from .text import TextPresentation, unicode_text

IMAGE_KEY = '_mcp_image_png'  # Removed by the protocol adapter, never JSON/base64 text.
COORDINATES = dict(units='game pixels', origin='top-left', x_direction='right', y_direction='down',
                   rectangle='[x, y, width, height]', canvas=[960, 544], order='later siblings draw over earlier siblings within a pass')
LIMITATIONS = ['Static UI compositions, not arbitrary story reconstruction or a native runtime capture.',
    'External actors/Live2D, timed particles, media and personal saves/unlocks are not reconstructed.',
    'Text uses current project font data with Qt rasterization; ruby/keyword decorations/reveal remain approximate.',
    'All supplied state is preview-local. No project, game file, GUI selection or simulator state is changed.']


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()


def image_reply(image, metadata, max_size=1024, origin=(0, 0)):
    if type(max_size) is not int or not 64 <= max_size <= 2048: raise ImageError('Image max_size must be64..2048')
    width, height = image.width(), image.height()
    if max(width, height) > max_size: image = image.scaled(max_size, max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    data = QByteArray(); buffer = QBuffer(data); buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, 'PNG'): raise ImageError('Could not encode visual preview')
    buffer.close(); raw = bytes(data)
    if len(raw) > 8 * 1024 * 1024: raise ImageError('PNG exceeds8MiB response budget; request a smaller max_size')
    metadata['image'] = dict(mime_type='image/png', width=image.width(), height=image.height(), bytes=len(raw),
        source_region=[*origin, width, height], source_to_preview_scale=[image.width() / width, image.height() / height],
        delivery='MCP image content block; coordinates in metadata remain original game/texture pixels')
    metadata[IMAGE_KEY] = raw
    return metadata


def protocol_image(result):
    """After owner-thread dispatch, keep PNG out of the JSON metadata/structured output."""
    if not isinstance(result, dict) or IMAGE_KEY not in result: return result
    from mcp.types import CallToolResult, ImageContent, TextContent
    data = dict(result); raw = data.pop(IMAGE_KEY)
    return CallToolResult(content=[TextContent(type='text', text=json.dumps(data, ensure_ascii=False)),
        ImageContent(type='image', data=base64.b64encode(raw).decode('ascii'), mime_type='image/png')], structured_content=data)


def asset_summary(asset):
    return dict(asset_id=asset.id, name=asset.name.strip(' \0'), category=asset.category, consumer=asset.consumer,
                source=asset.source, route=list(asset.route), width=asset.width, height=asset.height,
                format=asset.format, kind=asset.kind, member_bytes=asset.size, storage_order=asset.order, status=asset.status, error=asset.error,
                atlas_region_count=len(asset.regions), original_script_use_count=len(asset.references))


def layer_records(composition, catalog):
    records = []
    def walk(layers, parent=None, pass_id='canvas', path=()):
        for order, layer in enumerate(layers):
            route = (*path, order); identity = 'layer:' + '.'.join(map(str, route))
            record = dict(layer_id=identity, parent_id=parent, traversal_index=len(records), draw_order=order, pass_id=pass_id,
                name=layer.name, kind=layer.kind, destination_rect=list(layer.destination), source_rect=list(layer.source),
                rgba=list(layer.rgba), opacity=layer.rgba[3] / 255, clip_rect=list(layer.clip) or None,
                rotation=None if not layer.rotation else dict(degrees=layer.rotation[0], pivot=list(layer.rotation[1:])),
                blend=layer.blend, mask_target=layer.mask or None, output_target='@target:' + layer.target if layer.target else None,
                generated=layer.asset.startswith('@target:'), asset_id=layer.asset or None,
                source_flip_x=bool(layer.source and layer.source[2] < 0), source_flip_y=bool(layer.source and layer.source[3] < 0),
                drawn_to_canvas=pass_id == 'canvas' and layer.kind != 'target',
                child_ids=['layer:' + '.'.join(map(str, (*route, i))) for i in range(len(layer.children))])
            if layer.asset in catalog.by_id: record['asset'] = asset_summary(catalog.by_id[layer.asset])
            if layer.kind == 'target': record['meaning'] = 'Offscreen pass; children render into output_target, not directly onto the canvas'
            if layer.kind == 'solid': record['meaning'] = 'Colored rectangle; no source texture'
            if layer.kind == 'text':
                spans = []
                for i, glyph in enumerate(layer.glyphs):
                    rgb = glyph.get('rgb', layer.rgba[:3])
                    if spans and spans[-1]['rgb'] == rgb: spans[-1]['end_glyph'] = i + 1
                    else: spans.append(dict(start_glyph=i, end_glyph=i + 1, rgb=list(rgb)))
                record.update(text=unicode_text(layer.text), font_size=layer.size, glyph_count=len(layer.glyphs), color_spans=spans,
                    role='text_shadow' if 'shadow' in layer.name.casefold() else 'ui_text',
                    text_source='Authored layout text or supplied preview sample; this API does not edit its source',
                    meaning='Rendered UI text, not baked texture lettering; glyphs available through get_ui_scene_layers(include_glyphs=true)',
                    _glyphs=deepcopy(layer.glyphs))
            records.append(record)
            if layer.children: walk(layer.children, identity, '@target:' + layer.target, route)
    walk(composition.layers)
    return records


def page_layers(rows, start, limit, include_glyphs=False):
    if type(start) is not int or start < 0 or type(limit) is not int or not 1 <= limit <= 100: raise ImageError('Use nonnegative start and limit1..100')
    selected = []
    for row in rows[start:start + limit]:
        item = {key: deepcopy(value) for key, value in row.items() if key != '_glyphs'}
        if include_glyphs and '_glyphs' in row: item['glyphs'] = deepcopy(row['_glyphs'])
        selected.append(item)
    if len(json.dumps(selected, ensure_ascii=True)) > 2 * 1024 * 1024:
        raise ImageError('Layer page exceeds2MiB; reduce limit or omit include_glyphs')
    return dict(layers=selected, total_layers=len(rows), next_start=start + limit if start + limit < len(rows) else None)


class VisualContext:
    def __init__(self):
        self.source_key = None; self.catalog = None; self.scenes = OrderedDict(); self.local = threading.local()
        self.project_revision = None
        self.replacements = {}; self.replacement_key = None

    def bind(self, workspace):
        root = Path(workspace.project.root).resolve(); key = (str(root), id(getattr(workspace._runtime, 'original', None)))
        if key != self.source_key:
            catalog = build_catalog(root, getattr(workspace._runtime, 'descriptions', {}))
            names = ['Font.gsf', 'DFHSR4.TTC', *('env/' + name + '.dat' for name in (
                'env_string_format', 'env_config', 'env_game_utility', 'env_global', 'env_message_window'))]
            font_stamps = {name: stamp(root / name) for name in names}
            font_sources = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
            catalog.verify()
            if any(stamp(root / name) != value for name, value in font_stamps.items()):
                raise ImageError('Font source changed while preparing visual context; reload and retry')
            self.catalog = catalog; self.library = EnvironmentLibrary(root, catalog=catalog)
            self.loader = TextureLoader(AssetResolver(catalog)); self.source_key = key; self.scenes.clear()
            self.catalog_revision = fingerprint({name: item['sha256'] for name, item in catalog.sources.items()})
            self.font_stamps, self.font_sources = font_stamps, font_sources
        if self.project_revision != workspace.project.revision:
            self.scenes.clear(); self.project_revision = workspace.project.revision
        replacements = dict(getattr(workspace.project, 'texture_assets', {}))
        replacement_key = fingerprint({key: value['png_sha256'] for key, value in replacements.items()})
        if self.replacement_key != (self.source_key, replacement_key):
            self.replacements = replacements; self.replacement_key = (self.source_key, replacement_key)
            self.loader = TextureLoader(AssetResolver(self.catalog, replacements)); self.scenes.clear()
        self.root = root; self.verify()
        return self

    def verify(self):
        self.catalog.verify(); self.library.verify()
        if any(stamp(self.root / name) != value for name, value in self.font_stamps.items()):
            raise ImageError('Visual font/layout source changed; reload the game or restart standalone MCP')

    def font(self, workspace):
        asset = getattr(workspace.project, 'font_asset', None)
        key = (self.source_key, asset['manifest']['font_sha256'] if asset else None, fingerprint(self.font_sources))
        if getattr(self, 'font_template_key', None) != key:
            # Parsing creates no QRawFont. Immutable font bytes/tables may be
            # shared; raster objects/caches belong to the calling thread only.
            self.font_template = TextPresentation(self.root, font_asset=bytes.fromhex(asset['data_hex']) if asset else None)
            self.font_template_key = key
        def fresh():
            font = copy(self.font_template); font.raw_font = None; font.glyph_cache = {}; font.atlas_cache = {}
            return font, FontConsumer(font)
        if not getattr(workspace, 'live', False): return fresh()
        if getattr(self.local, 'font_key', None) != key:
            self.local.font, self.local.consumer = fresh(); self.local.font_key = key
        return self.local.font, self.local.consumer

    def check_catalog(self, expected=None):
        if expected is not None and expected != self.catalog_revision: raise ImageError('Stale catalog revision; call list_textures again')

    def textures(self, query='', category='', source='', start=0, limit=30):
        needle = query.casefold()
        assets = [a for a in self.catalog.assets if (not category or a.category == category) and (not source or a.source == source)
                  and needle in ' '.join((a.id, a.name, a.category, a.consumer)).casefold()]
        return dict(catalog_revision=self.catalog_revision, textures=[dict(asset_summary(a), replacement=self.replacement_info(a.id)) for a in assets[start:start + limit]],
            total=len(assets), next_start=start + limit if start + limit < len(assets) else None,
            categories=sorted({a.category for a in self.catalog.assets}), sources=sorted(self.catalog.sources),
            notes=['Known consumers describe intended use. Original-script uses are static potential references, not proven runtime scenes.'])

    def replacement_info(self, identity):
        from .textureassets import summary
        return summary(self.replacements[identity]) if identity in self.replacements else None

    def texture(self, identity, include_image=True, region=None, max_size=1024, view='current'):
        if identity not in self.catalog.by_id: raise ImageError('Unknown texture asset_id; call list_textures')
        asset = self.catalog.by_id[identity]
        result = dict(catalog_revision=self.catalog_revision, texture=asset_summary(asset), provenance=deepcopy(asset.chain),
            view=view, replacement=self.replacement_info(identity),
            source_sha256=self.catalog.sources[asset.source]['sha256'], coordinates=dict(units='texture pixels', rectangle='[x,y,width,height]', origin='top-left'),
            guidance='Texture lettering is baked into pixels. UI text layers are separately exposed by get_ui_scene; do not assume OCR text is a script field.')
        if not include_image: return result
        image = self.loader.resolver.image(identity) if view == 'current' else self.catalog.decode(identity); origin = (0, 0)
        if region is not None:
            x, y, w, h = region
            if min(x, y) < 0 or min(w, h) <= 0 or x + w > image.width() or y + h > image.height(): raise ImageError('Texture crop is outside original dimensions')
            image = image.copy(x, y, w, h); origin = (x, y)
        return image_reply(image, result, max_size, origin)

    def usage(self, identity, kind, start=0, limit=30):
        if identity not in self.catalog.by_id: raise ImageError('Unknown texture asset_id')
        asset = self.catalog.by_id[identity]; rows = asset.regions if kind == 'atlas_regions' else asset.references
        return dict(catalog_revision=self.catalog_revision, asset_id=identity, kind=kind, items=deepcopy(rows[start:start + limit]),
            total=len(rows), next_start=start + limit if start + limit < len(rows) else None,
            notes=['Uses refer to original scripts. Atlas mapping is partial; missing regions do not imply unused pixels.'])

    def describe(self, family, state=None):
        resolved, parameters = resolve_state(self.library, family, state)
        label, coverage = next((name, coverage) for key, name, coverage in FAMILIES if key == family)
        return dict(family=family, name=label, coverage=coverage, catalog_revision=self.catalog_revision,
                    state=resolved, parameters=parameters, coordinates=COORDINATES, limitations=LIMITATIONS,
                    state_policy='Only supplied preview state; describe again after changing page/view/count to obtain its authored bounds. Unknown keys/types/ranges reject.')

    def scene(self, workspace, family, state=None, include_image=True, max_size=1024, limit=50):
        description = self.describe(family, state); resolved = description['state']; font, consumer = self.font(workspace)
        composition = self.library.build(family, resolved, font)
        if resolved.get('context_image'):
            composition.layers.insert(0, Layer('Chosen context backdrop', asset=resolved['context_image'], source=[0, 0, 960, 544], destination=[0, 0, 960, 544]))
        rows = layer_records(composition, self.catalog)
        for row in rows:
            if row['asset_id'] in self.replacements: row['replacement'] = self.replacement_info(row['asset_id'])
        font_asset = getattr(workspace.project, 'font_asset', None)
        basis = dict(catalog_revision=self.catalog_revision, project_revision=workspace.project.revision, family=family, state=resolved,
                     texture_replacements={key: self.replacement_info(key) for key in self.replacements},
                     layout_sources=deepcopy(composition.sources), font_sources=self.font_sources,
                     font_asset_sha256=font_asset['manifest']['font_sha256'] if font_asset else None)
        identity = 'scene:' + fingerprint(basis)
        metadata = dict(scene_id=identity, **basis, coordinates=COORDINATES, coverage=description['coverage'],
            notes=composition.notes + LIMITATIONS, text_layer_count=sum(row['kind'] == 'text' for row in rows),
            assets=list(dict.fromkeys(row['asset_id'] for row in rows if row['asset_id'] and not row['generated'])),
            text_break_token=font.format.break_char, diagnostics=[], complete_visual=None)
        if include_image:
            textures, errors = self.loader.load(composition); image, issues = render_composition(composition, textures, consumer)
            metadata.update(diagnostics=errors + issues, complete_visual=not errors and not issues)
        self.verify()
        self.scenes[identity] = (metadata, rows); self.scenes.move_to_end(identity)
        while len(self.scenes) > 8: self.scenes.popitem(last=False)
        result = deepcopy(metadata); result.update(page_layers(rows, 0, limit))
        return image_reply(image, result, max_size) if include_image else result

    def layers(self, identity, start=0, limit=30, include_glyphs=False, kind='all'):
        if identity not in self.scenes: raise ImageError('Scene snapshot is stale, evicted or belongs to another session; call get_ui_scene again')
        metadata, rows = self.scenes[identity]; self.scenes.move_to_end(identity)
        if kind not in ('all', 'text', 'sprite', 'solid', 'target'): raise ImageError('Unknown layer kind')
        selected = rows if kind == 'all' else [row for row in rows if row['kind'] == kind]
        return dict(scene_id=identity, project_revision=metadata['project_revision'], catalog_revision=self.catalog_revision,
                    coordinates=COORDINATES, kind=kind, total_scene_layers=len(rows), offset_space='kind-filtered layer list; original IDs/order retained',
                    **page_layers(selected, start, limit, include_glyphs))
