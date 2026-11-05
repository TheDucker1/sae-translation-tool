"""Script codec for edited preview and separate game exports. Originals stay read-only.

Only seven text payloads are authored. Other payloads stay byte-identical except
known command-index operands. Metadata/post words follow command identity.
"""
import struct
from dataclasses import dataclass
from .engine import TEXT_OPS


class CodecError(ValueError):pass


class Reader:
    def __init__(self,data):self.data=data;self.pos=0
    def take(self,n):
        if n<0 or self.pos+n>len(self.data):raise CodecError('Truncated script data')
        out=self.data[self.pos:self.pos+n];self.pos+=n;return out
    def word(self,fmt='I'):return struct.unpack('<'+fmt,self.take(struct.calcsize(fmt)))[0]
    def string(self):return self.take(self.word()*2).decode('utf-16-le',errors='strict')
    def count(self):
        n=self.word()
        if n>len(self.data)-self.pos:raise CodecError('Count exceeds remaining data')
        return n


def number(value,fmt='i'):
    if not isinstance(value,int) or isinstance(value,bool):raise CodecError('Integer operand required')
    try:return struct.pack('<'+fmt,value)
    except struct.error as e:raise CodecError(str(e)) from e


def string(value):
    if not isinstance(value,str):raise CodecError('Text operand must be a string')
    try:raw=value.encode('utf-16-le',errors='strict')
    except UnicodeError as e:raise CodecError('Unpaired Unicode surrogate') from e
    if len(raw)>8*1024*1024:raise CodecError('Text exceeds editor payload budget')
    return number(len(raw)//2,'I')+raw


def reference_paths(op,args):
    if op==1:return [(k,) for k in ('start','alternate','resume')]
    if op==0x2be:return [('target',)]
    if op in {0x65,0x3f2}:return [('choices',i,'target') for i in range(len(args['choices']))]
    if op==0x3f6:return [('parents',i,'children',j,'target') for i,p in enumerate(args['parents']) for j in range(len(p['children']))]
    if op==0x3f8:return [('outcomes',i,'target') for i in range(len(args['outcomes']))]
    if op==0x3fa:return [(k,) for k in ('win','lose','draw')]
    return []


def at(value,path):
    for key in path:value=value[key]
    return value


def put(value,path,new):
    for key in path[:-1]:value=value[key]
    value[path[-1]]=new


def reference_sites(op,payload):
    """Payload byte positions, not guessed occurrences of equal integers."""
    r=Reader(payload);sites=[]
    def target(path):sites.append((path,r.pos));r.word('i')
    if op==1:
        r.string()
        for key in ('start','alternate','resume'):target((key,))
    elif op==0x2be:target(('target',))
    elif op in {0x65,0x3f2}:
        if op==0x3f2:r.word()
        for i in range(r.count()):
            target(('choices',i,'target'))
            if op==0x3f2:r.word('h')
            r.string()
            for _ in range(r.count()):r.string()
    elif op==0x3f6:
        for i in range(r.count()):
            r.string();r.string()
            for j in range(r.count()):target(('parents',i,'children',j,'target'));r.string()
    elif op==0x3f8:
        r.word('i')
        for i in range(2):target(('outcomes',i,'target'));r.string();r.word('i')
    elif op==0x3fa:
        for key in ('win','lose','draw'):target((key,))
    return sites


def text_end(op,payload):
    r=Reader(payload)
    if op==0x64:
        r.take(16);r.string();r.take(8)
    elif op in {0x65,0x3f2,0x3f6,0x3f8}:
        if op==0x3f8:
            r.take(4)
            for _ in range(2):r.take(4);r.string();r.take(4)
        elif op==0x3f6:
            for _ in range(r.count()):
                r.string();r.string()
                for _ in range(r.count()):r.take(4);r.string()
        else:
            if op==0x3f2:r.take(4)
            for _ in range(r.count()):
                r.take(4)
                if op==0x3f2:r.take(2)
                r.string()
                for _ in range(r.count()):r.string()
    elif op in {0x3ec,0x3f9}:
        if op==0x3ec:r.take(4)
        r.string();r.string()
    else:raise CodecError('Not a text opcode')
    return r.pos


def encode_text(op,a):
    n=number;s=string
    if op==0x64:return b''.join([n(a['route'],'I'),n(a['selector'],'I'),n(a['voice']),n(a['speaker']),s(a['text']),n(a['completion'],'I'),n(a['lane'],'I')])
    if op in {0x65,0x3f2}:
        out=n(a['duration'],'I') if op==0x3f2 else b'';out+=n(len(a['choices']),'I')
        for c in a['choices']:
            out+=n(c['target'])+(n(c['preview'],'h') if op==0x3f2 else b'')+s(c['label'])+n(len(c['extras']),'I')
            out+=b''.join(s(x) for x in c['extras'])
        return out
    if op==0x3f6:
        out=n(len(a['parents']),'I')
        for p in a['parents']:
            out+=s(p['label'])+s(p['condition'])+n(len(p['children']),'I')
            for c in p['children']:out+=n(c['target'])+s(c['label'])
        return out
    if op==0x3f8:
        if len(a['outcomes'])!=2:raise CodecError('Approach result requires exactly two outcomes')
        return n(a['required_gauge'])+b''.join(n(c['target'])+s(c['text'])+n(c['voice']) for c in a['outcomes'])
    if op in {0x3ec,0x3f9}:
        if len(a['texts'])!=2:raise CodecError('This opcode requires exactly two strings')
        return (n(a['chapter']) if op==0x3ec else b'')+b''.join(s(t) for t in a['texts'])
    raise CodecError('Only text opcodes can be authored')


@dataclass
class RawRecord:
    opcode:int
    payload:bytes
    post:int
    offset:int


def parse(blob):
    r=Reader(blob);count=r.word();first=r.word()
    if first<8 or first>len(blob) or count>(len(blob)-first)//10:raise CodecError('Invalid script header/count')
    header=r.take(first-8);records=[]
    for _ in range(count):
        offset=r.pos;size=r.word();op=r.word('H')
        if size<6:raise CodecError('Record smaller than header')
        records.append(RawRecord(op,r.take(size-6),0,offset))
    for record in records:record.post=r.word()
    return header,records,blob[r.pos:]


def assemble(header,records,tail):
    return number(len(records),'I')+number(8+len(header),'I')+header+b''.join(number(6+len(r.payload),'I')+number(r.opcode,'H')+r.payload for r in records)+b''.join(number(r.post,'I') for r in records)+tail
