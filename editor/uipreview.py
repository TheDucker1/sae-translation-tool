"""Read-only proposed/current UI text through the existing composition browser."""
from copy import copy
from pathlib import Path


def preview_snapshot(project,field_id,*,plan=None,selected=None):
    from .uitext import get_catalog,make_record
    c=get_catalog(project)
    if field_id not in c.fields:raise ValueError('Select a UI text field')
    recipes=[v['scene'] for v in c.fields[field_id].get('contracts',[]) if v.get('scene')]
    if not recipes:
        if c.fields[field_id]['fit_policy']=='retained':raise ValueError('This retained compatibility text has no drawn screen in the target Vita game. It remains editable/exportable; its consumer contract records the unused path.')
        raise ValueError('This field has no rendered composition. Inspect its role and consumer contract.')
    view=copy(project);view.ui_text_assets=project.ui_text_assets.copy()
    if plan is not None:
        if plan['revision']!=project.revision:raise ValueError('Stale Auto-fit plan; analyze again before previewing')
        view.font_asset=plan.get('font_asset',project.font_asset)
        for change in plan.get('ui_changes',[]):
            if selected is not None and change['field_id'] not in selected:continue
            key=change['field_id'];text=change['after_text']
            if text==c.fields[key]['original']:view.ui_text_assets.pop(key,None)
            else:view.ui_text_assets[key]=make_record(c,key,text)
    value=view.ui_text_assets.get(field_id,{}).get('text',c.fields[field_id]['original'])
    recipe=recipes[0];state=dict(recipe.get('state',{}))
    if recipe.get('composition'):
        combined=recipe['composition'];value=combined['joiner'].join(view.ui_text_assets.get(key,{}).get('text',c.fields[key]['original']) for key in combined['members'])
    if recipe.get('text_parameter')=='text':state['text']=value
    return view,dict(recipe,state=state),c,value


def show_ui_preview(owner,project,field_id,*,plan=None,selected=None,modal=False):
    from .imageassets import build_catalog
    from .fontpatch import effective_font
    from .compositionview import CompositionBrowser
    owner.guard_edit_snapshot(project,project.revision)
    view,recipe,c,value=preview_snapshot(project,field_id,plan=plan,selected=selected)
    image_catalog=getattr(owner,'_ui_fit_image_catalog',None)
    if image_catalog is None or image_catalog.root!=Path(project.root).resolve():
        image_catalog=build_catalog(project.root,getattr(owner.session,'descriptions',{}));owner._ui_fit_image_catalog=image_catalog
    try:image_catalog.verify()
    except (ValueError,OSError):
        image_catalog=build_catalog(project.root,getattr(owner.session,'descriptions',{}));owner._ui_fit_image_catalog=image_catalog
    browser=getattr(owner,'_ui_fit_preview',None)
    if browser is None:browser=CompositionBrowser(owner);owner._ui_fit_preview=browser
    records=view.ui_text_assets;font=effective_font(view,owner.session.text)
    browser.set_context(image_catalog,font,replacements=project.texture_assets,ui_text_assets=records,ui_text_catalog=c,defer=True)
    browser.setWindowTitle('Proposed UI text — read-only' if plan is not None else 'Current UI text — read-only')
    browser.show_recipe(recipe,value)
    if modal:browser.exec()
