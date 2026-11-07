"""Normalize once, then fit/check UI with the consumer's actual native rules."""
from copy import copy
import math,re
from .text import units,unicode_text
from .textlayout import TextLayoutService,native_newlines
from .uitextcodec import PRINTF
from .uifit import fixed_width,profile_context,tip_geometry,wrap_tip
from .uipanel import fit_panel


def substitute(value,arguments):
    """Native printf subset, retaining source positions of substituted operands."""
    out='';positions=[];at=0;arg=iter(arguments)
    for match in PRINTF.finditer(value):
        for i in range(at,match.start()):out+=value[i];positions.append((i,i+1))
        token=match[0]
        if token=='%%':text='%'
        else:
            item=next(arg)
            if token in ('%ls','%s'):text=str(item)
            elif re.fullmatch(r'%0?\d*[diu]',token):text=(token[:-1]+'d')%int(item)
            else:raise ValueError('Unsupported runtime format operand '+token)
        out+=text;positions.extend([(match.start(),match.end())]*len(text));at=match.end()
    for i in range(at,len(value)):out+=value[i];positions.append((i,i+1))
    if next(arg,None) is not None:raise ValueError('Unused format arguments')
    return out,positions


class ConsumerLayout(TextLayoutService):
    def __init__(self,font,contract,arguments=None):
        super().__init__(font,{});self.contract=contract;self.arguments=arguments
        if contract['width']<=0 or contract['height']<=0 or not math.isfinite(contract['scale']) or contract['scale']<=0:
            raise ValueError('Invalid native UI text region or font scale')
        if contract.get('dialog') and contract['dialog']['tile']<=0:raise ValueError('Invalid native dialog tile height')

    def dimensions(self,*args,**kw):
        c=self.contract
        return dict(width=c['width'],native_width=c['width'],scale=c['scale'],region=None,layout='ui_measured')

    def check_box(self,opcode,field,line_count,spec):
        c=self.contract;leading=int(self.font.height*c['scale']+self.font.leading);size=int(self.font.utility*c['scale'])
        height=max(0,line_count-1)*leading+size
        if height>c['height']:raise ValueError(f'UI text needs {height}px height; its region has {c["height"]}px. Shorten it.')
        if c.get('dialog'):
            d=c['dialog'];s=d['settings'];buttons=c['dialog_group']>=0
            content=line_count*leading+s[0]*2+(int(self.font.utility*d['button_scale'])+s[5] if buttons else 0)
            frame=math.ceil(content/d['tile'])*d['tile']+d['border']
            if frame>544:raise ValueError(f'Dialog grows to {frame}px, beyond the544px screen. Shorten it.')

    def projection(self,opcode,value,**kw):
        if self.arguments is None:return super().projection(opcode,value,**kw)
        expanded,positions=substitute(value,self.arguments)
        _,body,pairs,ruby=super().projection(opcode,expanded,**kw)
        pairs=[(char,positions[a][0],positions[b-1][1]) for char,a,b in pairs]
        return value,body,pairs,ruby


def fixed_check(value,c,font):
    size=int(font.utility*c['scale']);values=[]
    if PRINTF.search(value):
        if not c.get('format_samples'):raise ValueError('Formatted UI text needs runtime substitution context; raw placeholders cannot be measured as labels')
        for args in c['format_samples']:values.append(substitute(value,args)[0])
    else:values=[value]
    results=[]
    for text in values:
        if c.get('normalize_numbers'):text=unicode_text(font.format.normalize(units(text)))
        if any(ch in text for ch in '\r\n') or font.format.break_char in text:
            raise ValueError('This UI consumer is single-line; native line breaks are unsupported')
        missing=set(units(text))-(font.charset|font.cached.keys())
        if missing:raise ValueError('The game font has no glyphs for '+repr(unicode_text(''.join(sorted(missing)))))
        extent=fixed_width(text,size);measured=font.measure(units(text),size);x=c['point'][0]
        if c.get('align')=='center':x-=measured//2
        elif c.get('align')=='right':x-=measured
        right=x+extent
        if x<c['left'] or right>c['right']:
            raise ValueError(f'Single-line UI occupies x={x}..{right} ({extent}px); region x={c["left"]}..{c["right"]}. Shorten this label; it cannot wrap.')
        results.append(dict(text=text,width=extent,x=x,right=right,size=size))
    return results


def current(catalog,working,identity):return working.get(identity,catalog.fields[identity]['original'])


def profile_variants(catalog,working):
    labels=[{}, {}, {}];template=None
    for identity,f in catalog.fields.items():
        for c in f.get('contracts',[]):
            if c['kind'] in ('profile_result_component','hex_color'):
                table,index=c['component'];labels[table][index]=current(catalog,working,identity)
            elif c['kind']=='profile_result_template':template=(identity,c)
    variants=[[labels[0][i],labels[2][j],labels[1][j]] for i in labels[0] for j in labels[1] if j in labels[2]]
    return template,variants


def field_fit(identity,value,catalog,working,font,*,reflow,hyphenate,skip=False,project=None):
    f=catalog.fields[identity];checks=[];original=value
    contracts=f.get('contracts',[])
    if not contracts:raise ValueError('No native fitting contract is available for this source/layout')
    for c in contracts:
        kind=c['kind']
        if kind=='profile_tips':continue
        if kind=='requires_context':raise ValueError(c['note'])
        if kind=='fixed':checks.extend(fixed_check(value,c,font))
        elif kind=='retained_text':checks.append(dict(kind=kind,rendered=False,note=c['note']))
        elif kind=='composed_dialog':
            if c['joiner'] not in font.cached:
                raise ValueError('Native storage amount is an unsupported runtime glyph. Enable the font asset upgrade in Auto-fit to display its correct numeric value.')
            pieces=[native_newlines(current(catalog,working,key),font.format) for key in c['members']]
            if any(c['joiner'] in piece for piece in pieces):raise ValueError('Storage amount is inserted by the executable; do not put its runtime marker in either text fragment')
            packet=ConsumerLayout(font,c).wrap(0x3f8,c['joiner'].join(pieces),reflow=reflow,hyphenate=hyphenate)
            parts=packet['text'].split(c['joiner'])
            if len(parts)!=len(c['members']):raise ValueError('Wrapping changed the native storage insertion point')
            working.update(zip(c['members'],parts));value=working[identity]
            checks.append(dict(kind=kind,members=c['members'],runtime_display=c['runtime_display'],
                line_count=packet['line_count'],line_widths=packet['line_widths'],width=c['width'],
                note='Keep both fragment proposals checked; the runtime amount is supplied by the font asset, not serialized into the text.'))
        elif kind=='plain':
            value=native_newlines(value,font.format)
            prepared,_=font.format.prepare(value,font_tags=c.get('tags',False))
            missing=set(prepared)-(font.charset|font.cached.keys()|{font.format.break_char})
            if missing:raise ValueError('The game font has no glyphs for '+repr(unicode_text(''.join(sorted(missing)))))
            def fit(region):
                layout=ConsumerLayout(font,region)
                if skip:
                    glyphs=font.layout(prepared,region['width'],region['scale'])
                    count=max((g['line'] for g in glyphs),default=-1)+1;layout.check_box(0,'',count,{})
                    return dict(text=value,line_count=count,width=region['width'],normalization_only=True)
                packet=layout.wrap(0x3f8,value,reflow=reflow,hyphenate=hyphenate)
                return dict(text=packet['text'],line_count=packet['line_count'],line_widths=packet['line_widths'],
                    width=region['width'],panel_capacity=region.get('panel_capacity'),row_widths=region.get('row_widths'))
            packet=fit_panel(project,catalog,font,c,fit);value=packet.pop('text');checks.append(packet)
        elif kind=='fixed_rows':
            if c['leading']<=0 or c['height']<=0:raise ValueError('Invalid native description row spacing or height')
            size=int(font.utility*c['scale']);rows=max(1,(c['height']-size)//c['leading']+1)
            if skip:
                lines=value.split(c['separator']);widths=[fixed_width(line,size) for line in lines]
                if max(widths,default=0)>c['width']:raise ValueError('Existing description exceeds its authored row width')
                packet=dict(text=value,lines=lines,line_widths=widths,normalization_only=True)
            else:packet=wrap_tip(value,c['separator'],4096,c['width'],size,reflow=reflow,hyphenate=hyphenate,max_rows=rows)
            if len(packet['lines'])>rows:raise ValueError(f'UI description needs {len(packet["lines"])} rows; panel fits {rows}')
            value=packet['text'];checks.append(packet)
        elif kind=='help_group':
            if c['rectangle'] is None:raise ValueError('Scenario-navigation help requires its native owner rectangle; this table does not store one')
            size=int(font.utility*c['scale']);cursor=0;left=c['rectangle'][0];right=left+c['rectangle'][2]
            occupied=[];slots=[]
            for entry in c['members']:
                text=current(catalog,working,entry['field_id'])
                if '\n' in text or '\r' in text or font.format.break_char in text:raise ValueError('Button-help labels are single-line')
                missing=set(units(text))-(font.charset|font.cached.keys())
                if missing:raise ValueError('The game font has no glyphs for '+repr(unicode_text(''.join(sorted(missing)))))
                prefix=0;draw_prefix=0
                if entry['key']!=-1:
                    key=c['keys'][entry['key']];prefix=font.measure(units(key),font.utility)+font.measure(units(c['separator']),size)
                    draw_prefix=font.measure(units(key),0)
                nxt=cursor+prefix+font.measure(units(text),size)+c['gap'];x=right-nxt+draw_prefix
                end=x+fixed_width(text,size);occupied.append((x,end));slots.append((x-draw_prefix,end));cursor=nxt
            if any(a<left or b>right for a,b in occupied):raise ValueError(f'Combined button help exceeds its {c["rectangle"][2]}px strip. Shorten labels in this help row.')
            ordered=sorted(slots)
            if any(a[1]>b[0] for a,b in zip(ordered,ordered[1:])):raise ValueError('Combined button help overlaps neighboring labels/icons. Shorten labels in this help row.')
            checks.append(dict(group=c['group'],bounds=occupied,width=c['rectangle'][2]))
        elif kind=='hex_color':
            if not re.fullmatch('[0-9a-fA-F]{6}',value):raise ValueError('Profile color is a6-digit RGB value, not translated text')
            checks.append(dict(kind=kind))
        elif kind in ('profile_result_component','profile_result_template'):
            template,variants=profile_variants(catalog,working)
            if not template:raise ValueError('Profile result template/layout missing')
            tid,contract=template;text=current(catalog,working,tid)
            def fit_result(region):
                candidate=text
                if kind=='profile_result_template' and not skip:
                    for index,args in enumerate(variants):
                        candidate=ConsumerLayout(font,region,args).wrap(0x3f8,candidate,reflow=reflow and index==0,hyphenate=hyphenate)['text']
                for args in variants:
                    full=substitute(candidate,args)[0]
                    if len(units(full))>=128:raise ValueError('Combined profile result exceeds its128-unit native buffer')
                    plain,_=font.format.prepare(full,font_tags=True);glyphs=font.layout(plain,region['width'],region['scale'])
                    ConsumerLayout(font,region).check_box(0,'',max((g['line'] for g in glyphs),default=-1)+1,{})
                return candidate,region
            text,region=fit_panel(project,catalog,font,contract,fit_result)
            if kind=='profile_result_template':value=text
            checks.append(dict(kind='profile_result',variants=len(variants),width=region['width'],
                panel_capacity=region.get('panel_capacity'),row_widths=region.get('row_widths')))
        elif kind=='dialog_button_list':
            from .compositioncommon import dialog_environment
            e=dialog_environment(catalog.source('env/env_dialog.dat'));parts=value.split(c['separator'])
            if not 1<=len(parts)<=3:raise ValueError('Native dialog supports1–3 buttons')
            for i,label in enumerate(parts):
                x=480-e['settings'][3]//2+e['buttons'][len(parts)-1][i][0]
                checks.extend(fixed_check(label,dict(kind='fixed',scale=e['scales'][0],point=[x,0],align='center',left=x-e['focus'][4]//2,right=x+e['focus'][4]//2),font))
        elif kind=='truncation_suffix':
            if len(units(value))>1:raise ValueError('Native save-title truncation reserves one UTF16 unit for this suffix; use one glyph')
            checks.append(dict(kind=kind))
        elif kind in ('catalogue_metadata','save_metadata','glyph_prefix','separator'):
            if c.get('max_units') and len(units(value))>=c['max_units']:raise ValueError(f'Text exceeds its {c["max_units"]}-unit platform metadata buffer (including terminator)')
            checks.append(dict(kind=kind,note=c.get('note','Structured metadata; no game-font box')))
        elif kind in ('keyword_template','keyword_component'):
            raise ValueError('Keyword acquisition text needs its native notification layout; it is separate from approach choice cards')
        else:raise ValueError('Unsupported UI contract '+kind)
    return value,checks


def analyze_ui(project,font,asset,*,reflow=False,hyphenate=True,skip_japanese=True):
    from .uitext import get_catalog
    from .fontstyle import ui_proposal
    from .textcleanup import japanese_text
    catalog=get_catalog(project);view=copy(project);view.font_asset=asset
    before={identity:r['text'] for identity,r in project.ui_text_assets.items()};working=dict(before);changes=[];issues=[];checks=[]
    for identity in before:
        for contract in catalog.fields[identity].get('contracts',[]):
            if contract['kind']=='composed_dialog':
                for key in contract['members']:working.setdefault(key,catalog.fields[key]['original'])
    # All dependent groups and templates see the final normalized font strings.
    for identity,text in list(working.items()):
        try:working[identity]=ui_proposal(view,identity,text,font)['text']
        except ValueError as error:issues.append(dict(script_id=None,command_id=identity,reason=str(error)))
    context=profile_context(catalog,project.ui_text_assets);tip=None
    if context and any(catalog.fields[key]['fit_policy']=='profile_tips' and not(skip_japanese and japanese_text(value,font.format)) for key,value in before.items()):
        tip=tip_geometry(catalog,font);tip['columns']=context['original']*2;working[context['field']['field_id']]=str(tip['columns'])
    for identity in list(working):
        f=catalog.fields[identity];value=working[identity];skip=skip_japanese and japanese_text(value,font.format)
        try:
            if f['fit_policy']=='layout_setting':assessment=[dict(kind='layout_setting')]
            elif f['fit_policy']=='profile_tips':
                if tip and not skip:
                    packet=wrap_tip(value,reflow=reflow,hyphenate=hyphenate,**tip);value=packet['text'];assessment=[packet]
                else:
                    from .compositionmodes import description_lines
                    geometry=tip_geometry(catalog,font);columns=context['columns']
                    rows=description_lines(value,geometry['separator'],columns)
                    widths=[fixed_width(unicode_text(row),geometry['size']) for row in rows]
                    if max(widths,default=0)>geometry['width']:raise ValueError('Existing profile tips extend outside the authored text area')
                    assessment=[dict(line_count=len(rows),line_widths=widths,width=geometry['width'],columns=columns,normalization_only=True)]
            else:value,assessment=field_fit(identity,value,catalog,working,font,reflow=reflow,hyphenate=hyphenate,skip=skip,project=project)
            working[identity]=value
            note=('Retained compatibility text; no active Vita draw consumer.' if f['fit_policy']=='retained'
                else 'Native consumer checked: '+', '.join(dict.fromkeys(c['kind'] for c in f.get('contracts',[]))))
            if any(c['kind']=='composed_dialog' for c in f.get('contracts',[])):note+=' Keep both storage fragment proposals checked.'
            if f['fit_policy']=='profile_tips':note=f'Profile tips: {tip["width"]}px, {tip["columns"]} units, three rows. Keep the shared column-limit setting checked.' if tip else 'Profile tips: unchanged Japanese text'
            if f['fit_policy']=='layout_setting':note='Shared profile-tip column limit. Untouched original rows are preserved; keep checked with the wider tip proposals.'
            checks.append(dict(field_id=identity,command_id=identity,fit_policy=f['fit_policy'],ui_check=True,reason=note,assessment=assessment))
        except (ValueError,KeyError,IndexError,StopIteration,OSError) as error:
            issues.append(dict(script_id=None,command_id=identity,reason=str(error)))
            # Safe normalization can still be applied; failed wrapping is never exported.
        original=before.get(identity,f['original'])
        if value!=original:
            changes.append(dict(field_id=identity,command_id=identity,before_text=original,after_text=value,
                renderer=f['renderer'],contracts=f.get('contracts',[]),
                assessment=next((r['assessment'] for r in reversed(checks) if r['field_id']==identity),[]),
                note=next((r['reason'] for r in reversed(checks) if r['field_id']==identity),'Font normalization only; fitting reported separately.')))
    return changes,issues,checks


def validate_structure(field,text):
    """Check native non-display fields before storing a translation delta."""
    for c in field.get('contracts',[]):
        if c['kind']=='composed_dialog' and c['joiner'] in text:
            raise ValueError('The runtime amount glyph is inserted by the executable, not stored in either fragment')
        if c['kind']=='hex_color' and not re.fullmatch('[0-9a-fA-F]{6}',text):raise ValueError('Profile RGB field requires six hexadecimal digits')
        if c['kind']=='separator' and not text:raise ValueError('Native text separator cannot be empty')
        if c['kind']=='truncation_suffix' and len(units(text))>1:raise ValueError('Native save-title suffix reserves one UTF16 unit')
