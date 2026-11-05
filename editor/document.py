"""Stable-ID project, typed reference relocation, validation and undo transactions."""
from dataclasses import dataclass,field,asdict
from pathlib import Path
from copy import deepcopy
from collections import Counter
import hashlib,json,uuid
from .engine import TEXT_OPS,ROOT
from . import scriptcodec as codec
from .opcodes import CATALOG
from .semantics import condition,numeric
from .text import TextFormat
from .textlayout import normalize_arguments


class EditError(ValueError):pass


@dataclass
class Command:
    uid:str
    opcode:int
    args:dict
    raw:str
    post:int
    original_index:int|None
    authored:bool=False


@dataclass
class Script:
    id:int
    name:str
    original:str
    header:str
    tail:str
    commands:list


@dataclass
class Diagnostic:
    script:int
    command:str|None
    message:str
    severity:str='error'
    path:tuple=()


class Project:
    def __init__(self,scripts,root=''):
        self.scripts={s.id:s for s in scripts};self.root=root;self.revision=uuid.uuid4().hex
        self.baseline=self.scripts.copy()
        self.undo_stack=[];self.redo_stack=[];self.preview_issues=[];self.saved_revision=self.revision;self.touched=set();self.profile_links={}
        format_path=Path(root)/'env/env_string_format.dat' if root else None
        self.text_format=TextFormat(format_path.read_bytes()) if format_path and format_path.is_file() else None
        self.selection_layout=None
        self.font_asset=None
        selection_path=Path(root)/'env/env_script_select.dat' if root else None
        if selection_path and selection_path.is_file():
            from .environments import selection
            self.selection_layout=selection(selection_path.read_bytes())

    @classmethod
    def from_import(cls,bundle,metadata,root=''):
        names={s['id']:s['name'] for s in metadata};scripts=[]
        for item in bundle['scripts']:
            sid=item['id'];blob=bytes.fromhex(item['data_hex']);header,raw,tail=codec.parse(blob)
            if len(raw)!=len(item['commands']):raise EditError('Import/script reader disagree on command count')
            commands=[Command(f's{sid}:c{i}',r.opcode,deepcopy(c['args']),r.payload.hex(),r.post,i) for i,(r,c) in enumerate(zip(raw,item['commands']))]
            script=Script(sid,names.get(sid,str(sid)),blob.hex(),header.hex(),tail.hex(),commands)
            for c in commands:cls.bind(c.args,c.opcode,script)
            scripts.append(script)
        project=cls(scripts,root);project.profile_links=bundle.get('profile_links',{});return project

    @staticmethod
    def bind(args,opcode,script):
        for path in codec.reference_paths(opcode,args):
            value=codec.at(args,path)
            if isinstance(value,dict):continue
            if value==-1 and opcode==1 and path[0] in {'start','alternate'}:continue
            if value==len(script.commands) and opcode==1:target=f'end:{script.id}'
            elif isinstance(value,int) and 0<=value<len(script.commands):target=script.commands[value].uid
            else:target=f'missing:{script.id}:{value}'
            codec.put(args,path,{'$ref':target})

    def locations(self):return {c.uid:(sid,i) for sid,s in self.scripts.items() for i,c in enumerate(s.commands)}

    def refs(self):
        for sid,s in self.scripts.items():
            for c in s.commands:
                try:paths=codec.reference_paths(c.opcode,c.args)
                except (KeyError,TypeError):continue
                for path in paths:
                    value=codec.at(c.args,path)
                    if isinstance(value,dict) and '$ref' in value:yield sid,c.uid,path,value['$ref']

    def inbound(self,uid):return [(sid,source,path) for sid,source,path,target in self.refs() if target==uid]

    def arguments(self,sid,c,locations=None,display=False):
        args=deepcopy(c.args);locations=locations or self.locations()
        for path in codec.reference_paths(c.opcode,args):
            ref=codec.at(args,path)
            if isinstance(ref,dict):
                target=ref.get('$ref','')
                if target==f'end:{sid}':value=len(self.scripts[sid].commands)
                elif target in locations and locations[target][0]==sid:value=locations[target][1]
                elif display:value=f'<unresolved: {target}>'
                else:raise EditError(f'Unresolved or foreign local target {target}')
                codec.put(args,path,value)
        return args

    def compile(self,sid,locations=None):
        script=self.scripts[sid];locations=locations or self.locations();records=[]
        for c in script.commands:
            args=self.arguments(sid,c,locations)
            if c.authored:
                raw=bytes.fromhex(c.raw)
                tail=raw[codec.text_end(c.opcode,raw):] if raw else b''
                payload=codec.encode_text(c.opcode,args)+tail
            else:
                payload=bytearray.fromhex(c.raw)
                for path,offset in codec.reference_sites(c.opcode,payload):payload[offset:offset+4]=codec.number(codec.at(args,path))
                payload=bytes(payload)
            records.append(codec.RawRecord(c.opcode,payload,c.post,0))
        return codec.assemble(bytes.fromhex(script.header),records,bytes.fromhex(script.tail))

    def validate(self):
        out=[];locations=self.locations();total=sum(len(s.commands) for s in self.scripts.values())
        if self.font_asset:
            from .fontpatch import validate_asset
            try:validate_asset(self.font_asset,self.root)
            except (ValueError,KeyError,OSError,TypeError) as error:out.append(Diagnostic(-1,None,str(error)))
        original={c.uid:c for s in self.baseline.values() for c in s.commands}
        if len(locations)!=total:out.append(Diagnostic(-1,None,'Duplicate stable command IDs'))
        for sid,s in self.scripts.items():
            if sid not in self.baseline or s.header!=self.baseline[sid].header or s.tail!=self.baseline[sid].tail:out.append(Diagnostic(sid,None,'Opaque script header/tail changed outside supported editing'))
            if not s.commands:out.append(Diagnostic(sid,None,'A preview script needs at least one command'))
            intervals=[]
            for i,c in enumerate(s.commands):
                try:
                    base=original.get(c.uid)
                    if c.opcode not in TEXT_OPS and (base is None or c.opcode!=base.opcode or c.raw!=base.raw):raise EditError('Unsupported non-text opcode/payload edit')
                    if not c.authored and base is not None:
                        paths=codec.reference_paths(c.opcode,c.args)
                        left=deepcopy(c.args) if paths else c.args;right=deepcopy(base.args) if paths else base.args
                        for path in paths:codec.put(left,path,None);codec.put(right,path,None)
                        if left!=right:raise EditError('Unencoded argument changes outside supported text editing')
                    if 'decode_error' in c.args:raise EditError(c.args['decode_error'])
                    if c.opcode not in CATALOG or (not CATALOG[c.opcode].used and c.opcode!=0x2bd):raise EditError('Opaque opcode has no safe relocation/preview schema')
                    a=self.arguments(sid,c,locations)
                    for path in codec.reference_paths(c.opcode,a):
                        value=codec.at(a,path);boundary=c.opcode==1
                        if value==-1 and boundary and path[0]!='resume':continue
                        if not isinstance(value,int) or not 0<=value<(len(s.commands)+int(boundary)):raise EditError(f'Invalid command target at {path}: {value}')
                        if boundary and value>32767:raise EditError('Divergence boundary exceeds signed16 comparison domain')
                    if c.opcode==1:
                        condition(a['condition'])
                        start,alt,resume=(a[k] for k in ('start','alternate','resume'))
                        if resume<=i or (start>=0 and not i<start<resume) or (alt>=0 and not i<alt<resume) or (start>=0 and alt>=0 and start>=alt):raise EditError('Invalid true/alternate/merge interval ordering')
                        intervals.append((i,resume,c.uid))
                    if c.opcode==0x2bf and a['script']>=0 and a['script'] not in self.scripts:raise EditError('File destination does not exist')
                    if c.opcode in {0x65,0x3f2} and not a['choices']:raise EditError('Choice list must not be empty')
                    if c.opcode==0x65 and self.selection_layout:
                        points=self.selection_layout['points'][0 if len(a['choices'])==2 else 1]
                        if len(a['choices'])>len(points):raise EditError('Choice count exceeds original text-layout table')
                    if c.opcode==0x3f2 and len(a['choices'])>4:raise EditError('Battle choice UI requires 1–4 authored rows')
                    if c.opcode==0x3f2 and a['duration']>0x7fffffff:raise EditError('Battle timer exceeds the supported signed32 native clock domain')
                    if c.opcode==0x3f8 and any(row['voice']< -1 for row in a['outcomes']):raise EditError('Approach result voice ID must be -1 or nonnegative')
                    if c.opcode==0x3f6:
                        if not 1<=len(a['parents'])<=6 or any(not 1<=len(p['children'])<=3 for p in a['parents']):raise EditError('Approach flags require 1–6 parents and 1–3 children per parent')
                        for parent in a['parents']:numeric(parent['condition'])
                    if c.opcode==0x64 and not 0<=a['lane']<5:raise EditError('Dialogue requires lane0–4; route is an unsigned queue-policy word')
                    if c.authored:
                        codec.encode_text(c.opcode,a)
                        if self.text_format:self.text_format.validate(c.opcode,a)
                except (ValueError,KeyError,TypeError,IndexError,OverflowError) as e:out.append(Diagnostic(sid,c.uid,str(e)))
            stack=[]
            for start,end,uid in intervals:
                while stack and start>=stack[-1][1]:stack.pop()
                if stack and end>stack[-1][1]:out.append(Diagnostic(sid,uid,'Crossing conditional intervals; preserve nesting or retarget boundaries'))
                stack.append((start,end))
        # Provide exact source/path diagnostics for every broken reference, also
        # when another invalid field caused per-command validation to stop.
        for sid,uid,path,target in self.refs():
            if target.startswith('end:') and target==f'end:{sid}':continue
            if target not in locations or locations[target][0]!=sid:out.append(Diagnostic(sid,uid,f'Unresolved local reference: {target}',path=path))
        for item in self.preview_issues:
            s=self.scripts.get(item['script']);i=item.get('command',-1)
            out.append(Diagnostic(item['script'],s.commands[i].uid if s and isinstance(i,int) and 0<=i<len(s.commands) else None,'Preview parser: '+item['message']))
        return out

    def _transaction(self,sid,label,change):
        before=self.scripts.copy();draft=deepcopy(self.scripts[sid]);change(draft)
        self.scripts=self.scripts.copy();self.scripts[sid]=draft
        self.touched.add(sid)
        self.undo_stack.append((label,before,self.scripts.copy()));self.redo_stack.clear();self.preview_issues=[];self.revision=uuid.uuid4().hex

    def add(self,sid,index,opcode,args):
        if opcode not in TEXT_OPS:raise EditError('Only text opcodes can be inserted')
        if not 0<=index<=len(self.scripts[sid].commands):raise EditError('Insertion gap outside script')
        if any(c.opcode not in CATALOG or (not CATALOG[c.opcode].used and c.opcode!=0x2bd) for c in self.scripts[sid].commands):raise EditError('Structural relocation blocked by an opaque/unused opcode schema')
        uid='new:'+uuid.uuid4().hex;args=normalize_arguments(opcode,args,self.text_format);self.bind(args,opcode,self.scripts[sid])
        for path in codec.reference_paths(opcode,args):
            if codec.at(args,path)=={'$ref':f'self:{sid}'}:codec.put(args,path,{'$ref':uid})
        self._transaction(sid,'Insert text command',lambda s:s.commands.insert(index,Command(uid,opcode,args,'',0,None,True)))
        return uid

    def replace(self,sid,uid,opcode,args):
        old=next(c for c in self.scripts[sid].commands if c.uid==uid)
        if old.opcode not in TEXT_OPS or opcode not in TEXT_OPS:raise EditError('Only text opcodes can be edited/replaced')
        args=normalize_arguments(opcode,args,self.text_format);self.bind(args,opcode,self.scripts[sid])
        def change(s):
            i=next(i for i,c in enumerate(s.commands) if c.uid==uid)
            s.commands[i]=Command(uid,opcode,args,old.raw if opcode==old.opcode else '',old.post,old.original_index,True)
        self._transaction(sid,'Edit/replace text command',change)

    def delete(self,sid,uid,retarget=None):
        old=next(c for c in self.scripts[sid].commands if c.uid==uid)
        if old.opcode not in TEXT_OPS:raise EditError('Only text opcodes can be deleted')
        if retarget==uid:raise EditError('Cannot retarget to the deleted command')
        if retarget is not None and retarget not in {c.uid for c in self.scripts[sid].commands}:raise EditError('Replacement target must exist in the same file')
        def change(s):
            s.commands=[c for c in s.commands if c.uid!=uid]
            if retarget:
                for c in s.commands:
                    for path in codec.reference_paths(c.opcode,c.args):
                        if codec.at(c.args,path)=={'$ref':uid}:codec.put(c.args,path,{'$ref':retarget})
        self._transaction(sid,'Delete text command',change)

    def retarget(self,sid,source,path,target):
        if target not in {c.uid for c in self.scripts[sid].commands}:raise EditError('Target must be in the same script')
        def change(s):
            c=next(c for c in s.commands if c.uid==source)
            if tuple(path) not in codec.reference_paths(c.opcode,c.args):raise EditError('Not a typed command reference')
            codec.put(c.args,path,{'$ref':target})
        self._transaction(sid,'Retarget reference',change)

    def undo(self):
        if self.undo_stack:
            item=self.undo_stack.pop();self.redo_stack.append(item);self.scripts=item[1];self.preview_issues=[];self.revision=uuid.uuid4().hex
            if len(item)>3:self.font_asset=item[3]

    def redo(self):
        if self.redo_stack:
            item=self.redo_stack.pop();self.undo_stack.append(item);self.scripts=item[2];self.preview_issues=[];self.revision=uuid.uuid4().hex
            if len(item)>3:self.font_asset=item[4]

    def revision_request(self,entry,apply=True,validated=False):
        errors=[] if validated else self.validate()
        if errors:raise EditError(f'Project has {len(errors)} error(s); inspect Validation')
        scripts=[];locations=self.locations()
        for sid in sorted(self.touched):
            s=self.scripts[sid];blob=self.compile(sid,locations)
            if blob.hex()!=s.original:scripts.append(dict(id=sid,data_hex=blob.hex(),check_text=[i for i,c in enumerate(s.commands) if c.authored]))
        return dict(scripts=scripts,revision_id=self.revision,entry=entry,apply=apply,font_asset=self.font_asset)

    def display(self,sid):
        locations=self.locations();rows=[];offset=8+len(bytes.fromhex(self.scripts[sid].header))
        for i,c in enumerate(self.scripts[sid].commands):
            a=self.arguments(sid,c,locations,True)
            try:
                if c.authored:
                    raw=bytes.fromhex(c.raw);tail=raw[codec.text_end(c.opcode,raw):] if raw else b''
                    payload=codec.encode_text(c.opcode,a)+tail
                else:
                    payload=bytearray.fromhex(c.raw)
                    for path,pos in codec.reference_sites(c.opcode,payload):payload[pos:pos+4]=codec.number(codec.at(a,path))
                    payload=bytes(payload)
                size=len(payload)+6;raw=payload.hex()
            except (ValueError,KeyError,TypeError):size=None;raw=''
            rows.append(dict(index=i,uid=c.uid,opcode=c.opcode,args=a,offset=offset,size=size,raw=raw,post_word=c.post,original_index=c.original_index));offset=offset+size if offset is not None and size is not None else None
        return rows

    def summaries(self):
        rows=[]
        for sid,s in self.scripts.items():
            links=[]
            for i,c in enumerate(s.commands):
                if c.opcode==0x2bf:links.append(dict(command=i,target=c.args['script'],kind='file'))
                if c.opcode==0x3ed:
                    targets=self.profile_links.get(c.args['id'])
                    if targets is None:links.append(dict(command=i,target=None,kind='profile'))
                    else:links.extend(dict(command=i,target=target,kind='profile') for target in targets)
            rows.append(dict(id=sid,name=s.name,count=len(s.commands),opcodes={str(k):v for k,v in Counter(c.opcode for c in s.commands).items()},links=links))
        return rows

    def fingerprints(self):return {str(sid):hashlib.sha256(bytes.fromhex(s.original)).hexdigest() for sid,s in self.scripts.items()}

    def save(self,path):
        path=Path(path).resolve()
        if self.root and path.is_relative_to(Path(self.root).resolve()):raise EditError('Never save editor projects into original USRDIR')
        if path.is_relative_to((ROOT.parent/'impacto-sae').resolve()):raise EditError('Keep editor projects outside the Impacto checkout')
        data=dict(format='saekano-editor',version=1,root=self.root,revision=self.revision,touched=sorted(self.touched),fingerprints=self.fingerprints(),scripts=[asdict(self.scripts[sid]) for sid in sorted(self.touched)])
        if self.font_asset:data['font_asset']=self.font_asset
        temp=path.with_name(path.name+'.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path);self.saved_revision=self.revision

    @classmethod
    def load(cls,path,base):
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('format')!='saekano-editor' or data.get('version')!=1:raise EditError('Unsupported editor project format')
        if data['fingerprints']!=base.fingerprints():raise EditError('Project original scripts do not match the imported game data')
        scripts=base.baseline.copy()
        for raw in data['scripts']:
            commands=[Command(**c) for c in raw['commands']];raw={**raw,'commands':commands};script=Script(**raw)
            if script.id not in scripts:raise EditError('Project contains a foreign script ID')
            scripts[script.id]=script
        project=cls(list(scripts.values()),base.root);project.baseline=base.baseline.copy();project.profile_links=base.profile_links
        project.font_asset=data.get('font_asset')
        if project.font_asset:
            from .fontpatch import validate_asset
            validate_asset(project.font_asset,base.root)
        project.touched=set(data['touched'])
        if project.touched!=set(s['id'] for s in data['scripts']):raise EditError('Project changed-script index is inconsistent')
        if project.fingerprints()!=data['fingerprints']:raise EditError('Project provenance fingerprint is inconsistent')
        project.saved_revision=project.revision;return project
