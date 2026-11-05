"""Text-only preview surfaces. No game art, audio or mode-animation hosts.

Authored text placement/scale and branch rules come from the accepted source.
The editor presents text immediately, holds it for review, and records normal
selection/advance inputs. This is deliberately separate from game presentation.
"""
from .text import units,unicode_text
from .semantics import numeric

TEXT_OPS={0x64,0x65,0x3ec,0x3f2,0x3f6,0x3f8,0x3f9}


def glyph_width(g,scale):return g.get('pixel_advance',int(g['advance']*scale))


def block(font,value,origin,scale,*,width=None,center=False,baseline=False,rgb=None,tags=False,role='text',single_line=False):
    text,colors=(units(value).split('\0',1)[0],[]) if single_line else font.format.prepare(value,font_tags=tags)
    size=int(font.utility*scale)
    if not 0<size<=1024:raise ValueError('Text size outside preview budget')
    if single_line:
        glyphs=[];x=0
        for i,c in enumerate(text):
            advance=font.measure(c,size);glyphs.append(dict(code=ord(c),x=x,y=0,index=i,line=0,advance=advance/scale,pixel_advance=advance));x+=advance
    else:glyphs=font.layout(text,width=width or 2**20,scale=scale)
    extent=max((g['x']+glyph_width(g,scale) for g in glyphs),default=0)
    x,y=origin
    if center:x-=extent//2
    if baseline:y-=size
    return dict(text=unicode_text(text),units=text,glyphs=glyphs,origin=[x,y],size=size,
                colors=colors,color=(rgb or [0,0,0,255])[:],role=role)


def prepare(session,op,args):
    """Prepare a whole text surface once. Selection mutation lives in runtime."""
    s=session;f=s.text;e=s.settings
    surface=dict(opcode=op,blocks=[],panels=[],options=[],kind='',note='',parent=None,epoch=s.now)
    if op==0x3ec:
        env=e['chapter_text'];surface['kind']='Chapter title'
        for index,value in enumerate(args['texts']):
            point=env['positions'][index];size=int(f.utility*env['scale'])
            surface['blocks'].append(block(f,value,[point[0],point[1]-size//2],env['scale'],role=f'title{index}',single_line=True))
    elif op==0x3f9:
        env=e['battle'];surface['kind']='Battle introduction'
        size=int(f.utility*env['text_scale']);name_size=int(f.utility*env['name_scale'])
        for side,value in enumerate(args['texts']):
            base=env['text_positions'][side];panel_size=int(36*env['text_scale'])
            panel_width=env['padding']+f.measure(units(value),0 if side else panel_size)
            center=base[0]+(-panel_width//2 if side else panel_width//2)
            surface['blocks'].append(block(f,value,[center,base[1]-size//2],env['text_scale'],center=True,
                                           rgb=[255]*4,role=f'versus{side}',single_line=True))
            actor=s.side_characters[side]
            if 0<=actor<len(env['names']):
                pos=env['name_positions'][side];dims=env['name_sizes'][actor]
                center=pos[0]+(-dims[0]//2 if side else dims[0]//2)+env['name_offsets'][actor]
                surface['blocks'].append(block(f,env['names'][actor],[center,pos[1]-name_size//2],
                                               env['name_scale'],center=True,rgb=[255]*4,role=f'name{side}',single_line=True))
    elif op==0x3f8:
        env=e['approach'];outcome=0 if s.approach>=args['required_gauge'] else 1
        surface.update(kind='Approach result',outcome=outcome,epoch=s.now,forced=False,
                       note='Success' if outcome==0 else 'Failure')
        surface['blocks'].append(block(f,args['outcomes'][outcome]['text'],env['result_origin'],
                                       env['result_scale'],width=env['result_width'],tags=True,role='result'))
    elif op in {0x65,0x3f2}:surface['kind']='Battle choices' if op==0x3f2 else 'Choices'
    elif op==0x3f6:
        enabled=[i for i,p in enumerate(args['parents']) if numeric(p['condition'],s.banks)==1]
        if any(i>=6 or not 1<=len(args['parents'][i]['children'])<=3 for i in enabled):
            raise ValueError('Approach menu exceeds parent/child flag layout')
        surface.update(kind='Approach choices',enabled_parents=enabled)
    else:raise ValueError('Not a text surface')
    return surface


def choice_rows(session,surface,args):
    """Rebuild the small visible menu after input/state changes, retaining IDs."""
    s=session;f=s.text;op=surface['opcode'];shared=s.settings['selection']
    blocks=[];options=[]
    def option(label,action,item,enabled=True,reason='',**extra):
        if not enabled:item['color'][3]=min(item['color'][3],100)
        blocks.append(item)
        glyphs=item['glyphs'];scale=item['size']/f.utility
        width=max((g['x']+glyph_width(g,scale) for g in glyphs),default=0)
        height=max((g['y']+item['size'] for g in glyphs),default=item['size'])
        options.append(dict(label=label,action=action,enabled=enabled,reason=reason,
                            rect=[item['origin'][0]-20,item['origin'][1]-10,max(80,width)+40,height+20],**extra))
    if op==0x65:
        entries=args['choices'];points=shared['points'][0 if len(entries)==2 else 1]
        if not entries or len(entries)>len(points):raise ValueError('Ordinary choice exceeds authored point tables')
        for i,row in enumerate(entries):
            point=points[i];origin=[point[0]+shared['words'][4],point[1]+shared['words'][5]]
            history=s.choice_history.get((s.sid,s.pc),set())
            item=block(f,row['label'],origin,shared['scale'],center=True,rgb=shared['colors'][int((i,) in history)],role=f'choice{i}',single_line=True)
            option(row['label'],dict(choice=i),item,ordinal=i)
    elif op==0x3f2:
        env=s.settings['battle'];rows=args['choices']
        if not 1<=len(rows)<=4:raise ValueError('Battle choices require 1–4 authored rows')
        for i,row in enumerate(rows[1:],1):
            control=i-1;point=env['choice_positions'][control]
            item=block(f,row['label'],[0,0],f.scale,width=env['width'],tags=True,role=f'choice{i}')
            lines=max((g['line'] for g in item['glyphs']),default=0)+1
            offset=env['choice_offsets'][1 if lines==1 else 0]
            extent=max((g['x']+int(g['advance']*f.scale) for g in item['glyphs']),default=0)
            item['origin']=[point[0]+offset[0]-extent//2,point[1]+offset[1]]
            option(row['label'],dict(choice=i),item,ordinal=i)
            if control<len(env['labels']):
                offset=env['label_positions'][control];size=int(f.utility*env['label_scale'])
                blocks.append(block(f,env['labels'][control],[point[0]+offset[0],point[1]+offset[1]-size//2],
                                    env['label_scale'],center=True,rgb=[255]*4,role=f'key{i}',single_line=True))
        options.append(dict(label='Timeout → '+(rows[0]['label'] or f"#{rows[0]['target']}"),
                            action=dict(timeout=True),enabled=True,reason='',rect=None,ordinal=0))
        surface['note']=f"{max(0,args['duration']-(s.now-surface['epoch']))/1000:.1f}s · row 0 is the timeout route"
    elif op==0x3f6:
        env=s.settings['approach'];enabled=surface['enabled_parents'];selected=surface['parent']
        for display,original in enumerate(enabled):
            if len(enabled)>=5:
                focus=enabled.index(selected) if selected is not None else 0
                row=(display-focus+2)%len(enabled)
                point=[env['offset'][0],env['offset'][1]+env['scroll_distance']*row]
            else:
                table=env['points'][0 if len(enabled)==3 else 1]
                if display>=len(table):raise ValueError('Approach parents exceed authored point table')
                point=table[display]
            row=args['parents'][original];origin=[point[0]+env['text_offset'][0],point[1]+env['text_offset'][1]]
            item=block(f,row['label'],origin,env['scale'],center=True,baseline=True,role=f'parent{original}',single_line=True)
            if selected is not None:item['color'][3]=128
            option(row['label'],dict(parent=original),item,ordinal=original,selected=selected==original)
        if selected is not None:
            children=args['parents'][selected]['children'];points=shared['points'][0 if len(children)==2 else 1]
            for child,row in enumerate(children):
                if child>=len(points):raise ValueError('Approach children exceed authored point table')
                point=points[child];used=bool(s.approach_flags[selected*3+child])
                origin=[point[0]+shared['words'][4],point[1]+shared['words'][5]]
                item=block(f,row['label'],origin,shared['scale'],center=True,role=f'child{selected}/{child}',single_line=True)
                option(row['label'],dict(choice=selected,child=child),item,not used,'Already used' if used else '',
                       parent=selected,ordinal=child)
            options.append(dict(label='Back to parents',action=dict(back=True),enabled=True,reason='',rect=None))
        surface['note']='Select a parent, then a child. Used children cannot be chosen.' if enabled else 'No enabled parents; waiting for valid scenario state.'
    surface['blocks']=blocks;surface['options']=options


def packets(session,surface):
    """Render-ready glyphs plus independent semantic text and hit regions."""
    font=session.text;glyphs=[];items=[];panels=[]
    for item in surface['blocks']:
        color=item['color'];size=item['size'];origin=item['origin'];glist=item['glyphs']
        count=len(glist);elapsed=session.now-surface.get('epoch',session.now)
        revealed=not (surface['opcode']==0x3f8 or surface.get('reveal')) or surface.get('forced',False)
        interval=font.intervals[2]
        visible=count if revealed or not interval else max(1,elapsed//interval)
        for i,g in enumerate(glist):
            alpha=color[3] if i<visible else 0;rgb=color[:3]
            for begin,end,tint in item['colors']:
                if begin<=i<end:rgb=tint;break
            if chr(g['code'])==font.format.following[26][0]:rgb=[255]*3
            cached=font.cached.get(chr(g['code']))
            width=math_ceil(cached[3]*size/font.bitmap_height) if cached else size//2 if 0x20<=g['code']<=0x7e or 0xff61<=g['code']<=0xffa0 else size
            glyphs.append(dict(code=g['code'],rect=[origin[0]+g['x'],origin[1]+g['y'],width,size],color=rgb+[alpha]))
        items.append(dict(text=item['text'],role=item['role'],revealed=revealed or visible>=count))
        extent=max((g['x']+glyph_width(g,size/font.utility) for g in glist),default=0)
        height=max((g['y']+size for g in glist),default=size)
        panels.append(dict(rect=[origin[0]-24,origin[1]-12,max(40,extent)+48,height+24],
                           dark=color[:3]==[255]*3))
    return dict(glyphs=glyphs,text_items=items,panels=panels,choices=surface['options'],
                text_waiting=True,text_ready=all(i['revealed'] for i in items),text_kind=surface['kind'],
                text_note=surface['note'])


def ready(session,surface):
    if not (surface['opcode']==0x3f8 or surface.get('reveal')) or surface.get('forced'):return True
    count=sum(len(b['glyphs']) for b in surface['blocks'])
    return session.now-surface['epoch']>=count*session.text.intervals[2]


def math_ceil(value):
    import math
    return math.ceil(value)
