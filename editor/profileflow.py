"""Profile-mode story semantics without its native UI/art/audio implementation.

Reference: profile.cpp, profileitems.cpp, profilemode.cpp, seekmap.cpp.
Selections are authored event records; stats are published only at handoff.
"""
import re
from .archive import Archive
from .scriptcodec import Reader
from .environments import table
from .semantics import signed16


def signed32(value):return (value+2**31)%2**32-2**31


def number(value):
    match=re.match(r'\s*([+-]?)([0-9]+)',value)
    if not match:raise ValueError('Profile numeric token contains no decimal digits')
    n=int(match[2])
    if n>0xffffffff:raise ValueError('Profile numeric token exceeds unsigned32')
    return signed32(-n if match[1]=='-' else n)


def rows(text,separator):
    """Native quoted token rules: bare CR/LF delimit; CRLF ends the row."""
    position=0;fields=[];value=''
    while position<len(text):
        ch=text[position];position+=1
        if ch=='"':
            while position<len(text):
                ch=text[position];position+=1
                if ch=='"':
                    if position==len(text) or text[position]!='"':break
                    position+=1
                value+=ch
        elif ch in {separator,'\r','\n'}:
            fields.append(value);value=''
            if ch=='\r' and position<len(text) and text[position]=='\n':
                position+=1;yield fields;fields=[]
        else:value+=ch
    if value or fields:yield fields+[value]


def environment(data):
    r=Reader(data);r.take(15);intro=r.word('i');r.take(3*36);r.word()
    r.take(4*36+8+2*36+4+5*36);table(r,4)
    r.take(36+16+36+2*36+16+4*36+32+36);table(r,8)
    r.take(36);table(r,36);r.take(8+4+12);r.word();table(r,8)
    r.take(8+2*36);r.word();r.take(8);r.string()
    for _ in range(r.count()):r.string();r.word()
    r.string();r.take(4+36)
    labels=[[r.string() for _ in range(r.count())] for _ in range(3)];format=r.string()
    r.take(36);table(r,8);r.word();r.take(8);duration=r.word('i')
    r.take(13*4);r.string();r.take(2*16+2*36+8)
    stats=[0]*12;count=r.count()
    if count>4:raise ValueError('Profile stats exceed four characters')
    for i in range(count):
        n=r.count()
        if n>3:raise ValueError('Profile stats exceed three fields')
        for j in range(n):stats[i*3+j]=r.word('i')
    return dict(stats=stats,labels=labels,format=format,intro=intro,stat_duration=duration)


def name_hash(value):
    value=value.split('\0',1)[0].rsplit('.',1)[0]
    value=value.encode('ascii');crc=0xffffffff
    for ch in value:
        if 65<=ch<=90:ch+=32
        crc^=ch<<24
        for _ in range(8):crc=((crc<<1)^(0x04c11db7 if crc&0x80000000 else 0))&0xffffffff
    return crc


def script_names(first):
    """Native seekmap script ordering, independent of archive display names."""
    lines=first.read(5,gzip=True).decode('cp932').split('\r\n');position=0
    def node(depth=0):
        nonlocal position
        if depth>128 or position>=len(lines):raise ValueError('Truncated/deep seekmap')
        fields=lines[position].split();position+=1
        if len(fields)<4:raise ValueError('Invalid seekmap record')
        flags=int(fields[4]) if len(fields)>4 else 0;count=int(fields[5]) if len(fields)>5 else 0
        if not 0<=count<=1000000:raise ValueError('Invalid seekmap child count')
        children=[]
        if flags&2:position+=count
        else:children=[node(depth+1) for _ in range(count)]
        return fields[0],children
    root=node()
    if len(root[1])<=4:raise ValueError('Seekmap script section missing')
    return [child[0] for child in root[1][4][1]]


def load(root,archive,names):
    env=environment((root/'env/env_otaku_mode.dat').read_bytes())
    first=Archive((root/'first.dat').read_bytes());tables=Archive(first.read(3));catalog=[]
    for i in range(len(tables.entries)):
        entries=[]
        for row in rows(tables.read(i).decode('utf-16-le'),'\t'):
            if row and row[0]=='ON':
                if len(row)<5:raise ValueError('Truncated profile item row')
                entries.append(dict(id=number(row[1]),category=number(row[2]),name=row[3].split('\0',1)[0],description=row[4].split('\0',1)[0]))
        if len(entries)!=30:raise ValueError('Profile catalog requires thirty authored rows')
        catalog.append(entries)
    if len(catalog)!=4:raise ValueError('Profile catalog requires four characters')
    ordered=script_names(first)
    if len(ordered)!=len(names):raise ValueError('Seekmap/archive script count mismatch')
    index={}
    for i,name in enumerate(ordered):index.setdefault(name_hash(name),i)
    bank=Archive(Archive(archive.read(3)).read(1));scenes=[]
    for i in range(len(bank.entries)):
        characters=[]
        for row in rows(bank.read(i).decode('cp932'),','):
            if not row or row[0]!='ON':continue
            if len(row)<3:raise ValueError('Truncated profile scene row')
            if row[1]=='CHARA':characters.append(dict(id=number(row[2]),events=[]))
            elif row[1]=='DATA':
                if not characters or len(row)<12:raise ValueError('Truncated profile event')
                values=list(map(number,row[2:7]));name=row[7].split('\0',1)[0]
                characters[-1]['events'].append(dict(values=values,script=name,target=index.get(name_hash(name),-1),
                    presentation=list(map(number,row[8:10])),response=row[10].split('\0',1)[0],tail=number(row[11])))
        if not 1<=len(characters)<=4 or any(not 0<=c['id']<4 or len(c['events'])!=10 for c in characters):
            raise ValueError('Profile scene must have 1–4 characters with ten authored events each')
        scenes.append(characters)
    return dict(environment=env,catalog=catalog,scenes=scenes)


def result_text(metadata,ordinal,character,event):
    env=metadata['environment'];eventid=event['values'][0]
    if not 0<=eventid<30 or not 0<=ordinal<4:raise ValueError('Profile event outside owner table')
    category=metadata['catalog'][ordinal][eventid]['category'];labels=env['labels']
    if character<0 or character>=len(labels[0]) or category<0 or category>=min(len(labels[1]),len(labels[2])):raise ValueError('Profile result label outside environment')
    args=[labels[0][character],labels[2][category],labels[1][category]];at=0
    def replace(match):
        nonlocal at
        if match[0]=='%%':return '%'
        if match[0]!='%ls' or at>=3:raise ValueError('Unsupported profile result format')
        value=args[at].split('\0',1)[0];at+=1;return value
    text=re.sub(r'%ls|%%|%.?',replace,env['format'].split('\0',1)[0])
    if at!=3 or len(text.encode('utf-16-le'))>=256:raise ValueError('Invalid profile result text extent')
    return text


def options(metadata,scene):
    out=[]
    for ordinal,character in enumerate(metadata['scenes'][scene]):
        for event,row in enumerate(character['events']):
            item=metadata['catalog'][ordinal][row['values'][0]]
            out.append(dict(ordinal=ordinal,event=event,character=character['id'],label=item['name'],description=item['description'],target=row['target']))
    return out


def commit_stats(session,ordinal,character,event):
    base=character*3
    for i,delta in enumerate(event['values'][2:5]):
        session.profile_stats[base+i]=min(100,signed32(session.profile_stats[base+i]+delta))
    category=event['values'][1]
    if 0<=category<=2:session.trophies.add(34-category)
    for i in range(3):
        if session.profile_stats[base+i]==100:session.trophies.add(26+i)


def publish(session,ordinal):
    for i,value in enumerate(session.profile_stats):session.banks['L'][30+i]=signed16(value)
    session.profile_cached=ordinal
