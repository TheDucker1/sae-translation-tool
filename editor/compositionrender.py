"""Qt raster consumer for shared UI draw lists; no native engine dependency."""
from collections import OrderedDict
from dataclasses import replace
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from .imagecodec import ImageError, checkpoint
from .composition import Composition, walk_layers


class AssetResolver:
    """Layouts retain asset identities. Future replacement providers use this seam."""
    def __init__(self, catalog):
        self.catalog = catalog

    def image(self, identity, cancelled=None):
        return self.catalog.decode(identity, cancelled)


class TextureLoader:
    """Worker-owned decoded cache, bounded across previews as well as per batch."""
    def __init__(self, resolver):
        self.resolver = resolver; self.cache = OrderedDict(); self.bytes = 0

    def load(self, composition, progress=None, cancelled=None):
        textures, errors, total = {}, [], 0
        self.resolver.catalog.verify()
        for identity in dict.fromkeys(layer.asset for layer in walk_layers(composition.layers)
                                      if layer.asset and not layer.asset.startswith('@target:') and (layer.rgba[3] or layer.blend == 'multiply')):
            checkpoint(cancelled)
            if progress: progress('Loading composition texture ' + identity)
            try:
                if identity in self.cache:
                    image = self.cache[identity]; self.cache.move_to_end(identity)
                else:
                    image = self.resolver.image(identity, cancelled)
                    size = image.sizeInBytes()
                    while self.cache and self.bytes + size > 64 * 1024 * 1024:
                        _, old = self.cache.popitem(last=False); self.bytes -= old.sizeInBytes()
                    if size <= 64 * 1024 * 1024:
                        self.cache[identity] = image; self.bytes += size
                total += image.sizeInBytes()
                if total > 128 * 1024 * 1024:
                    raise ImageError('Composition textures exceed 128 MiB batch budget')
                textures[identity] = image
            except (ValueError, KeyError, OSError) as error:
                checkpoint(cancelled)
                errors.append(f'{identity}: {error}')
        self.resolver.catalog.verify(); checkpoint(cancelled)
        return textures, errors


def tint_image(image, rgb):
    if list(rgb) == [255, 255, 255]: return image
    pixels = image.convertToFormat(QImage.Format_RGBA8888)
    raw = bytearray(pixels.constBits())
    for channel, level in enumerate(rgb):
        table = bytes(i * level // 255 for i in range(256))
        raw[channel::4] = raw[channel::4].translate(table)
    return QImage(bytes(raw), pixels.width(), pixels.height(), pixels.width() * 4, QImage.Format_RGBA8888).copy()


def clamped_crop(image, x, y, width, height):
    """Match the source renderer's LinearClamp addressing, including atlas overscan."""
    if x >= 0 and y >= 0 and x + width <= image.width() and y + height <= image.height():
        return image.copy(x, y, width, height)
    def segments(start, length, extent):
        cuts = sorted({0, length, min(length, max(0, -start)), min(length, max(0, extent - start))})
        result = []
        for a, b in zip(cuts, cuts[1:]):
            at = max(0, min(extent - 1, start + a))
            size = 1 if start + a < 0 or start + a >= extent else b - a
            result.append((a, b - a, at, size))
        return result
    result = QImage(width, height, QImage.Format_RGBA8888); result.fill(0)
    p = QPainter(result); p.setCompositionMode(QPainter.CompositionMode_Source)
    for dx, dw, sx, sw in segments(x, width, image.width()):
        for dy, dh, sy, sh in segments(y, height, image.height()):
            p.drawImage(QRectF(dx, dy, dw, dh), image, QRectF(sx, sy, sw, sh))
    p.end()
    return result


class FontConsumer:
    def __init__(self, font):
        self.font = font; self.cache = OrderedDict()

    def glyph(self, code, rgb):
        key = (code, tuple(rgb))
        if key in self.cache:
            self.cache.move_to_end(key); return self.cache[key]
        data = self.font.glyph(code)
        if data.get('missing'): return None
        image = QImage(bytes.fromhex(data['rgba']), data['width'], data['height'],
                       data['width'] * 4, QImage.Format_RGBA8888).copy()
        if data['bitmap']:
            image = tint_image(image, rgb)
        else:
            p = QPainter(image); p.setCompositionMode(QPainter.CompositionMode_SourceIn)
            p.fillRect(image.rect(), QColor(*rgb)); p.end()
        while len(self.cache) >= 512: self.cache.popitem(last=False)
        self.cache[key] = image
        return image


def render_composition(composition, textures, font_consumer=None, *, _targets=None, _depth=0):
    """Normal UI source-over quads, crop/flip, RGB multiply, opacity and pivot rotation."""
    if _depth > 4: raise ImageError('Composition target nesting exceeds budget')
    targets = {} if _targets is None else _targets
    frame = QImage(960, 544, QImage.Format_RGBA8888); frame.fill(QColor(*composition.clear))
    p = QPainter(frame); p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    issues = []
    try:
        for layer in composition.layers:
            if layer.kind == 'target':
                if not layer.target or len(targets) >= 8: raise ImageError('Invalid/excessive composition targets')
                child = Composition(layer.name, layers=layer.children, clear=tuple(layer.rgba))
                target, child_issues = render_composition(child, textures, font_consumer, _targets=targets, _depth=_depth + 1)
                targets['@target:' + layer.target] = target; issues.extend(child_issues); continue
            if not layer.rgba[3] and layer.blend != 'multiply': continue
            if layer.blend == 'multiply':
                if layer.kind not in ('sprite', 'solid'): raise ImageError('Multiply requires a quad primitive')
                source, child_issues = render_composition(Composition('Multiply source', layers=[replace(layer, blend='normal')], clear=(0, 0, 0, 0)),
                                                         textures, font_consumer, _targets=targets, _depth=_depth + 1)
                issues.extend(child_issues)
                # Native blend3 is dstRGBA * srcRGBA, including alpha. Qt's
                # source-over Multiply mode has a different alpha equation.
                coverage = QImage(960, 544, QImage.Format_RGBA8888); coverage.fill(0)
                cp = QPainter(coverage)
                if layer.clip: cp.setClipRect(QRectF(*layer.clip))
                if layer.rotation:
                    degrees, x, y = layer.rotation; cp.translate(x, y); cp.rotate(degrees); cp.translate(-x, -y)
                cp.fillRect(QRectF(*layer.destination), QColor('white')); cp.end()
                p.end(); dst, src, mask = bytearray(frame.constBits()), bytes(source.constBits()), bytes(coverage.constBits())
                for at in range(0, len(dst), 4):
                    if mask[at + 3]:
                        for channel in range(4): dst[at + channel] = dst[at + channel] * src[at + channel] // 255
                frame = QImage(bytes(dst), 960, 544, 960 * 4, QImage.Format_RGBA8888).copy()
                p = QPainter(frame); p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                continue
            if layer.blend != 'normal': raise ImageError('Unsupported composition blend: ' + layer.blend)
            p.save()
            try:
                if layer.clip: p.setClipRect(QRectF(*layer.clip))
                p.setOpacity(layer.rgba[3] / 255)
                if layer.rotation:
                    degrees, x, y = layer.rotation
                    p.translate(x, y); p.rotate(degrees); p.translate(-x, -y)
                if layer.kind == 'text':
                    if font_consumer is None:
                        issues.append('Original font is unavailable; text layers were not drawn.'); continue
                    for glyph in layer.glyphs:
                        image = font_consumer.glyph(glyph['code'], layer.rgba[:3])
                        if image is None:
                            issues.append(f"Missing font glyph U+{glyph['code']:04X}"); continue
                        p.drawImage(QRectF(*glyph['rect']), image)
                elif layer.kind == 'solid':
                    p.fillRect(QRectF(*layer.destination), QColor(*layer.rgba[:3]))
                elif layer.kind == 'sprite':
                    image = targets.get(layer.asset) if layer.asset.startswith('@target:') else textures.get(layer.asset)
                    if image is None:
                        issues.append(f'{layer.name}: texture unavailable ({layer.asset})'); continue
                    sx, sy, sw, sh = layer.source
                    if not sw or not sh or not layer.destination[2] or not layer.destination[3]: continue
                    if abs(sw) * abs(sh) > 64 * 1024 * 1024:
                        issues.append(f'{layer.name}: crop exceeds decode budget'); continue
                    piece = clamped_crop(image, sx + min(sw, 0), sy + min(sh, 0), abs(sw), abs(sh))
                    if sw < 0 or sh < 0:
                        axes = Qt.Orientation(0)
                        if sw < 0: axes |= Qt.Horizontal
                        if sh < 0: axes |= Qt.Vertical
                        piece = piece.flipped(axes)
                    piece = tint_image(piece, layer.rgba[:3])
                    p.drawImage(QRectF(*layer.destination), piece)
                else:
                    issues.append(f'{layer.name}: unsupported primitive {layer.kind}')
            finally:
                p.restore()
    finally:
        if p.isActive(): p.end()
    return frame, list(dict.fromkeys(issues))
