"""Asset-backed profile tips and explicit UI fitting coverage."""
from functools import lru_cache
import re
from unicodedata import name
from .text import fixed_extent,units,unicode_text
from .wrapwords import can_mechanically_hyphenate


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


def row_metrics(font,size,text):
    from .choiceart import make_label
    packed=make_label(font,text,size,align='left')
    if packed:return len(packed.cells),packed.width
    row=units(text)
    return len(row),fixed_extent(row,size,font)


def wrap_tip(text,separator,columns,width,size,*,reflow=False,hyphenate=True,max_rows=3,metrics=None):
    """Three explicit native rows, bounded by pixels AND UTF16 split count."""
    if not separator or columns<1 or size<2 or width<size:raise ValueError('Invalid profile tips geometry')
    text=text.replace('\r\n','\n').replace('\r','\n').replace('\n',separator)
    if reflow:text=' '.join(part.strip() for part in text.split(separator))
    rows=[]
    metrics=lru_cache(maxsize=1024)(metrics or (lambda value:(len(units(value)),fixed_extent(units(value),size,None))))
    def fits(value):
        count,extent=metrics(value)
        return count<=columns and extent<=width
    for hard in text.split(separator):
        words=re.findall(r'\S+',hard)
        merged=' '.join(words)
        if fits(merged):
            rows.append(merged)
            continue
        line=''
        for word in words:
            candidate=line+' '+word if line else word
            if fits(candidate):line=candidate;continue
            if line:rows.append(line);line=''
            while not fits(word):
                if not can_mechanically_hyphenate(word):
                    raise ValueError('An accented word exceeds the row. Shorten it or choose an intentional break.')
                if not hyphenate:raise ValueError('Profile tips word exceeds a row; enable mechanical hyphens or shorten it')
                cut=0
                for i in range(1,len(word)):
                    if fits(word[:i]+'-'):cut=i
                    else:break
                if not cut:raise ValueError('Profile tips word cannot fit even with a hyphen')
                rows.append(word[:cut]+'-');word=word[cut:]
            line=word
        rows.append(line)
    if len(rows)>max_rows:raise ValueError(f'Text needs {len(rows)} rows; native panel has {"three" if max_rows==3 else max_rows}. Shorten the description.')
    return dict(text=separator.join(rows),lines=rows,width=width,size=size,columns=columns,
                line_widths=[metrics(row)[1] for row in rows],line_cells=[metrics(row)[0] for row in rows])


def tip_geometry(catalog,font=None):
    from .compositionmodes import profile_environment,profile_separator
    from .composition import EnvironmentLibrary
    env=profile_environment(catalog.source('env/env_otaku_mode.dat'))
    if font is None:
        import struct
        utility=struct.unpack_from('<i',catalog.source('env/env_game_utility.dat'),3)[0]
    else:utility=font.utility
    size=int(utility*env['description_scale'])
    # Authored18 full Japanese cells, not18 narrow Latin cells. Keep that area.
    return dict(size=size,width=env['columns']*size,
        separator=profile_separator(EnvironmentLibrary(catalog.root)))


def fit_profile_tip(catalog,field,text,font,columns,*,reflow=False,hyphenate=False,geometry=None):
    from .choiceart import ui_row_placement
    from .compositionmodes import description_lines
    geometry=geometry or tip_geometry(catalog,font)
    packing=ui_row_placement(field,font)
    if packing:metrics=lambda row:row_metrics(font,geometry['size'],row)
    else:
        def metrics(text):
            row=units(text)
            return len(row),fixed_extent(row,geometry['size'],font)
    separator=geometry['separator']
    value=text.replace('\r\n','\n').replace('\r','\n').replace('\n',separator)

    def native_rows():
        rows=description_lines(value,separator,columns)
        widths=[fixed_extent(row,geometry['size'],font) for row in rows]
        if max(widths,default=0)>geometry['width']:
            raise ValueError('Profile tips extend outside the authored text area')
        return dict(text=value,lines=[unicode_text(row) for row in rows],line_widths=widths,
                    line_cells=list(map(len,rows)),columns=columns,native_character_wrap=True,**geometry)

    try:
        if len(units(text))>4096:raise ValueError('UI text exceeds the 4096 UTF-16 unit editing limit')
        if font is not None and not reflow and not any('LATIN' in name(c,'') for c in text if c.isalpha()):
            from .textcleanup import japanese_text
            if japanese_text(text,font.format):
                return native_rows()
        try:
            return wrap_tip(value,columns=columns,reflow=reflow,hyphenate=hyphenate,metrics=metrics,**geometry)
        except ValueError:
            # Keep the original input path for older fonts when the native
            # character-based layout already produces valid rows.
            if not packing and not reflow:return native_rows()
            raise
    except ValueError as error:
        raise ValueError(f'{field["field_id"]}: {error} ({geometry["width"]}px per row, {columns} UTF-16 cells)') from error


def pack_rows(text,separator,size,encode):
    return separator.join(encode(row,size,align='left')[0] for row in text.split(separator))


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


def validate_tips(catalog,node,records,spans,font=None,*,packed=False):
    context=profile_context(catalog,records)
    if not context or not node['table'] or node['table'][2]!='profile_items':return
    from .compositionmodes import description_lines
    from .choiceart import ChoiceAtlas,ui_row_placement
    geometry=tip_geometry(catalog,font)
    separator,size,width=(geometry[key] for key in ('separator','size','width'))
    columns=context['columns']
    validation_atlas=ChoiceAtlas(font) if not packed and getattr(font,'pair_spacing',None) else None
    for i,span in enumerate(spans):
        if not span.role.endswith('description'):continue
        field_id=node['id']+'#s'+str(i)
        text=span.text.split('\0',1)[0]
        if validation_atlas and field_id in records and ui_row_placement(catalog.fields[field_id],font):
            text=pack_rows(text,separator,size,validation_atlas.encode)
        try:
            rows=description_lines(text,separator,columns)
        except ValueError as error:
            raise ValueError(f'{field_id}: {error} ({columns} UTF-16 cells per row)') from error
        for line,row in enumerate(rows,1):
            extent=fixed_extent(row,size,font)
            if extent>width:
                raise ValueError(f'{field_id}: profile tip row {line} is {extent}px; the panel fits {width}px. Use Auto-fit or shorten it.')
