"""GPDA writing with retained counted names, entry kinds and physical payloads."""
from dataclasses import dataclass
import struct
import zlib
from .archive import Archive
from .scriptcodec import CodecError

SECTOR=2048
REVERSE=bytes(int(f'{i:08b}'[::-1],2) for i in range(256))


def content_crc(data):
    """Native MSB CRC32, initialFFFFFFFF, no final xor (not name hashing)."""
    reflected=zlib.crc32(bytes(data).translate(REVERSE))^0xffffffff
    return int.from_bytes(reflected.to_bytes(4,'little').translate(REVERSE),'big')


def payload(archive,index,physical=False):
    entry=archive.entries[index]
    end=(archive.entries[index+1].offset if index+1<len(archive.entries) else struct.unpack_from('<I',archive.data,4)[0]) if physical else entry.offset+entry.size
    return archive.data[entry.offset:end]


def name_bytes(archive,index):
    at=struct.unpack_from('<I',archive.data,28+index*16)[0]
    if not at:return None
    size=struct.unpack_from('<I',archive.data,at)[0]
    return bytes(archive.data[at+4:at+4+size])


@dataclass(frozen=True)
class Member:
    name:bytes|None
    kind:int
    data:bytes
    physical:bytes|None=None


def member(archive,index):
    e=archive.entries[index]
    return Member(name_bytes(archive,index),e.kind,bytes(payload(archive,index)),bytes(payload(archive,index,True)))


def align(buffer):buffer.extend(b'\0'*(-len(buffer)%SECTOR))


def pack_members(members,reserved=0):
    """Build an archive when member ordering/count changes (voice companions)."""
    members=list(members);out=bytearray(16+16*len(members));names=[]
    for m in members:
        names.append(len(out) if m.name is not None else 0)
        if m.name is not None:out.extend(struct.pack('<I',len(m.name))+m.name)
    align(out)
    for i,m in enumerate(members):
        at=len(out);body=m.physical if m.physical is not None else m.data
        if not body.startswith(m.data):raise CodecError('Physical GPDA payload disagrees with logical bytes')
        out.extend(body);align(out)
        struct.pack_into('<IIII',out,16+16*i,at,m.kind,len(m.data),names[i])
    struct.pack_into('<4sIII',out,0,b'GPDA',len(out),reserved,len(members))
    return bytes(out)


def repack(archive,replacements):
    """Retain the original table/name prefix and untouched physical spans."""
    if any(not isinstance(i,int) or not 0<=i<len(archive.entries) for i in replacements):raise CodecError('Replacement outside GPDA')
    changes={i:bytes(data) for i,data in replacements.items() if bytes(data)!=payload(archive,i)}
    if not changes:return bytes(archive.data)
    first=archive.entries[0].offset;end=struct.unpack_from('<I',archive.data,4)[0]
    for i in range(len(archive.entries)):
        at=struct.unpack_from('<I',archive.data,28+16*i)[0]
        if at and (at+4>first or at+4+struct.unpack_from('<I',archive.data,at)[0]>first):
            raise CodecError('GPDA names outside retained prefix; unsafe relocation')
    out=bytearray(archive.data[:first])
    for i,e in enumerate(archive.entries):
        at=len(out)
        if i in changes:out.extend(changes[i]);align(out)
        else:out.extend(payload(archive,i,True))
        struct.pack_into('<I',out,16+16*i,at)
        if i in changes:struct.pack_into('<I',out,24+16*i,len(changes[i]))
    struct.pack_into('<I',out,4,len(out));out.extend(archive.data[end:])
    Archive(out)  # Bounds/order/name sanity before any export can publish it.
    return bytes(out)
