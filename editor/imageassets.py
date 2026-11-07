"""Read-only whole-tree image inventory, provenance and separate extraction."""
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
import struct
import tempfile
import threading
import zlib
from .archive import Archive
from .packing import payload
from .imagecodec import ImageError, ImageCancelled, checkpoint, inspect_gxt, decode_gxt
from .imageusage import BANKS, family, static_references, message_regions, font_regions


MAX_FILE = 512 * 1024 * 1024
MAX_MEMBER = 128 * 1024 * 1024


def stamp(path):
    s = path.stat()
    return (s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino)


def unpack_member(archive, index):
    entry = archive.entries[index]
    raw = payload(archive, index, physical=entry.kind == 2)
    compressed = bytes(raw[:2]) == b'\x1f\x8b'
    if compressed:
        decoder = zlib.decompressobj(31)
        decoded = decoder.decompress(raw, MAX_MEMBER + 1)
        if len(decoded) > MAX_MEMBER or not decoder.eof:
            raise ImageError('Truncated or oversized gzip member')
        if entry.kind != 2 and decoder.unused_data:
            raise ImageError('Unexpected bytes after gzip member')
        return decoded, True
    if entry.kind == 1:
        raise ImageError('Type 1 member has no gzip signature')
    if entry.kind not in (0, 2):
        raise ImageError(f'Unsupported GPDA member kind {entry.kind}')
    return raw, False


def font_sections(data):
    if len(data) < 16 or bytes(data[:4]) != b'FONT' or struct.unpack_from('<I', data, 4)[0] != 0:
        raise ImageError('Unsupported FONT container')
    count, size = struct.unpack_from('<II', data, 8)
    if not 2 <= count <= 258 or size != len(data) or 16 + count * 8 > size:
        raise ImageError('Invalid FONT extent/table')
    sections, previous = [], 16 + count * 8
    for i in range(count):
        at, length = struct.unpack_from('<II', data, 16 + i * 8)
        if at < previous or at + length > size:
            raise ImageError('FONT section outside container')
        sections.append((at, length)); previous = at + length
    return sections


@dataclass
class ImageAsset:
    id: str
    source: str
    route: tuple
    name: str
    chain: list
    category: str
    consumer: str
    kind: str
    size: int
    width: int = 0
    height: int = 0
    format: str = ''
    order: str = ''
    status: str = 'Ready'
    error: str = ''
    regions: list = field(default_factory=list)
    references: list = field(default_factory=list)

    @property
    def location(self):
        return self.source + ''.join(f' / {i}' for i in self.route)

    def to_dict(self):
        return asdict(self)


class ImageCatalog:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.assets = []
        self.by_id = {}
        self.sources = {}
        self.issues = []
        self.coverage = []
        self.dynamic_references = []
        self.counts = dict(containers=0, leaves=0, scanned_files=0)
        self.raw_cache = OrderedDict()
        self.raw_cache_bytes = 0
        self._cache_lock = threading.RLock()

    def verify(self):
        for source, metadata in self.sources.items():
            if stamp(self.root / source) != metadata['stamp']:
                raise ImageError(f'Source changed: {source}. Re-index before browsing or extracting.')

    def source_data(self, source):
        with self._cache_lock:
            return self._source_data(source)

    def _source_data(self, source):
        self.verify()
        if source in self.raw_cache:
            self.raw_cache.move_to_end(source)
            return self.raw_cache[source]
        data = (self.root / source).read_bytes()
        if hashlib.sha256(data).hexdigest() != self.sources[source]['sha256']:
            raise ImageError(f'Source content changed: {source}. Re-index required.')
        while self.raw_cache and self.raw_cache_bytes + len(data) > 96 * 1024 * 1024:
            _, old = self.raw_cache.popitem(last=False); self.raw_cache_bytes -= len(old)
        if len(data) <= 96 * 1024 * 1024:
            self.raw_cache[source] = data; self.raw_cache_bytes += len(data)
        return data

    def read(self, asset_id, cancelled=None):
        asset = self.by_id[asset_id]
        data = self.source_data(asset.source)
        for step in asset.chain:
            checkpoint(cancelled)
            if step['container'] == 'GPDA':
                data, _ = unpack_member(Archive(data), step['index'])
            else:
                at, size = font_sections(data)[step['index']]
                data = data[at:at + size]
        self.verify()
        return bytes(data)

    def read_member(self, source, route, cancelled=None):
        """Read immutable catalogue metadata through the same GPDA/gzip cache."""
        if source not in self.sources: raise ImageError('Source was not part of this inventory')
        data = self.source_data(source)
        for index in route:
            checkpoint(cancelled)
            archive = Archive(data)
            if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(archive.entries):
                raise ImageError('Metadata member index outside archive')
            data, _ = unpack_member(archive, index)
        self.verify(); checkpoint(cancelled)
        return bytes(data)

    def decode(self, asset_id, cancelled=None):
        asset = self.by_id[asset_id]
        data = self.read(asset_id, cancelled)
        if asset.kind == 'GXT':
            return decode_gxt(data, cancelled)
        from PySide6.QtGui import QImage
        image = QImage.fromData(data)
        if image.isNull():
            raise ImageError('Qt could not decode image')
        checkpoint(cancelled)
        return image.convertToFormat(QImage.Format_RGBA8888)

    def summary(self):
        return dict(images=len(self.assets), ready=sum(a.status == 'Ready' for a in self.assets),
                    **self.counts, coverage=self.coverage, issues=self.issues,
                    dynamic_references=self.dynamic_references,
                    notes=['Static references are original-script potential uses, not executed scene coverage.',
                           'Dynamic resources and indirect native screen bindings are not exhaustive.',
                           'Save-slot thumbnails are generated in personal saves, outside original asset inventory.'])


def build_catalog(root, descriptions=None, progress=None, cancelled=None):
    catalog = ImageCatalog(root)
    if not catalog.root.is_dir():
        raise ImageError('Select a valid USRDIR folder')
    references, catalog.dynamic_references = static_references(descriptions or {}, cancelled or (lambda: False))
    regions = {}
    env = catalog.root / 'env/env_message_window.dat'
    if env.is_file():
        try:
            before = stamp(env); blob = env.read_bytes()
            regions = message_regions(blob)
            if before != stamp(env):
                raise ImageError('Message environment changed during indexing')
            catalog.sources['env/env_message_window.dat'] = dict(stamp=before, sha256=hashlib.sha256(blob).hexdigest())
        except (ValueError, OSError, struct.error) as error:
            catalog.issues.append(dict(location='env/env_message_window.dat', error=str(error)))
    visited = set()

    def image(data, source, route, chain, name, kind, extra_regions=()):
        category, consumer = family(source, route)
        asset_id = source + ':' + '/'.join(map(str, route))
        asset = ImageAsset(asset_id, source, route, name, chain, category, consumer, kind, len(data))
        asset.regions = list(regions.get((source, route), ())) + list(extra_regions)
        if source == 'resource.dat':
            for prefix, uses in references.items():
                if route[:len(prefix)] == prefix:
                    asset.references.extend(uses)
        try:
            if kind == 'GXT':
                info = inspect_gxt(data)
                asset.width, asset.height, asset.format, asset.order = info.width, info.height, info.format, info.order
            else:
                from PySide6.QtCore import QBuffer, QByteArray, QIODevice
                from PySide6.QtGui import QImageReader
                buffer = QBuffer(); buffer.setData(QByteArray(bytes(data))); buffer.open(QIODevice.ReadOnly)
                reader = QImageReader(buffer); size = reader.size()
                if not size.isValid() or size.width() * size.height() > 64 * 1024 * 1024:
                    raise ImageError('Invalid standard-image dimensions or decode budget exceeded')
                asset.width, asset.height, asset.format = size.width(), size.height(), kind
        except (ValueError, struct.error) as error:
            asset.status, asset.error = 'Unsupported / invalid', str(error)
        catalog.assets.append(asset); catalog.by_id[asset.id] = asset

    def walk(data, source, route=(), chain=None, name='', depth=0):
        checkpoint(cancelled)
        chain = chain or []
        if depth > 24 or catalog.counts['leaves'] + catalog.counts['containers'] > 500000:
            raise ImageError('Container depth/entry budget exceeded')
        signature = bytes(data[:4])
        if signature == b'GPDA':
            archive = Archive(data); catalog.counts['containers'] += 1
            for i, entry in enumerate(archive.entries):
                checkpoint(cancelled)
                child_route = route + (i,)
                visited.add((source, child_route))
                try:
                    child, compressed = unpack_member(archive, i)
                    physical_size = len(payload(archive, i, True))
                    step = dict(container='GPDA', index=i, name=entry.name, kind=entry.kind,
                                offset=entry.offset, logical_size=entry.size, physical_size=physical_size,
                                compression='gzip' if compressed else 'none',
                                offset_space='source file' if not chain else 'decoded parent container')
                    walk(child, source, child_route, chain + [step], entry.name, depth + 1)
                except ImageCancelled:
                    raise
                except (ValueError, OSError, struct.error, zlib.error) as error:
                    catalog.issues.append(dict(location=source + ':' + '/'.join(map(str, child_route)),
                                               name=entry.name, error=str(error)))
            return
        if signature == b'FONT':
            sections = font_sections(data)
            try:
                glyphs = font_regions(data, sections)
            except (ValueError, struct.error) as error:
                glyphs = {}; catalog.issues.append(dict(location=source, error=str(error)))
            catalog.counts['containers'] += 1
            for i, (at, size) in enumerate(sections[:-2]):
                step = dict(container='FONT', index=i, name=f'atlas {i}', offset=at,
                            logical_size=size, physical_size=size, compression='none',
                            offset_space='source file' if not chain else 'decoded parent container')
                image(data[at:at + size], source, route + (i,), chain + [step],
                      f'Font atlas {i}', 'GXT', glyphs.get(i, ()))
            return
        catalog.counts['leaves'] += 1
        suffix = Path(name.rstrip()).suffix.lower()
        kind = ('GXT' if signature == b'GXT\0' or suffix == '.gxt' else
                'PNG' if signature == b'\x89PNG' or suffix == '.png' else
                'JPEG' if bytes(data[:3]) == b'\xff\xd8\xff' or suffix in ('.jpg', '.jpeg') else '')
        if kind:
            image(data, source, route, chain, name or Path(source).name, kind)

    for path in sorted(catalog.root.rglob('*')):
        checkpoint(cancelled)
        if not path.is_file():
            continue
        relative = path.relative_to(catalog.root).as_posix()
        catalog.counts['scanned_files'] += 1
        if not path.resolve().is_relative_to(catalog.root):
            catalog.issues.append(dict(location=relative, error='External symbolic-link target skipped'))
            continue
        with path.open('rb') as stream:
            head = stream.read(4)
        if head not in (b'GPDA', b'FONT', b'GXT\0', b'\x89PNG') and head[:3] != b'\xff\xd8\xff' and path.suffix.lower() not in ('.gxt', '.png', '.jpg', '.jpeg', '.gsf'):
            continue
        if progress:
            progress(f'Indexing {relative} — {len(catalog.assets)} images')
        try:
            before = stamp(path)
            if before[0] > MAX_FILE:
                raise ImageError('Source exceeds 512 MiB in-memory index budget')
            data = path.read_bytes()
            if before != stamp(path):
                raise ImageError('Source changed during indexing')
            catalog.sources[relative] = dict(stamp=before, sha256=hashlib.sha256(data).hexdigest())
            walk(data, relative)
        except ImageCancelled:
            raise
        except (ValueError, OSError, struct.error, zlib.error) as error:
            catalog.issues.append(dict(location=relative, error=str(error)))
    for (source, bank), (category, consumer) in BANKS.items():
        if source not in catalog.sources:
            continue
        assets = [a for a in catalog.assets if a.source == source and a.route and a.route[0] == bank]
        catalog.coverage.append(dict(source=source, bank=bank, category=category, consumer=consumer,
                                     scanned=(source, (bank,)) in visited, images=len(assets)))
    catalog.verify()
    return catalog


def extract_images(catalog, ids, destination, mode='both', progress=None, cancelled=None):
    """All-or-nothing publication to a separate new/empty directory. No repacking."""
    if mode not in ('raw', 'png', 'both'):
        raise ImageError('Extraction mode must be raw, png or both')
    ids = list(dict.fromkeys(ids))
    if not ids or any(key not in catalog.by_id for key in ids):
        raise ImageError('Choose at least one indexed image')
    target = Path(destination).expanduser().resolve()
    if target == catalog.root or target.is_relative_to(catalog.root) or catalog.root.is_relative_to(target):
        raise ImageError('Extraction folder must be separate from source USRDIR')
    if not target.parent.is_dir():
        raise ImageError('Output parent folder does not exist')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ImageError('Choose a new/empty extraction folder; existing files are never overwritten')
    catalog.verify()
    manifest = dict(schema=1, operation='read-only image extraction', sources=catalog.sources,
                    images=[], scope=catalog.summary(), original_data_modified=False)
    # Manifest paths are relative to USRDIR. No local usernames or absolute source
    # paths are necessary to identify an archive/member for later tooling.
    with tempfile.TemporaryDirectory(prefix='.saekano-images-', dir=target.parent) as temporary:
        staging = Path(temporary) / 'images'; staging.mkdir()
        for i, key in enumerate(ids):
            checkpoint(cancelled)
            asset = catalog.by_id[key]
            if progress:
                progress(f'Extracting {i + 1}/{len(ids)}: {asset.name}')
            raw = catalog.read(key, cancelled)
            safe_name = re.sub(r'[^\w.-]+', '_', Path(asset.name.strip()).stem, flags=re.UNICODE)[:70] or 'image'
            prefix = f'{i:05d}_{safe_name}'
            row = dict(asset=asset.to_dict(), raw_sha256=hashlib.sha256(raw).hexdigest(), files={})
            if mode in ('raw', 'both'):
                suffix = '.gxt' if asset.kind == 'GXT' else '.png' if asset.kind == 'PNG' else '.jpg'
                name = prefix + suffix
                # Avoid a raw PNG colliding with the separately decoded PNG.
                if suffix == '.png' and mode == 'both': name = prefix + '.original.png'
                (staging / name).write_bytes(raw); row['files']['raw'] = name
            if mode in ('png', 'both'):
                image = catalog.decode(key, cancelled)
                name = prefix + '.png'
                if not image.save(str(staging / name), 'PNG'):
                    raise ImageError(f'Could not save PNG for {asset.id}')
                row['files']['png'] = name
            manifest['images'].append(row)
        checkpoint(cancelled); catalog.verify()
        (staging / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        if target.exists():
            target.rmdir()  # Fails safely if another process populated it meanwhile.
        staging.rename(target)
    return dict(path=str(target), count=len(ids), mode=mode)
