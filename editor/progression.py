"""Logical command state and completion hosts for the translator simulator.

No pixels, SDK objects, audio mixing or media decoding. State, requests, channel
ownership, timer endpoints and input/service completion remain executable.
"""
import re
from .semantics import numeric,signed16

HANDLED={0xca,0xcb,0xce,0x190,0x191,0x1c3,0x1c4,0x258,0x259,0x25a,0x25b,
         0x2c2,0x2c6,0x3ea,0x3f7,0x3fd,0x400,0x640}


def manager(s):
    s.scene=dict(images={},references={},fills={},particles={},filter_mode=0,filter_intensity=0.,
                 rule=dict(cached_rule=-1,cached_background=-1,active=False,progress=0),
                 effect_value=0,effect_restore=0,effect_channel=7,quake_active=False)
    s.channels={};s.gate=None;s.mouth=dict(enabled=False,ids=[-1]*5)
    s.window_types=[0,0];s.date=[0,0];s.mission=-1
    s.bgm=-1;s.se=-1;s.se_channel=0;s.bgm_volume=100;s.se_volume=100


def track_number(text):
    match=re.match(r'[ \t\r\n\v\f]*([+-]?)([0-9]*)',text)
    value=int(match[2] or '0');limit=2**31 if match[1]=='-' else 2**31-1
    value=min(value,limit);return -value if match[1]=='-' else value


def reset_effect(s):
    s.scene['effect_value']=s.scene['effect_restore']
    for channel in (s.scene['effect_channel'],s.scene['effect_channel']+1):s.channels.pop(channel,None)


def interpolate(start,end,epoch,duration,now):
    if duration<0:raise ValueError('Negative transition duration')
    return end if not duration or now-epoch>=duration else start+int((end-start)*(now-epoch)/duration)


def start(s,c,state,lane):
    op,a=c['opcode'],c['args'];scene=s.scene
    if op in {0xca,0xc8,0xc9,0x190,0x191}:reset_effect(s)
    if op==0x258:
        track=track_number(a['track'])
        if track<0:raise ValueError('Negative BGM track ID')
        s.bgm=track;s.bgm_volume=a['volume'];s.channels[0]=dict(kind='bgm',track=track)
        s.music_history.add(track)
    elif op==0x259:s.bgm=-1;s.channels.pop(0,None)
    elif op==0x25a:
        if not lane and a['route']:return
        if a['track']<0:raise ValueError('Negative SE track ID')
        s.channels[a['channel']+2]=dict(kind='se',track=a['track'])
        if a['remember']:s.se=a['track'];s.se_channel=a['channel'];s.se_volume=a['volume']
    elif op==0x25b:
        s.channels.pop(a['channel']+2,None)
        if s.se_channel==a['channel']:s.se=-1
    elif op==0x2c6:s.mouth=dict(enabled=a['enabled'],ids=a['ids'][:])
    elif op==0x3ea:
        s.day=bool(a['enabled']);s.date=[a['month'],a['day']];s.working_day=dict(enabled=s.day,date=s.date[:])
    elif op==0x640:
        s.trophies.add(a['trophy'])
        if all(s.banks['G'][20:35]):s.trophies.add(25)
    elif op==0xca:
        if not 0<=a['slot']<4:raise ValueError('Fill slot outside 0–3')
        scene['fills'][a['slot']]=dict(color=a['color']&0xffffff,opacity=a['from'],bucket=a['bucket'])
    elif op==0xcb:
        category=a['category'];slot=a['slot'];id=numeric(a['texture'],s.banks)
        if category not in {0,1,2} or not 0<=slot<(10 if category==2 else 4):raise ValueError('Image category/slot outside native domain')
        if id< -1 or id>=s.asset_counts[category]:raise ValueError('Image ID outside imported metadata')
        if a['route'] or a['owner']:raise ValueError('Unverified image lane/slot-owned path')
        key=(category,slot);old=scene['images'].get(key,dict(scale=0))
        state['old_scale']=old['scale']
        scene['images'][key]=dict(texture=id,opacity=a['from']&255,scale=a['scale'],bucket=a['bucket'],
                                  geometry=[signed16(x) for x in a['geometry']])
        if id>=0:
            ref=(category,id)
            if old.get('texture')!=id or not scene['references'].get(ref,0):
                scene['references'][ref]=(scene['references'].get(ref,0)+1)&0xffffffff
            if category==0:s.last_background=id
            elif category==1:s.cg_history.add(id)
    elif op==0xce:
        id=a['id_or_index']
        if a['source']:
            bank=s.banks['L' if a['source']==1 else 'G']
            if not 0<=id<len(bank):raise ValueError('Image release variable outside bank')
            id=bank[id]
        category=0 if a['category']==0 else 1 if a['category']==1 else 2
        if 0<=id<s.asset_counts[category]:scene['references'][(category,id)]=0
    elif op in {0x3fd,0x400}:
        state['filter_from']=int(scene['filter_intensity']*100) if op==0x400 else 0
        if op==0x3fd:scene['filter_mode']=1
    elif op==0x191:
        if a['rule']<0 or a['rule']>=s.rule_count or a['background_kind'] not in range(5):raise ValueError('Invalid rule/background request')
        rule=scene['rule'];kind=a['background_kind'];image=a.get('color_or_image',-1)
        if kind>=2 and image<0:raise ValueError('Negative wipe background')
        if kind==3 and image!=rule['cached_background']:s.cg_history.add(image)
        rule.update(direction=a['direction'],parameter=a['parameter'],background_kind=kind,cached_rule=a['rule'],
                    cached_background=image if kind>=2 else rule['cached_background'],color=image if kind==0 else None)
        state['stage']=0
    elif op==0x190:scene['quake_active']=True
    elif op==0x1c3:
        if not lane and a['route']:return
        if a['group']<0 or a['effect']<0 or a['target'] not in {0,1}:raise ValueError('Invalid particle request')
        scene['particles'][a['group']]=dict(effect=a['effect'],x=a['x'],y=a['y'],character=a['character'],
            persistent=not lane and a['persistent']==1,scale=a['scale'],color=a['color']&0xffffffff,opacity=100)
    elif op==0x1c4:
        if a['duration']<=16:scene['particles'].pop(a['group'],None)
    elif op==0x2c2:
        s.channels.clear()  # Shared physical channels stop; remembered resume fields survive.
        s.gate=dict(kind='movie',name=a['movie'],allow_skip=a['allow_skip'],started=True,completed=False)
    elif op==0x3f7:
        if a['mission']< -1:raise ValueError('Invalid mission voice ID')
        s.mission=a['mission'];s.gate=dict(kind='mission',id=s.mission,ready=True,completed=False)
        s.channels.pop(11,None)
        if s.mission>=0:s.channels[11]=dict(kind='mission',track=s.mission)


def update(s,c,state,inputs,lane):
    op,a=c['opcode'],c['args'];scene=s.scene;skip=bool(inputs.get('skip'));elapsed=s.now-state['epoch']
    if op in {0x258,0x259,0x25a,0x25b,0xce,0x2c6,0x3ea,0x640}:return True
    if op==0x2c2:
        # External decoder EOF is an explicit virtual service input. Game skip
        # only skips when the authored command allows it; no invented duration.
        done=bool(inputs.get('service_complete') or (inputs.get('advance') and a['allow_skip']))
        if done:s.gate['completed']=True;s.fade=255;s.gate=None
        return done
    if op==0x3f7:
        if not inputs.get('advance'):return False
        s.channels.pop(11,None);s.gate=None;return True
    if op==0xca:
        value=a['to'] if skip else interpolate(a['from'],a['to'],state['epoch'],a['duration'],s.now)
        scene['fills'][a['slot']]['opacity']=value;return skip or elapsed>=a['duration']
    if op==0xcb:
        image=scene['images'][(a['category'],a['slot'])]
        if image['texture']==-1:return True
        image['opacity']=(a['to'] if skip else interpolate(a['from'],a['to'],state['epoch'],a['duration'],s.now))&255
        scale=a['scale'] if skip else interpolate(state['old_scale'],a['scale'],state['epoch'],a['duration'],s.now)
        image['scale']=signed16(scale) if a['category']==2 else scale&255
        return skip or elapsed>=a['duration']
    if op in {0x3fd,0x400}:
        target=0 if op==0x400 else 100
        value=target if skip else interpolate(state['filter_from'],target,state['epoch'],a['duration'],s.now)
        scene['filter_intensity']=value/100
        done=skip or elapsed>=a['duration']
        if done and op==0x400:scene['filter_mode']=0
        return done
    if op==0x191:
        rule=scene['rule'];forward=a['direction']==0;start,end=(-100,100) if forward else (100,-100)
        if state['stage']==0:
            state['stage']=1;state['phase_epoch']=s.now;rule.update(active=True,progress=start);return False
        if not skip and rule['progress']!=end:
            rule['progress']=interpolate(start,end,state['phase_epoch'],a['duration'],s.now);return False
        rule['progress']=end
        if a['direction']==1:rule.update(cached_rule=-1,cached_background=-1,active=False)
        return True
    if op==0x190:
        done=skip or elapsed>=a['attack']+a['hold']+a['decay']
        if done:scene['quake_active']=False
        return done
    if op==0x1c3:return True
    if op==0x1c4:
        if a['duration']<=16:return True
        item=scene['particles'].get(a['group'])
        if item:item['opacity']=interpolate(100,0,state['epoch'],a['duration'],s.now)
        if elapsed<a['duration']:return False  # Skip retains the deadline too.
        scene['particles'].pop(a['group'],None);return True
    raise ValueError('Missing logical progression handler')


def view(s):
    return dict(bgm=s.bgm,se=s.se,se_channel=s.se_channel,bgm_volume=s.bgm_volume,se_volume=s.se_volume,
        active_channels=dict(s.channels),service_gate=s.gate,window_types=s.window_types[:],
        music_history=sorted(s.music_history),cg_history=sorted(s.cg_history),trophies=sorted(s.trophies),
        battle_history=sorted(s.battle_history),
        day_visible=s.day,date=s.date[:],working_day=s.working_day,chapter=s.chapter,titles=s.titles[:],
        last_background=s.last_background,approach_flags=s.approach_flags[:],mission=s.mission,
        images=[dict(category=k[0],slot=k[1],**v) for k,v in sorted(s.scene['images'].items())],
        resource_references=[dict(category=k[0],resource=k[1],count=v) for k,v in sorted(s.scene['references'].items())],
        particles=dict(s.scene['particles']),filter=dict(mode=s.scene['filter_mode'],intensity=s.scene['filter_intensity']),
        rule=dict(s.scene['rule']),mouth=dict(s.mouth),profile_stats=s.profile_stats[:],profile_cached=s.profile_cached,
        model_parameters=[dict(p) for p in s.model_parameters],
        queued_lanes=[list(q) for q in s.lanes],lane_cursors=s.lane_cursors[:])
