"""Texture export preflight and sparse GPDA/gzip/FONT ancestor rebuilding."""
import gzip
from collections import defaultdict
from .archive import Archive
from .packing import repack
from .imageassets import unpack_member, font_sections, build_catalog
from .imagecodec import ImageError, ImageCancelled, checkpoint
from .textureassets import validate_collection, png_bytes, decode_png, sha
from .gxtwriter import encode_gxt, constraints


def prepare_textures(records, root, progress=None, cancelled=None, catalog=None):
    """Pure preparation. Returns encoded changes, report rows and guarded catalog."""
    if not records: return {}, [], catalog
    catalog = catalog or build_catalog(root, progress=progress, cancelled=cancelled)
    validate_collection(records, root, catalog)
    changes = defaultdict(list); rows = []
    for identity, record in sorted(records.items()):
        checkpoint(cancelled)
        if progress: progress('Encoding texture ' + identity + '…')
        asset = catalog.by_id[identity]
        try:
            if asset.kind != 'GXT': raise ImageError('Game export supports original GXT textures only')
            if any(s.get('kind') == 2 for s in asset.chain):
                raise ImageError('Type2 texture injection is unsupported; original game inventory uses no such paths')
            original = catalog.read(identity, cancelled)
            encoded = encode_gxt(original, decode_png(png_bytes(record)), cancelled)
        except ImageCancelled: raise
        except ImageError as error:
            raise ImageError(f'{identity}: {error}') from error
        changed = encoded != original
        if changed: changes[asset.source].append((asset.chain, encoded))
        rows.append(dict(asset_id=identity, source=asset.source, route=list(asset.route), changed=changed,
            constraints=constraints(asset), png_sha256=record['png_sha256'], rgba_sha256=record['rgba_sha256'],
            original_gxt_sha256=sha(original), output_gxt_sha256=sha(encoded), bytes=len(encoded)))
    catalog.verify(); return dict(changes), rows, catalog


def patch_tree(data, changes, cancelled=None):
    """Rebuild each shared ancestor once; existing kinds/names/order stay intact."""
    checkpoint(cancelled)
    leaves = [encoded for chain, encoded in changes if not chain]
    if leaves:
        if len(changes) != 1: raise ImageError('Overlapping texture replacement paths')
        return leaves[0]
    groups = defaultdict(list); containers = set()
    for chain, encoded in changes:
        step = chain[0]; containers.add(step['container'])
        groups[step['index']].append((chain[1:], encoded))
    if containers == {'GPDA'}:
        archive = Archive(data); replaced = {}
        for index, children in groups.items():
            if archive.entries[index].kind not in (0, 1): raise ImageError('Unsupported texture GPDA kind')
            child, compressed = unpack_member(archive, index)
            result = patch_tree(child, children, cancelled)
            if result != child: replaced[index] = gzip.compress(result, compresslevel=9, mtime=0) if compressed else result
        return repack(archive, replaced)
    if containers == {'FONT'}:
        # Original GXT sizes remain fixed: retain FONT table offsets/gaps and all
        # generated atlases, glyph metrics and charset bytes exactly as supplied.
        sections = font_sections(data); out = bytearray(data)
        for index, children in groups.items():
            if index >= len(sections) - 2: raise ImageError('Texture path points outside FONT atlases')
            at, size = sections[index]; result = patch_tree(data[at:at + size], children, cancelled)
            if len(result) != size: raise ImageError('FONT atlas extent changed unexpectedly')
            out[at:at + size] = result
        return bytes(out)
    raise ImageError('Unsupported or conflicting texture container path')


def changed_paths(changes):
    """Seek rows exist only in stored archives, but decoded deeper paths are safe
    to include: the relocator follows real seek nodes and never invents offsets.
    """
    result = {()}
    for chain, _ in changes:
        path = ()
        for step in chain:
            path += (step['index'],); result.add(path)
    return result
