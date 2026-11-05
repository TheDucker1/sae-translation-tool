"""Typed Saekano command decoding, ported from the accepted loader semantics.

Only consumed fields are decoded; record padding stays in raw payloads.
Unknown registrations remain opaque and cannot silently execute.
"""
import math
from .scriptcodec import Reader, CodecError


WORDS = {
    0: 'bank index operation operand_kind operand',
    0x2be: 'target', 0x2bf: 'script', 0x2c0: 'duration honor_skip',
    0xc8: 'duration', 0xc9: 'duration', 0x3fd: 'duration', 0x400: 'duration',
    0x12c: 'duration channel', 0x12d: 'duration channel', 0x12e: 'speaker window_type',
    0x1f4: 'route character opacity_from opacity_to duration background lane',
    0x1f5: 'route character x y lane',
    0x1f6: 'route character x y duration background lane',
    0x1f7: 'route character x y duration background lane',
    0x1f8: 'route character scale duration background lane',
    0x1f9: 'route character source value duration lane',
    0x1fa: 'route character source value duration lane',
    0x202: 'character',
    0x3ea: 'enabled month day', 0x3ed: 'id', 0x3ee: 'id',
    0x3ef: 'history side0_group side0_entry side1_group side1_entry gauge',
    0x3fa: 'win lose draw', 0x3f4: 'character delta', 0x3f5: 'delta',
    0x259: 'fade', 0x25b: 'channel fade',
    0x25a: 'route track channel volume remember lane',
    0xca: 'slot color from to duration bucket', 0xce: 'category source id_or_index',
    0x1c4: 'group duration', 0x3f7: 'mission', 0x640: 'trophy',
}


def decode(op, payload):
    r, a = Reader(payload), {}
    def words(names, fmt='i'):
        for name in names.split(): a[name] = r.word(fmt)
    if op in WORDS: words(WORDS[op])
    elif op in {0x66, 0x3fc, 0x2bd}: pass
    elif op == 1:
        a['condition'] = r.string(); words('start alternate resume')
    elif op == 0x64:
        words('route selector', 'I'); words('voice speaker'); a['text'] = r.string()
        words('completion lane', 'I')
        if a['lane'] >= 5: raise CodecError('Message lane exceeds engine lane count')
    elif op in {0x65, 0x3f2}:
        a['duration'] = r.word() if op == 0x3f2 else 0
        a['choices'] = []
        for _ in range(r.count()):
            target = r.word('i'); preview = r.word('h') if op == 0x3f2 else -1
            label = r.string(); extras = [r.string() for _ in range(r.count())]
            a['choices'].append(dict(target=target, preview=preview, label=label, extras=extras))
    elif op == 0x3f6:
        a['parents'] = []
        for _ in range(r.count()):
            label, condition = r.string(), r.string()
            children = [dict(target=r.word('i'), label=r.string()) for _ in range(r.count())]
            a['parents'].append(dict(label=label, condition=condition, children=children))
    elif op == 0x3f8:
        a['required_gauge'] = r.word('i')
        a['outcomes'] = [dict(target=r.word('i'), text=r.string(), voice=r.word('i')) for _ in range(2)]
    elif op in {0x3ec, 0x3f9}:
        if op == 0x3ec: a['chapter'] = r.word('i')
        a['texts'] = [r.string(), r.string()]
    elif op == 0x258: a['track'] = r.string(); words('volume')
    elif op == 0x2c2: a['movie'] = r.string(); a['allow_skip'] = bool(r.word())
    elif op == 0x1fb: words('character priority', 'H')
    elif op == 0x201: words('red green blue duration background', 'H')
    elif op == 0x204:
        words('mode character face'); a['unused'] = [r.word(),r.word()]
    elif op == 0xcb:
        words('route category', 'I'); a['texture'] = r.string(); words('slot', 'I')
        a['geometry'] = [r.word('i') for _ in range(6)] if a['category'] == 2 else [0] * 6
        words('bucket from to duration scale owner lane')
    elif op == 0x190:
        words('selector', 'I'); x, dx, y, dy = (r.word('i') for _ in range(4))
        a.update(amplitude=[x,y], leg_duration=[dx & 0xffffffff,dy & 0xffffffff])
        words('hold attack decay', 'I')
    elif op == 0x191:
        words('direction parameter duration rule background_kind')
        if a['background_kind'] != 1: words('color_or_image')
    elif op == 0x1c3:
        words('route target group effect')
        a['character'] = r.word('i') if a['target'] == 1 else -1
        words('x y persistent scale color lane')
    elif op == 0x2c6:
        a['enabled'] = bool(r.word()); a['ids'] = [r.word('h') for _ in range(5)]
    elif op == 0x438:
        a = dict(selector=r.word(), target=0, value=0, vector=[0.,0.], transition=0, color=[0,0,0,0])
        selector = a['selector']
        if selector in {2,3,4,6,12,13,15,16,17,19,20,21,22,23,24,25}: a['target'] = r.word('i')
        if selector in {2,4,6,16,17,20,23,24,25}: a['value'] = r.word('i')
        elif selector == 3: a['value'] = int(bool(r.word()))
        elif selector in {12,13}:
            a['vector'] = [r.word('f'), r.word('f')]; a['transition'] = r.word('i')
        elif selector == 21: a['color'] = list(reversed([r.word() & 255 for _ in range(4)]))
        elif selector == 22: a['vector'][0] = r.word('f')
        if not all(math.isfinite(v) for v in a['vector']): raise CodecError('Non-finite model parameter')
    else: a['payload_hex'] = payload.hex()
    return a
