"""Lossless replacements in an original single-texture GXT storage layout."""
from .imagecodec import ImageError, checkpoint, compact, inspect_gxt, decode_gxt


def constraints(asset):
    return dict(encoding_supported=asset.kind == 'GXT' and asset.status == 'Ready',
        dimensions=[asset.width, asset.height], resize=False,
        format=asset.format, order=asset.order, preserve_original_format=True,
        maximum_colors=256 if asset.format.startswith('P8') else None,
        transparency='opaque only' if asset.format == 'P8 opaque RGB' else '8-bit alpha',
        quantization=False,
        note='Keep atlas crops, glyph records and scene geometry unchanged. Export preflight checks actual pixels and container support.')


def stored_positions(info, cancelled=None):
    """Stored Morton index -> linear pixel index, including rectangular blocks."""
    w, h = info.width, info.height
    minimum = min(w, h); k = minimum.bit_length() - 1; mask = minimum - 1
    for i in range(w * h):
        if i % 16384 == 0: checkpoint(cancelled)
        even, odd = compact(i), compact(i >> 1)
        block = i >> (2 * k) << (2 * k)
        if h < w:
            j = block | ((odd & mask) << k) | (even & mask)
            x, y = divmod(j, h)
        else:
            j = block | ((even & mask) << k) | (odd & mask)
            y, x = divmod(j, w)
        yield y * w + x


def encode_gxt(original, image, cancelled=None):
    """Preserve header/extents/format/stride/order/padding; never quantize pixels."""
    from PySide6.QtGui import QImage
    checkpoint(cancelled); info = inspect_gxt(original)
    if (image.width(), image.height()) != (info.width, info.height):
        raise ImageError(f'GXT requires original dimensions {info.width}×{info.height}')
    image = image.convertToFormat(QImage.Format_RGBA8888)
    rgba = bytes(image.constBits())
    old_image = decode_gxt(original, cancelled)
    if rgba == bytes(old_image.constBits()): return bytes(original)
    out = bytearray(original); count = info.width * info.height
    if info.palette_offset:
        colors = {}; linear = bytearray(count)
        for i in range(count):
            if i % 16384 == 0: checkpoint(cancelled)
            color = rgba[i * 4:i * 4 + 4]
            if info.opaque and color[3] != 255:
                raise ImageError('Original P8 opaque RGB cannot store transparency; make every pixel opaque')
            if color not in colors:
                if len(colors) == 256:
                    raise ImageError('Original P8 GXT permits at most256 distinct RGBA colors (including transparent pixels); replacement exceeds256. Reduce its palette explicitly; export never quantizes.')
                colors[color] = None
        # Reuse original color slots where possible; allocate remaining slots in
        # first-pixel order. Identical decoded imports leave the entire GXT intact.
        old = {}
        for i in range(256):
            b, g, r, a = original[info.palette_offset + i * 4:info.palette_offset + i * 4 + 4]
            old.setdefault(bytes((r, g, b, 255 if info.opaque else a)), i)
        used = set()
        for color in colors:
            if color in old: colors[color] = old[color]; used.add(old[color])
        free = iter(i for i in range(256) if i not in used)
        for color, slot in colors.items():
            if slot is None: slot = next(free); colors[color] = slot
            r, g, b, a = color; at = info.palette_offset + slot * 4
            out[at:at + 4] = bytes((b, g, r, a))
        for i in range(count):
            if i % 16384 == 0: checkpoint(cancelled)
            linear[i] = colors[rgba[i * 4:i * 4 + 4]]
        bpp = 1
    else:
        linear = bytearray(len(rgba)); linear[0::4] = rgba[2::4]
        linear[1::4] = rgba[1::4]; linear[2::4] = rgba[0::4]; linear[3::4] = rgba[3::4]
        bpp = 4
    if info.order == 'swizzled':
        for stored, position in enumerate(stored_positions(info, cancelled)):
            at = info.pixel_offset + stored * bpp; src = position * bpp
            out[at:at + bpp] = linear[src:src + bpp]
    else:
        row_bytes = info.width * bpp
        for y in range(info.height):
            checkpoint(cancelled); at = info.pixel_offset + y * info.stride * bpp
            out[at:at + row_bytes] = linear[y * row_bytes:(y + 1) * row_bytes]
    result = bytes(out)
    # Validate through the independent reader before any archive can be written.
    decoded = decode_gxt(result, cancelled)
    if bytes(decoded.constBits()) != rgba: raise ImageError('GXT roundtrip changed replacement pixels')
    return result
