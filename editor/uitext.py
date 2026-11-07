"""UI translation inventory, sparse validated deltas and effective asset bytes."""
from dataclasses import replace
import hashlib
from pathlib import Path
import re
import struct
from .archive import Archive
from .imageassets import stamp, unpack_member
from .uitextcodec import parsers,counted_spans,table_spans,rewrite,encode_span


def sha(data):return hashlib.sha256(data).hexdigest()

CATEGORIES=dict(env_help_mgr='Button help',env_global='Global UI / save descriptions',env_script='Chapter / ending',
    env_save_manager='Save messages',env_scene_title='Title',env_system_menu='System menu',env_dialog='Dialogs',
    env_saveload='Save / load',env_backlog='Backlog',env_option='Settings',env_omake='Extras',
    env_otaku_mode='Profiles',env_tukkomi='Battle',env_string_format='Text control syntax',env_first='Startup',
    env_debug='Debug UI',env_test='Test UI',env_keyword='Keyword labels')


class UiTextCatalog:
    def __init__(self,root):
        self.root=Path(root).resolve();self.sources={};self.nodes={};self.fields={};self.coverage=[];self.issues=[];self._raw={};self._members={}

    def verify(self):
        if any(stamp(self.root/name)!=v['stamp'] for name,v in self.sources.items()):raise ValueError('UI text source changed; reload/re-index before editing or exporting')

    def source(self,name):
        if name not in self._raw:
            path=self.root/name;before=stamp(path)
            if before[0]>512*1024*1024:raise ValueError('UI text source exceeds512MiB')
            data=path.read_bytes()
            if before!=stamp(path):raise ValueError('UI source changed while reading')
            self._raw[name]=data;self.sources[name]=dict(stamp=before,sha256=sha(data))
        self.verify();return self._raw[name]

    def read(self,name,route):
        route=tuple(route);key=(name,route)
        if key not in self._members:
            if not route:self._members[key]=(self.source(name),[])
            else:
                data,chain=self.read(name,route[:-1]);a=Archive(data);index=route[-1]
                child,_=unpack_member(a,index)
                self._members[key]=(bytes(child),chain+[dict(container='GPDA',index=index)])
        return self._members[key]

    def add(self,name,route,category,parser=None,table=None):
        data,chain=self.read(name,route);node_id=name+':'+('/'.join(map(str,route)))
        spans=counted_spans(data,parser) if parser else table_spans(data,*table)
        movie_names=set()
        if name.endswith('env_omake.dat'):
            movies=parser(data).movies
            for i in range(len(spans)-1):
                if [spans[i].text,spans[i+1].text] in movies:movie_names.add(i)
        # These are actual resource/control fields, distinct from displayed text.
        for i,span in enumerate(spans):
            protected='';role=span.role
            if name.endswith('env_string_format.dat'):protected='Text parser syntax / character maps, not a display string'
            if name.endswith('env_global.dat'):
                if i==0:protected='Save product identifier'
                elif 13<=i<len(spans)-3 or i>=len(spans)-2:protected='Input glyph, separator or line-breaking rules'
                elif i in (9,10,len(spans)-3):role='button choices'
            if name.endswith('env_first.dat') and i>0:protected='Optional-content product identifier / archive name'
            if name.endswith('env_debug.dat') and i==3:protected='Debug navigation glyph'
            if name.endswith('env_dialog.dat') and i==0:protected='Dialog line separator'
            if i in movie_names:protected='Movie resource name; translate its separate title field'
            text=span.text.split('\0',1)[0]
            if re.fullmatch(r'[\w./\\-]+\.(?:dat|mp4|usm|moc|mtn|gsf|ttc|gxt|awb|png|jpe?g|bmp|wav)',text,re.I):protected='Resource filename'
            spans[i]=replace(span,role=role,editable=not protected,reason=protected)
        node=dict(id=node_id,source=name,route=list(route),chain=chain,category=category,data=data,
            spans=spans,sha256=sha(data),parser=parser,table=table)
        self.nodes[node_id]=node
        from .fontstyle import ui_renderer,NOTES
        for i,span in enumerate(spans):
            identity=node_id+'#s'+str(i)
            renderer=ui_renderer(name,span.role,i,span.editable)
            self.fields[identity]=dict(field_id=identity,node_id=node_id,index=i,source=name,route=list(route),category=category,
                role=span.role,original=span.text.split('\0',1)[0],editable=span.editable,reason=span.reason,
                encoding=span.encoding,offset=span.start,bytes=span.end-span.start,
                renderer=renderer,font_guidance=NOTES.get(renderer,'Protected non-display syntax.'),
                format_tokens=re.findall(r'%(?:%|[^%\s]*?[diuoxXfFeEgGaAcCsSpn])|≪[^≫]*≫|[①-⑳]',span.text),
                guidance='Preserve format/control tokens. UI DrawString does not word-wrap automatically. Dialog/description authored breaks use ＿; preview the relevant screen.')
        self.coverage.append(dict(source=name,route=list(route),category=category,fields=len(spans),status='Parsed'))

    def summary(self):
        return dict(fields=len(self.fields),editable=sum(f['editable'] for f in self.fields.values()),coverage=self.coverage,issues=self.issues,
            renderer_counts={kind:sum(f['renderer']==kind for f in self.fields.values()) for kind in sorted({f['renderer'] for f in self.fields.values()})},
            notes=['Scenario opcode text remains in the script editor.',
                'Baked texture lettering uses PNG replacements; executable literals and personal-save text are not asset fields.',
                'Known source schemas are parsed; coverage is not a claim of every native screen being playtested.'])


def build_catalog(root):
    c=UiTextCatalog(root);registry=parsers()
    for path in sorted((c.root/'env').glob('*.dat')):
        name='env/'+path.name
        try:
            if path.stem in registry:c.add(name,(),CATEGORIES[path.stem],registry[path.stem])
            else:
                c.source(name);c.coverage.append(dict(source=name,route=[],category='Layout / runtime configuration',fields=0,status='No display-string reader in current source'))
        except (ValueError,IndexError,struct.error) as e:c.issues.append(dict(source=name,error=str(e)))
    for name in ('first.dat','resource.dat'):
        if not (c.root/name).is_file():continue
        try:
            if name=='first.dat':
                a=Archive(c.source(name))
                if len(a.entries)>3:
                    bank=Archive(c.read(name,(3,))[0])
                    for i in range(len(bank.entries)):c.add(name,(3,i),'Profile item names / descriptions',table=('utf-16-le','\t','profile_items'))
            else:
                a=Archive(c.source(name))
                if len(a.entries)>3:
                    scenes=Archive(c.read(name,(3,1))[0])
                    for i in range(len(scenes.entries)):c.add(name,(3,1,i),'Profile responses',table=('cp932',',','profile_responses'))
                if len(a.entries)>2:
                    c.add(name,(2,0,0,0),'CG gallery titles',table=('utf-16-le',',','cg_titles'))
        except (ValueError,IndexError,struct.error) as e:c.issues.append(dict(source=name,error=str(e)))
    c.verify();return c


def get_catalog(project):
    c=getattr(project,'_ui_text_catalog',None)
    if c is None or c.root!=Path(project.root).resolve():c=build_catalog(project.root);project._ui_text_catalog=c
    c.verify();return c


def make_record(c,identity,text):
    c.verify()
    if identity not in c.fields:raise ValueError('Unknown UI text field_id or changed source schema')
    f=c.fields[identity];n=c.nodes[f['node_id']];span=n['spans'][f['index']];encode_span(span,text)
    return dict(text=text,source_sha256=c.sources[f['source']]['sha256'],member_sha256=n['sha256'],
        offset=span.start,span_sha256=sha(n['data'][span.start:span.end]))


def validate_records(records,c):
    if not isinstance(records,dict) or len(records)>16384:raise ValueError('Invalid UI text replacement collection')
    c.verify()
    for identity,record in records.items():
        if not isinstance(record,dict) or set(record)!={'text','source_sha256','member_sha256','offset','span_sha256'}:raise ValueError('Invalid UI text replacement record')
        if record!=make_record(c,identity,record['text']):raise ValueError('UI text source fingerprint mismatch: '+identity)


def effective_node(c,node_id,records,data=None):
    n=c.nodes[node_id];edits={f['index']:records[key]['text'] for key,f in c.fields.items() if f['node_id']==node_id and key in records}
    if not edits:return n['data'] if data is None else data
    original=n['data']
    if data is not None and data!=original:raise ValueError('Overlapping UI text/other asset edit at '+node_id)
    result=rewrite(original,n['spans'],edits)
    # Read again by the consumer schema. Length changes must relocate subsequent
    # fields naturally, never by replacing equal byte strings across the file.
    spans=counted_spans(result,n['parser']) if n['parser'] else table_spans(result,*n['table'])
    if len(spans)!=len(n['spans']):raise ValueError('UI text edits changed the native field structure')
    for i,text in edits.items():
        if spans[i].text.split('\0',1)[0]!=text:raise ValueError('UI text rewrite did not roundtrip')
    if n['source'].endswith('env_otaku_mode.dat'):
        from .compositionmodes import profile_environment
        e=profile_environment(result);labels=e['labels'];pattern=e['format']
        for character in labels[0]:
            for index in range(min(len(labels[1]),len(labels[2]))):
                args=iter((character,labels[2][index],labels[1][index]))
                formatted=re.sub(r'%ls|%%',lambda m:'%' if m[0]=='%%' else next(args),pattern)
                if len(formatted.encode('utf-16-le'))>=256:raise ValueError('Combined profile result labels exceed the native128-unit result buffer; shorten the labels/format')
    return result


def prepare(records,root,catalog=None):
    if not records:return {},[],None
    c=catalog or build_catalog(root);validate_records(records,c);changes={};rows=[]
    nodes={c.fields[key]['node_id'] for key in records}
    for node_id in sorted(nodes):
        n=c.nodes[node_id];result=effective_node(c,node_id,records)
        if result!=n['data']:changes.setdefault(n['source'],[]).append((n['chain'],result))
    for key,record in records.items():
        f=c.fields[key];rows.append(dict(field_id=key,source=f['source'],route=f['route'],changed=record['text']!=f['original']))
    c.verify();return changes,rows,c
