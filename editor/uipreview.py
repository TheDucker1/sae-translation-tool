"""Read-only snapshots of text fitting through the existing composition browser."""
from copy import copy
from pathlib import Path


def _plan_view(project,plan,selected):
    from .uitext import get_catalog,make_record
    from .pairspacing import config_for
    c=get_catalog(project)
    view=copy(project);view.ui_text_assets=project.ui_text_assets.copy()
    if plan is not None:
        if plan['revision']!=project.revision:raise ValueError('Stale Auto-fit plan; analyze again before previewing')
        view.font_asset=plan.get('font_asset',project.font_asset)
        for change in plan.get('ui_changes',[]):
            if selected is not None and change['field_id'] not in selected:continue
            key=change['field_id'];text=change['after_text']
            if text==c.fields[key]['original']:view.ui_text_assets.pop(key,None)
            else:view.ui_text_assets[key]=make_record(c,key,text,pairing=config_for(view.font_asset))
    return view,c


def preview_snapshot(project,field_id,*,plan=None,selected=None):
    view,c=_plan_view(project,plan,selected)
    if field_id not in c.fields:raise ValueError('Select a UI text field')
    recipes=[v['scene'] for v in c.fields[field_id].get('contracts',[]) if v.get('scene')]
    if not recipes:
        if c.fields[field_id]['fit_policy']=='retained':raise ValueError('This retained compatibility text has no drawn screen in the target Vita game. It remains editable/exportable; its consumer contract records the unused path.')
        raise ValueError('This field has no rendered composition. Inspect its role and consumer contract.')
    value=view.ui_text_assets.get(field_id,{}).get('text',c.fields[field_id]['original'])
    recipe=recipes[0];state=dict(recipe.get('state',{}))
    if recipe['family']=='slots' and 'text' not in state:
        from .previewgallery import screen_presets
        sample=next(row['state'] for row in screen_presets(view) if row['screen_id']=='save')
        state.update({key:sample[key] for key in ('text','script_sample') if key in sample})
    if recipe.get('composition'):
        combined=recipe['composition'];value=combined['joiner'].join(view.ui_text_assets.get(key,{}).get('text',c.fields[key]['original']) for key in combined['members'])
    if recipe.get('text_parameter')=='text':state['text']=value
    return view,dict(recipe,state=state),c,value


def script_preview_frames(project,command_id,plan,*,before=False):
    from .engine import TEXT_OPS
    if plan['revision']!=project.revision:raise ValueError('Stale Auto-fit plan; analyze again before previewing')
    location=project.locations().get(command_id)
    if location is None:raise ValueError('Select a script text command')
    sid,index=location
    commands=project.scripts[sid].commands
    command=commands[index];opcode=command.opcode
    if opcode not in TEXT_OPS:raise ValueError('Select a script text command')
    change=next((row for row in plan['changes'] if row['command_id']==command_id),None)
    pages=change['pages'] if change and not before else [command.args]
    battle=change['dialogue_mode']=='battle' if change else any(c.opcode==0x3EF for c in commands)
    frames=[]
    def visible(text):
        return text.split('\0',1)[0]
    def frame(name,family,**state):
        frames.append(dict(label=name,family=family,state=state))
    for page,args in enumerate(pages,1):
        if opcode==0x64:
            value=visible(args['text'])
            if battle:
                frame(f'Page {page}','battle',view=1,bubble_1=3,dialogue_0=value)
            else:
                speaker=args.get('speaker',-1)
                frame(f'Page {page}','message',speaker=speaker if 0<=speaker<=8 else -1,text=value)
        elif opcode in {0x65,0x3F2}:
            first=1 if opcode==0x3F2 else 0
            values='\n'.join(visible(row['label']) for row in args['choices'][first:])
            if opcode==0x65:
                frame('Scenario choices','choices',text=values)
            else:
                frame('Battle choices','battle',view=2,choices=values)
        elif opcode==0x3EC:
            frame('Chapter captions','calendar',text='\n'.join(map(visible,args['texts'])))
        elif opcode==0x3F9:
            frame('Battle captions','battle',view=0,caption_0=visible(args['texts'][0]),caption_1=visible(args['texts'][1]))
        elif opcode==0x3F8:
            for i,name in enumerate(('Success','Failure')):
                frame(name,'profile',view=5,success=i==0,result_text=visible(args['outcomes'][i]['text']))
        elif opcode==0x3F6:
            rows=[[visible(parent['label']),*(visible(child['label']) for child in parent['children'])] for parent in args['parents']]
            topics='\n'.join(' | '.join(value.replace('\\','\\\\').replace('|','\\|') for value in row) for row in rows)
            frame('Approach topics','profile',view=4,topics=topics,child_focus=False)
            for i,_ in enumerate(rows):
                frame(f'Topic {i+1} choices','profile',view=4,topics=topics,selected=i,child_focus=True)
    return frames


def script_preview_snapshot(project,command_id,plan,frame,*,before=False,selected=None):
    frames=script_preview_frames(project,command_id,plan,before=before)
    if not 0<=frame<len(frames):raise ValueError('Preview frame is out of range')
    view,catalog=_plan_view(project,None if before else plan,selected)
    return view,frames[frame],catalog,[item['label'] for item in frames]


def show_ui_preview(owner,project,field_id,*,plan=None,selected=None,modal=False):
    view,recipe,c,value=preview_snapshot(project,field_id,plan=plan,selected=selected)
    title='Proposed UI text' if plan is not None else 'Current UI text'
    show_snapshot(owner,project,view,recipe,c,title,modal,override_text=value)


def show_snapshot(owner,project,view,recipe,catalog,title,modal,*,override_text=None):
    from .imageassets import build_catalog
    from .fontpatch import effective_font
    from .compositionview import CompositionBrowser
    owner.guard_edit_snapshot(project,project.revision)
    image_catalog=getattr(owner,'_ui_fit_image_catalog',None)
    if image_catalog is None or image_catalog.root!=Path(project.root).resolve():
        image_catalog=build_catalog(project.root,getattr(owner.session,'descriptions',{}));owner._ui_fit_image_catalog=image_catalog
    try:image_catalog.verify()
    except (ValueError,OSError):
        image_catalog=build_catalog(project.root,getattr(owner.session,'descriptions',{}));owner._ui_fit_image_catalog=image_catalog
    browser=getattr(owner,'_ui_fit_preview',None)
    if browser is None:browser=CompositionBrowser(owner);owner._ui_fit_preview=browser
    records=view.ui_text_assets;font=effective_font(view,owner.session.text)
    browser.set_context(image_catalog,font,replacements=project.texture_assets,ui_text_assets=records,ui_text_catalog=catalog,defer=True,
        battle_badges=project.battle_badges)
    browser.setWindowTitle(title+' — read-only')
    browser.show_recipe(recipe,override_text)
    if modal:browser.exec()
