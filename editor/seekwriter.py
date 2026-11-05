"""Relocate the native absolute seek tree while preserving row formatting."""
from dataclasses import dataclass,field
import re
from .archive import Archive
from .packing import content_crc,payload
from .scriptcodec import CodecError


@dataclass
class Node:
    line:bytes
    spans:list
    tokens:list
    children:list=field(default_factory=list)
    opaque:list=field(default_factory=list)

    def updated(self,offset,size,crc):
        line=self.line
        for index,value in reversed(list(zip((1,2,3),(offset,size,crc)))):
            a,b=self.spans[index]
            if value<0 or value>0xffffffff:raise CodecError('Seek metadata exceeds unsigned32')
            if int(self.tokens[index])!=value:line=line[:a]+str(value).encode('ascii')+line[b:]
        return line


def parse(data):
    if len(data)>32*1024*1024:raise CodecError('Seekmap exceeds budget')
    lines=data.splitlines(keepends=True);position=0;nodes=0
    def read(depth=0):
        nonlocal position,nodes
        if depth>128 or nodes>=1000000 or position>=len(lines):raise CodecError('Invalid seek tree depth/count')
        line=lines[position];position+=1;nodes+=1
        if not line.endswith(b'\r\n') or b'\0' in line:raise CodecError('Seekmap requires CRLF rows without NUL')
        matches=list(re.finditer(rb'[^ \t\v\f]+',line[:-2]));tokens=[m[0] for m in matches]
        if not 4<=len(tokens)<=6:raise CodecError('Invalid seek row field count')
        if any(not re.fullmatch(rb'[0-9]+',v) or int(v)>0xffffffff for v in tokens[1:]):raise CodecError('Invalid seek numeric field')
        n=Node(line,[m.span() for m in matches],tokens);flags=int(tokens[4]) if len(tokens)>4 else 0;count=int(tokens[5]) if len(tokens)>5 else 0
        if count>len(lines)-position:raise CodecError('Seek children exceed remaining rows')
        if flags&2:n.opaque=lines[position:position+count];position+=count
        else:n.children=[read(depth+1) for _ in range(count)]
        return n
    root=read()
    if position!=len(lines):raise CodecError('Unexpected trailing seek rows')
    return root


def relocate(data,old_resource,new_resource,changed_paths):
    root=parse(data);rows=[];visited=0
    def walk(node,old,new,old_at,new_at,path):
        nonlocal visited
        visited+=1
        if (int(node.tokens[1]),int(node.tokens[2]))!=(old_at,len(old)):
            raise CodecError('Source seekmap offset/size disagrees with archive at '+str(path))
        checksum=int(node.tokens[3])
        if path in changed_paths:
            if content_crc(old)!=checksum:raise CodecError('Source seekmap checksum mismatch at '+str(path))
            checksum=content_crc(new)
            if node.opaque:raise CodecError('Cannot relocate a changed opaque seek subtree')
        rows.append(node.updated(new_at,len(new),checksum));rows.extend(node.opaque)
        if not node.children:return
        a,b=Archive(old),Archive(new)
        if len(node.children)!=len(a.entries) or len(a.entries)!=len(b.entries):raise CodecError('Seek/archive child count changed unexpectedly')
        for i,child in enumerate(node.children):
            name=child.tokens[0].decode('cp932')
            if name!=a.entries[i].name.rstrip(' \0') or a.entries[i].name!=b.entries[i].name:
                raise CodecError('Seek/archive names disagree at '+str(path+(i,)))
            walk(child,payload(a,i),payload(b,i),old_at+a.entries[i].offset,new_at+b.entries[i].offset,path+(i,))
    walk(root,memoryview(old_resource),memoryview(new_resource),0,0,())
    return b''.join(rows),visited
