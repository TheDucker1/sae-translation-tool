"""Read-only translator projection of shared static flow; never a second VM."""
from collections import Counter
from .engine import NAMES,TEXT_OPS,text_fields
from .flowmodel import clean_text
from .text import unicode_text

STATE={0,1,0x2be,0x2bf,0x2c0,0x3ea,0x3ed,0x3ee,0x3ef,0x3f4,0x3f5,0x3f7,0x3fa,0x3fc,0x640}
AUDIO={0x258,0x259,0x25a,0x25b,0x2c6}
ACTORS=set(range(0x1f4,0x1fc))|{0x201,0x202,0x204,0x438}
SCENE={0xc8,0xc9,0xca,0xcb,0xce,0x190,0x191,0x1c3,0x1c4,0x3fd,0x400}
WINDOW={0x66,0x12c,0x12d,0x12e}
# Movies are logical completion/input gates even though they contain no text.
IMPORTANT=TEXT_OPS|STATE|{0x2c2}
QUIET=AUDIO|ACTORS|SCENE|WINDOW


def readable(value,opcode,formatter=None):
    if formatter is None:return dict(text=clean_text(value),speaker=None,display_policy='markup-stripped fallback; no format environment')
    try:
        if opcode==0x64:
            parsed=formatter.ordinary(value)
            text,_=formatter.prepare(parsed['body'],unit_text=True)
            return dict(text=unicode_text(text).replace(unicode_text(formatter.break_char),'\n'),
                        speaker=unicode_text(parsed['name']) or None)
        text,_=formatter.prepare(value,font_tags=opcode in {0x3f2,0x3f8})
        return dict(text=unicode_text(text).replace(unicode_text(formatter.break_char),'\n'),speaker=None)
    except (ValueError,UnicodeError) as error:
        return dict(text=value,speaker=None,display_error=str(error))


def text_lines(command,formatter=None):
    """Readable text and authored roles/ordinals; raw text remains elsewhere."""
    op,a=command.opcode,command.args;rows=[]
    for field,value in text_fields(dict(opcode=op,args=a)):
        row=dict(field=field,**readable(value,op,formatter))
        if op==0x64:row.update(role='dialogue',speaker_id=a['speaker'],has_voice=a['voice']>=0)
        elif op in {0x65,0x3f2}:
            i=int(field.split('[')[1].split(']')[0]);row.update(role='timeout' if op==0x3f2 and i==0 else 'choice',ordinal=i,target=a['choices'][i]['target'])
        elif op==0x3f6:
            parent=int(field.split('[')[1].split(']')[0]);row.update(parent=parent,condition=a['parents'][parent]['condition'])
            if '.children[' in field:
                child=int(field.split('children[')[1].split(']')[0]);row.update(role='approach_choice',child=child,used_flag=parent*3+child,target=a['parents'][parent]['children'][child]['target'])
            else:row['role']='approach_topic'
        elif op==0x3f8:
            i=int(field.split('[')[1].split(']')[0]);row.update(role='success' if i==0 else 'failure',target=a['outcomes'][i]['target'],required_gauge=a['required_gauge'])
        elif op==0x3ec:row['role']='title' if field=='texts[0]' else 'subtitle'
        elif op==0x3f9:row['role']='battle_caption_0' if field=='texts[0]' else 'battle_caption_1'
        rows.append(row)
    return rows


def state_summary(command):
    op,a=command.opcode,command.args
    if op==0:
        bank='L' if a['bank']==0 else 'G';operand=(('L' if a['operand_kind']==0 else 'G')+f"[{a['operand']}]" if a['operand_kind']<2 else str(a['operand']))
        return f"{bank}[{a['index']}] {['=','+=','-='][min(a['operation'],2)]} {operand}"
    if op==1:return 'Condition: '+a['condition']
    if op==0x2be:return 'Jump'
    if op==0x2bf:return 'End scenario' if a['script']<0 else f"Continue in script {a['script']}"
    if op==0x2c0:return f"Wait {a['duration']} ms; honor_skip={a['honor_skip']}"
    if op==0x2c2:return f"Movie cue {a['movie']}; completion gate, allow_skip={a['allow_skip']}"
    if op==0x3ea:return f"Date {a['month']}/{a['day']}; visible={bool(a['enabled'])}"
    if op==0x3ed:return f"Profile scene {a['id']}; authored choice/stat handoff"
    if op==0x3ee:return f"Enter approach mode {a['id']}"
    if op==0x3ef:return f"Enter battle; sides {a['side0_group']}/{a['side1_group']}, gauge {a['gauge']}"
    if op==0x3f4:return f"Battle gauge command: character {a['character']}, delta {a['delta']}"
    if op==0x3f5:return f"Approach gauge delta {a['delta']}"
    if op==0x3f7:return f"Mission cue {a['mission']}; confirmation gate"
    if op==0x3fa:return 'Battle result routes from the current gauge'
    if op==0x3fc:return 'Clear approach used-choice flags'
    if op==0x640:return f"Trophy request {a['trophy']}"
    return NAMES.get(op,f'{op:04X}')


def cue_kind(op):
    return 'audio' if op in AUDIO else 'character/model' if op in ACTORS else 'image/effect' if op in SCENE else 'text window'


def project_flow(commands,flow,formatter=None):
    """Group presentation only. Every state command and nonsequential target stays visible."""
    leaders={0}
    for e in flow['edges']:
        if e['script']==-2 and e['target']!=e['source']+1:leaders.add(e['target'])
    groups=[];pending=[]
    def flush():
        if pending:groups.append(tuple(pending));pending.clear()
    for i,c in enumerate(commands):
        important=c.opcode in IMPORTANT or c.opcode not in QUIET
        if important or i in leaders:flush()
        pending.append(i)
        if important:flush()
    flush();membership={i:g[0] for g in groups for i in g};cards=[]
    for group in groups:
        first=commands[group[0]];card=dict(command_id=first.uid,index=group[0],last_index=group[-1],
            last_command_id=commands[group[-1]].uid,command_count=len(group),outgoing=[],incoming=[])
        if first.opcode in TEXT_OPS:
            card.update(kind='dialogue' if first.opcode==0x64 else 'text_choice' if first.opcode in {0x65,0x3f2,0x3f6,0x3f8} else 'caption',
                        opcode=first.opcode,name=NAMES.get(first.opcode),lines=text_lines(first,formatter))
            if first.opcode==0x3f2:card['timeout_ms']=first.args['duration']
        elif first.opcode in QUIET:
            selected=[commands[i] for i in group];kinds=Counter(cue_kind(c.opcode) for c in selected)
            card.update(kind='presentation_cues',summary=', '.join(f'{n} {kind}' for kind,n in kinds.items()),
                opcodes={f'{op:04X}':n for op,n in Counter(c.opcode for c in selected).items()},
                character_ids=sorted({c.args['character'] for c in selected if isinstance(c.args.get('character'),int) and c.args['character']>=0}),
                queued_lanes=sorted({c.args['lane'] for c in selected if c.args.get('route') and 'lane' in c.args}),
                timed_commands=sum(bool(c.args.get('duration',0)) for c in selected),
                detail_request=dict(tool='list_commands',arguments=dict(start=group[0],limit=min(100,len(group)),text_only=False)))
        else:card.update(kind='condition' if first.opcode==1 else 'flow_state',opcode=first.opcode,name=NAMES.get(first.opcode),summary=state_summary(first))
        cards.append(card)
    by_start={c['index']:c for c in cards};seen=set()
    for e in flow['edges']:
        source=membership[e['source']];target=membership[e['target']] if e['script']==-2 else None
        if source==target and e['target']==e['source']+1:continue
        identity=(source,target,e['script'],e['label'])
        if identity in seen:continue
        seen.add(identity)
        link=dict(label=e['label'],source_id=commands[source].uid,source_command_id=commands[e['source']].uid,
            target_id=commands[target].uid if target is not None else None,
            target_command_index=e['target'],target_script=e['script'])
        by_start[source]['outgoing'].append(link)
        if target is not None:by_start[target]['incoming'].append(link)
    return cards


def destination(link):
    if link['target_script']==-2:return link['target_id']
    if link['target_script']>=0:return f"script {link['target_script']} / #{link['target_command_index']}"
    return 'unresolved handoff' if link['target_script']==-3 else 'END'


def transcript(cards):
    lines=[]
    for card in cards:
        lines.append(f"#{card['index']} [{card['command_id']}] "+card['kind'])
        if card.get('summary'):lines.append('  '+card['summary'])
        for row in card.get('lines',[]):
            who=row.get('speaker') or ('Unlabelled' if row['role']=='dialogue' else row['role'])
            label=f"{row['field']} · {who}"
            if 'condition' in row:label+=' · when '+row['condition']
            target=row.get('target');suffix=' → '+target['$ref'] if isinstance(target,dict) and '$ref' in target else ''
            lines.append('  '+label+': '+row['text']+suffix)
        for edge in card['outgoing']:
            # Choice labels already appear next to their targets; conditions,
            # jumps/merges and ordinary next links keep the graph explicit.
            lines.append('  → '+destination(edge)+' ['+clean_text(edge['label'])+']')
    return '\n'.join(lines)
