"""Python editor session: original-file import, preview and deterministic replay.

This is an editor runtime, not a game executable. Accepted C++ source is a
reference only. Commands retain progression/state with logical media/resource
hosts. Presentation is reduced; Qt rasterizes the original font.
"""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import threading
from .archive import Archive, describe
from .semantics import condition, numeric, dispatch, flow_index, signed16
from .text import TextPresentation, unicode_text
from . import environments
from . import presentation
from . import progression,profileflow


def checked_index(value, count):
    if not isinstance(value,int) or not 0<=value<count:raise ValueError('Index outside supported range')
    return value


class Session:
    """Synchronous Python API, serialized while the GUI imports in a worker."""
    def __init__(self):
        self.lock=threading.RLock();self.original={};self.descriptions={};self.revision='original'

    def call(self, op, **args):
        with self.lock:
            try:return deepcopy(self._call(op,**args))
            except (ValueError,IndexError,KeyError,OSError) as error:raise RuntimeError(str(error)) from error

    def _call(self,op,**a):
        if op=='open':return self.open(a['path'])
        if not self.original:raise ValueError('Open a game folder first')
        if op=='project':return dict(scripts=[dict(id=sid,**self.describe(sid)) for sid in self.original],revision=self.revision,profile_links=self.profile_targets())
        if op=='script':
            result=dict(self.describe(a['id']));result['flow']=flow_index(result['commands'],profile_links=self.profile_targets());return result
        if op=='view':return self.view()
        if op=='glyph':return self.text.glyph(a['code'])
        if op=='route':return dict(entry=self.entry,actions=self.actions,visits=self.visits,revision=self.revision)
        if op=='reset':self.reset(a['script']);return self.view()
        if op=='evaluate':
            banks=deepcopy(self.banks);self.patch_banks(banks,a.get('edits',[]))
            return dict(value=condition(self.command()['args']['condition'],banks))
        if op=='revision':return self.apply_revision(**a)
        if op in {'restore','rewind'}:
            if a.get('revision',self.revision)!=self.revision:raise ValueError('Route belongs to a different script revision')
            actions=a.get('actions',self.actions);count=a.get('count',len(actions))
            if not 0<=count<=len(actions):raise ValueError('Replay count outside route')
            candidate=self.candidate();candidate.reset(a.get('entry',self.entry))
            for action in actions[:count]:
                candidate.action(action)
                if candidate.error:raise ValueError('Replay failed: '+candidate.error)
            expected=a.get('expected',{});view=candidate.view()
            for key,value in expected.items():
                if key=='phase':
                    if ('after' if view['boundary']==4 else 'before' if view['boundary'] in {0,5,6} else 'in_progress')!=value:
                        raise ValueError('Replay did not reach requested position phase')
                elif view.get(key)!=value:raise ValueError('Replay did not reach requested position '+key)
            self.adopt(candidate);return view
        if op in {'step','jump','choose','set','patch'}:
            self.action(dict(op=op,**a));return self.view()
        raise ValueError('Unknown editor session operation '+op)

    def open(self,path):
        root=Path(path).resolve();archive=Archive((root/'resource.dat').read_bytes())
        scripts=Archive(archive.read(4))
        profile_metadata=profileflow.load(root,archive,[e.name for e in scripts.entries])
        # Construct completely before replacing the active document/session.
        originals={sid:Archive(Archive(scripts.read(sid)).read(0)).read(0,gzip=True)
                   for sid in range(len(scripts.entries))}
        descriptions={sid:describe(blob) for sid,blob in originals.items()}
        presentation=TextPresentation(root)
        settings=dict(battle=environments.battle((root/'env/env_tukkomi.dat').read_bytes()),
                      approach=environments.approach((root/'env/env_approach.dat').read_bytes()),
                      chapter=environments.chapter((root/'env/env_script.dat').read_bytes()),
                      chapter_text=environments.chapter_text((root/'env/env_script.dat').read_bytes()),
                      selection=environments.selection((root/'env/env_script_select.dat').read_bytes()))
        metadata=[]
        for sid,data in descriptions.items():
            commands=data['commands'];counts=Counter(c['opcode'] for c in commands)
            links=[]
            for c in commands:
                if c['opcode']==0x2bf:links.append(dict(command=c['index'],target=c['args']['script'],kind='file'))
                elif c['opcode']==0x3ed:
                    scene=c['args']['id']
                    targets={row['target'] for char in profile_metadata['scenes'][scene] for row in char['events']}
                    links.extend(dict(command=c['index'],target=target,kind='profile') for target in sorted(targets))
            metadata.append(dict(id=sid,name=scripts.entries[sid].name,count=len(commands),
                                 opcodes={str(k):v for k,v in counts.items()},links=links))
        self.root=root;self.original=originals;self.descriptions=descriptions;self.overrides={}
        self.profile_metadata=profile_metadata
        self.asset_counts=[len(Archive(archive.read(i)).entries) for i in (5,9,10)]
        self.rule_count=len(Archive(archive.read(11)).entries);self.model_count=len(Archive(archive.read(0)).entries)
        self.metadata=metadata;self.text=presentation;self.original_text=presentation;self.settings=settings;self.revision='original';self.reset(0)
        return dict(scripts=metadata)

    def describe(self,sid):
        if sid not in self.original:raise ValueError('Script ID outside imported corpus')
        return self.overrides.get(sid,self.descriptions[sid])

    def candidate(self):
        candidate=Session()
        for key in ('root','original','descriptions','metadata','text','original_text','settings','revision','profile_metadata','asset_counts','rule_count','model_count'):
            setattr(candidate,key,getattr(self,key))
        candidate.overrides=self.overrides.copy()
        return candidate

    def adopt(self,candidate):
        lock=self.lock;self.__dict__.update(candidate.__dict__);self.lock=lock

    def apply_revision(self,scripts,revision_id,entry,apply=True,font_asset=None,**_):
        candidate=self.candidate();candidate.overrides={};candidate.revision=revision_id;issues=[]
        from .fontpatch import effective_font
        original=self.original_text
        candidate.text=effective_font(type('FontProject',(),dict(root=self.root,font_asset=font_asset))(),original)
        for item in scripts:
            sid=item['id']
            if sid not in self.original:raise ValueError('Edited script ID outside corpus')
            try:
                data=describe(bytes.fromhex(item['data_hex']));candidate.overrides[sid]=data
                for command in data['commands']:
                    if 'decode_error' in command['args']:
                        issues.append(dict(script=sid,command=command['index'],message=command['args']['decode_error']))
                for index in item.get('check_text',[]):
                    c=data['commands'][index];candidate.text.validate(c['opcode'],c['args'])
            except (ValueError,IndexError,KeyError) as e:issues.append(dict(script=sid,command=-1,message=str(e)))
        result=dict(issues=issues,warnings=[])
        if not issues and apply:
            candidate.reset(entry);result['view']=candidate.view();self.adopt(candidate)
        return result

    def reset(self,script):
        self.describe(script)
        self.entry=script;self.sid=script;self.pc=0;self.boundary=0;self.now=0
        self.banks={'L':[0]*1024,'G':[0]*80};self.battle=50;self.approach=0
        self.mode='ordinary';self.split_dialogue=False;self.side0=-1;self.side_characters=[-1,-1];self.approach_flags=[0]*18
        self.stack=();self.pending=-1;self.pending_file=-2;self.actors={};self.models={}
        self.messages={};self.work={};self.lanes=[[] for _ in range(5)];self.active_lanes=[False]*5
        self.actions=[];self.visits=[];self.sandbox=False;self.repairs=[];self.error=''
        self.fade=255;self.day=False;self.windows=[100,100];self.tweens=[]
        self.default_tint=[255,255,255]
        self.bgm=-1;self.se=-1;self.se_channel=0
        self.surface=None;self.omitted=[];self.omitted_count=0;self.choice_history={}
        self.lane_cursors=[-1]*5;self.foreground_actors=set();self.background_actors=set()
        self.music_history=set();self.battle_history=set();self.cg_history=set();self.trophies=set();self.last_background=-1
        self.working_day=None;self.chapter=0;self.titles=[]
        self.profile_stats=self.profile_metadata['environment']['stats'][:];self.profile_cached=0;self.profile_flow=None
        self.model_parameters=[dict(target=-1,value=0.) for _ in range(2)]
        progression.manager(self)
        # Load-time battle fields are applied before the first command starts.
        self.load_context();self.observe()

    def profile_targets(self):
        return {i:sorted({e['target'] for c in scene for e in c['events']}) for i,scene in enumerate(self.profile_metadata['scenes'])}

    def load_context(self):
        for c in self.describe(self.sid)['commands']:
            if c['opcode']==0x3ef:
                a=c['args'];self.mode='battle';self.split_dialogue=True;self.side0=a['side0_group'];self.battle=a['gauge'];self.day=False
                self.side_characters=[a['side0_group'],a['side1_group']]

    def change_file(self,target):
        # A new script manager preserves owner banks/history, not the previous
        # file's split dialogue, gauges, approach flags or scene runtimes.
        self.describe(target);self.sid=target;self.pc=0;self.stack=();self.pending=-1;self.pending_file=-2
        self.work={};self.messages={};self.surface=None;self.actors={};self.models={};self.tweens=[]
        self.lanes=[[] for _ in range(5)];self.active_lanes=[False]*5
        self.lane_cursors=[-1]*5;self.foreground_actors=set();self.background_actors=set();self.model_parameters=[dict(target=-1,value=0.) for _ in range(2)]
        self.mode='ordinary';self.split_dialogue=False;self.side0=-1;self.side_characters=[-1,-1]
        self.battle=50;self.approach=0;self.approach_flags=[0]*18;self.day=False
        progression.manager(self)
        self.boundary=5;self.load_context()

    def command(self,index=None):
        commands=self.describe(self.sid)['commands'];index=self.pc if index is None else index
        return commands[checked_index(index,len(commands))]

    def observe(self):
        if self.error or self.boundary not in {0,4,5,6}:return
        item=dict(script=self.sid,command=self.pc,phase='after' if self.boundary==4 else 'before',
                  count=len(self.actions),time=self.now,sandbox=self.sandbox)
        if not self.visits or self.visits[-1]!=item:self.visits.append(item)

    @staticmethod
    def patch_banks(banks,edits):
        for e in edits:
            if e['kind'] not in banks:raise ValueError('Condition edits require L/G variables')
            bank=banks[e['kind']];index=checked_index(e['index'],len(bank));value=e['value']
            if not -32768<=value<=32767:raise ValueError('Variable exceeds signed16 range')
            bank[index]=value

    def action(self,action):
        op=action.get('op')
        if op not in {'step','jump','choose','set','patch'}:raise ValueError('Unknown replay action: '+str(op))
        # Reject malformed interventions before recording or modifying state.
        if op=='jump':
            try:checked_index(action['target'],len(self.describe(self.sid)['commands']))
            except ValueError:raise ValueError('Jump target outside script') from None
        elif op in {'patch','set'}:
            edits=action.get('edits',[action])
            banks=deepcopy(self.banks)
            for e in edits:
                if e['kind'] in banks:self.patch_banks(banks,[e])
                elif e['kind'] not in {'battle','approach'}:raise ValueError('Unknown state kind')
                elif self.boundary not in {0,5,6}:raise ValueError('Gauge intervention must precede Start')
        elif op=='choose':
            # Candidate copy prevents an invalid forced branch from corrupting
            # the active preview or tape.
            candidate=self.candidate();candidate.__dict__.update(deepcopy({k:v for k,v in self.__dict__.items()
                if k not in {'lock','text','settings','original','descriptions','metadata','overrides','profile_metadata','asset_counts','rule_count','model_count'}}))
            candidate.force_choice(action.get('choice',0),action.get('child',0))
            self.adopt(candidate)
        if op=='step' and (not isinstance(action.get('dt',16),int) or action.get('dt',16)<0):
            raise ValueError('Virtual clock delta must be nonnegative')
        self.actions.append(deepcopy(action))
        if op=='jump':self.jump(action['target'])
        elif op in {'patch','set'}:
            self.repairs=[]
            for e in action.get('edits',[action]):
                bank=e['kind'];value=e['value']
                if bank in self.banks:
                    old=self.banks[bank][e['index']];self.banks[bank][e['index']]=value;field=f"?{bank}{e['index']}"
                else:old=getattr(self,bank);setattr(self,bank,value);field=bank+' gauge'
                self.repairs.append(dict(field=field,before=old,after=value))
            self.sandbox=True;self.error=''
        elif op=='step':
            dt=action.get('dt',16)
            self.now+=dt
            try:self.step(action);self.error=''
            except (ValueError,IndexError,KeyError) as error:self.error=f'script {self.sid} command {self.pc}: {error}'
        self.observe()

    def jump(self,target):
        self.pc=target;self.boundary=0;self.stack=();self.pending=-1;self.pending_file=-2
        self.work={};self.messages={};self.surface=None;self.gate=None;self.profile_flow=None;self.lanes=[[] for _ in range(5)];self.active_lanes=[False]*5;self.lane_cursors=[-1]*5
        self.sandbox=True;self.error=''

    def force_choice(self,parent,child):
        c=self.command();op,a=c['opcode'],c['args'];self.repairs=[]
        if op==0x3f6:
            p=a['parents'][checked_index(parent,len(a['parents']))]
            checked_index(child,len(p['children']));expression=p['condition']
            if expression.startswith(('?L','?G')):
                numeric(expression,self.banks);bank,index=expression[1],int(expression[2:])
                self.repairs.append(dict(field=expression,before=self.banks[bank][index],after=1));self.banks[bank][index]=1
            flag=checked_index(parent*3+child,len(self.approach_flags));self.approach_flags[flag]=0
            if numeric(expression,self.banks)!=1:raise ValueError('Disabled approach parent')
            self.approach_flags[flag]=1;target=p['children'][child]['target']
        elif op==0x3f8:
            checked_index(parent,2);value=a['required_gauge']-(1 if parent else 0)
            self.repairs.append(dict(field='approach gauge',before=self.approach,after=value));self.approach=value
            target=a['outcomes'][parent]['target']
        elif op==0x3fa:
            checked_index(parent,3);value=[51,49,50][parent]
            self.repairs.append(dict(field='battle gauge',before=self.battle,after=value));self.battle=value
            target=a[['win','lose','draw'][parent]]
        elif op in {0x65,0x3f2}:target=a['choices'][checked_index(parent,len(a['choices']))]['target']
        else:raise ValueError('Current command is not a choice/result')
        checked_index(target,len(self.describe(self.sid)['commands']));self.jump(target)

    def actor(self,id):
        id &= 0xffff
        return self.actors.setdefault(id,dict(id=id,x=0,y=0,scale=100,color=[255,255,255,0],
                                               visible=False,pose=-1,face=-1,priority=0,history=[]))

    def tween(self,object,key,target,duration,source=None):
        if duration<0:raise ValueError('Negative transition duration')
        source=object[key] if source is None else source
        self.tweens=[t for t in self.tweens if not (t[0] is object and t[1]==key)]
        object[key]=source;self.tweens.append((object,key,source,target,self.now,duration))

    def tick_tweens(self):
        pending=[]
        for obj,key,start,end,epoch,duration in self.tweens:
            elapsed=self.now-epoch
            obj[key]=end if duration==0 or elapsed>=duration else start+int((end-start)*elapsed/duration)
            if elapsed<duration:pending.append((obj,key,start,end,epoch,duration))
        self.tweens=pending
        for actor in self.actors.values():actor['visible']=actor['color'][3]>0
        for queue in (self.foreground_actors,self.background_actors):
            finished={id for id in queue if not any(t[0] is self.actors[id] or t[0] is self.actors[id]['color'] for t in pending)}
            queue.difference_update(finished)

    def settle_actor(self,actor,channels=None):
        """Skip completes logical channels, including their shared wait membership."""
        def selected(t):
            return ((t[0] is actor or t[0] is actor['color']) if channels is None
                    else t[0] is actor['color'] and t[1] in channels)
        for t in self.tweens:
            if selected(t):t[0][t[1]]=t[3]
        self.tweens=[t for t in self.tweens if not selected(t)]
        self.tick_tweens()

    def start(self,index,lane=False):
        c=self.command(index);op,a=c['opcode'],c['args']
        if 'decode_error' in a:raise ValueError(a['decode_error'])
        state=dict(epoch=self.now,queued=False,pending=False);self.work[(index,lane)]=state
        if not lane:self.surface=None
        queued=bool(a.get('route',0))
        if op in progression.HANDLED:
            progression.start(self,c,state,lane)
            if op in {0x2c2,0x3f7}:self.omit(c,'Presentation replaced by logical completion/input service; command state retained')
        elif op==0x64 and (lane or not queued):
            if a['selector'] or a['completion']:raise ValueError('Message selector/append route is not implemented in the Python preview')
            parsed=self.text.format.ordinary(a['text']);body,_=self.text.format.prepare(parsed['body'],unit_text=True)
            glyphs=self.text.layout(body,width=self.settings['battle']['width'] if self.split_dialogue else None,ruby=parsed['ruby'])
            side=0 if not self.split_dialogue or a['speaker'] in {-1,self.side0} else 1
            self.messages[side]={**parsed,'body':body,'side':side,'epoch':self.now,'alphas':[None]*len(glyphs),
                                 'glyphs':glyphs,'revealed':False,'forced':False,'command':index,'fired':set()}
            if a['voice']>=0:self.channels[7+side*2]=dict(kind='dialogue',track=a['voice'])
        elif op in presentation.TEXT_OPS:
            self.surface=presentation.prepare(self,op,a)
            if op==0x65:state['saved_day']=self.day;self.day=False
            if op==0x3ec:self.chapter=a['chapter'];self.titles=a['texts'][:]
            if op in {0x65,0x3f2,0x3f6}:presentation.choice_rows(self,self.surface,a)
        elif op==0x3ed:self.begin_profile(a['id'])
        elif op==0x3fa:
            state['outcome']=1 if self.battle<50 else 0 if self.battle>50 else 2
            self.omit(c,'Battle result artwork/audio omitted; gauge still selects the authored destination')
        elif op in {0x3f4,0x3f5}:
            state['from']=self.battle if op==0x3f4 else self.approach
            env=self.settings['battle' if op==0x3f4 else 'approach'];state['duration']=env['duration']
            if op==0x3f4:
                side0=a['character']==self.side0;delta=a['delta'] if side0 else -a['delta']
                target=(self.battle+delta+2**31)%2**32-2**31
                target=min(target,100-env['minimum']) if side0 else max(target,env['minimum'])
                state['to']=target;self.battle=target
            else:
                if not 0<=self.approach<=100:raise ValueError('Initial approach gauge outside 0–100')
                state['to']=max(0,min(100,self.approach+a['delta']))
        elif op==0x66:self.messages.pop(0,None)
        elif op==0x12e:
            side=0 if self.mode!='battle' or a['speaker'] in {-1,self.side0} else 1
            self.window_types[side]=a['window_type']
        elif op==0x1fb:self.actor(a['character'])['priority']=a['priority']
        elif op==0x202:
            if a['character'] not in self.actors:raise ValueError('Character history requires an existing actor')
            self.actors[a['character']]['history'].clear()  # Numeric ID, never the native string overread.
        elif op==0x201:
            self.default_tint=[a[field]&255 for field in ('red','green','blue')]
            for actor in self.actors.values():
                for channel,value in enumerate(self.default_tint):self.tween(actor['color'],channel,value,a['duration'])
            (self.background_actors if a['background'] else self.foreground_actors).update(self.actors)
        elif op==0x204:
            if a['mode']==0:self.actor(a['character'])['reserved_face']=a['face']
        elif op in {0x1f4,0x1f5,0x1f6,0x1f7,0x1f8,0x1f9,0x1fa}:
            actor=self.actor(a['character'])
            if op==0x1f4:actor['color'][:3]=self.default_tint[:]
            if op in {0x1f9,0x1fa}:
                source=a['source']
                if source not in {0,1,2}:raise ValueError('Invalid character operand source')
                state['value']=self.work.get((index,False),{}).get('value') if lane else None
                if state['value'] is None:state['value']=a['value'] if source==0 else self.banks['L' if source==1 else 'G'][checked_index(a['value'],1024 if source==1 else 80)]
                if op==0x1f9:
                    if state['value']<0:raise ValueError('Negative character pose ID')
                    state['previous']=self.work.get((index,False),{}).get('previous',actor['pose']) if lane else actor['pose']
                    state['installed']=False;state['seen']=False
                    if not queued:actor['pose']=state['value']
                    else:actor['pending_pose']=state['value']
        elif op==0x438:
            self.start_model(a)
        elif op in {0xc8,0xc9}:
            state['from']=255 if op==0xc8 else 0;state['to']=0 if op==0xc8 else 255
            self.fade=state['from'];progression.reset_effect(self)
        elif op==0x3ee:
            self.mode='approach';self.approach=0;self.day=False
            self.channels.pop(2,None);self.channels.pop(3,None)
        elif op==0x3ef:
            self.mode='battle';self.split_dialogue=True;self.side0=a['side0_group'];self.side_characters=[a['side0_group'],a['side1_group']]
            self.battle=a['gauge'];self.day=False
            self.battle_history.add(a['history']);self.channels.pop(2,None);self.channels.pop(3,None)

    def omit(self,command,reason):
        self.omitted_count+=1
        self.omitted.append(dict(script=self.sid,command=command['index'],opcode=command['opcode'],reason=reason))
        self.omitted=self.omitted[-16:]

    def begin_profile(self,scene):
        checked_index(scene,len(self.profile_metadata['scenes']))
        self.profile_flow=dict(scene=scene,stage='select',selection=None)
        self.day=False;self.mode='profile'
        for channel in (0,2,3):self.channels.pop(channel,None)
        self.profile_surface()

    def profile_surface(self,stage=None,selection=None):
        flow=dict(self.profile_flow)
        if stage is not None:flow['stage']=stage
        if selection is not None:flow['selection']=selection
        if stage=='select':flow['selection']=None
        stage=flow['stage'];metadata=self.profile_metadata
        surface=dict(opcode=0x3ed,blocks=[],panels=[],options=[],kind='Profile '+stage,note='',parent=None,
                     epoch=self.now,reveal=stage in {'result','response'},forced=False)
        if stage=='select':
            surface['note']='Choose an authored profile item. Its stat changes and next script are retained.'
            for item in profileflow.options(metadata,flow['scene']):
                name=metadata['environment']['labels'][0][item['character']]
                surface['options'].append(dict(label=name+' / '+item['label'],
                    action=dict(profile_ordinal=item['ordinal'],profile_event=item['event']),enabled=True,
                    reason=item['description'],rect=None))
            text='Profile event selection'
        else:
            ordinal,event=flow['selection'];character=metadata['scenes'][flow['scene']][ordinal]
            row=character['events'][event]
            if stage=='confirm':
                text=metadata['catalog'][ordinal][row['values'][0]]['name']
                surface['options']=[dict(label='Confirm',action=dict(confirm_profile=True),enabled=True,reason='',rect=None),
                                    dict(label='Cancel',action=dict(cancel_profile=True),enabled=True,reason='',rect=None)]
            elif stage=='result':text=profileflow.result_text(metadata,ordinal,character['id'],row)
            else:text=row['response']
        surface['blocks']=[presentation.block(self.text,text,[400,234],self.settings['approach']['result_scale'],
                                              width=self.settings['approach']['result_width'],tags=stage=='result',role='profile_'+stage)]
        self.profile_flow=flow;self.surface=surface

    def update_profile(self,inputs):
        flow=self.profile_flow;stage=flow['stage'];advance=bool(inputs.get('advance'))
        if stage=='select':
            if 'profile_ordinal' not in inputs or 'profile_event' not in inputs:return
            scene=self.profile_metadata['scenes'][flow['scene']]
            ordinal=checked_index(inputs['profile_ordinal'],len(scene));event=checked_index(inputs['profile_event'],len(scene[ordinal]['events']))
            self.profile_surface(stage='confirm',selection=(ordinal,event));return
        if stage=='confirm':
            if inputs.get('cancel_profile'):self.profile_surface(stage='select')
            elif inputs.get('confirm_profile'):self.profile_surface(stage='result')
            return
        if not presentation.ready(self,self.surface):
            if advance or inputs.get('reveal'):self.surface['forced']=True
            return
        if not advance:return
        ordinal,event=flow['selection'];character=self.profile_metadata['scenes'][flow['scene']][ordinal];row=character['events'][event]
        if stage=='result':
            self.profile_surface(stage='response');profileflow.commit_stats(self,ordinal,character['id'],row)
            self.channels[7]=dict(kind='profile_response',track=row['tail']);return
        self.channels.pop(7,None);self.channels.pop(0,None)
        profileflow.publish(self,ordinal);target=row['target'];self.profile_flow=None;self.surface=None
        if target<0:self.boundary=7
        else:self.change_file(target);self.boundary=6

    def start_model(self,a):
        selector,target,value=a['selector'],a['target'],a['value']
        if selector==2:
            checked_index(target,self.model_count)
            record=next((m for m in self.models.values() if m.get('resource')==target),None)
            if record is None:
                record=dict(id=value,resource=target,x=0.,y=0.,scale=100.,color=[255]*4,visible=False,pose=-1,face=-1,priority=0,model=True)
                self.models[value]=record
            return
        if selector in {19,20}:return
        if selector==22:
            for slot in self.model_parameters:
                if slot['target'] in {-1,target}:slot.update(target=target,value=a['vector'][0])
            return
        if selector==15:self.models.pop(target,None);return
        if selector not in {3,4,6,12,13,16,17,21,23,24,25}:raise ValueError('Unsupported model selector '+str(selector))
        actor=self.models.setdefault(target,dict(id=target,x=0.,y=0.,scale=100.,color=[255]*4,visible=False,pose=-1,face=-1,priority=0,model=True))
        if selector!=6 and 'resource' not in actor:raise ValueError('Model operation requires a loaded record')
        if selector==3:actor['visible']=bool(value)
        elif selector==6:actor['pose']=signed16(value)
        elif selector in {12,13}:
            values=a['vector'];duration=a['transition']
            if selector==12:
                self.tween(actor,'x',values[0],duration);self.tween(actor,'y',values[1],duration)
            else:self.tween(actor,'scale',values[0]*100,duration)
        elif selector in {16,17}:actor['face']=value
        elif selector==21:actor['color']=a['color'][:]
        elif selector in {4,23,24,25}:actor[f'motion_{selector}']=value

    def update(self,index,inputs,lane=False):
        c=self.command(index);op,a=c['opcode'],c['args'];key=(index,lane)
        if key not in self.work:self.start(index,lane)
        state=self.work[key];elapsed=self.now-state['epoch'];skip=inputs.get('skip',False)
        if a.get('route',0) and not lane and op not in {0xcb,0x1f9}:return True
        if op in progression.HANDLED:return progression.update(self,c,state,inputs,lane)
        if op==0x64:
            message=next((m for m in self.messages.values() if m['command']==index),None)
            if message is None:raise ValueError('Message context was not started')
            if state['pending']:
                for _,_,keyword in message['keywords']:self.banks['L'][keyword]=1
                self.channels.pop(7+message['side']*2,None)
                return True
            if not message['revealed']:
                if inputs.get('advance') or inputs.get('reveal') or skip:message['forced']=True
                return False
            state['pending']=bool(inputs.get('advance') or skip or a['completion']==1);return False
        if op in {0x1f4,0x1f5,0x1f6,0x1f7,0x1f8,0x1f9,0x1fa}:
            if a.get('route',0) and not lane:return True
            actor=self.actor(a['character']);duration=a.get('duration',0)
            if op==0x1f5:actor['x'],actor['y']=a['x'],a['y'];return True
            if op==0x1fa:actor['face']=state['value'];return True
            if op==0x1f9:return self.update_pose(actor,a,state,skip,lane)
            if not state['queued']:
                state['queued']=True
                if op==0x1f4:self.tween(actor['color'],3,a['opacity_to'],duration,a['opacity_from'])
                elif op in {0x1f6,0x1f7}:
                    for field in ('x','y'):self.tween(actor,field,a[field]+(actor[field] if op==0x1f7 else 0),duration)
                elif op==0x1f8:self.tween(actor,'scale',a['scale'],duration)
                state['tween_epoch']=self.now
                (self.background_actors if lane or a.get('background') else self.foreground_actors).add(actor['id'])
            if skip:
                self.settle_actor(actor)
                return True
            return lane or bool(a.get('background')) or not self.foreground_actors
        if op in {0xc8,0xc9}:
            duration=a['duration']
            if duration<0:raise ValueError('Negative fade duration')
            self.fade=state['to'] if skip or not duration or elapsed>=duration else state['from']+int((state['to']-state['from'])*elapsed/duration)
            return skip or elapsed>=duration
        if op==0x2c0:return (skip and not a['honor_skip']) or elapsed>= (a['duration'] if a['duration']>=0 else (1<<64)+a['duration'])
        if op in {0x12c,0x12d}:
            duration=a['duration']&0xffffffff;done=skip or not duration or elapsed>=duration
            progress=100 if done else elapsed*100//duration;self.windows[bool(a['channel'])]=progress if op==0x12c else 100-progress
            return done
        if op in {0x65,0x3f2,0x3f6,0x3f8,0x3f9,0x3ec}:return self.update_surface(op,a,state,inputs)
        if op==0x3fa:
            target=a[['win','lose','draw'][state['outcome']]]
            checked_index(target,len(self.describe(self.sid)['commands']));self.pending=target;return True
        if op==0:
            bank=self.banks['L' if a['bank']==0 else 'G'];i=checked_index(a['index'],len(bank));kind=a['operand_kind']
            operand=a['operand'] if kind>1 else self.banks['L' if kind==0 else 'G'][checked_index(a['operand'],1024 if kind==0 else 80)]
            bank[i]=signed16(operand if a['operation']==0 else bank[i]+operand if a['operation']==1 else bank[i]-operand);return True
        if op==1:
            truth=condition(a['condition'],self.banks);self.stack+=((a['start'] if truth else -1,a['alternate'],a['resume']),);return True
        if op==0x2be:self.pending=a['target'];return True
        if op==0x2bf:self.pending_file=a['script'];return True
        if op==0x3fc:self.approach_flags=[0]*18;return True
        if op==0x201:
            if skip:
                for actor in self.actors.values():self.settle_actor(actor,{0,1,2})
            return skip or not a['duration'] or bool(a['background']) or not self.foreground_actors
        if op in {0x3f4,0x3f5}:
            duration=state['duration'];done=skip or elapsed>=duration
            if op==0x3f5:
                progress=100 if done or not duration else elapsed*100//duration
                # Preserve the intended snap-to-original-target correction on
                # normal-to-skip; never add the entire delta to partial progress.
                self.approach=state['to'] if done else state['from']+int((state['to']-state['from'])*progress/100)
            return done
        if op in {0x66,0x12e,0x1fb,0x202,0x204,0x2bd,0x3ee,0x3ef,0x438}:return True
        raise ValueError(f'Python execution for opcode {op:04X} is not implemented')

    def update_pose(self,actor,a,state,skip,lane):
        # Logical resources are ready immediately. Preserve main/lane ordering,
        # shared foreground gate and crossfade completion without loading art.
        if not lane:
            if a['route'] and not skip:return True
            if not state['seen']:state['seen']=True;return False
            if a['route']:return True
        equal=state['previous']==state['value']
        if lane and equal:
            if actor.get('reserved_face',-1)>=0:actor['face']=actor['reserved_face']
            actor['reserved_face']=-1;return True
        if not state['installed']:
            if self.foreground_actors and not (lane and skip):return False
            if lane and not skip:actor['pose']=state['value']
            if actor.get('reserved_face',-1)>=0:actor['face']=actor['reserved_face']
            actor['reserved_face']=-1;actor['history'].append(state['value'])
            state['installed']=True;state['installed_at']=self.now
            state['duration']=0 if skip or state['previous']<0 else a['duration']
            if state['duration']<0:raise ValueError('Negative pose duration')
        return skip or self.now-state['installed_at']>=state['duration']

    def update_surface(self,op,a,state,inputs):
        surface=self.surface
        if surface is None or surface['opcode']!=op:raise ValueError('Text surface does not belong to current command')
        advance=bool(inputs.get('advance') or inputs.get('skip'))
        target=None;history=None
        if op in {0x3ec,0x3f9}:return advance
        if op==0x3f8:
            if not presentation.ready(self,surface):
                if advance or inputs.get('reveal'):surface['forced']=True
                return False
            if not advance:return False
            target=a['outcomes'][surface['outcome']]['target']
        elif op in {0x65,0x3f2}:
            timeout=op==0x3f2 and (inputs.get('timeout') or self.now-surface['epoch']>=a['duration'])
            if not timeout and 'choice' not in inputs:return False
            ordinal=0 if timeout else checked_index(inputs['choice'],len(a['choices']))
            target=a['choices'][ordinal]['target'];history=None if timeout else (ordinal,)
        elif op==0x3f6:
            if inputs.get('back'):surface['parent']=None;return False
            if 'parent' in inputs:
                parent=inputs['parent']
                if parent not in surface['enabled_parents']:raise ValueError('Approach parent is disabled')
                surface['parent']=parent;return False
            if 'choice' not in inputs or 'child' not in inputs:return False
            parent=inputs['choice'];child=inputs['child']
            if parent!=surface['parent']:raise ValueError('Select an enabled approach parent before its child')
            checked_index(parent,len(a['parents']));row=a['parents'][parent];checked_index(child,len(row['children']))
            if numeric(row['condition'],self.banks)!=1:raise ValueError('Approach parent is disabled')
            if self.approach_flags[parent*3+child]:raise ValueError('Approach child already used')
            target=row['children'][child]['target'];history=(parent,child)
        checked_index(target,len(self.describe(self.sid)['commands']))
        if op==0x3f6:self.approach_flags[history[0]*3+history[1]]=1
        if op==0x65:self.day=state['saved_day']
        if history is not None:self.choice_history.setdefault((self.sid,self.pc),set()).add(history)
        self.pending=target;return True

    def step(self,inputs):
        if self.boundary==7:self.tick_tweens();self.update_messages();return
        if self.profile_flow is not None:
            self.update_profile(inputs)
            if self.profile_flow is not None:self.boundary=2
            return  # Native profile owner suspends the script manager/lanes.
        if self.boundary==4:
            c=self.command();a=c['args']
            self.surface=None
            if self.pending_file!=-2:
                target=self.pending_file
                if target<0:self.boundary=7
                else:
                    self.change_file(target)
            else:
                if a.get('route',0) and self.pending<0:
                    lane=checked_index(a['lane'],5);self.lanes[lane].append(self.pc)
                self.pc,self.stack=dispatch(self.pc,self.stack,len(self.describe(self.sid)['commands']),self.pending)
                self.pending=-1;self.boundary=7 if self.pc==len(self.describe(self.sid)['commands']) else 0
        elif self.boundary in {0,5,6}:
            self.start(self.pc);self.boundary=1
            if self.command()['opcode']==0x64:self.update_lanes()
        else:
            done=self.update(self.pc,inputs)
            self.boundary=4 if done else 2 if self.command()['opcode'] in {0x64,0x65,0x3f2} else 3
            if not done:self.update_lanes(skipping=bool(inputs.get('skip')),flush=bool(inputs.get('flush_lanes')))
        self.tick_tweens();self.update_messages()

    def update_lanes(self,skipping=False,flush=False):
        for lane,queue in enumerate(self.lanes):
            if flush and queue:self.active_lanes[lane]=True
            if not queue or not self.active_lanes[lane]:continue
            if self.lane_cursors[lane]<0:self.lane_cursors[lane]=0
            while self.lane_cursors[lane]<len(queue):
                index=queue[self.lane_cursors[lane]]
                done=self.update(index,dict(skip=skipping or flush),True)
                if done or skipping or flush:
                    self.lane_cursors[lane]+=1;self.work.pop((index,True),None)
                if not (skipping or flush):break
            if self.lane_cursors[lane]>=len(queue):queue.clear();self.active_lanes[lane]=False;self.lane_cursors[lane]=-1

    def update_messages(self):
        for m in self.messages.values():
            count=len(m['glyphs']);interval=self.text.intervals[2]
            visible=count if not interval or m['forced'] else min(count,max(1,(self.now-m['epoch'])//interval))
            for i in range(visible):
                if m['alphas'][i] is None:m['alphas'][i]=self.now
            # The editor's disclosed silent/character-clock policy supplies
            # marker time instead of an audio playback cursor.
            for marker,(before,lane,time) in enumerate(m['markers']):
                if marker not in m['fired'] and self.now-m['epoch']>=time:
                    m['fired'].add(marker)
                    if self.lanes[lane]:self.active_lanes[lane]=True
            m['revealed']=m['forced'] or (visible==count and all(t is not None and self.now-t>=200 for t in m['alphas']))

    def view(self):
        c=self.command() if self.pc<len(self.describe(self.sid)['commands']) else dict(opcode=-1,args={})
        messages=[];glyphs=[]
        def append(text,x,y,size,rgb):
            for char in text:
                width=size//2 if 0x20<=ord(char)<=0x7e or 0xff61<=ord(char)<=0xffa0 else size
                cached=self.text.cached.get(char)
                rect=[x,y,math_ceil(cached[3]*size/self.text.bitmap_height) if cached else width,
                      math_ceil(self.text.bitmap_height*size/self.text.bitmap_height) if cached else size]
                glyphs.append(dict(code=ord(char),rect=rect,color=rgb[:]))
                x+=width
        for side,m in sorted(self.messages.items() if self.surface is None and self.gate is None else []):
            messages.append(dict(name=unicode_text(m['name']),body=unicode_text(m['body']),side=side,revealed=m['revealed']))
            size=int(self.text.utility*self.text.name_scale);x,y=self.text.name_origin
            append(m['name'],x-self.text.measure(m['name'],size)//2,y-size//2,size,self.text.name_color[:3]+[255])
            origin=self.text.origin
            if self.split_dialogue:
                env=self.settings['battle'];line_count=max((g['line'] for g in m['glyphs']),default=0)+1
                width=max((g['x']+int(g['advance']*self.text.scale) for g in m['glyphs']),default=0)
                base=env['positions'][side];offset=env['line_offsets'][1 if line_count==1 else 0]
                origin=[base[0]+offset[0]-width//2,base[1]+offset[1]]
            for i,g in enumerate(m['glyphs']):
                epoch=m['alphas'][i];alpha=255 if m['forced'] else 0 if epoch is None else min(255,(self.now-epoch)*255//200)
                rgb=self.text.unread[:3]
                if any(begin<=i<end for begin,end,_ in m['keywords']):rgb=self.text.keyword_colors[0][:3]
                x=origin[0]+g['x'];y=origin[1]+g['y'];size=int(self.text.utility*self.text.scale)
                append(chr(g['code']),x,y,size,rgb+[alpha])
            for begin,end,reading in m['ruby']:
                span=[(i,g) for i,g in enumerate(m['glyphs']) if begin<=g['index']<end]
                if not span:continue
                first=span[0][1];size=int(self.text.utility*self.text.ruby_scale)
                extent=sum(int(g['advance']*self.text.scale) for _,g in span)
                x=origin[0]+first['x']+extent//2-self.text.measure(reading,size)//2
                y=origin[1]+first['y']+self.text.ruby_y
                epoch=m['alphas'][span[0][0]];alpha=255 if m['forced'] else 0 if epoch is None else min(255,(self.now-epoch)*255//200)
                append(reading,x,y,size,self.text.unread[:3]+[alpha])
        active_message=any(m['command']==self.pc for m in self.messages.values())
        pending=self.work.get((self.pc,False),{}).get('pending',False)
        extras=dict(choices=[],text_items=[dict(text=m['body'],role='dialogue',revealed=m['revealed']) for m in messages],panels=[],text_waiting=c['opcode']==0x64 and active_message and not pending and self.boundary not in {0,4,5,7},
                    text_ready=all(m['revealed'] for m in messages),text_kind='Dialogue' if messages else '',text_note='')
        if self.surface is not None:
            if c['opcode'] in {0x65,0x3f2,0x3f6}:presentation.choice_rows(self,self.surface,c['args'])
            extras=presentation.packets(self,self.surface);glyphs+=extras.pop('glyphs')
            if self.boundary==4:extras['text_waiting']=False;extras['choices']=[]
        if self.gate:
            movie=self.gate['kind']=='movie'
            extras.update(text_waiting=True,text_ready=True,text_kind='Movie' if movie else 'Mission cue',
                text_note='Presentation is suppressed; logical completion is still required.',
                choices=[dict(label='Complete simulated movie' if movie else 'Confirm mission cue',
                              action=dict(service_complete=True) if movie else dict(advance=True),enabled=True,reason='',rect=None)])
        return dict(script=self.sid,command=self.pc,opcode=c['opcode'],args=c['args'],boundary=self.boundary,
                    time=self.now,error=self.error,sandbox=self.sandbox,repairs=self.repairs,
                    actors=sorted(list(self.actors.values())+list(self.models.values()),key=lambda a:(a['priority'],a['id'])),
                    variables=[[k,i,v] for k,bank in self.banks.items() for i,v in enumerate(bank) if v],
                    battle=self.battle,approach=self.approach,messages=messages,glyphs=glyphs,
                    history=len(self.actions),fade=self.fade,mode=self.mode,omitted=self.omitted,
                    omitted_count=self.omitted_count,preview_policy='Scenario simulator: command state retained; graphics/audio output reduced',
                    logic=progression.view(self),**extras)


def math_ceil(value):
    import math
    return math.ceil(value)
