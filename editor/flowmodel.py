"""Translation-focused graph projection. No execution/state inference here."""
from dataclasses import dataclass, field
from collections import Counter, deque
import re
from .engine import NAMES, TEXT_OPS, BRANCHES, text_fields


def clean_text(text):
    # Display only. Copy/inspector always use original strings, including markup.
    for left,right in [('《','》'),('〈','〉'),('<','>')]:
        pattern=re.escape(left+'RUBY'+right)+r'(.*?)'+re.escape(left+'RT'+right)+r'.*?'+re.escape(left+'/RUBY'+right)
        text=re.sub(pattern,r'\1',text,flags=re.DOTALL|re.IGNORECASE)
    return re.sub(r'[〈《][^〉》]*[〉》]|<[^>]*>', '', text.replace('\x00','')).replace('\n',' ')


@dataclass
class Card:
    key: str
    title: str
    body: str
    kind: str
    commands: tuple = ()
    script: int | None = None
    tooltip: str = ''
    detached: bool = False


@dataclass
class Link:
    source: str
    target: str
    label: str = ''


@dataclass
class Diagram:
    cards: dict = field(default_factory=dict)
    links: list = field(default_factory=list)
    command_cards: dict = field(default_factory=dict)


CONTROL = BRANCHES | {0x2BE, 0x2BF, 0x3ED}
EFFECTS = {0xC8,0xC9,0xCA,0xCB,0x190,0x191,0x1C3,0x1C4,0x3FD,0x400}


def script_diagram(script, commands, analysis, details=False):
    diagram=Diagram(); groups=[]; current=[]
    # Preserve every nonsequential target and reference boundary as a leader.
    leaders={0}
    for edge in analysis.edges:
        if edge.script is None and edge.target!=edge.source+1:leaders.add(edge.target)
        if edge.label not in {'next','fallthrough'}:leaders.add(edge.source)
    for ref in analysis.references:
        if ref.script is None and ref.label!='fallthrough':leaders.add(ref.target)
    def flush():
        if current:groups.append(tuple(current));current.clear()
    for c in commands:
        i=c['index']; important=c['opcode'] in TEXT_OPS|CONTROL
        if important or i in leaders or details:flush()
        current.append(i)
        if important or details:flush()
    flush()
    for members in groups:
        first=commands[members[0]]; op=first['opcode']; key=f'c{members[0]}'
        fields=text_fields(first)
        if fields:
            kind='choice' if op in {0x65,0x3F2,0x3F6,0x3F8} else 'text'
            title=f"#{members[0]}  {NAMES.get(op) or 'Text'}"
            body='\n'.join(f'{path}: {clean_text(value)}' for path,value in fields)
            tooltip='\n\n'.join(f'{path}\n{value}' for path,value in fields)
        elif op in CONTROL:
            kind='branch'; title=f"#{members[0]}  {NAMES.get(op) or 'Control'}"
            body=first['args'].get('condition') or str(first['args']);tooltip=body
        else:
            kind='quiet';title=f"#{members[0]}"+(f"–{members[-1]}" if len(members)>1 else '')+f'  ·  {len(members)} setup / presentation'
            effects=[NAMES.get(commands[i]['opcode']) or hex(commands[i]['opcode']) for i in members if commands[i]['opcode'] in EFFECTS]
            body=('Effects: '+', '.join(dict.fromkeys(effects))) if effects else 'State / characters / audio (collapsed)'
            tooltip='\n'.join(f"#{i} {NAMES.get(commands[i]['opcode']) or hex(commands[i]['opcode'])}" for i in members)
            if details:body=str(first['args'])
        diagram.cards[key]=Card(key,title,body,kind,members,script,tooltip,not any(i in analysis.entry_possible for i in members))
        for i in members:diagram.command_cards[i]=key
    seen=set()
    for e in analysis.edges:
        source=diagram.command_cards[e.source]
        if e.script is None:
            if e.target not in diagram.command_cards:continue
            target=diagram.command_cards[e.target]
        else:
            target=f'file{e.script}'
            label='Unresolved profile handoff' if e.script==-3 else 'End' if e.script<0 else f'File {e.script:03}'
            diagram.cards.setdefault(target,Card(target,label,'Double-click to open file' if e.script>=0 else 'Destination outside this static script graph','file',(),e.script))
        identity=source,target,e.label
        if source==target and e.target==e.source+1:continue
        if identity not in seen:diagram.links.append(Link(*identity));seen.add(identity)
    return diagram


def file_diagram(scripts, selected=None, neighbors=True):
    diagram=Diagram(); known={s['id']:s for s in scripts}; keep=set(known)
    if neighbors and selected is not None:
        keep={selected}
        for s in scripts:
            for link in s.get('links',[]):
                if s['id']==selected and link['target'] in known:keep.add(link['target'])
                if link['target']==selected:keep.add(s['id'])
    for sid in sorted(keep):
        s=known[sid]; count=sum(int(n) for op,n in s['opcodes'].items() if int(op) in TEXT_OPS)
        key=f'f{sid}';diagram.cards[key]=Card(key,f"{sid:03}  {s['name'].strip(chr(0))}",f"{count} text commands · {s['count']} total",'file',(),sid)
    for sid in sorted(keep):
        for link in known[sid].get('links',[]):
            target=link['target']
            if target in keep:key=f'f{target}'
            elif target is None or target<0:
                key=f"terminal{sid}_{link['command']}";title='Profile: unresolved destination' if target is None else 'End'
                diagram.cards[key]=Card(key,title,f"from #{link['command']}",'branch')
            elif target not in known:
                key=f'missing{target}';diagram.cards[key]=Card(key,f'Missing file {target}','Unresolved reference','branch')
            else:continue
            diagram.links.append(Link(f'f{sid}',key,f"#{link['command']} {link['kind']}"))
    return diagram


def layered_positions(diagram):
    """Iterative SCC condensation + DAG ranks; loops never recurse or disappear."""
    keys=list(diagram.cards); outgoing={k:[] for k in keys}; incoming={k:[] for k in keys}
    for e in diagram.links:outgoing[e.source].append(e.target);incoming[e.target].append(e.source)
    visited=set(); order=[]
    for root in keys:
        if root in visited:continue
        work=[(root,False)]
        while work:
            node,done=work.pop()
            if done:order.append(node);continue
            if node in visited:continue
            visited.add(node);work.append((node,True));work.extend((n,False) for n in reversed(outgoing[node]) if n not in visited)
    component={}; groups=[]
    for root in reversed(order):
        if root in component:continue
        cid=len(groups); members=[];work=[root];component[root]=cid
        while work:
            node=work.pop();members.append(node)
            for other in incoming[node]:
                if other not in component:component[other]=cid;work.append(other)
        groups.append(members)
    adj={i:set() for i in range(len(groups))};degree=Counter()
    for e in diagram.links:
        a,b=component[e.source],component[e.target]
        if a!=b and b not in adj[a]:adj[a].add(b);degree[b]+=1
    key_order={key:i for i,key in enumerate(keys)}
    local_depth={};height={}
    for cid,members in enumerate(groups):
        roots=[k for k in members if any(component[p]!=cid for p in incoming[k])]
        if not roots:roots=[min(members,key=key_order.get)]
        queue=deque(sorted(roots,key=key_order.get))
        for key in queue:local_depth[key]=0
        while queue:
            key=queue.popleft()
            for child in outgoing[key]:
                if component[child]==cid and child not in local_depth:local_depth[child]=local_depth[key]+1;queue.append(child)
        height[cid]=max(local_depth[k] for k in members)+1
    rank={i:0 for i in adj};queue=deque(i for i in adj if not degree[i])
    while queue:
        i=queue.popleft()
        for j in sorted(adj[i]):
            rank[j]=max(rank[j],rank[i]+height[i]);degree[j]-=1
            if not degree[j]:queue.append(j)
    rows={}
    for i,group in enumerate(groups):
        for key in sorted(group,key=key_order.get):rows.setdefault(rank[i]+local_depth[key],[]).append(key)
    # Barycentric ordering reduces crossings without an external layout package.
    horizontal={key:idx for row in rows.values() for idx,key in enumerate(row)}
    for _ in range(4):
        for r,row in sorted(rows.items()):
            row.sort(key=lambda k:sum(horizontal[n] for n in incoming[k])/len(incoming[k]) if incoming[k] else horizontal[k])
            for idx,key in enumerate(row):horizontal[key]=idx
    return {key:((idx-(len(row)-1)/2)*420,r*240) for r,row in rows.items() for idx,key in enumerate(row)}
