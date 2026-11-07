"""Lossless PNG project deltas. No GXT encoder or original/game archive writes."""
import base64
import hashlib
from pathlib import Path
import struct
import zlib
from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage
from .imagecodec import ImageError, checkpoint
from .imageassets import build_catalog, stamp

MAX_PNG = 32 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_TEXTURES = 4096
SIGNATURE = b'\x89PNG\r\n\x1a\n'
RECORD_FIELDS = {'format', 'version', 'asset_id', 'width', 'height', 'source', 'source_kind', 'source_format',
                 'png_sha256', 'rgba_sha256', 'png_bytes', 'png_base64'}


def sha(data): return hashlib.sha256(data).hexdigest()


def decode_png(data, expected_size=None):
    """Validate bounded static <=8-bit PNG, preserving straight RGBA incl.alpha0 RGB."""
    if not isinstance(data, bytes) or not 45 <= len(data) <= MAX_PNG or not data.startswith(SIGNATURE):
        raise ImageError('Expected a PNG of at most32MiB')
    at = 8; first = True; dimensions = None; pixels = False; ended = False
    while at < len(data):
        if at + 12 > len(data): raise ImageError('Truncated PNG chunk')
        length = struct.unpack_from('>I', data, at)[0]; kind = data[at + 4:at + 8]; end = at + 12 + length
        if end > len(data): raise ImageError('PNG chunk exceeds file extent')
        payload = data[at + 8:end - 4]
        if zlib.crc32(kind + payload) & 0xffffffff != struct.unpack_from('>I', data, end - 4)[0]:
            raise ImageError('PNG chunk checksum mismatch')
        if first:
            if kind != b'IHDR' or length != 13: raise ImageError('PNG must begin with one IHDR')
            width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', payload)
            if not width or not height or width * height > 64 * 1024 * 1024: raise ImageError('PNG dimensions exceed64 megapixels')
            if depth == 16: raise ImageError('16-bit PNG is unsupported; supply8-bit pixels to avoid precision loss')
            if depth not in (1, 2, 4, 8) or color not in (0, 2, 3, 4, 6) or compression or filtering or interlace > 1:
                raise ImageError('Unsupported PNG pixel layout')
            dimensions = width, height; first = False
            if expected_size is not None and dimensions != expected_size:
                raise ImageError(f'Replacement must retain original dimensions {expected_size[0]}×{expected_size[1]}; atlas/layout coordinates are unchanged')
        elif kind == b'IHDR': raise ImageError('Duplicate PNG IHDR')
        if kind == b'acTL': raise ImageError('Animated PNG is unsupported; supply one static texture')
        if kind == b'IDAT': pixels = True
        if kind == b'IEND':
            if length or end != len(data): raise ImageError('Invalid PNG ending or trailing data')
            ended = True; break
        at = end
    if not ended or not pixels: raise ImageError('PNG image data or ending is missing')
    image = QImage.fromData(data, 'PNG')
    if image.isNull() or (image.width(), image.height()) != dimensions: raise ImageError('PNG decoding failed')
    return image.convertToFormat(QImage.Format_RGBA8888)


def encode_png(image):
    data = QByteArray(); buffer = QBuffer(data); buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, 'PNG'): raise ImageError('Could not encode PNG')
    buffer.close(); result = bytes(data)
    if len(result) > MAX_PNG: raise ImageError('PNG exceeds32MiB project limit')
    return result


def read_png(path):
    path = Path(path); before = stamp(path)
    if before[0] > MAX_PNG: raise ImageError('PNG exceeds32MiB project limit')
    data = path.read_bytes()
    if stamp(path) != before: raise ImageError('PNG changed while reading; retry import')
    return data


def summary(record): return {key: value for key, value in record.items() if key != 'png_base64'}


def png_bytes(record):
    text = record.get('png_base64')
    if not isinstance(text, str) or len(text) > ((MAX_PNG + 2) // 3) * 4: raise ImageError('Texture PNG payload exceeds project limit')
    try: data = base64.b64decode(text, validate=True)
    except (ValueError, UnicodeError) as error: raise ImageError('Invalid texture PNG payload') from error
    if len(data) != record.get('png_bytes') or sha(data) != record.get('png_sha256'): raise ImageError('Texture PNG checksum/size mismatch')
    return data


def make_replacement(catalog, identity, data):
    asset = catalog.by_id.get(identity)
    if asset is None or asset.status != 'Ready': raise ImageError('Select a supported original texture ID, not a generated target')
    image = decode_png(data, (asset.width, asset.height))
    if (image.width(), image.height()) != (asset.width, asset.height):
        raise ImageError(f'Replacement must retain original dimensions {asset.width}×{asset.height}; atlas/layout coordinates are unchanged')
    original = catalog.read(identity)
    return dict(format='saekano-png-texture', version=1, asset_id=identity, width=asset.width, height=asset.height,
        source=dict(file=asset.source, route=list(asset.route), sha256=catalog.sources[asset.source]['sha256'], member_sha256=sha(original)),
        source_kind=asset.kind, source_format=asset.format, png_sha256=sha(data), rgba_sha256=sha(bytes(image.constBits())),
        png_bytes=len(data), png_base64=base64.b64encode(data).decode('ascii'))


def validate_record(record, identity, catalog):
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS or record.get('format') != 'saekano-png-texture' or record.get('version') != 1:
        raise ImageError('Unsupported texture project record')
    if record['asset_id'] != identity: raise ImageError('Texture record identity mismatch')
    asset = catalog.by_id.get(identity)
    if asset is None or asset.status != 'Ready': raise ImageError('Texture source identity is missing/unsupported')
    source = record['source']
    if not isinstance(source, dict) or set(source) != {'file', 'route', 'sha256', 'member_sha256'}:
        raise ImageError('Invalid texture source provenance')
    if source['file'] != asset.source or source['route'] != list(asset.route) or source['sha256'] != catalog.sources[asset.source]['sha256']:
        raise ImageError('Texture source does not match original game data')
    if source['member_sha256'] != sha(catalog.read(identity)): raise ImageError('Original texture member changed')
    if record['source_kind'] != asset.kind or record['source_format'] != asset.format: raise ImageError('Texture source format mismatch')
    image = decode_png(png_bytes(record), (asset.width, asset.height))
    if (record['width'], record['height']) != (asset.width, asset.height) or (image.width(), image.height()) != (asset.width, asset.height):
        raise ImageError('Texture replacement dimensions changed')
    if sha(bytes(image.constBits())) != record['rgba_sha256']: raise ImageError('Texture decoded pixel checksum mismatch')


def check_budget(records):
    if not isinstance(records, dict) or len(records) > MAX_TEXTURES: raise ImageError('Texture collection exceeds4096 entries')
    total = 0
    for record in records.values():
        if not isinstance(record, dict) or type(record.get('png_bytes')) is not int or not 0 < record['png_bytes'] <= MAX_PNG:
            raise ImageError('Invalid texture PNG size')
        total += record['png_bytes']
    if total > MAX_TOTAL: raise ImageError('Project texture PNGs exceed128MiB total')


def validate_collection(records, root, catalog=None):
    check_budget(records)
    if not records: return catalog
    catalog = catalog or build_catalog(root)
    catalog.verify()
    for identity, record in records.items(): validate_record(record, identity, catalog)
    catalog.verify(); return catalog


def write_png(path, data, original_root):
    """Create a separate PNG, never overwrite any file or write into game data."""
    from .engine import ROOT
    target = Path(path).resolve(); original = Path(original_root).resolve()
    if target.is_relative_to(original) or target.is_relative_to((ROOT.parent / 'impacto-sae').resolve()):
        raise ImageError('PNG output must stay outside original game data and Impacto')
    if target.suffix.lower() != '.png' or not target.parent.is_dir(): raise ImageError('Choose a .png filename in an existing separate folder')
    decode_png(data)
    with target.open('xb') as stream:
        try: stream.write(data)
        except BaseException:
            stream.close(); target.unlink(missing_ok=True); raise
    return dict(path=str(target), bytes=len(data), png_sha256=sha(data))


def replacement_image(record, cancelled=None):
    checkpoint(cancelled); image = decode_png(png_bytes(record)); checkpoint(cancelled)
    return image
