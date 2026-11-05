"""Export a validated project as a separate complete patched USRDIR, in Python."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
from .archive import Archive
from .packing import payload,member,pack_members,repack
from .seekwriter import relocate


class ExportError(ValueError):pass
class ExportCancelled(ExportError):pass


def checkpoint(progress,cancelled,message):
    if cancelled and cancelled():raise ExportCancelled('Export cancelled; original data unchanged.')
    if progress:progress(message)


def nested(archive,index):
    if archive.entries[index].kind!=0:raise ExportError('Expected type0 nested archive')
    return Archive(payload(archive,index))


def voice_ids(commands):
    result=[];seen=set()
    for c in commands:
        op,a=c.opcode,c.args
        ids=[a['voice']] if op==0x64 else [a['mission']] if op==0x3f7 else [v['voice'] for v in a['outcomes']] if op==0x3f8 else []
        for id in ids:
            if id< -1 or id>32767:raise ExportError('Voice ID outside native signed16 domain')
            if id>=0 and id not in seen:seen.add(id);result.append(id)
    return result


def table_rows(data,width):
    if len(data)<4:raise ExportError('Truncated history table')
    n=struct.unpack_from('<I',data)[0];end=4+n*width*4
    if end>len(data):raise ExportError('Truncated history rows')
    return [struct.unpack_from('<'+'I'*width,data,4+i*width*4) for i in range(n)],data[end:]


def encode_rows(rows,tail=b''):
    out=bytearray(struct.pack('<I',len(rows)))
    for row in rows:out.extend(struct.pack('<'+'I'*len(row),*row))
    return bytes(out)+tail


def history_tables(project,first,changed):
    tables=nested(first,4);decoded=[table_rows(tables.read(i),w) for i,w in enumerate((1,3,2))]
    counts=decoded[0][0];branches=decoded[1][0];reads=decoded[2][0]
    if len(counts)!=len(project.scripts):raise ExportError('History script count disagrees with source')
    grouped=[]
    for rows in (branches,reads):
        groups={};previous=-1
        for row in rows:
            if row[0] not in project.scripts or row[0]<previous:raise ExportError('Noncanonical history file groups')
            groups.setdefault(row[0],[]).append(row);previous=row[0]
        grouped.append(groups)
    new_counts=[];new_branches=[];new_reads=[]
    for sid,s in sorted(project.scripts.items()):
        if counts[sid][0]!=len(project.baseline[sid].commands):raise ExportError('Source command-count metadata mismatch')
        new_counts.append((len(s.commands),))
        if sid not in changed:
            new_branches.extend(grouped[0].get(sid,[]));new_reads.extend(grouped[1].get(sid,[]));continue
        oldb={row[1]&0xffff:row for row in grouped[0].get(sid,[])}
        oldr={row[1]&0x7fff:row for row in grouped[1].get(sid,[])}
        if len(oldb)!=len(grouped[0].get(sid,[])) or len(oldr)!=len(grouped[1].get(sid,[])):raise ExportError('Duplicate source history endpoints')
        for index,c in enumerate(s.commands):
            old=oldb.get(c.original_index);op=c.opcode
            flags=(len(c.args['choices']) if op in {0x65,0x3f2} else len(c.args['parents'])*4 if op==0x3f6 else old[2] if op==0x3ee and old else None)
            if op==0x3ee and old is None:raise ExportError('Missing source approach-entry history registration')
            if flags is not None:
                if index>0xffff:raise ExportError('Choice history endpoint exceeds unsigned16')
                new_branches.append((sid,index|((old[1]&0xffff0000) if old else 0),flags))
            if op==0x64:
                if index>0x7fff:raise ExportError('Read-history endpoint exceeds15-bit command domain')
                old=oldr.get(c.original_index)
                new_reads.append((sid,index|((old[1]&0xffff8000) if old else 0)))
    replacements={i:encode_rows(rows,decoded[i][1]) for i,rows in enumerate((new_counts,new_branches,new_reads))}
    return repack(tables,replacements)


def prepare_archives(project,source=None,progress=None,cancelled=None):
    """Pure preparation: no output writes; returns patched pair and a report."""
    checkpoint(progress,cancelled,'Validating project and source scripts…')
    issues=project.validate()
    if issues:
        locations=project.locations()
        raise ExportError('Project validation failed: '+ '; '.join(
            f'Script {d.script}, command {locations.get(d.command,(-1,"?"))[1]} ({d.command}): {d.message}' for d in issues[:5]))
    root=Path(source or project.root).resolve()
    first_bytes=(root/'first.dat').read_bytes();resource_bytes=(root/'resource.dat').read_bytes()
    first=Archive(first_bytes);resource=Archive(resource_bytes);scripts=nested(resource,4)
    if set(project.scripts)!=set(range(len(scripts.entries))):raise ExportError('Project/source script registry differs')
    locations=project.locations();changed={};objects={}
    for sid,s in sorted(project.scripts.items()):
        checkpoint(None,cancelled,'')
        numbered=nested(scripts,sid);obj=nested(numbered,0)
        original=obj.read(0,gzip=True)
        if original!=bytes.fromhex(s.original):raise ExportError(f'Source script {sid} changed since project import')
        if sid in project.touched:
            compiled=project.compile(sid,locations)
            if compiled!=original:changed[sid]=compiled;objects[sid]=(numbered,obj)
    report=dict(format='saekano-game-export',version=1,revision=project.revision,changed_scripts=[],
                source_hashes={name:hashlib.sha256(data).hexdigest() for name,data in [('first.dat',first_bytes),('resource.dat',resource_bytes)]},
                requires_fresh_progress=False,notes=['Original game files and personal saves are not modified.'])
    font=bytes.fromhex(project.font_asset['data_hex']) if project.font_asset else None
    if font:report['font_asset']={k:v for k,v in project.font_asset['manifest'].items() if k!='glyphs'}
    if not changed:
        report['output_hashes']=report['source_hashes'].copy()
        return dict(first=first_bytes,resource=resource_bytes,report=report,font=font)
    checkpoint(progress,cancelled,'Preparing script objects and voice companions…')
    needs_voices={sid for sid in changed if voice_ids(project.scripts[sid].commands)!=voice_ids(project.baseline[sid].commands)}
    pool={}
    if needs_voices:
        for sid in sorted(project.scripts):
            checkpoint(None,cancelled,'')
            obj=nested(nested(scripts,sid),0);ids=voice_ids(project.baseline[sid].commands)
            archive=Archive(obj.read(1,gzip=True))
            if len(archive.entries)!=len(ids):raise ExportError(f'Script {sid}: envelope count differs from source voice ordering')
            for index,id in enumerate(ids):
                item=member(archive,index)
                if item.kind!=0:raise ExportError('Unsupported voice-envelope kind')
                if id in pool and pool[id].data!=item.data:raise ExportError(f'Conflicting original envelope for voice {id}')
                pool.setdefault(id,item)
    replacements={};paths={() ,(4,)}
    for sid,compiled in changed.items():
        numbered,obj=objects[sid];leaves={0:gzip.compress(compiled,compresslevel=9,mtime=0)}
        paths.update({(4,sid),(4,sid,0),(4,sid,0,0)})
        if sid in needs_voices:
            ids=voice_ids(project.scripts[sid].commands);missing=[id for id in ids if id not in pool]
            if missing:raise ExportError(f'Script {sid}: no original envelope for voice IDs {missing[:8]}')
            old=Archive(obj.read(1,gzip=True));reserved=struct.unpack_from('<I',old.data,8)[0]
            leaves[1]=gzip.compress(pack_members([pool[id] for id in ids],reserved),compresslevel=9,mtime=0)
            paths.add((4,sid,0,1))
        replacements[sid]=repack(numbered,{0:repack(obj,leaves)})
        current=project.scripts[sid];baseline=project.baseline[sid]
        shape=lambda commands:[(c.uid,c.opcode,len(c.args['choices']) if c.opcode in {0x65,0x3f2} else tuple(len(p['children']) for p in c.args['parents']) if c.opcode==0x3f6 else None) for c in commands]
        structural=shape(current.commands)!=shape(baseline.commands)
        report['requires_fresh_progress']|=structural
        report['changed_scripts'].append(dict(id=sid,name=current.name.strip(' \0'),original_commands=len(baseline.commands),commands=len(current.commands),structural=structural,voice_companion_rebuilt=sid in needs_voices,sha256=hashlib.sha256(compiled).hexdigest()))
    new_resource=repack(resource,{4:repack(scripts,replacements)})
    checkpoint(progress,cancelled,'Relocating seek-map offsets, sizes and content checksums…')
    seek,visited=relocate(first.read(5,gzip=True),resource_bytes,new_resource,paths)
    metadata=history_tables(project,first,changed)
    new_first=repack(first,{4:metadata,5:gzip.compress(seek,compresslevel=9,mtime=0)})
    report['seek_records']=visited
    report['output_hashes']={name:hashlib.sha256(data).hexdigest() for name,data in [('first.dat',new_first),('resource.dat',new_resource)]}
    if report['requires_fresh_progress']:report['notes'].append('Use fresh game saves/history: command or choice identities changed; old progress is not migrated.')
    return dict(first=new_first,resource=new_resource,report=report,font=font)


def export_game(project,destination,progress=None,cancelled=None):
    source=Path(project.root).resolve();destination=Path(destination).expanduser().resolve()
    if not project.root or not source.is_dir():raise ExportError('Project has no valid original USRDIR')
    if destination==source or destination.is_relative_to(source) or source.is_relative_to(destination):raise ExportError('Export folder must be separate from original USRDIR')
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):raise ExportError('Choose an empty or new export folder; existing files are never overwritten')
    if not destination.parent.is_dir():raise ExportError('Export parent folder does not exist')
    # Capture regular files first: no links/junction traversal, no editor output
    # recursively copied back into the game, no hardlinks to original assets.
    files=[];directories=[]
    for path in sorted(source.rglob('*')):
        if path.is_symlink() or path.is_junction():raise ExportError('Linked source paths are not supported: '+str(path.relative_to(source)))
        if path.is_file():files.append(path)
        elif path.is_dir():directories.append(path.relative_to(source))
    prepared=prepare_archives(project,source,progress,cancelled)
    required=sum(p.stat().st_size for p in files)+len(prepared['first'])+len(prepared['resource'])+len(prepared['font'] or b'')
    if shutil.disk_usage(destination.parent).free<required:raise ExportError('Not enough free space for a complete game-data copy')
    with tempfile.TemporaryDirectory(prefix='.saekano-export-',dir=destination.parent) as temporary:
        container=Path(temporary).resolve()
        if container.parent!=destination.parent:raise ExportError('Unexpected staging directory location')
        staging=container/'USRDIR';staging.mkdir();copied=[]
        for relative in directories:(staging/relative).mkdir(parents=True,exist_ok=True)
        for path in files:
            relative=path.relative_to(source);target=staging/relative;target.parent.mkdir(parents=True,exist_ok=True)
            checkpoint(progress,cancelled,'Exporting '+str(relative)+'…')
            if relative.as_posix() in {'first.dat','resource.dat'}:
                target.write_bytes(prepared['first' if relative.name=='first.dat' else 'resource'])
            elif relative.as_posix()=='Font.gsf' and prepared['font'] is not None:target.write_bytes(prepared['font'])
            else:
                before=path.stat()
                with path.open('rb') as src,target.open('xb') as out:
                    while chunk:=src.read(4*1024*1024):
                        checkpoint(None,cancelled,'');out.write(chunk)
                after=path.stat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ExportError('Source changed during copy: '+str(relative))
            copied.append(relative.as_posix())
        report=prepared['report'];report['files']=copied
        (staging/'saekano-export.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        checkpoint(progress,cancelled,'Publishing completed export…')
        if destination.exists():destination.rmdir()  # Only an empty directory can be removed.
        try:staging.replace(destination)
        except OSError:
            destination.mkdir(exist_ok=True);raise
    return dict(path=str(destination),**report)
