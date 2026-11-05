"""Interactive translation workspace using the existing project and simulator."""
from copy import copy,deepcopy
from dataclasses import asdict
from functools import wraps
import hashlib
import json
from pathlib import Path
import re
import tempfile
import threading
from typing import Annotated,Literal,Any
import uuid
from pydantic import Field
from .engine import ROOT,TEXT_OPS,NAMES,text_fields
from .document import Project
from .scriptcodec import reference_paths,at,put
from .semantics import flow_index
from .opcodes import CATALOG,markdown
from .templates import template
from .runtime import Session
from .gameexport import export_game
from .mcp_models import TranslationEdit,CommandEdit,PreviewInput,BankEdit,Id,Index,Limit,PixelRect
from .dialogueview import project_flow,transcript,readable
from .textlayout import TextLayoutService,native_field
from .fontpatch import effective_font
from .mcp_models import UiTextEdit

GUIDE=(ROOT/'docs/TRANSLATOR_GUIDE.md').read_text(encoding='utf-8')


def locked(fn):
    @wraps(fn)
    def wrapped(self,*args,**kwargs):
        with self.lock:return fn(self,*args,**kwargs)
    return wrapped


def digest(data):return hashlib.sha256(data).hexdigest()
def fields(command):return dict(text_fields(dict(opcode=command.opcode,args=command.args)))
def field_path(name):return tuple(int(x) if x.isdecimal() else x for x in name.replace('[','.').replace(']','').split('.'))


class TranslationWorkspace:
    def __init__(self,usrdir,workspace,project_file='translation.saekano.json'):
        root=Path(usrdir).expanduser().resolve();runtime=Session();metadata=runtime.call('open',path=str(root))
        project=Project.from_import(runtime.call('project'),metadata['scripts'],str(root))
        self.initialize(project,runtime,workspace,project_file,True)

    def initialize(self,project,runtime,workspace,project_file='translation.saekano.json',load_saved=False):
        """Bind an already-loaded model/session; live GUI must not reload a disk shadow."""
        self.lock=threading.RLock();self.root=Path(project.root).resolve();self.workspace=Path(workspace).expanduser().resolve()
        if self.workspace.is_relative_to(self.root) or self.root.is_relative_to(self.workspace):raise ValueError('Workspace must be separate from original USRDIR')
        if self.workspace.is_relative_to((ROOT.parent/'impacto-sae').resolve()):raise ValueError('Workspace must stay outside Impacto')
        self.workspace.mkdir(parents=True,exist_ok=True)
        self.project=project
        self._runtime=runtime;self._preview_revision=None;self._disk_hashes={};self._cache={}
        self._baseline={c.uid:c for s in self.project.baseline.values() for c in s.commands}
        self.source_fingerprint=digest(json.dumps(self.project.fingerprints(),sort_keys=True).encode())
        self.profile=dict(target_language='',style_notes='',glossary={},progress_note='')
        self._context_path=self.path('translation-context.json')
        if self._context_path.exists():
            data=json.loads(self._context_path.read_text(encoding='utf-8'))
            if data.get('source_fingerprint')!=self.source_fingerprint:raise ValueError('Workspace context belongs to different game scripts')
            self.profile=data['profile'];self._disk_hashes[str(self._context_path)]=digest(self._context_path.read_bytes())
        self.project_file=project_file
        path=self.path(project_file)
        if load_saved and path.exists():
            self.project=Project.load(path,self.project);self._disk_hashes[str(path)]=digest(path.read_bytes())

    def path(self,name):
        if not name or Path(name).is_absolute():raise ValueError('Use a workspace-relative path')
        path=(self.workspace/name).resolve()
        if not path.is_relative_to(self.workspace) or path==self.workspace:raise ValueError('Path escapes configured workspace')
        return path

    def check_revision(self,expected):
        if expected!=self.project.revision:raise ValueError('Stale project revision; read current context/status and retry')

    def locations(self):
        key=('locations',self.project.revision)
        if key not in self._cache:self._cache[key]=self.project.locations()
        return self._cache[key]

    def command(self,sid,uid):
        location=self.locations().get(uid)
        if location is None or location[0]!=sid:raise ValueError('Command ID is missing or belongs to a different script')
        return location[1],self.project.scripts[sid].commands[location[1]]

    def script(self,sid):
        if sid not in self.project.scripts:raise ValueError('Unknown script ID')
        return self.project.scripts[sid]

    def packet(self,sid,command,include_arguments=True):
        baseline=self._baseline.get(command.uid);original=fields(baseline) if baseline else {}
        texts=[dict(field=path,original=original.get(path),current=value,changed=original.get(path)!=value,
                    control_tokens=self.controls(value),display=readable(value,command.opcode,self.project.text_format)) for path,value in fields(command).items()]
        result=dict(script_id=sid,command_id=command.uid,index=self.locations()[command.uid][1],opcode=command.opcode,
                    opcode_hex=f'{command.opcode:04X}',name=NAMES.get(command.opcode,'Unknown'),text_fields=texts,
                    editable=command.opcode in TEXT_OPS)
        if include_arguments:result['arguments']=deepcopy(command.args)
        return result

    def controls(self,text):
        f=self.project.text_format
        opening,closing=(f.tokens[0][0],f.tokens[1][0]) if f else ('《','》')
        return re.findall(re.escape(opening)+'.*?'+re.escape(closing),text,flags=re.DOTALL)

    def diagnostics(self,project=None):
        p=project or self.project;key=('validation',p.revision)
        if p is self.project and key in self._cache:return self._cache[key]
        result=p.validate()
        if p is self.project:self._cache[key]=result
        return result

    def candidate(self):
        candidate=copy(self.project);candidate.scripts=self.project.scripts.copy()
        candidate.touched=self.project.touched.copy();candidate.undo_stack=[];candidate.redo_stack=[];candidate.preview_issues=[]
        return candidate

    def commit(self,candidate,label):
        issues=self.diagnostics(candidate)
        if issues:raise ValueError('Batch rejected without changes: '+json.dumps([asdict(d) for d in issues[:12]],ensure_ascii=False))
        p=self.project;p.remember((label,p.scripts.copy(),candidate.scripts.copy()));p.redo_stack=[]
        p.scripts=candidate.scripts;p.touched=candidate.touched;p.preview_issues=[];p.revision=uuid.uuid4().hex
        self._cache={};self._preview_revision=None
        self._cache[('validation',p.revision)]=[]

    def flow(self,sid):
        key=('flow',self.project.revision,sid)
        if key not in self._cache:
            self._cache[key]=flow_index(self.project.display(sid),profile_links=self.project.profile_links)
        return self._cache[key]

    def dialogue_cards(self,sid):
        key=('dialogue',self.project.revision,sid)
        if key not in self._cache:
            cards=project_flow(self.script(sid).commands,self.flow(sid),self.project.text_format)
            for card in cards:
                if card['kind']=='presentation_cues':card['detail_request']['arguments']['script_id']=sid
            self._cache[key]=cards
        return self._cache[key]

    def edge(self,sid,edge):
        result=deepcopy(edge);commands=self.script(sid).commands
        result['source_id']=commands[edge['source']].uid
        if edge['script']==-2:
            result['target_id']=commands[edge['target']].uid
        elif edge['script']>=0 and edge['script'] in self.project.scripts:
            result['target_id']=self.script(edge['script']).commands[edge['target']].uid
        else:result['target_id']=None
        return result

    @locked
    def get_translation_guide(self)->dict[str,Any]:
        """Read the translation workflow, editable fields, native text controls and state limitations first."""
        return dict(guide=GUIDE,profile=deepcopy(self.profile),revision=self.project.revision,
                    workspace=str(self.workspace),project_file=self.project_file)

    @locked
    def configure_translation(self,target_language:Annotated[str,Field(min_length=1,max_length=100)],
            style_notes:Annotated[str,Field(max_length=10000)]|None=None,glossary:dict[str,str]|None=None,
            progress_note:Annotated[str,Field(max_length=10000)]|None=None,expected_context_revision:Id|None=None)->dict[str,Any]:
        """Persist language and supplied style/glossary/handoff fields; omitted optional fields are retained. No script edits."""
        current=self.context_revision()
        if (getattr(self,'live',False) or expected_context_revision is not None) and expected_context_revision!=current:
            raise ValueError('Stale or missing expected_context_revision; read get_status before changing translation policy/notes')
        if glossary and (len(glossary)>1000 or any(len(k)>1000 or len(v)>2000 for k,v in glossary.items())):raise ValueError('Glossary exceeds workspace context budget')
        profile=dict(target_language=target_language,style_notes=self.profile['style_notes'] if style_notes is None else style_notes,
                     glossary=deepcopy(self.profile['glossary'] if glossary is None else glossary),
                     progress_note=self.profile['progress_note'] if progress_note is None else progress_note)
        data=dict(format='saekano-translation-context',version=1,source_fingerprint=self.source_fingerprint,profile=profile)
        self.atomic_json(self._context_path,data);self.profile=profile
        return dict(profile=deepcopy(profile),revision=self.project.revision,context_revision=self.context_revision())

    def context_revision(self):return digest(json.dumps(self.profile,sort_keys=True,ensure_ascii=False).encode())

    @locked
    def get_status(self)->dict[str,Any]:
        """Read current revision, unsaved state, text-change counts, saved context and preview revision."""
        key=('stats',self.project.revision)
        if key not in self._cache:
            total=modified=0
            for s in self.project.scripts.values():
                for c in s.commands:
                    base=self._baseline.get(c.uid);old=fields(base) if base else {}
                    for name,value in fields(c).items():total+=1;modified+=old.get(name)!=value
            self._cache[key]=dict(scripts=len(self.project.scripts),text_fields=total,modified_text_fields=modified)
        return dict(revision=self.project.revision,unsaved=self.project.saved_revision!=self.project.revision,
                    texture_replacement_count=len(getattr(self.project,'texture_assets',{})),
                    ui_text_replacement_count=len(getattr(self.project,'ui_text_assets',{})),
                    font_asset={k:self.project.font_asset['manifest'].get(k) for k in ('format','font_sha256','source_sha256','generator_revision')} if self.project.font_asset else None,
                    project_file=self.project_file,profile=deepcopy(self.profile),context_revision=self.context_revision(),**self._cache[key],
                    preview_current=self._preview_revision==self.project.revision,
                    note='Changed text is not a claim of linguistic review. GUI/MCP exchange saved projects, not live shared state.')

    @locked
    def list_scripts(self,start:Index=0,limit:Limit=30,query:Annotated[str,Field(max_length=200)]='')->dict[str,Any]:
        """Page script IDs/names/counts. start is an offset in the name-filtered script list."""
        scripts=[s for s in self.project.scripts.values() if query.casefold() in s.name.casefold()]
        rows=[dict(id=s.id,name=s.name.strip(' \0'),commands=len(s.commands),text_commands=sum(c.opcode in TEXT_OPS for c in s.commands),has_edit_history=s.id in self.project.touched) for s in scripts[start:start+limit]]
        return dict(revision=self.project.revision,scripts=rows,next_start=start+limit if start+limit<len(scripts) else None)

    @locked
    def list_ui_text(self,query:Annotated[str,Field(max_length=200)]='',category:Annotated[str,Field(max_length=100)]='',
                     source:Annotated[str,Field(max_length=240)]='',include_protected:bool=False,start:Index=0,limit:Limit=30)->dict[str,Any]:
        """Discover non-script labels/prompts/settings/help/keyword/catalogue text, all languages. Page stable field IDs and original/current text. Protected syntax/resource names are optional; coverage/issues reported."""
        from .uitext import get_catalog
        c=get_catalog(self.project);rows=[];needle=query.casefold()
        for key,f in c.fields.items():
            current=self.project.ui_text_assets.get(key,{}).get('text',f['original'])
            if not include_protected and not f['editable']:continue
            if category and category!=f['category'] or source and source!=f['source']:continue
            if needle not in ' '.join((key,f['category'],f['original'],current)).casefold():continue
            rows.append(dict(f,current=current,modified=key in self.project.ui_text_assets))
        return dict(revision=self.project.revision,fields=rows[start:start+limit],total=len(rows),next_start=start+limit if start+limit<len(rows) else None,
            categories=sorted({f['category'] for f in c.fields.values()}),inventory=c.summary())

    @locked
    def get_ui_text(self,field_id:Id)->dict[str,Any]:
        """Read UI text field encoding/location/tokens/restrictions and neighboring strings for translation context."""
        from .uitext import get_catalog
        c=get_catalog(self.project)
        if field_id not in c.fields:raise ValueError('Unknown UI text field_id; call list_ui_text')
        f=c.fields[field_id];node=c.nodes[f['node_id']]
        neighbors=[dict(row,current=self.project.ui_text_assets.get(key,{}).get('text',row['original'])) for key,row in c.fields.items()
            if row['node_id']==f['node_id'] and abs(row['index']-f['index'])<=2]
        return dict(revision=self.project.revision,field=dict(f,current=self.project.ui_text_assets.get(field_id,{}).get('text',f['original'])),
            source_sha256=c.sources[f['source']]['sha256'],member_sha256=node['sha256'],neighbors=neighbors)

    @locked
    def apply_ui_text(self,edits:Annotated[list[UiTextEdit],Field(min_length=1,max_length=100)],expected_revision:Id)->dict[str,Any]:
        """Atomically translate known UI fields with exact expected_text/revision. Preserve placeholders/control syntax, encoding and native table structure. Undo/save/scene preview/export share these changes."""
        self.check_revision(expected_revision)
        rows=[UiTextEdit.model_validate(e) if isinstance(e,dict) else e for e in edits]
        changed=self.project.set_ui_texts([(e.field_id,e.expected_text,e.translation) for e in rows]);self._cache={};self._preview_revision=None
        return dict(revision=self.project.revision,changed=changed,applied_fields=[e.field_id for e in rows])

    def visual_context(self,expected_catalog_revision=None):
        from .visualcontext import VisualContext
        if not hasattr(self,'_visual_context'):self._visual_context=VisualContext()
        context=self._visual_context.bind(self);context.check_catalog(expected_catalog_revision)
        return context

    @locked
    def list_textures(self,query:Annotated[str,Field(max_length=200)]='',category:Annotated[str,Field(max_length=100)]='',
                      source:Annotated[str,Field(max_length=240)]='',start:Index=0,limit:Limit=30,
                      expected_catalog_revision:Id|None=None)->dict[str,Any]:
        """Discover/page original texture IDs, dimensions, formats and intended consumers. Exact category/source filters; query searches names/IDs/uses."""
        return self.visual_context(expected_catalog_revision).textures(query,category,source,start,limit)

    @locked
    def get_texture(self,asset_id:Id,include_image:bool=True,region:PixelRect|None=None,
                    max_size:Annotated[int,Field(ge=64,le=2048,strict=True)]=1024,
                    expected_catalog_revision:Id|None=None,view:Literal['current','original']='current')->dict[str,Any]:
        """Get current project pixels (default) or view=original, plus source provenance and replacement metadata. region=[x,y,w,h] is an in-bounds crop. PNG is a native MCP image block."""
        return self.visual_context(expected_catalog_revision).texture(asset_id,include_image,region,max_size,view)

    @locked
    def import_texture_png(self,asset_id:Id,filename:Annotated[str,Field(min_length=1,max_length=240)],expected_revision:Id,
                           expected_png_sha256:Id|None=None,expected_catalog_revision:Id|None=None)->dict[str,Any]:
        """Import a same-size lossless <=8-bit PNG as a project replacement. Undo/revision guarded. Game export checks original GXT palette/alpha constraints separately; exact PNG retained."""
        from .textureassets import read_png,sha,summary
        self.check_revision(expected_revision);context=self.visual_context(expected_catalog_revision);data=read_png(self.path(filename))
        if expected_png_sha256 is not None and sha(data)!=expected_png_sha256:raise ValueError('PNG file checksum changed; inspect the current file and retry')
        previous=self.project.revision;changed=self.project.set_texture(asset_id,data,context.catalog)
        self._cache={}
        if self._preview_revision==previous:self._preview_revision=self.project.revision
        return dict(revision=self.project.revision,asset_id=asset_id,changed=changed,replacement=summary(self.project.texture_assets[asset_id]),scope='project replacement; check_texture_export checks lossless game encoding before export_game_copy')

    @locked
    def check_texture_export(self,expected_revision:Id,asset_id:Id|None=None,start:Index=0,limit:Limit=30)->dict[str,Any]:
        """Read-only actual GXT encoding preflight (no files written). Check one replacement or all; pages report rows. Original size/format retained, P8 <=256 RGBA colors, opaque stays opaque; no quantization."""
        from .textureexport import prepare_textures
        from .imagecodec import ImageError
        self.check_revision(expected_revision)
        records=self.project.texture_assets
        if asset_id is not None:
            if asset_id not in records:raise ValueError('No PNG replacement for this asset_id')
            records={asset_id:records[asset_id]}
        try:_,rows,_=prepare_textures(records,self.project.root)
        except ImageError as error:return dict(revision=self.project.revision,valid=False,issues=[str(error)],files_written=False)
        return dict(revision=self.project.revision,valid=True,issues=[],files_written=False,total=len(rows),
            textures=rows[start:start+limit],next_start=start+limit if start+limit<len(rows) else None)

    @locked
    def remove_texture_replacement(self,asset_id:Id,expected_revision:Id)->dict[str,Any]:
        """Revert one project texture to its original pixels as an Undo transaction. Original files and saved projects are untouched until Save."""
        self.check_revision(expected_revision);previous=self.project.revision;self.project.remove_texture(asset_id);self._cache={}
        if self._preview_revision==previous:self._preview_revision=self.project.revision
        return dict(revision=self.project.revision,asset_id=asset_id,removed=True)

    @locked
    def write_texture_png(self,asset_id:Id,filename:Annotated[str,Field(min_length=1,max_length=240)],expected_revision:Id,
                          view:Literal['current','original']='current')->dict[str,Any]:
        """Write a separate new workspace-relative PNG for external image editing. Never overwrite files. Current replacement bytes are copied exactly; original GXT pixels are decoded losslessly. No project/game changes."""
        from .textureassets import png_bytes,encode_png,write_png
        self.check_revision(expected_revision);context=self.visual_context()
        data=png_bytes(context.replacements[asset_id]) if view=='current' and asset_id in context.replacements else encode_png(context.catalog.decode(asset_id))
        return dict(revision=self.project.revision,asset_id=asset_id,view=view,**write_png(self.path(filename),data,self.project.root))

    @locked
    def get_texture_usage(self,asset_id:Id,kind:Literal['atlas_regions','script_uses']='atlas_regions',
                          start:Index=0,limit:Limit=30,expected_catalog_revision:Id|None=None)->dict[str,Any]:
        """Page known atlas regions or literal original-script uses. Missing mappings do not imply unused assets; these are potential uses, not observed scene execution."""
        return self.visual_context(expected_catalog_revision).usage(asset_id,kind,start,limit)

    @locked
    def list_ui_scenes(self)->dict[str,Any]:
        """List supported static UI-scene families and coverage. Use describe_ui_scene for state fields/bounds, then get_ui_scene for image and layer/text data."""
        from .composition import FAMILIES
        from .visualcontext import COORDINATES,LIMITATIONS
        return dict(project_revision=self.project.revision,families=[dict(family=key,name=name,coverage=coverage) for key,name,coverage in FAMILIES],
                    coordinates=COORDINATES,limitations=LIMITATIONS)

    @locked
    def describe_ui_scene(self,family:Annotated[str,Field(min_length=1,max_length=40)],state:dict[str,Any]|None=None,
                          expected_catalog_revision:Id|None=None)->dict[str,Any]:
        """Discover this family's exact parameter names/defaults/types/choices and state-dependent bounds. Unknown or invalid supplied fields reject; no GUI/game state changes."""
        return self.visual_context(expected_catalog_revision).describe(family,state)

    @locked
    def get_ui_scene(self,family:Annotated[str,Field(min_length=1,max_length=40)],state:dict[str,Any]|None=None,
                     include_image:bool=True,max_size:Annotated[int,Field(ge=64,le=2048,strict=True)]=1024,
                     limit:Limit=50,expected_catalog_revision:Id|None=None)->dict[str,Any]:
        """Render a whole supported static UI scene with current project font and explicit preview state. Returns PNG image plus revision-bound scene_id, paged layers/text, source hashes and limits. Pass current translated text via state, not a guessed story position."""
        return self.visual_context(expected_catalog_revision).scene(self,family,state,include_image,max_size,limit)

    @locked
    def get_ui_scene_layers(self,scene_id:Id,start:Index=0,limit:Limit=30,include_glyphs:bool=False,
                            kind:Literal['all','text','sprite','solid','target']='all')->dict[str,Any]:
        """Page the exact scene snapshot: draw order/pass, texture/target/mask, crop/position/size/clip/rotation/color, and text/style. Optional glyphs provide codepoints/rectangles/colors. Stale/evicted snapshots reject."""
        return self.visual_context().layers(scene_id,start,limit,include_glyphs,kind)

    @locked
    def list_commands(self,script_id:Index,start:Index=0,limit:Limit=30,text_only:bool=True,
                      query:Annotated[str,Field(max_length=200)]='')->dict[str,Any]:
        """Detailed command paging with stable IDs/raw editable text; use get_dialogue_flow for primary reading. Cursors are revision-scoped."""
        s=self.script(script_id);rows=[];cursor=start
        while cursor<len(s.commands) and len(rows)<limit:
            c=s.commands[cursor];cursor+=1
            if text_only and c.opcode not in TEXT_OPS:continue
            if query and query.casefold() not in ' '.join(fields(c).values()).casefold():continue
            rows.append(self.packet(script_id,c,False))
        return dict(revision=self.project.revision,commands=rows,next_start=cursor if cursor<len(s.commands) else None)

    @locked
    def get_context(self,script_id:Index,command_id:Id,
                    neighbours:Annotated[int,Field(ge=0,le=8)]=3,details:bool=False)->dict[str,Any]:
        """Read original/current editable text and readable dialogue context. Compact cues by default; details=true reveals exact arguments."""
        index,c=self.command(script_id,command_id);commands=self.script(script_id).commands
        text_indices=[i for i,x in enumerate(commands) if x.opcode in TEXT_OPS]
        before=[i for i in text_indices if i<index][-neighbours:] if neighbours else []
        after=[i for i in text_indices if i>index][:neighbours]
        low=before[0] if before else index;high=after[-1] if after else index
        cards=[card for card in self.dialogue_cards(script_id) if card['last_index']>=low and card['index']<=high]
        quiet=[card for card in cards if card['kind'] not in {'dialogue','text_choice','caption'}]
        cues=([self.packet(script_id,x) for x in commands[low:high+1] if x.opcode not in TEXT_OPS] if details else quiet)
        result=dict(revision=self.project.revision,command=self.packet(script_id,c,details),
                    neighbouring_text=[self.packet(script_id,commands[i],False) for i in before+after],
                    dialogue_flow=transcript(cards),state_cues=cues[:30],state_cues_truncated=len(cues)>30,
                    edges=[self.edge(script_id,e) for e in self.flow(script_id)['edges'] if e['source']==index or (e['script']==-2 and e['target']==index)],
                    flow_issues=self.flow(script_id)['issues'],
                    context_kind='Physical neighbours/potential edges, not a proven runtime route')
        if c.opcode==0x64 and self.project.text_format:
            result['speaker_prefix']=result['command']['text_fields'][0]['display']['speaker']
        return result

    @locked
    def get_dialogue_flow(self,script_id:Index,start:Index=0,limit:Limit=30)->dict[str,Any]:
        """Primary reading view: speaker/dialogue, labelled choices and branches/state, with grouped inspectable media cues. Potential flow, not a route."""
        self.script(script_id);cards=self.dialogue_cards(script_id)
        selected=[c for c in cards if c['last_index']>=start];page=deepcopy(selected[:limit])
        return dict(revision=self.project.revision,script_id=script_id,view='dialogue flow',potential_only=True,
                    transcript=transcript(page),cards=page,next_start=selected[limit]['index'] if len(selected)>limit else None,
                    starts_before_requested=bool(page and page[0]['index']<start),
                    issues=self.flow(script_id)['issues'],
                    guidance='Read the transcript and follow explicit branch targets. Media groups retain command ranges/opcodes; ask get_context(details=true) or list_commands(text_only=false) for detail. Fetch raw current fields before editing.')

    @locked
    def list_opcodes(self,query:Annotated[str,Field(max_length=200)]='',used_only:bool=True,start:Index=0,limit:Limit=30)->dict[str,Any]:
        """Search the same opcode catalogue as the human editor by name, hex/decimal code, behaviour or argument meaning; fetch opcode_help for full detail."""
        matches=[]
        for code,op in sorted(CATALOG.items()):
            if used_only and not op.used:continue
            text=f'{code:04x} 0x{code:x} {code} {op.name} {op.behavior} '+' '.join(f.key+' '+f.meaning for f in op.fields)
            if query.casefold() not in text.casefold():continue
            matches.append(dict(opcode=code,opcode_hex=f'{code:04X}',name=op.name,summary=op.behavior,used=op.used,editable=code in TEXT_OPS))
        return dict(opcodes=matches[start:start+limit],matches=len(matches),next_start=start+limit if start+limit<len(matches) else None,
                    help_tool='opcode_help',help_arguments='opcode: numeric code from this catalogue')

    @locked
    def search_text(self,query:Annotated[str,Field(min_length=1,max_length=200)],script_id:Index|None=None,
                    start:Index=0,limit:Limit=20)->dict[str,Any]:
        """Search original/current text fields. start is a revision-scoped field ordinal in the selected corpus."""
        scripts=[self.script(script_id)] if script_id is not None else self.project.scripts.values()
        cursor=0;rows=[];more=False
        for s in scripts:
            for c in s.commands:
                base=self._baseline.get(c.uid);old=fields(base) if base else {}
                for name,value in fields(c).items():
                    at_cursor=cursor;cursor+=1
                    if at_cursor<start:continue
                    if query.casefold() not in (value+'\n'+(old.get(name) or '')).casefold():continue
                    if len(rows)==limit:more=True;break
                    rows.append(dict(script_id=s.id,command_id=c.uid,index=self.locations()[c.uid][1],field=name,original=old.get(name),current=value,cursor=at_cursor))
                if more:break
            if more:break
        return dict(revision=self.project.revision,matches=rows,next_start=rows[-1]['cursor']+1 if more else None)

    @locked
    def get_script_flow(self,script_id:Index,command_id:Id|None=None,
                        depth:Annotated[int,Field(ge=0,le=4)]=1,start:Index=0,limit:Limit=80)->dict[str,Any]:
        """Read paged potential command/file edges; optionally restrict to a command's bounded neighbourhood."""
        flow=self.flow(script_id);edges=flow['edges']
        if command_id is not None:
            index,_=self.command(script_id,command_id);nodes={index}
            for _ in range(depth):nodes|={e['target'] for e in edges if e['source'] in nodes and e['script']==-2}|{e['source'] for e in edges if e['target'] in nodes and e['script']==-2}
            edges=[e for e in edges if e['source'] in nodes or (e['script']==-2 and e['target'] in nodes)]
        return dict(revision=self.project.revision,potential_only=True,edges=[self.edge(script_id,e) for e in edges[start:start+limit]],
                    next_start=start+limit if start+limit<len(edges) else None,issues=flow['issues'])

    @locked
    def get_file_links(self,script_id:Index)->dict[str,Any]:
        """Read possible incoming/outgoing script handoffs, including profile destinations; no route is implied."""
        self.script(script_id);incoming=[];outgoing=[]
        for s in self.project.summaries():
            for link in s['links']:
                row=dict(source_script=s['id'],source_id=self.script(s['id']).commands[link['command']].uid,**link)
                if s['id']==script_id:outgoing.append(row)
                if link['target']==script_id:incoming.append(row)
        return dict(revision=self.project.revision,potential_only=True,incoming=incoming,outgoing=outgoing)

    @locked
    def opcode_help(self,opcode:Index,technical:bool=False)->dict[str,Any]:
        """Read self-contained opcode behaviour, argument meanings/rules, completion and editing support; no source files needed."""
        op=CATALOG.get(opcode)
        if not op:raise ValueError('Unknown opcode')
        return dict(opcode=opcode,name=op.name,help=markdown(op,technical),fields=[asdict(f) for f in op.fields],editable=opcode in TEXT_OPS)

    @locked
    def command_template(self,script_id:Index,opcode:Index,target_command_id:Id)->dict[str,Any]:
        """Get one of the seven typed text templates with stable reference targets, for deliberate structural edits."""
        self.command(script_id,target_command_id)
        return dict(revision=self.project.revision,opcode=opcode,arguments=template(opcode,target_command_id))

    @locked
    def format_text(self,script_id:Index,command_id:Id,field:Id,
                    text:Annotated[str,Field(max_length=131070)]|None=None,
                    width:Annotated[int,Field(ge=1,le=4096,strict=True)]|None=None,
                    dialogue_mode:Literal['ordinary','battle']='ordinary',full_width_latin:bool=False)->dict[str,Any]:
        """Propose game-compatible word wrapping without editing. Optional full_width_latin converts supported visible ASCII before fitting, preserving controls/spaces. Timed SP QUE explicit breaks reject; single-line labels check screen positions. Choose dialogue mode explicitly."""
        _,command=self.command(script_id,command_id);allowed=fields(command)
        if field not in allowed:raise ValueError('Field is not editable translation text')
        font=effective_font(self.project,self._runtime.text);profile=bool(self.project.font_asset)
        result=TextLayoutService(font,self._runtime.settings).wrap(command.opcode,allowed[field] if text is None else text,field=field,width=width,dialogue_mode=dialogue_mode,full_width_latin=full_width_latin or profile and command.opcode in {0x64,0x3f2,0x3f8},preserve_speaker=profile)
        return dict(revision=self.project.revision,script_id=script_id,command_id=command_id,field=field,**result)

    @locked
    def analyze_text_cleanup(self,script_id:Index|None=None,command_ids:Annotated[list[Id],Field(max_length=1000)]|None=None,
            skip_japanese:bool=True,hyphenate:bool=True,paginate:bool=True,
            max_lines:Annotated[int,Field(ge=1,le=20,strict=True)]|None=None,
            width:Annotated[int,Field(ge=1,le=4096,strict=True)]|None=None,
            label_width:Annotated[int,Field(ge=1,le=4096,strict=True)]|None=None,
            dialogue_mode:Literal['auto','ordinary','battle']='auto',limit:Limit=30,full_width_latin:bool=False,proportional_latin:bool=False)->dict[str,Any]:
        """Analyze cleanup/page proposals. proportional_latin generates an asset-only Font.gsf with variable dialogue widths, aliases and matching fit, retained by Apply/save/Undo/export; names/simple UI remain fixed. full_width_latin alone only widens PVF text. Timed/queued/append restrictions remain. Omit script_id for whole project; review font_asset and text before Apply."""
        from .textcleanup import analyze_cleanup,public_plan
        plan=analyze_cleanup(self.project,self._runtime.text,self._runtime.settings,
            script_ids=None if script_id is None else [script_id],command_ids=command_ids,skip_japanese=skip_japanese,
            hyphenate=hyphenate,paginate=paginate,max_lines=max_lines,width=width,label_width=label_width,dialogue_mode=dialogue_mode,full_width_latin=full_width_latin,proportional_latin=proportional_latin)
        plans=getattr(self,'_cleanup_plans',{});plans[plan['plan_id']]=plan
        while len(plans)>4:plans.pop(next(iter(plans)))
        self._cleanup_plans=plans;return public_plan(plan,limit=limit)

    @locked
    def get_text_cleanup_plan(self,plan_id:Id,start:Index=0,limit:Limit=30)->dict[str,Any]:
        """Page before/after text, proposed pages, box metrics and skipped issues. Plan remains tied to its original project revision."""
        from .textcleanup import public_plan
        plan=getattr(self,'_cleanup_plans',{}).get(plan_id)
        if plan is None:raise ValueError('Unknown/expired cleanup plan; analyze again')
        return public_plan(plan,start,limit)

    @locked
    def apply_text_cleanup(self,plan_id:Id,expected_revision:Id,
                           command_ids:Annotated[list[Id],Field(max_length=1000)]|None=None)->dict[str,Any]:
        """Apply cleanup text and a reviewed font_asset update atomically as one Undo transaction. font_changed can apply with no text changes. Omit command_ids for all text proposals; an empty list still applies a pending font update. Reject stale/invalid plans without edits."""
        from .textcleanup import apply_cleanup
        self.check_revision(expected_revision);plan=getattr(self,'_cleanup_plans',{}).get(plan_id)
        if plan is None:raise ValueError('Unknown/expired cleanup plan; analyze again')
        result=apply_cleanup(self.project,plan,command_ids);self._cache={};self._preview_revision=None
        return result

    @locked
    def apply_translations(self,edits:Annotated[list[TranslationEdit],Field(min_length=1,max_length=100)],expected_revision:Id)->dict[str,Any]:
        """Atomically replace approved text fields. Enter becomes a native break. wrap_words fits using original metrics; full_width_latin converts supported visible ASCII then fits. Both check current text/revision and preserve controls. Timed explicit breaks reject."""
        self.check_revision(expected_revision);candidate=self.candidate();groups={};seen=set();applied=[]
        for edit in edits:
            _,c=self.command(edit.script_id,edit.command_id);key=(edit.script_id,edit.command_id,edit.field)
            if key in seen:raise ValueError('Duplicate field in translation batch')
            seen.add(key);allowed=fields(c)
            if edit.field not in allowed:raise ValueError('Field is not editable translation text')
            old=allowed[edit.field]
            if old!=edit.expected_text:raise ValueError('Stale expected_text; read current context and retry')
            translated=native_field(c.opcode,edit.translation,self.project.text_format);layout=None
            profile=bool(self.project.font_asset) and c.opcode in {0x64,0x3f2,0x3f8}
            if edit.wrap_words or edit.full_width_latin or profile:
                layout=TextLayoutService(effective_font(self.project,self._runtime.text),self._runtime.settings).wrap(c.opcode,translated,field=edit.field,width=edit.layout_width,dialogue_mode=edit.dialogue_mode,full_width_latin=edit.full_width_latin or profile,preserve_speaker=profile);translated=layout['text']
            elif edit.layout_width is not None:raise ValueError('layout_width requires wrap_words=true or full_width_latin=true')
            if self.controls(old)!=self.controls(translated):raise ValueError('Text-only translation must preserve native control tokens and order')
            if old.partition('\0')[1:]!=translated.partition('\0')[1:]:raise ValueError('Do not introduce or alter NUL-terminated hidden text')
            if old==translated:continue
            args=groups.setdefault((edit.script_id,c.uid),deepcopy(c.args));put(args,field_path(edit.field),translated)
            applied.append(dict(script_id=edit.script_id,command_id=c.uid,field=edit.field,text=translated,layout=layout))
        for (sid,uid),args in groups.items():candidate.replace(sid,uid,self.command(sid,uid)[1].opcode,args)
        if applied:self.commit(candidate,'MCP translation batch')
        return dict(revision=self.project.revision,applied=applied,valid=True)

    @locked
    def edit_commands(self,edits:Annotated[list[CommandEdit],Field(min_length=1,max_length=20)],expected_revision:Id)->dict[str,Any]:
        """Deliberate atomic text-command insert/delete/replace. Use stable $ref targets; reject broken references/invalid final batches."""
        self.check_revision(expected_revision);candidate=self.candidate();result=[]
        for edit in edits:
            script=candidate.scripts.get(edit.script_id)
            if not script:raise ValueError('Unknown script ID')
            index=next((i for i,c in enumerate(script.commands) if c.uid==edit.command_id),None)
            if index is None:raise ValueError('Unknown command anchor')
            if edit.action=='delete':
                if edit.opcode is not None or edit.arguments is not None:raise ValueError('Delete does not accept opcode/arguments')
                candidate.delete(edit.script_id,edit.command_id,edit.replacement_id);uid=edit.command_id
            else:
                if edit.opcode is None or edit.arguments is None or edit.replacement_id is not None:raise ValueError('Insert/replace requires opcode/arguments, without replacement_id')
                # Reject numeric command references; relocation must use stable identities.
                for path in reference_paths(edit.opcode,edit.arguments):
                    value=at(edit.arguments,path)
                    if not isinstance(value,dict) or set(value)!={'$ref'}:raise ValueError('Use stable {$ref: command_id} references')
                if edit.action=='replace':candidate.replace(edit.script_id,edit.command_id,edit.opcode,edit.arguments);uid=edit.command_id
                else:uid=candidate.add(edit.script_id,index+int(edit.action=='insert_after'),edit.opcode,edit.arguments)
            result.append(dict(action=edit.action,command_id=uid,script_id=edit.script_id))
        self.commit(candidate,'MCP structural batch')
        return dict(revision=self.project.revision,changes=result,valid=True)

    @locked
    def validate_project(self,limit:Limit=50)->dict[str,Any]:
        """Validate encoding/text controls, typed targets, branch structure and counts; this does not judge translation quality."""
        issues=self.diagnostics()
        return dict(revision=self.project.revision,valid=not issues,issue_count=len(issues),issues=[asdict(d) for d in issues[:limit]])

    @locked
    def undo(self,expected_revision:Id)->dict[str,Any]:
        """Undo one accepted text/structural batch, keeping originals and on-disk projects untouched until Save."""
        self.check_revision(expected_revision);key=self.project.scenario_key();current=self._preview_revision==self.project.revision
        self.project.undo();self._cache={};self._preview_revision=self.project.revision if current and key==self.project.scenario_key() else None
        return dict(revision=self.project.revision,can_undo=bool(self.project.undo_stack),can_redo=bool(self.project.redo_stack))

    @locked
    def redo(self,expected_revision:Id)->dict[str,Any]:
        """Redo one previously undone batch; never silently reapply a stale revision."""
        self.check_revision(expected_revision);key=self.project.scenario_key();current=self._preview_revision==self.project.revision
        self.project.redo();self._cache={};self._preview_revision=self.project.revision if current and key==self.project.scenario_key() else None
        return dict(revision=self.project.revision,can_undo=bool(self.project.undo_stack),can_redo=bool(self.project.redo_stack))

    def check_disk(self,path):
        if path.exists() and self._disk_hashes.get(str(path))!=digest(path.read_bytes()):raise ValueError('File already exists or changed outside this session; load it explicitly or choose a new filename')
        if not path.exists() and str(path) in self._disk_hashes:raise ValueError('Loaded file disappeared outside this session; choose a new filename')

    def atomic_json(self,path,data):
        self.check_disk(path);path.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.mcp-save-',dir=self.workspace) as folder:
            temp=Path(folder)/'context.json';temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            self.check_disk(path);temp.replace(path)
        self._disk_hashes[str(path)]=digest(path.read_bytes())

    @locked
    def save_project(self,expected_revision:Id,filename:Annotated[str,Field(min_length=1,max_length=240)]|None=None)->dict[str,Any]:
        """Save the current GUI-readable project (or a named new copy). Refuse unfamiliar/external overwrites and invalid drafts."""
        self.check_revision(expected_revision)
        if self.diagnostics():raise ValueError('Fix validation errors before saving through MCP')
        filename=self.project_file if filename is None else filename
        path=self.path(filename)
        if path==self._context_path or not filename.endswith('.saekano.json'):raise ValueError('Use a .saekano.json project filename')
        self.check_disk(path);path.parent.mkdir(parents=True,exist_ok=True);saved=self.project.saved_revision
        try:
            with tempfile.TemporaryDirectory(prefix='.mcp-save-',dir=self.workspace) as folder:
                temp=Path(folder)/'project.saekano.json';self.project.save(temp);self.check_disk(path);temp.replace(path)
        except Exception:self.project.saved_revision=saved;raise
        self._disk_hashes[str(path)]=digest(path.read_bytes());self.project_file=filename
        return dict(revision=self.project.revision,filename=filename,sha256=self._disk_hashes[str(path)],saved=True)

    @locked
    def load_project(self,filename:Annotated[str,Field(min_length=1,max_length=240)],expected_revision:Id,discard_unsaved:bool=False)->dict[str,Any]:
        """Open a workspace project with source-fingerprint checks; requires explicit discard_unsaved to replace unsaved memory."""
        self.check_revision(expected_revision)
        if self.project.saved_revision!=self.project.revision and not discard_unsaved:raise ValueError('Unsaved edits: save first or explicitly discard_unsaved')
        path=self.path(filename);stamp=digest(path.read_bytes());candidate=Project.load(path,self.project)
        if digest(path.read_bytes())!=stamp:raise ValueError('Project file changed while opening; active project unchanged')
        if candidate.validate():raise ValueError('Loaded project is invalid; active project unchanged')
        self.project=candidate;self.project_file=filename;self._cache={};self._preview_revision=None
        self._disk_hashes[str(path)]=stamp
        return self.get_status()

    @locked
    def export_game_copy(self,folder:Annotated[str,Field(min_length=1,max_length=240)],expected_revision:Id)->dict[str,Any]:
        """Only when a patched data copy is requested: export to a separate new/empty workspace folder; never launch/configure a game."""
        self.check_revision(expected_revision);target=self.path(folder)
        if self.workspace.is_relative_to(target):raise ValueError('Export must be below the workspace root')
        result=export_game(self.project,target)
        return dict(revision=self.project.revision,path=result['path'],changed_scripts=result['changed_scripts'],changed_textures=result['changed_textures'],changed_ui_text=result['changed_ui_text'],textures=result['textures'],requires_fresh_progress=result['requires_fresh_progress'])

    def require_preview(self):
        if self._preview_revision!=self.project.revision:raise ValueError('Preview is absent/stale after edits; call preview_start')

    def check_state_revision(self,expected):
        checker=getattr(self,'live_state_check',None)
        if checker:checker(expected)

    def preview_packet(self):
        view=self._runtime.call('view');sid,pc=view['script'],view['command'];commands=self.script(sid).commands
        return dict(revision=self.project.revision,script_id=sid,command_id=commands[pc].uid if pc<len(commands) else None,
            index=pc,opcode=view['opcode'],boundary=view['boundary'],time_ms=view['time'],sandbox=view['sandbox'],
            state_origin=f'Execution/replay from fresh file {self._runtime.entry}; earlier story state is not imported',
            error=view['error'],mode=view['mode'],messages=view['messages'],text_items=view['text_items'],
            text_ready=view['text_ready'],text_waiting=view['text_waiting'],choices=view['choices'],
            variables=view['variables'],logic=view['logic'],actors=view['actors'],actions=view['history'])

    @locked
    def preview_start(self,script_id:Index,expected_revision:Id,expected_state_revision:Id|None=None)->dict[str,Any]:
        """Start the same Python scenario simulator from an explicitly fresh file entry, applying current validated edits."""
        self.check_state_revision(expected_state_revision);self.check_revision(expected_revision);self.script(script_id)
        if self.diagnostics():raise ValueError('Invalid project cannot run')
        result=self._runtime.call('revision',**self.project.revision_request(script_id,validated=True))
        if result['issues']:raise ValueError('Preview parser rejected the project: '+json.dumps(result['issues']))
        self._preview_revision=self.project.revision;return self.preview_packet()

    @locked
    def preview_view(self)->dict[str,Any]:
        """Inspect logical scenario state and visible text/normal inputs, without glyphs/images/audio output."""
        self.require_preview();return self.preview_packet()

    @locked
    def preview_step(self,inputs:PreviewInput,expected_state_revision:Id|None=None)->dict[str,Any]:
        """Advance one VM boundary with normal inputs (including choices/virtual EOF); no branch/state repair."""
        self.check_state_revision(expected_state_revision);self.require_preview();values=inputs.model_dump(exclude_none=True);values['dt']=values.pop('dt_ms')
        self._runtime.call('step',**values);return self.preview_packet()

    @locked
    def preview_run(self,max_steps:Annotated[int,Field(ge=1,le=2000)]=200,
                    dt_ms:Annotated[int,Field(ge=0,le=1000)]=33,auto_advance:bool=True,
                    stop_at_command_id:Id|None=None,expected_state_revision:Id|None=None)->dict[str,Any]:
        """Bounded normal execution; stop at choices/gates/errors/end or before a target. Never auto-select or fake service completion."""
        self.check_state_revision(expected_state_revision);self.require_preview()
        if stop_at_command_id and stop_at_command_id not in self.locations():raise ValueError('Unknown target command ID')
        reason='step_budget';steps=0
        for _ in range(max_steps):
            v=self.preview_packet()
            if v['error']:reason='error';break
            if v['boundary']==7:reason='ended';break
            if v['choices']:reason='input';break
            if stop_at_command_id==v['command_id'] and v['boundary'] in {0,5,6}:reason='target';break
            if not auto_advance and v['text_waiting'] and v['text_ready']:reason='text';break
            self._runtime.call('step',dt=dt_ms,advance=auto_advance);steps+=1
        return dict(**self.preview_packet(),stop_reason=reason,steps=steps)

    @locked
    def preview_rewind(self,action_count:Index,expected_state_revision:Id|None=None)->dict[str,Any]:
        """Recover scenario state by replaying recorded actions to a prior count; never splice a cursor into unrelated state."""
        self.check_state_revision(expected_state_revision);self.require_preview()
        if action_count>len(self._runtime.actions):raise ValueError('Action count exceeds recorded route')
        self._runtime.call('rewind',count=action_count);return self.preview_packet()

    @locked
    def preview_debug(self,action:Literal['patch','force_choice','jump'],
                      edits:Annotated[list[BankEdit],Field(max_length=40)]|None=None,
                      choice:Index=0,child:Index=0,target_command_id:Id|None=None,expected_state_revision:Id|None=None)->dict[str,Any]:
        """Explicit sandbox intervention only: patch banks/gauges, force an authored branch, or splice a current-file cursor."""
        self.check_state_revision(expected_state_revision);self.require_preview()
        if action!='patch' and edits:raise ValueError('Bank edits apply only to the patch debug action')
        if action=='patch':
            if not edits:raise ValueError('Patch requires bank/gauge edits')
            self._runtime.call('patch',edits=[e.model_dump() for e in edits])
        elif action=='force_choice':self._runtime.call('choose',choice=choice,child=child)
        else:
            pc,_=self.command(self._runtime.sid,target_command_id);self._runtime.call('jump',target=pc)
        return self.preview_packet()
