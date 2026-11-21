"""Choose text aliases for native variable-layout and fixed-cursor consumers."""
import re
from unicodedata import normalize

from .uitextcodec import PRINTF


FIXED='fixed_cursor'
LAYOUT='measured_layout'
UNKNOWN='consumer_unverified'
NOTES={FIXED:'Native DrawString uses fixed cells. Eligible labels can pack proportional Latin glyphs into those cells.',
       LAYOUT:'Native layout uses measured glyph advances. The selected proportional font aliases are supported.',
       'layout_setting':'Typed asset layout setting, not translated display text. Auto-fit derives its safe range from the original layout.',
       UNKNOWN:'The renderer for this field is not verified; font normalization is unavailable.'}


def ui_renderer(source,role,index,editable=True):
    if not editable:return 'protected'
    if role=='Profile tips column limit':return 'layout_setting'
    if role=='dialog prompt' or role.startswith('profile_responses'):return LAYOUT
    if role=='fixed UI label':return FIXED
    if role.startswith(('profile_items','cg_titles')) or role=='button choices':return FIXED
    name=source.rsplit('/',1)[-1]
    if name=='env_system_menu.dat':return LAYOUT
    if name in {'env_help_mgr.dat','env_scene_title.dat','env_dialog.dat','env_option.dat','env_omake.dat',
                'env_otaku_mode.dat','env_tukkomi.dat','env_keyword.dat'}:return FIXED
    if name=='env_save_manager.dat' and index in {44,52,55}:return LAYOUT
    return UNKNOWN


def fixed_latin(value,font=None):
    """Repair Latin aliases while retaining native separators and non-Latin text."""
    letters=any('A'<=c<='Z' or 'a'<=c<='z' or 'Ａ'<=c<='Ｚ' or 'ａ'<=c<='ｚ' for c in value)
    out=[]
    double_quote=font is not None and '"' in font.cached
    for c in value:
        if c=='＂' and double_quote:c='"'
        elif c in '“”' and double_quote and letters:c='"'
        elif 0xff01<=ord(c)<=0xff5e and c not in '＿＂':c=chr(ord(c)-0xfee0)
        elif letters:c={'‘':"'",'’':"'"}.get(c,c)
        out.append(c)
    return ''.join(out)


def match_style(value,font,renderer):
    """Keep placeholders, embedded tags, UI icons and hidden suffixes opaque."""
    from .textlayout import full_width_text
    if renderer==LAYOUT:
        text=full_width_text(value,font,preserve_format=True)['text']
        return dict(text=text,changed=text!=value,renderer=renderer,note=NOTES[LAYOUT])
    visible,separator,hidden=value.partition('\0')
    pattern=r'《[^》]*》|≪[^≫]*≫|[①-⑳]|'+PRINTF.pattern
    parts=re.split('('+pattern+')',visible)
    for i in range(0,len(parts),2):
        if renderer==FIXED:parts[i]=fixed_latin(parts[i],font)
    text=''.join(parts)+separator+hidden
    note=NOTES.get(renderer,'Protected syntax is retained.')
    if renderer==FIXED and font is not None and 'A' not in font.cached:
        note='Auto-fit can upgrade this selected font to readable UI bitmap glyphs. Native cursor spacing remains fixed.'
    return dict(text=text,changed=text!=value,renderer=renderer,note=note)


def project_ui_font(project):
    from .fontpatch import overridden_font_atlases
    from .pairspacing import config_for
    from .text import TextPresentation
    asset=project.font_asset
    key=(project.root,asset['manifest']['font_sha256'])
    cached=getattr(project,'_ui_style_font',None)
    if not cached or cached[0]!=key:
        font=TextPresentation(project.root,font_asset=bytes.fromhex(asset['data_hex']))
        font.asset_sha256=key[1];font.pair_spacing=config_for(asset)
        cached=(key,font);project._ui_style_font=cached
    cached[1].fit_atlas_overrides=overridden_font_atlases(project)
    return cached[1]


def ui_proposal(project,field_id,text,font,*,fit_tip=False,reflow=False,records=None):
    from .uitext import get_catalog,wire_value
    from .pairspacing import config_for
    catalog=get_catalog(project)
    if field_id not in catalog.fields:raise ValueError('Unknown UI text field_id')
    field=catalog.fields[field_id]
    if not field['editable']:raise ValueError(field['reason'] or 'Protected UI field')
    if project.font_asset and field['renderer'] in {FIXED,LAYOUT} and font is None:
        font=project_ui_font(project)
    original=text
    is_tip=field['fit_policy']=='profile_tips'
    if is_tip:text=normalize('NFC',text)
    result=match_style(text,font,field['renderer']) if project.font_asset else dict(text=text,changed=False,renderer=field['renderer'],note='Select a proportional font asset to match font aliases.')
    if is_tip and fit_tip and text!=field['original']:
        from .uifit import fit_profile_tip,profile_context
        context=profile_context(catalog,project.ui_text_assets if records is None else records)
        if context is not None:
            layout=fit_profile_tip(catalog,field,result['text'],font,context['columns'],reflow=reflow)
            note=f'Profile tip fits {len(layout["lines"])} of 3 rows at {layout["width"]}px per row.'
            if layout.get('native_character_wrap'):note+=' Uses the game’s character-based line breaks.'
            result.update(text=layout['text'],layout=layout,note=note)
        else:
            result['note']='Profile tip layout is unavailable without the profile environment.'
    result['changed']=result['text']!=original
    from .uitextcodec import encode_span
    node=catalog.nodes[field['node_id']];span=node['spans'][field['index']]
    encode_span(span,wire_value(span,result['text'],config_for(project.font_asset)))
    return dict(field_id=field_id,**result)


def translated_ui_edits(project):
    edits=[]
    for identity,record in project.ui_text_assets.items():
        proposal=ui_proposal(project,identity,record['text'],None)
        if proposal['changed']:edits.append((identity,record['text'],proposal['text']))
    return edits


def unverified_ui_fields(project):
    from .uitext import get_catalog
    catalog=get_catalog(project)
    return [identity for identity in project.ui_text_assets if catalog.fields[identity]['renderer']==UNKNOWN]
