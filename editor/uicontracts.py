"""Bind native text consumers to stable asset fields, through parser provenance."""
from copy import deepcopy
from .scriptcodec import Reader,STRING_OBSERVER


class FieldText(str):
    def __new__(cls,value,field_id):
        result=super().__new__(cls,value);result.field_id=field_id;return result


class Contracts:
    def __init__(self,catalog):
        self.c=catalog;self.decoded={};self.bound={}

    def parse(self,source,parser=None):
        key=(source,parser)
        if key in self.decoded:return self.decoded[key]
        node=self.c.nodes[source+':'];mapping={s.start:source+':#s'+str(i) for i,s in enumerate(node['spans'])}
        def observe(reader,start,end,value):
            return FieldText(value,mapping[start]) if start in mapping else value
        token=STRING_OBSERVER.set(observe)
        try:result=(parser or node['parser'])(node['data'])
        finally:STRING_OBSERVER.reset(token)
        self.decoded[key]=result;return result

    def bind(self,value,kind,*,renderer='fixed_cursor',**kw):
        if not isinstance(value,FieldText):return
        scene=kw.get('scene')
        if scene:
            scene=deepcopy(scene);state=scene.setdefault('state',{})
            choices={'extras':dict(root=0,cg=1,movies=2,music=3,replay=4),
                     'profile':dict(selection=0,result=1,response=2),
                     'battle':dict(introduction=0,dialogue=1,choices=2,results=3)}
            if isinstance(state.get('view'),str):state['view']=choices[scene['family']][state['view']]
            kw['scene']=scene
        contract=dict(kind=kind,renderer=renderer,**kw)
        values=self.bound.setdefault(value.field_id,[])
        if contract not in values:values.append(contract)

    def plain(self,value,width,scale,height,*,scene=None,tags=False,**kw):
        self.bind(value,'plain',renderer='measured_layout',width=width,scale=scale,height=height,
            tags=tags,scene=scene,**kw)

    def fixed(self,value,point,scale,left=0,right=960,*,align='left',scene=None,**kw):
        self.bind(value,'fixed',point=list(point),scale=scale,left=left,right=right,
            align=align,scene=scene,**kw)

    def dialog(self,value,group=1):
        from .compositioncommon import dialog_environment
        e=self.parse('env/env_dialog.dat',dialog_environment)
        self.plain(value,e['settings'][6],e['scales'][1],544,
            scene=dict(family='dialogs',state=dict(group=group),text_parameter='text'),dialog_group=group,
            dialog=dict(settings=e['settings'],tile=e['parts'][0][5],border=e['parts'][0][5]+e['parts'][6][5],button_scale=e['scales'][0]))

    def simple(self):
        from .composition import title_environment
        from .compositionsettings import settings_environment
        from .compositioncommon import dialog_environment
        if 'env/env_scene_title.dat:' in self.c.nodes:
            e=self.parse('env/env_scene_title.dat',title_environment)
            for i,value in enumerate(e.labels):
                if i>=len(e.points[0x314]):continue
                p=e.points[0x314][i];x=p[0]+e.signed(0x388)
                from .composition import blit
                shape=deepcopy(e.sprite[0x2f0]);shape['x'],shape['y']=p
                box=blit('',15,63,shape).destination
                self.fixed(value,[x,p[1]],e.floating(0x38c),max(0,box[0]),min(960,box[0]+box[2]),
                    scene=dict(family='title',state=dict(selected=i)))
        if 'env/env_option.dat:' in self.c.nodes:
            e=self.parse('env/env_option.dat',settings_environment);point=e.point[0x4b0];scale=e.floating(0x4ac)
            for page,key in ((0,0x14c),(1,0x1d0)):
                for row,labels in enumerate(e.string_rows[key]):
                    for choice,value in enumerate(labels):
                        state=dict(page=page,selected=row)
                        if page==0 and row in (3,4,5,6):state['text_toggle_'+str(row-3)]=choice==0
                        if page==1 and row==5:state['audio_toggle']=choice==0
                        self.fixed(value,point,scale,align='right',scene=dict(family='settings',state=state))
            for row,chars in enumerate(e.string_grids[0x3e4]):
                for char,labels in enumerate(chars):
                    for choice,value in enumerate(labels):
                        state=dict(page=2,selected=row,voice_character=char)
                        if row:state['voice_'+str(char)]=choice==0
                        else:state['voice_mode']=choice
                        self.fixed(value,point,scale,align='right',scene=dict(family='settings',state=state))
            self.dialog(e.save_question)
        if 'env/env_dialog.dat:' in self.c.nodes:
            e=self.parse('env/env_dialog.dat',dialog_environment)
            for group,buttons in enumerate(e['groups']):
                for i,(prefix,label) in enumerate(buttons):
                    self.bind(prefix,'glyph_prefix',renderer='parser_data',note='Authored input-glyph prefix, not ordinary Latin text')
                    pos=e['buttons'][len(buttons)-1][i];x=480-e['settings'][3]//2+pos[0]
                    self.fixed(label,[x,0],e['scales'][0],x-e['focus'][4]//2,x+e['focus'][4]//2,align='center',
                        scene=dict(family='dialogs',state=dict(group=group)))

    def profile(self):
        from .compositionmodes import profile_environment
        if 'env/env_otaku_mode.dat:' not in self.c.nodes:return
        e=self.parse('env/env_otaku_mode.dat',profile_environment)
        from .profileflow import rows,number
        import re
        response_scenes={};item_scenes={}
        for node in self.c.nodes.values():
            if not node['table'] or node['table'][2]!='profile_responses':continue
            ordinal=-1;event=0;sid=node['route'][-1]
            byrow={int(re.search(r'row (\d+)',s.role)[1]):node['id']+'#s'+str(i) for i,s in enumerate(node['spans'])}
            for row_index,row in enumerate(rows(node['data'].decode('cp932'),',')):
                if len(row)<3 or row[0]!='ON':continue
                if row[1]=='CHARA':ordinal+=1;event=0
                elif row[1]=='DATA':
                    state=dict(scene=sid,ordinal=ordinal,event=(event-3)%10)
                    if row_index in byrow:response_scenes[byrow[row_index]]=dict(family='profile',state=dict(state,view='response'))
                    item_scenes.setdefault((ordinal,number(row[2])),dict(family='profile',state=state));event+=1
        self.dialog(e['confirmation'])
        for i,table in enumerate(e['labels']):
            for j,value in enumerate(table):
                self.bind(value,'hex_color' if i==2 else 'profile_result_component',
                    renderer='parser_data' if i==2 else 'measured_layout',component=[i,j])
        from .compositionmodes import approach_environment
        result=approach_environment(self.c.source('env/env_approach.dat'))
        from .composition import message_environment
        cursors=message_environment(self.c.source('env/env_message_window.dat'))['cursors']
        excludes=[]
        from .composition import blit
        for shape,point in zip(cursors,result['cursor_positions']):
            shape=deepcopy(shape);shape['x'],shape['y']=point;excludes.append(blit('',1,2,shape).destination)
        self.bind(e['format'],'profile_result_template',renderer='measured_layout',width=result['text_width'],
            scale=result['text_scale'],height=min(544,result['frame']['y']+result['frame']['h'])-result['text_origin'][1],tags=True,
            panel_asset='resource.dat:1/12',panel_shape=result['fill'],origin=result['text_origin'],excludes=excludes,
            scene=dict(family='profile',state=dict(view='result')))
        for node in self.c.nodes.values():
            if not node['table']:continue
            for i,span in enumerate(node['spans']):
                value=FieldText(span.text,node['id']+'#s'+str(i))
                if span.role.startswith('profile_responses'):
                    from .composition import blit
                    box=blit('',1,0,e['response_window']).destination
                    self.plain(value,e['response_width'],e['response_scale'],min(544,box[1]+box[3])-e['response_origin'][1],
                        panel_asset='resource.dat:3/3/1',panel_shape=e['response_window'],origin=e['response_origin'],
                        scene=response_scenes.get(value.field_id))
                elif span.role.startswith('profile_items') and span.role.endswith('name'):
                    points=e['positions'];offset=e['label_offset'];frame=e['itemframe']
                    # Carousel clips to500..960. Use its settled focused slot3;
                    # edge rows intentionally animate out of the clipped viewport.
                    x,y=points[3];dx,dy=offset
                    self.fixed(value,[x+dx,y+dy],e['label_scale'],max(500,x),min(960,x+frame['w']),
                        scene=item_scenes.get((node['route'][-1],i//2)))
                elif span.role.startswith('profile_items') and span.role.endswith('description'):
                    self.bind(value,'profile_tips',scene=item_scenes.get((node['route'][-1],i//2)))

    def prompts(self):
        for field in self.c.fields.values():
            if field['role']=='dialog prompt':self.dialog(FieldText(field['original'],field['field_id']))

    def help(self):
        from .compositionlists import global_ui_environment
        style=self.parse('env/env_global.dat',global_ui_environment)
        def groups(data):
            r=Reader(data);r.take(47);out=[]
            rect=lambda:[r.word('i') for _ in range(4)]
            def items(rectangle,name):
                entries=[(r.word('i'),r.string()) for _ in range(r.count())]
                out.append(dict(rectangle=rectangle,entries=entries,name=name))
            def rows(rectangle,name):
                for i in range(r.count()):items(rectangle,name+'/'+str(i))
            common=rect();items(common,'Common');rows(rect(),'Settings');rows(rect(),'Save / load')
            root=rect();items(root,'Extras');rows(rect(),'CG');rows(rect(),'Music');rows(root,'Movies');rows(rect(),'Replay')
            # These tables have no own rectangle. They are supplied by their
            # navigation owner, which is not part of the supported compositions.
            rows(None,'Scenario navigation');items(None,'Scenario confirmation');items(None,'Scenario tools');rows(None,'Scenario skip')
            return out
        for group in self.parse('env/env_help_mgr.dat',groups):
            members=[dict(key=key,field_id=value.field_id) for key,value in group['entries']]
            name,_,row=group['name'].partition('/');index=int(row) if row else 0
            scene=None
            if name=='Common':scene=dict(family='backlog',state={})
            elif name=='Settings' and index<2:scene=dict(family='settings',state=dict(page=index,selected=3 if index else 0))
            elif name=='Save / load' and index<2:scene=dict(family='slots',state=dict(mode=index))
            elif name=='Extras':scene=dict(family='extras',state=dict(view='root'))
            elif name=='CG' and index<2:scene=dict(family='extras',state=dict(view='cg',image_view=bool(index)))
            elif name=='Music' and index<6:
                scene=dict(family='extras',state=dict(view='music',music_mode=(0,2,1)[index//2],playing=bool(index%2)))
            elif name in ('Movies','Replay') and index==0:scene=dict(family='extras',state=dict(view=name.lower()))
            for _,value in group['entries']:
                self.bind(value,'help_group',rectangle=group['rectangle'],members=members,
                    keys=list(map(str,style['keys'])),separator=str(style['separator']),
                    scale=style['scale'],gap=style['gap'],group=group['name'],scene=scene)

    def extras(self):
        from .compositionextras import extras_environment
        e=self.parse('env/env_omake.dat',extras_environment);c=e.common
        for i,value in enumerate(c['labels']):
            self.fixed(value,c['text_position'],c['text_scale'],align='right',scene=dict(family='extras',state=dict(view='root',selected=i)))
        self.dialog(c['prompt'])
        def text(value,point,scale,*,left=0,right=960,align='left',view=None,state=None):
            self.fixed(value,e.point[point],e.floating(scale),left,right,align=align,
                scene=dict(family='extras',state=dict(view=view,**(state or {}))))
        for i,row in enumerate(e.music):
            text(row['title'],0xd73c,0xd744,right=e.rect[0xd688][0]+e.rect[0xd688][2],view='music',state=dict(selected=i))
            text(row['title'],0xd76c,0xd774,align='center',view='music',state=dict(selected=i,playing=True))
        text(e.strings[0xd7d4],0xd73c,0xd744,right=e.rect[0xd688][0]+e.rect[0xd688][2],view='music',state=dict(unlocked=False))
        text(e.strings[0xd80c],0xd76c,0xd774,align='center',view='music')
        for point in (0xd778,0xd780):
            text(e.strings[0xd848],point,0xd788,view='music')
            if isinstance(e.strings[0xd848],FieldText):
                longest=max((row['duration'] for row in e.music),default=0)
                self.bound[e.strings[0xd848].field_id][-1].update(format_samples=[[longest//60,59],[e.signed(0xd844),e.signed(0xd844)]],normalize_numbers=True)
        for i,row in enumerate(e.movies):text(row[1],0xda78,0xda80,align='center',view='movies',state=dict(selected=i))
        text(e.strings[0xd89c],0xda78,0xda80,align='center',view='movies',state=dict(unlocked=False))
        clip=e.rect[0xdbe4]
        for i,row in enumerate(e.replays):
            for value,point,scale in ((row[0],0xdca0,0xdcb8),(row[1],0xdcb0,0xdcb8),(row[2],0xdcc0,0xdcc8)):
                right=e.point[0xdca8][0] if point==0xdca0 else clip[0]+clip[2]
                text(value,point,scale,left=clip[0],right=right,view='replay',state=dict(selected=i))
            p=e.point[0xdccc];frame=e.sprite[0xdd5c];height=min(544,frame['y']+frame['h'])-p[1]
            inset=p[0]-frame['x'];width=frame['w']-inset*2
            self.bind(row[3],'fixed_rows',point=p,scale=e.floating(0xdcd8),width=width,height=height,
                leading=e.signed(0xdcd4),separator=str(e.strings[0xdf08]),scene=dict(family='extras',state=dict(view='replay',selected=i)))
        text(e.strings[0xded0],0xdca8,0xdcbc,left=clip[0],right=e.point[0xdcb0][0],view='replay')
        text(e.strings[0xdf40],0xdcc0,0xdcc8,left=clip[0],right=clip[0]+clip[2],view='replay',state=dict(unlocked=False))
        text(e.strings[0xdf78],0xdccc,0xdcd8,view='replay',state=dict(unlocked=False))
        self.bind(e.strings[0xdf08],'separator',renderer='parser_data')
        self.dialog(e.strings[0xde60]);self.dialog(e.strings[0xde98])
        # Fraction marker sits inside every thumbnail's face frame.
        p=e.point[0xd404];face=e.sprite[0xd398]
        self.fixed(e.strings[0xd3cc],[p[0],p[1]],e.floating(0xd40c),0,face['w'])
        for key in (0xd440,0xd79c):
            self.bind(e.strings[key],'catalogue_metadata',renderer='metadata',note='Declared legacy gallery text; no draw consumer in the current source')
        for node in self.c.nodes.values():
            if node['table'] and node['table'][2]=='cg_titles':
                for i,span in enumerate(node['spans']):
                    self.bind(FieldText(span.text,node['id']+'#s'+str(i)),'catalogue_metadata',renderer='metadata',
                        note='CG draw path uses thumbnails and numeric ordinals; this name identifies the catalogue entry, not a drawn label')

    def slots(self):
        from .compositionlists import slot_environment
        e=self.parse('env/env_saveload.dat',slot_environment)
        x=e.sprite[0x168]['x'];clip=e.rect[0x148];right=min(960,clip[0]+clip[2])
        for key,point,scale,samples in ((0x468,0x294,0x2a4,[[9999,12,31]]),(0x4a0,0x29c,0x2a4,[[23,59]]),
                (0x4d8,0x2a8,0x2b0,[[99,99]]),(0x510,0x2a8,0x2b0,None)):
            p=e.point[point];limit=min([right]+[x+e.point[other][0] for other in (0x294,0x29c,0x2a8) if e.point[other][1]==p[1] and e.point[other][0]>p[0]])
            self.fixed(e.strings[key],[x+p[0],p[1]],e.floating(scale),max(0,clip[0]),limit,
                format_samples=samples,normalize_numbers=bool(samples),scene=dict(family='slots',state={}))
        self.bind(e.strings[0x580],'truncation_suffix',scale=e.floating(0x2bc),max_units=e.signed(0x2c0),
            note='Appended after the native truncated save title; keep concise')
        self.bind(e.strings[0x548],'save_metadata',renderer='metadata')
        for table in e.string_tables.values():
            for value in table:self.bind(value,'catalogue_metadata',renderer='metadata',note='Save-browser authored name table; no direct draw consumer in the supported source')

    def battle(self):
        from .compositionbattle import battle_environment
        e=self.parse('env/env_tukkomi.dat',battle_environment)
        for char,value in enumerate(e['names']):
            for side in range(2):
                p=e['name_positions'][side];w,h=e['name_sizes'][char];x=p[0]-w if side else p[0]
                center=p[0]+(-w//2 if side else w//2)+e['name_offsets'][char]
                self.fixed(value,[center,p[1]],e['name_scale'],x,x+w,align='center',
                    scene=dict(family='battle',state=dict(view='introduction',**{'side_'+str(side):char})))
        for i,value in enumerate(e['labels']):
            p=e['choice_positions'][i];off=e['label_positions'][i]
            center=p[0]+off[0];others=[q[0]+d[0] for q,d in zip(e['choice_positions'],e['label_positions'])]
            left=max([0]+[(center+x)//2 for x in others if x<center]);right=min([960]+[(center+x)//2 for x in others if x>center])
            self.fixed(value,[center,p[1]+off[1]],e['label_scale'],left,right,align='center',scene=dict(family='battle',state=dict(view='choices')))

    def legacy(self):
        for f in self.c.fields.values():
            if not f['editable'] or f['field_id'] in self.bound:continue
            value=FieldText(f['original'],f['field_id']);name=f['source'].rsplit('/',1)[-1];i=f['index']
            if name=='env_save_manager.dat':
                if i<3:self.bind(value,'save_metadata',renderer='metadata',max_units=(32,64,256)[i])
                elif i in (4,5):self.bind(value,'dialog_button_list',separator='＿')
                elif i in (46,47):self.bind(value,'requires_context',renderer='measured_layout',note='Storage requirement message is assembled from two fields and a runtime value; it must be checked as a composed message')
                elif i>=44:self.dialog(value,group=-1 if i in (44,45) else 0)
                else:self.bind(value,'requires_context',renderer='consumer_unverified',note='Legacy save path; current source binds mode2 strings44..55 only. Native case/formatting context is needed.')
            elif name=='env_global.dat':
                if i in (1,2,3):self.bind(value,'save_metadata',renderer='metadata',max_units=(32,64,256)[i-1])
                elif i in (9,10,23):self.bind(value,'dialog_button_list',separator='＿')
                else:self.bind(value,'requires_context',renderer='consumer_unverified',note='Bootstrap/platform fallback text; runtime owner/layout is required')
            elif name=='env_script.dat':
                if i in (1,2,3,7):self.bind(value,'save_metadata',renderer='metadata')
                elif i==0:self.bind(value,'catalogue_metadata',renderer='metadata',note='Legacy keyword-acquisition template; its opcode has no occurrence in the imported game')
            elif name=='env_keyword.dat':self.bind(value,'catalogue_metadata',renderer='metadata',note='Keyword name catalogue; supported approach choices use their own script labels. No direct draw consumer in the current source.')
            elif name=='env_system_menu.dat':self.dialog(value)
            elif name=='env_otaku_mode.dat' and i<5:
                self.bind(value,'catalogue_metadata',renderer='metadata',note='Legacy profile caption parts; live result text is assembled from the separate labels/template')
            elif name=='env_saveload.dat' and i==0:
                self.bind(value,'save_metadata',renderer='metadata',note='Native save-browser product name, not a game-font label')
            elif name in ('env_debug.dat','env_test.dat','env_first.dat'):
                if name=='env_first.dat':self.dialog(value,group=-1)
                else:self.bind(value,'requires_context',renderer='consumer_unverified',note='Debug/test native owner is not exposed in the current playable composition paths')


def annotate(catalog):
    """Bound contracts are immutable source facts; final font metrics come later."""
    b=Contracts(catalog)
    for method in (b.simple,b.profile,b.prompts,b.help,b.extras,b.slots,b.battle,b.legacy):
        try:method()
        except (KeyError,ValueError,OSError,IndexError) as error:
            # Minimal fixtures / incomplete imports retain explicit unresolved
            # fields. Never replace missing layout data with guessed dimensions.
            catalog.consumer_issues.append(dict(family=method.__name__,reason=str(error)))
    for identity,contracts in b.bound.items():
        field=catalog.fields[identity]
        if not field['editable']:continue
        field['contracts']=contracts;field['renderer']=contracts[0]['renderer']
        kinds={c['kind'] for c in contracts}
        metadata={'catalogue_metadata','save_metadata','hex_color','glyph_prefix','separator'}
        context='requires_context' in kinds or any(c['kind']=='help_group' and c['rectangle'] is None for c in contracts)
        field['fit_policy']='profile_tips' if kinds=={'profile_tips'} else 'requires_context' if context else 'metadata' if kinds<=metadata else 'consumer_checked'
        from .fontstyle import NOTES
        field['font_guidance']=NOTES.get(field['renderer'],'Structured metadata; ordinary font normalization is not applicable.')
