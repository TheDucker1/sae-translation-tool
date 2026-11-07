"""Choose text aliases for native variable-layout and fixed-cursor consumers."""
import re

from .uitextcodec import PRINTF


FIXED='fixed_cursor'
LAYOUT='measured_layout'
UNKNOWN='consumer_unverified'
NOTES={FIXED:'Native DrawString uses fixed cells. The upgraded font supplies readable Latin bitmap letters in those cells; spacing remains fixed.',
       LAYOUT:'Native layout uses measured glyph advances. The selected proportional font aliases are supported.',
       UNKNOWN:'The renderer for this field is not verified; font normalization is unavailable.'}


def ui_renderer(source,role,index,editable=True):
    if not editable:return 'protected'
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
    visible,separator,hidden=value.partition('\0')
    pattern=r'《[^》]*》|≪[^≫]*≫|[①-⑳]|'+PRINTF.pattern
    parts=re.split('('+pattern+')',visible)
    for i in range(0,len(parts),2):
        if renderer==FIXED:parts[i]=fixed_latin(parts[i],font)
        elif renderer==LAYOUT:parts[i]=full_width_text(parts[i],font)['text']
    text=''.join(parts)+separator+hidden
    note=NOTES.get(renderer,'Protected syntax is retained.')
    if renderer==FIXED and font is not None and 'A' not in font.cached:
        note='Auto-fit can upgrade this selected font to readable UI bitmap glyphs. Native cursor spacing remains fixed.'
    return dict(text=text,changed=text!=value,renderer=renderer,note=note)


def ui_proposal(project,field_id,text,font):
    from .uitext import get_catalog
    catalog=get_catalog(project)
    if field_id not in catalog.fields:raise ValueError('Unknown UI text field_id')
    field=catalog.fields[field_id]
    if not field['editable']:raise ValueError(field['reason'] or 'Protected UI field')
    if project.font_asset and field['renderer'] in {FIXED,LAYOUT} and font is None:
        from .text import TextPresentation
        key=(project.root,project.font_asset['manifest']['font_sha256'])
        cached=getattr(project,'_ui_style_font',None)
        if not cached or cached[0]!=key:
            cached=(key,TextPresentation(project.root,font_asset=bytes.fromhex(project.font_asset['data_hex'])))
            project._ui_style_font=cached
        font=cached[1]
    result=match_style(text,font,field['renderer']) if project.font_asset else dict(text=text,changed=False,renderer=field['renderer'],note='Select a proportional font asset to match font aliases.')
    from .uitextcodec import encode_span
    node=catalog.nodes[field['node_id']];encode_span(node['spans'][field['index']],result['text'])
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
