"""Reviewable existing-text cleanup and atomic stable-ID dialogue pagination."""
from copy import copy,deepcopy
from dataclasses import replace
import re
import unicodedata
import uuid
from .engine import text_fields,TEXT_OPS
from .text import units,unicode_text,TIMED_BREAK_ERROR
from .textlayout import TextLayoutService,field_path,native_newlines,supports_breaks,reflow_breaks
from .scriptcodec import put
from .semantics import flow_index


def japanese_text(value,formatter,dialogue=False):
    """Simple script detection, not language identification; Han also covers Chinese."""
    if dialogue:
        try:plain=unicode_text(formatter.ordinary(value,geometry_only=True)['body'])
        except ValueError:plain=value
    else:plain=value
    # Reading annotations/controls and the speaker are not the translated body.
    op,cl=map(unicode_text,(formatter.tokens[0],formatter.tokens[1]))
    plain=re.sub(re.escape(op+unicode_text(formatter.following[9])+cl)+'.*?'+re.escape(unicode_text(formatter.following[10])),'',plain,flags=re.DOTALL|re.IGNORECASE)
    plain=re.sub(re.escape(op)+'.*?'+re.escape(cl),'',plain,flags=re.DOTALL)
    if dialogue:
        quote=plain.find(unicode_text(formatter.following[1]))
        if quote>=0:plain=plain[quote:]
    return any(0x3041<=ord(c)<=0x309f or 0x30a1<=ord(c)<=0x30ff or 0x31f0<=ord(c)<=0x31ff
               or 0xff66<=ord(c)<=0xff9f or 0x3400<=ord(c)<=0x4dbf or 0x4e00<=ord(c)<=0x9fff
               or 0xf900<=ord(c)<=0xfaff or 0x20000<=ord(c)<=0x323af or c in '々〆〇' for c in plain)


def dialogue_capacity(font,settings,mode):
    """Visible glyph rows inside authored frame and the960x544 stage."""
    size=int(font.utility*font.scale);leading=int(font.height*font.scale+font.leading)
    if leading<=0:raise ValueError('Invalid dialogue line advance')
    if mode=='ordinary':
        x,y,w,h=font.message_bounds;top=font.origin[1];bottom=min(544,y+h)
        if top<max(0,y):raise ValueError('Dialogue origin lies outside its frame')
    else:
        env=settings['battle'];bubble=env['bubble'];height=int(abs(env['bubble_scale'])*bubble['height'])
        anchor=bubble['alignment']//3
        offset=height//2 if anchor==1 else height if anchor==2 else 0
        spaces=[]
        for _,y in env['positions']:
            top=y+env['line_offsets'][0][1];bottom=min(544,y-offset+height)
            if top<max(0,y-offset):raise ValueError('Battle text origin lies outside its bubble')
            spaces.append(bottom-top)
        top=0;bottom=min(spaces)
    count=(bottom-top-size)//leading+1
    if count<1:raise ValueError('No complete text line fits the visible dialogue box')
    return count


def append_context_commands(project,sid):
    """Possible nonempty retained buffer at a message, using existing CFG edges."""
    script=project.scripts[sid];messages=[c for c in script.commands if c.opcode==0x64]
    if not any(c.args.get('completion') for c in messages):return set()
    if any(c.args.get('route') and c.args.get('completion') for c in messages):
        return {c.uid for c in messages}  # Timed lane execution can interleave.
    graph=flow_index(project.display(sid),profile_links=project.profile_links);out={}
    for edge in graph['edges']:
        if edge['script']==-2:out.setdefault(edge['source'],set()).add(edge['target'])
    work=[(0,False)];seen=set();before={}
    while work:
        index,retained=work.pop()
        if (index,retained) in seen or not 0<=index<len(script.commands):continue
        seen.add((index,retained));before.setdefault(index,set()).add(retained);c=script.commands[index]
        after=bool(c.args.get('completion')) if c.opcode==0x64 and not c.args.get('route') else retained
        work.extend((target,after) for target in out.get(index,()))
    return {c.uid for i,c in enumerate(script.commands) if c.opcode==0x64 and (i not in before or True in before[i])}


def split_pages(service,text,mode,width,max_lines,hyphenate):
    """Repeat the native speaker/quote form and balance keywords across pages."""
    f=service.font.format;source,body,pairs,_=service.projection(0x64,text);parsed=f.ordinary(source)
    if parsed['markers']:raise ValueError('Timed SP QUE text cannot be paginated automatically')
    opening=closing=prefix='';payload=source
    quote=f.following[1];end_quote=f.tokens[5][0]
    if body.startswith(quote) and body.endswith(end_quote):
        first,last=pairs[0][1],pairs[-1][1]
        prefix=source[:first];opening=source[first:pairs[0][2]];closing=source[last:pairs[-1][2]]
        if source[pairs[-1][2]:]:raise ValueError('Trailing speaker controls require manual pagination')
        payload=source[pairs[0][2]:last]
    elif parsed['name'] or body.startswith(quote):raise ValueError('Unbalanced/aside speaker quotation requires manual pagination')
    # Reserve both repeated quote glyphs while packing pages. This is conservative
    # on interior lines and prevents adding a closing quote from overflowing one.
    allowance=sum(max(int(service.font.measure(c,service.font.utility)*service.font.scale),
                      int(service.font.measure(f.tokens[4][1] if c==f.tokens[4][0] else c,service.font.utility)*service.font.scale))
                  for c in units(opening+closing))
    wrapped=service.wrap(0x64,source,width=width-allowance,dialogue_mode=mode,hyphenate=hyphenate)
    source=wrapped['text']
    if opening:
        _,_,mapped,_=service.projection(0x64,source);payload=source[mapped[0][2]:mapped[-1][1]]
    else:payload=source
    op,cl=f.tokens[0][0],f.tokens[1][0];stack=[];pages=[];current='';line=1;i=0
    while i<len(payload):
        c=payload[i]
        if c==op:
            end=payload.find(cl,i+1)
            if end<0:raise ValueError('Unterminated inline control')
            token=payload[i:end+1];tag=units(payload[i+1:end]).upper()
            if tag==f.following[8]:stack.append(('ruby',token,unicode_text(f.following[10])))
            elif tag==f.following[9]:pass
            elif units(token).upper()==f.following[10]:
                if not stack or stack[-1][0]!='ruby':raise ValueError('Unbalanced ruby range')
                stack.pop()
            elif tag.startswith(f.following[11]+' '):stack.append(('keyword',token,op+unicode_text(f.following[12])+cl))
            elif tag==f.following[12]:
                if not stack or stack[-1][0]!='keyword':raise ValueError('Unbalanced keyword range')
                stack.pop()
            else:raise ValueError('Inline control cannot be divided across dialogue pages')
            current+=token;i=end+1;continue
        if c==f.break_char:
            if any(s[0]=='ruby' for s in stack):raise ValueError('Ruby with an explicit internal break needs manual pagination')
            if line==max_lines:
                pages.append(prefix+opening+current+''.join(s[2] for s in reversed(stack))+closing)
                current=''.join(s[1] for s in stack);line=1
            else:current+=c;line+=1
        else:current+=c
        i+=1
    if stack:raise ValueError('Unclosed inline control')
    if current or not pages:pages.append(prefix+opening+current+closing)
    verified=[]
    for page in pages:
        packet=service.wrap(0x64,page,width=width,dialogue_mode=mode,hyphenate=hyphenate)
        if packet['line_count']>max_lines:raise ValueError('Repeated speaker/controls exceed page capacity')
        if f.ordinary(packet['text'])['name']!=parsed['name']:raise ValueError('Pagination would change the parsed speaker')
        verified.append(packet)
    return verified


def analyze_cleanup(project,font,settings,*,script_ids=None,command_ids=None,skip_japanese=True,
                    hyphenate=True,paginate=True,max_lines=None,width=None,label_width=None,dialogue_mode='auto',full_width_latin=False,proportional_latin=False,reflow=False):
    if dialogue_mode not in {'auto','ordinary','battle'}:raise ValueError('Invalid dialogue layout mode')
    for value in (width,label_width):
        if value is not None and (isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=4096):raise ValueError('Width must be1–4096px')
    if max_lines is not None and (isinstance(max_lines,bool) or not isinstance(max_lines,int) or not 1<=max_lines<=20):raise ValueError('Page lines must be1–20')
    sids=sorted(project.scripts) if script_ids is None else sorted(set(script_ids));wanted=None if command_ids is None else set(command_ids)
    if any(sid not in project.scripts for sid in sids):raise ValueError('Unknown script ID')
    if wanted is not None and wanted-set(project.locations()):raise ValueError('Unknown command ID')
    plan=dict(plan_id=uuid.uuid4().hex,revision=project.revision,changes=[],issues=[],scanned=0,eligible=0)
    from .fontpatch import make_asset,effective_font,GENERATOR_REVISION
    font=effective_font(project,font)
    asset=project.font_asset
    if proportional_latin and (asset is None or asset['manifest'].get('generator_revision',1)<GENERATOR_REVISION):asset=make_asset(project.root)
    plan['font_changed']=asset!=project.font_asset
    if asset:
        font=effective_font(type('FontProject',(),dict(root=project.root,font_asset=asset))(),font)
        plan['font_asset']=asset
    from .textregions import BattleTextRegions
    regions=BattleTextRegions(project,font,settings)
    for sid in sids:
        script=project.scripts[sid]
        retained_context=append_context_commands(project,sid)
        for c in script.commands:
            if c.opcode not in TEXT_OPS or wanted is not None and c.uid not in wanted:continue
            service=TextLayoutService(font,settings,project=project,script_id=sid,command=c,regions=regions)
            mode=service.resolve_mode(dialogue_mode)
            convert_width=full_width_latin or bool(asset and supports_breaks(c.opcode))
            plan['scanned']+=1
            fields=[(key,value) for key,value in text_fields(dict(opcode=c.opcode,args=c.args)) if value and (not skip_japanese or not japanese_text(value,font.format,c.opcode==0x64))]
            if not fields:continue
            plan['eligible']+=1
            try:
                unsafe=[];conversion_packet=None;timed=False
                if c.opcode==0x64:
                    parsed_geometry=font.format.ordinary(c.args['text'],geometry_only=True)
                    timed=bool(parsed_geometry['markers'])
                    if c.args['selector']:unsafe.append('Inherited/selector dialogue')
                    if c.uid in retained_context:unsafe.append('Previous message may retain appended text')
                    if unsafe:
                        if convert_width:
                            conversion_packet=service.convert_dialogue_width(c.args['text'],width=width,dialogue_mode=mode,preserve_speaker=bool(asset))
                        geometry=deepcopy(conversion_packet) if conversion_packet else service.measure_dialogue(c.args['text'],width=width,dialogue_mode=mode)
                        capacity=(geometry.get('region') or {}).get('capacity') or dialogue_capacity(font,settings,mode)
                        if max_lines is not None:capacity=min(capacity,max_lines)
                        standalone_fits=geometry['line_count']<=capacity and max(geometry['line_widths'],default=0)<=geometry['width'] and not geometry['ruby_overflow']
                        context_required=bool(c.args['selector'] or c.uid in retained_context)
                        geometry.update(capacity=capacity,standalone_fits=standalone_fits,fits=None if context_required else standalone_fits,
                                        context_required=context_required,auto_edit=bool(conversion_packet and conversion_packet['changed']))
                        reason=', '.join(unsafe)+': text measured; automatic wrapping/pagination remains disabled.'
                        if conversion_packet:reason+=' Full-width conversion only; control tags, timing, glyph counts and existing breaks preserved.'
                        if parsed_geometry['markers'] and font.format.break_char in parsed_geometry['body']:reason+=' '+TIMED_BREAK_ERROR
                        if context_required:reason+=' Combined appended/inherited display also needs preceding route/buffer state.'
                        if geometry['contains_plain_newlines']:reason+=' LF/CR are not native line breaks in the existing script.'
                        plan['issues'].append(dict(script_id=sid,command_id=c.uid,reason=reason,measurement=geometry))
                        if not conversion_packet or not conversion_packet['changed']:continue
                    else:
                        source=native_newlines(c.args['text'],font.format)
                        parsed=font.format.ordinary(reflow_breaks(source,font.format) if reflow else source)
                args=deepcopy(c.args);details=[]
                for key,value in fields:
                    if c.opcode==0x3f2 and field_path(key)[1]==0:continue  # Timeout text has no rendered control.
                    try:
                        packet=conversion_packet or service.wrap(c.opcode,value,field=key,width=width if supports_breaks(c.opcode) else label_width,dialogue_mode=mode,hyphenate=hyphenate,full_width_latin=convert_width,preserve_speaker=bool(asset),reflow=reflow)
                    except (ValueError,KeyError,IndexError,OverflowError) as error:
                        plan['issues'].append(dict(script_id=sid,command_id=c.uid,field=key,reason=str(error)));continue
                    put(args,field_path(key),packet['text']);details.append(dict(field=key,**packet))
                if not details:continue
                pages=[args];capacity=None;warnings=[]
                if asset:warnings.append('Asset-only proportional dialogue font: Font.gsf is saved/exported with this project. Existing Japanese glyphs are retained; ASCII word spaces become shorter globally. Speaker/simple UI strings still use fixed cursor spacing.')
                if convert_width:
                    conversions=[p['full_width_conversion'] for p in details]
                    count=sum(p['converted_characters'] for p in conversions)
                    kept=''.join(sorted(set(''.join(p['preserved_ascii'] for p in conversions))))
                    warnings.append(f'Full-width Latin: {count} display characters converted before fitting; ordinary spaces and controls unchanged.'
                                    +(f' Preserved ASCII with no safe full-width replacement: {kept!r}.' if kept else ''))
                if c.opcode in {0x3f2,0x3f8}:
                    warnings.append('Choice/result bounds checked. Branch opcodes are not paginated.')
                if c.opcode==0x64:
                    capacity=(details[0].get('region') or {}).get('capacity') or dialogue_capacity(font,settings,mode)
                    if max_lines is not None:capacity=min(capacity,max_lines)
                    if unsafe:warnings.append('Conversion only. '+reason)
                    if timed and not unsafe and details[0]['line_count']>capacity and not details[0].get('wrapping_skipped'):
                        packet=service.convert_dialogue_width(c.args['text'],width=width,dialogue_mode=mode,preserve_speaker=bool(asset),convert=convert_width)
                        packet['fit_warning']=f'Timed text needs {details[0]["line_count"]} lines; this box fits {capacity}. Shorten it to fit one message.'
                        details=[dict(field='text',**packet)];args['text']=packet['text'];pages=[args]
                    if details[0].get('fit_warning'):
                        measurement=deepcopy(details[0]);standalone=measurement['line_count']<=capacity and max(measurement['line_widths'],default=0)<=measurement['width'] and not measurement.get('ruby_overflow')
                        measurement.update(capacity=capacity,standalone_fits=standalone,fits=standalone,context_required=False,auto_edit=args!=c.args)
                        reason='Timed SP QUE dialogue: '+details[0]['fit_warning']+' Conversion only; review the measured text.'
                        plan['issues'].append(dict(script_id=sid,command_id=c.uid,reason=reason,measurement=measurement));warnings.append(reason)
                    if not unsafe and not details[0].get('wrapping_skipped') and details[0]['line_count']>capacity:
                        if timed or c.args['route'] or c.args['completion']:
                            raise ValueError(f'Text needs {details[0]["line_count"]} lines; this box fits {capacity}. Timed/queued/append dialogue cannot be paginated safely; shorten it.')
                        if not paginate:raise ValueError(f"Dialogue needs {details[0]['line_count']} lines; box fits {capacity}. Enable pagination.")
                        packets=split_pages(service,args['text'],mode,details[0]['width'],capacity,hyphenate);pages=[]
                        for i,packet in enumerate(packets):
                            page=deepcopy(args);page['text']=packet['text']
                            if i:page['voice']=-1
                            pages.append(page)
                        details=packets
                        if args['voice']>=0:warnings.append('Voice stays on page1; continuation pages are silent. Original audio is not split.')
                        if parsed['keywords']:warnings.append('Keyword flags publish as their new pages complete; pagination adds advance/backlog boundaries.')
                    if timed and details[0].get('break_strategy')=='spaces':
                        warnings.append('Timed text uses spaces to trigger native wrapping. Queue tags/times are preserved; cue character indices follow the inserted spaces.')
                if len(pages)>1 or args!=c.args:
                    plan['changes'].append(dict(script_id=sid,command_id=c.uid,opcode=c.opcode,before_texts=dict(text_fields(dict(opcode=c.opcode,args=c.args))),
                        after_texts=[dict(text_fields(dict(opcode=c.opcode,args=p))) for p in pages],pages=pages,details=details,
                        page_count=len(pages),capacity=capacity,dialogue_mode=mode,warnings=warnings))
            except (ValueError,KeyError,IndexError,OverflowError) as error:
                plan['issues'].append(dict(script_id=sid,command_id=c.uid,reason=str(error)))
    plan['summary']=dict(scanned=plan['scanned'],eligible=plan['eligible'],changed_commands=len(plan['changes']),
                         inserted_commands=sum(c['page_count']-1 for c in plan['changes']),reported=len(plan['issues']))
    return plan


def public_plan(plan,start=0,limit=30):
    result=deepcopy({**{k:v for k,v in plan.items() if k!='font_asset'},'changes':[{k:v for k,v in c.items() if k!='pages'} for c in plan['changes'][start:start+limit]],
        'issues':plan['issues'][start:start+limit],
        'next_start':start+limit if start+limit<max(len(plan['changes']),len(plan['issues'])) else None})
    if plan.get('font_asset'):result['font_asset']={k:v for k,v in plan['font_asset']['manifest'].items() if k!='glyphs'}
    return result


def apply_cleanup(project,plan,command_ids=None):
    if project.revision!=plan['revision']:raise ValueError('Stale cleanup plan; analyze the current project again. Nothing applied.')
    changes={c['command_id']:c for c in plan['changes']}
    wanted=set(changes) if command_ids is None else set(command_ids)
    if wanted-set(changes):raise ValueError('Selected command is not in this cleanup plan')
    font_changed=plan.get('font_asset',project.font_asset)!=project.font_asset
    if not wanted and not font_changed:return dict(revision=project.revision,changes=[],inserted_commands=0,font_changed=False)
    from .document import Command
    candidate=copy(project);candidate.scripts=project.scripts.copy();candidate.preview_issues=[]
    candidate.font_asset=plan.get('font_asset',project.font_asset)
    affected={changes[uid]['script_id'] for uid in wanted};result=[];inserted=0
    for sid in affected:
        rows=[]
        for old in project.scripts[sid].commands:
            change=changes.get(old.uid) if old.uid in wanted else None
            if change is None:rows.append(old);continue
            new_ids=[]
            for i,args in enumerate(change['pages']):
                uid=old.uid if i==0 else 'new:'+uuid.uuid4().hex
                rows.append(Command(uid,old.opcode,deepcopy(args),old.raw if i==0 else '',old.post if i==0 else 0,old.original_index if i==0 else None,True))
                if i:new_ids.append(uid);inserted+=1
            result.append(dict(script_id=sid,command_id=old.uid,inserted_ids=new_ids))
        candidate.scripts[sid]=replace(project.scripts[sid],commands=rows)
    issues=candidate.validate()
    if issues:raise ValueError(f'Cleanup rejected without changes: file{issues[0].script}/{issues[0].command}: {issues[0].message}')
    before=project.scripts.copy();before_font=project.font_asset;project.scripts=candidate.scripts;project.font_asset=candidate.font_asset
    project.remember(('Auto-fit translated text',before,project.scripts.copy(),before_font,project.font_asset));project.redo_stack=[]
    project.touched.update(affected);project.preview_issues=[];project.revision=uuid.uuid4().hex
    return dict(revision=project.revision,changes=result,inserted_commands=inserted,valid=True,font_changed=font_changed)
