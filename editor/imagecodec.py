"""Read-only Vita GXT pixels. No game renderer or native build dependency."""
from dataclasses import asdict, dataclass
import struct


class ImageError(ValueError):
    pass


class ImageCancelled(ImageError):
    pass


def checkpoint(cancelled=None):
    if cancelled and cancelled():
        raise ImageCancelled('Image operation cancelled; original data unchanged.')


@dataclass(frozen=True)
class TextureInfo:
    width: int
    height: int
    format: str
    order: str
    pixel_offset: int
    pixel_size: int
    stride: int
    palette_offset: int = 0
    opaque: bool = False

    def to_dict(self):
        return asdict(self)


def inspect_gxt(data):
    """Validate the layouts actually consumed by Saekano, including storage padding."""
    if len(data) < 64 or bytes(data[:4]) != b'GXT\0':
        raise ImageError('Truncated or invalid GXT header')
    w = lambda at: struct.unpack_from('<I', data, at)[0]
    if w(4) != 0x10000003 or w(8) != 1:
        raise ImageError('Unsupported GXT version or texture count (expected one texture)')
    begin, size, p4, p8 = w(12), w(16), w(20), w(24)
    at, pixel_size, palette, flags, order, fmt = (w(i) for i in (32, 36, 40, 44, 48, 52))
    width, height, mipmaps = struct.unpack_from('<HHI', data, 56)
    if not width or not height or width * height > 64 * 1024 * 1024:
        raise ImageError('Invalid dimensions or image exceeds 64 megapixel decode budget')
    if begin < 64 or begin + size > len(data) or at != begin or at + pixel_size > begin + size:
        raise ImageError('GXT pixels outside declared data extent')
    if order not in (0, 0x60000000) or mipmaps != 1:
        raise ImageError(f'Unsupported GXT order 0x{order:08x} or mipmap count {mipmaps}')
    swizzled = order == 0
    if swizzled and (width & (width - 1) or height & (height - 1)):
        raise ImageError('Swizzled GXT dimensions must be powers of two')
    if fmt in (0x95001000, 0x95005000):
        if p4 != 0 or p8 != 1 or palette != 0:
            raise ImageError('Unsupported GXT palette configuration')
        bpp, name, palette_at = 1, 'P8 ARGB' if fmt == 0x95001000 else 'P8 opaque RGB', begin + size - 1024
        if palette_at not in (at + pixel_size, (at + pixel_size + 63) & ~63):
            raise ImageError('Invalid GXT palette extent')
    elif fmt == 0x0c001000:
        if p4 or p8:
            raise ImageError('Unexpected palettes in RGBA GXT')
        bpp, name, palette_at = 4, 'RGBA (stored BGRA)', 0
    else:
        raise ImageError(f'Unsupported GXT pixel format 0x{fmt:08x}')
    stride = width if swizzled or pixel_size == width * height * bpp else (width + 7) & ~7
    if stride * height * bpp != pixel_size:
        raise ImageError('GXT pixel extent does not match dimensions/row stride')
    return TextureInfo(width, height, name, 'swizzled' if swizzled else 'linear',
                       at, pixel_size, stride, palette_at, fmt == 0x95005000)


def compact(value):
    value &= 0x55555555
    value = (value ^ (value >> 1)) & 0x33333333
    value = (value ^ (value >> 2)) & 0x0f0f0f0f
    value = (value ^ (value >> 4)) & 0x00ff00ff
    return (value ^ (value >> 8)) & 65535


def linear_pixels(data, info, cancelled=None):
    bpp = 1 if info.palette_offset else 4
    source = memoryview(data)[info.pixel_offset:info.pixel_offset + info.pixel_size]
    if info.order == 'linear':
        return bytes(source)
    width, height = info.width, info.height
    minimum = min(width, height)
    k, mask = minimum.bit_length() - 1, minimum - 1
    out = bytearray(width * height * bpp)
    # Rectangular Morton layout, rather than a square-only interleave.
    for i in range(width * height):
        if i % 16384 == 0:
            checkpoint(cancelled)
        even, odd = compact(i), compact(i >> 1)
        block = i >> (2 * k) << (2 * k)
        if height < width:
            j = block | ((odd & mask) << k) | (even & mask)
            x, y = divmod(j, height)
        else:
            j = block | ((even & mask) << k) | (odd & mask)
            y, x = divmod(j, width)
        dest = (y * width + x) * bpp
        if bpp == 1:
            out[dest] = source[i]
        else:
            out[dest:dest + 4] = source[i * 4:i * 4 + 4]
    return bytes(out)


def decode_gxt(data, cancelled=None):
    """Return an owning RGBA QImage; safe in a worker without GUI/font access."""
    from PySide6.QtGui import QImage, qRgba
    checkpoint(cancelled)
    info = inspect_gxt(data)
    pixels = linear_pixels(data, info, cancelled)
    if info.palette_offset:
        image = QImage(pixels, info.width, info.height, info.stride, QImage.Format_Indexed8)
        colors = []
        for i in range(256):
            b, g, r, a = data[info.palette_offset + i * 4:info.palette_offset + i * 4 + 4]
            colors.append(qRgba(r, g, b, 255 if info.opaque else a))
        image.setColorTable(colors)
    else:
        # GXT ARGB words are little-endian BGRA bytes, Qt ARGB32 has the same layout.
        image = QImage(pixels, info.width, info.height, info.stride * 4, QImage.Format_ARGB32)
    result = image.convertToFormat(QImage.Format_RGBA8888)
    if result.isNull():
        raise ImageError('Qt could not allocate decoded texture')
    checkpoint(cancelled)
    return result
