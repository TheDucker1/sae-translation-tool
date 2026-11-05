"""Read-only GPDA/gzip access. No engine library or extracted-data cache."""
import zlib
from dataclasses import dataclass
from .scriptcodec import Reader, CodecError, parse


@dataclass(frozen=True)
class Entry:
    offset: int
    size: int
    kind: int
    name: str


class Archive:
    def __init__(self, data):
        self.data = memoryview(data)
        r = Reader(self.data)
        if bytes(r.take(4)) != b'GPDA': raise CodecError('Invalid GPDA signature')
        end, _, count = (r.word() for _ in range(3))
        if not 16 <= end <= len(data) or count > (end - 16) // 16:
            raise CodecError('Invalid GPDA extent/table')
        self.entries = []
        table_end, previous = 16 + count * 16, None
        for _ in range(count):
            offset, kind, size, name_at = (r.word() for _ in range(4))
            if offset < table_end or offset + size > end:
                raise CodecError('GPDA payload outside container')
            if previous and previous.offset + previous.size > offset:
                raise CodecError('Unordered/overlapping GPDA entries')
            name = ''
            if name_at:
                n = Reader(self.data[:end]); n.take(name_at)
                name = bytes(n.take(n.word())).decode('cp932').rstrip('\0')
            previous = Entry(offset, size, kind, name)
            self.entries.append(previous)

    def read(self, index, gzip=False):
        entry = self.entries[index]
        data = bytes(self.data[entry.offset:entry.offset + entry.size])
        if entry.kind == 0 and not gzip: return data
        if entry.kind not in {0,1}: raise CodecError(f'Unsupported GPDA entry type {entry.kind}')
        decoder = zlib.decompressobj(31)
        output = decoder.decompress(data, 64 * 1024 * 1024 + 1)
        if len(output) > 64 * 1024 * 1024 or not decoder.eof or decoder.unused_data:
            raise CodecError('Invalid, trailing or oversized gzip resource')
        return output


def describe(data):
    from .decode import decode
    _, records, _ = parse(data)
    commands = []
    for i, record in enumerate(records):
        try: args = decode(record.opcode, record.payload)
        except (ValueError, IndexError) as error: args = {'decode_error': str(error)}
        commands.append(dict(index=i, opcode=record.opcode, args=args,
                             offset=record.offset, size=6 + len(record.payload),
                             raw=record.payload.hex(), post_word=record.post))
    return dict(data_hex=data.hex(), commands=commands)
