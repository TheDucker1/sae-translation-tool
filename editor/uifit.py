"""Asset-backed profile tips and explicit UI fitting coverage."""
import re
from .text import units,unicode_text


TIP_COLUMNS='Profile tips column limit'


def fit_policy(role,renderer,editable=True):
    if not editable:return 'protected'
    if role==TIP_COLUMNS:return 'layout_setting'
    if role.startswith('profile_items') and role.endswith('description'):return 'profile_tips'
    if renderer=='consumer_unverified':return 'consumer_unverified'
    return 'font_only'


def profile_context(catalog,records):
    fields=[f for f in catalog.fields.values() if f['role']==TIP_COLUMNS]
    if not fields:return None
    field=fields[0];original=int(field['original'])
    columns=int(records.get(field['field_id'],{}).get('text',original))
    return dict(field=field,original=original,columns=columns)


def fixed_width(text,size):
    return sum(size//2 if 0x20<=ord(c)<=0x7e or 0xff61<=ord(c)<=0xffa0 else size for c in units(text))


def wrap_tip(text,separator,columns,width,size,*,reflow=False,hyphenate=True):
    """Three explicit native rows, bounded by pixels AND UTF16 split count."""
    if not separator or columns<1 or size<2 or width<size:raise ValueError('Invalid profile tips geometry')
    text=text.replace('\r\n','\n').replace('\r','\n').replace('\n',separator)
    if reflow:text=' '.join(part.strip() for part in text.split(separator))
    rows=[]
    fits=lambda value:len(units(value))<=columns and fixed_width(value,size)<=width
    for hard in text.split(separator):
        line=''
        for word in re.findall(r'\S+',hard):
            candidate=line+' '+word if line else word
            if fits(candidate):line=candidate;continue
            if line:rows.append(line);line=''
            while not fits(word):
                if not hyphenate:raise ValueError('Profile tips word exceeds a row; enable mechanical hyphens or shorten it')
                cut=0
                for i in range(1,len(word)):
                    if fits(word[:i]+'-'):cut=i
                    else:break
                if not cut:raise ValueError('Profile tips word cannot fit even with a hyphen')
                rows.append(word[:cut]+'-');word=word[cut:]
            line=word
        rows.append(line)
    if len(rows)>3:raise ValueError(f'Profile tips need {len(rows)} rows; native panel has three. Shorten the description.')
    return dict(text=separator.join(rows),lines=rows,width=width,size=size,columns=columns,
                line_widths=[fixed_width(row,size) for row in rows])


def tip_geometry(catalog,font):
    from .compositionmodes import profile_environment,profile_separator
    from .composition import EnvironmentLibrary
    env=profile_environment(catalog.source('env/env_otaku_mode.dat'))
    size=int(font.utility*env['description_scale'])
    # Authored18 full Japanese cells, not18 narrow Latin cells. Keep that area.
    return dict(size=size,width=env['columns']*size,
        separator=profile_separator(EnvironmentLibrary(catalog.root)))


def preserved_tip_edits(catalog,node,records,edits):
    """A larger shared count must not reflow untouched original Japanese rows."""
    context=profile_context(catalog,records)
    if not context or context['columns']==context['original'] or not node['table'] or node['table'][2]!='profile_items':return
    from .compositionmodes import description_lines,profile_separator
    from .composition import EnvironmentLibrary
    separator=profile_separator(EnvironmentLibrary(catalog.root))
    for i,span in enumerate(node['spans']):
        if span.role.endswith('description') and i not in edits:
            rows=description_lines(span.text,separator,context['original'])
            edits[i]=separator.join(unicode_text(row) for row in rows)


def validate_tips(catalog,node,records,spans):
    context=profile_context(catalog,records)
    if not context or not node['table'] or node['table'][2]!='profile_items':return
    from .compositionmodes import description_lines,profile_separator
    from .composition import EnvironmentLibrary
    from .compositionmodes import profile_environment
    import struct
    separator=profile_separator(EnvironmentLibrary(catalog.root))
    env=profile_environment(catalog.source('env/env_otaku_mode.dat'))
    utility=struct.unpack_from('<i',catalog.source('env/env_game_utility.dat'),3)[0]
    size=int(utility*env['description_scale']);width=context['original']*size
    for span in spans:
        if span.role.endswith('description'):
            rows=description_lines(span.text,separator,context['columns'])
            if any(fixed_width(row,size)>width for row in rows):
                raise ValueError('Profile tips extend outside the authored text area; use Auto-fit or shorten the description')
