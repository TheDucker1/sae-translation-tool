"""Translation formatting that writes native breaks, using shared game metrics."""
from copy import deepcopy
from pathlib import Path
import re
import unicodedata
from .engine import TEXT_OPS, text_fields
from .scriptcodec import put
from .text import fixed_extent, units, unicode_text
from .textregions import region_area
from .pairspacing import shape_script


def field_path(name):return tuple(int(x) if x.isdecimal() else x for x in name.replace('[','.').replace(']','').split('.'))


def native_newlines(value,formatter):
    """Convert editor line endings outside control tags; never rewrite operands."""
    if formatter is None:return value
    opening,closing=formatter.tokens[0][0],formatter.tokens[1][0]
    parts=re.split('('+re.escape(opening)+'.*?'+re.escape(closing)+')',value,flags=re.DOTALL)
    for i in range(0,len(parts),2):parts[i]=re.sub(r'\r\n|\r|\n',formatter.break_char,parts[i])
    return ''.join(parts)


def normalize_arguments(opcode,args,formatter):
    result=deepcopy(args)
    for path,value in text_fields(dict(opcode=opcode,args=args)):
        put(result,field_path(path),native_field(opcode,value,formatter))
    return result


def editable_newlines(value,formatter):
    return value.replace(formatter.break_char,'\n') if formatter else value


def reflow_breaks(value,formatter,*,collapse_padding=False):
    """Explicit repair option for old wrapping; keep tags and ruby readings."""
    opening,closing=formatter.tokens[0][0],formatter.tokens[1][0]
    parts=re.split('('+re.escape(opening)+'.*?'+re.escape(closing)+')',value,flags=re.DOTALL)
    reading=False
    for i,part in enumerate(parts):
        if i%2:
            tag=units(part[1:-1]).upper()
            if tag==formatter.following[9]:reading=True
            elif units(part).upper()==formatter.following[10]:reading=False
        elif not reading:
            part=part.replace(formatter.break_char,' ').replace('\r\n',' ').replace('\r',' ').replace('\n',' ')
            parts[i]=re.sub(r' {2,}', ' ', part) if collapse_padding else part
    return ''.join(parts)


def supports_breaks(opcode):return opcode in {0x64,0x3f2,0x3f8}


def native_field(opcode,value,formatter):
    converted=native_newlines(value,formatter)
    if not supports_breaks(opcode):
        if converted!=value:raise ValueError('This label/caption is drawn as a single line by the game; shorten it instead of inserting a newline')
        return value
    if opcode==0x64 and formatter is not None:formatter.ordinary(converted)
    return converted


def is_text_field(opcode,path):
    name='.'.join(str(x) for x in path)
    patterns={0x64:r'text',0x65:r'choices\.\d+\.label',0x3ec:r'texts\.[01]',
              0x3f2:r'choices\.\d+\.label',0x3f6:r'parents\.\d+\.(?:label|children\.\d+\.label)',
              0x3f8:r'outcomes\.[01]\.text',0x3f9:r'texts\.[01]'}
    return bool(re.fullmatch(patterns.get(opcode,r'(?!)'),name))


def full_width_text(value,font,*,controls=True,preserve_speaker=False,preserve_format=False):
    """Convert display text, never commands or the reserved native break marker."""
    f=font.format;opening,closing=f.tokens[0][0],f.tokens[1][0]
    result=[];converted=0;preserved=set();i=0;available=font.charset|font.cached.keys();previous='';double_open=False
    from .uitextcodec import PRINTF
    speaker_end=value.find(f.following[1]) if preserve_speaker else 0
    if speaker_end>0:result.append(value[:speaker_end]);i=speaker_end
    while i<len(value):
        c=value[i]
        if c=='\0':result.append(value[i:]);break  # Hidden suffix is opaque.
        if preserve_format and c=='%':
            token=PRINTF.match(value,i)
            if token:result.append(token[0]);i=token.end();previous='x';continue
        if preserve_format and c=='≪':
            end=value.find('≫',i+1)
            if end<0:raise ValueError('Unterminated UI control')
            result.append(value[i:end+1]);i=end+1;continue
        if controls and c==opening:
            end=value.find(closing,i+1)
            if end<0:raise ValueError('Unterminated text control')
            result.append(value[i:end+1]);i=end+1;continue
        if '!'<=c<='~':
            candidate=chr(ord(c)+0xfee0)
            if c in "'\"":
                quote=('”' if double_open else '“') if c=='"' else ('’' if previous.isalnum() or previous in '.,!?)]}」』' else '‘')
                if quote in font.cached:candidate=quote
                if c=='"':double_open=not double_open
            try:encodable=candidate.encode('cp932').decode('cp932')==candidate
            except UnicodeError:encodable=False
            if (candidate!=f.break_char and candidate in available
                    and f.normalize(candidate)==candidate and encodable):
                c=candidate;converted+=1
            else:preserved.add(c)
        if c in '“”':double_open=c=='“'
        result.append(c);previous=c;i+=1
    return dict(text=''.join(result),converted_characters=converted,preserved_ascii=''.join(sorted(preserved)))


def measured_script_field(opcode, field):
    return supports_breaks(opcode) and (opcode != 0x3F2 or field != 'choices[0].label')


def script_font_text(font, value, opcode, args, field, *, authored):
    """Select display glyphs with the same rules in preview and archive output."""
    if font is None:
        return value
    if authored and getattr(font, 'asset_sha256', None):
        if measured_script_field(opcode, field):
            value = full_width_text(value, font, preserve_speaker=opcode == 0x64)['text']
        elif opcode in TEXT_OPS and not supports_breaks(opcode):
            from .fontstyle import FIXED, match_style
            value = match_style(value, font, FIXED)['text']
    return shape_script(value, opcode, args, field, font.format, getattr(font, 'pair_spacing', None),keyword_markup=authored)


class TextLayoutService:
    normalize_script_font = True

    def __init__(self,font,settings,*,project=None,script_id=None,command=None,regions=None):
        self.font=font;self.settings=settings;self.command=command;self.project=project
        self.proportional=bool(getattr(project,'font_asset',None) or getattr(font,'asset_sha256',None))
        # Battle ownership is established while loading the file, before Start.
        self.mode='battle' if project is not None and any(c.opcode==0x3ef for c in project.scripts[script_id].commands) else 'ordinary'
        self.regions=regions
        if self.regions is None and project is not None:
            from .textregions import BattleTextRegions
            self.regions=BattleTextRegions(project,font,settings)

    def resolve_mode(self,mode):
        if mode not in {'auto','ordinary','battle'}:raise ValueError('Unknown dialogue layout')
        return self.mode if mode=='auto' else mode

    def label_width(self,value,scale):
        size=int(self.font.utility*scale)
        return fixed_extent(units(value),size,self.font)

    def convert_dialogue_width(self,value,*,width=None,dialogue_mode='auto',preserve_speaker=False,convert=True):
        """One-for-one visible conversion without changing queue indices or breaks."""
        conversion=full_width_text(value,self.font,preserve_speaker=preserve_speaker) if convert else dict(text=value,converted_characters=0,preserved_ascii='')
        source=conversion.pop('text')
        # Validate executable controls, including the timed explicit-break ban.
        self.font.format.ordinary(source)
        geometry=self.measure_dialogue(source,width=width,dialogue_mode=dialogue_mode)
        geometry['measurement']='converted_command_text'
        return dict(**geometry,editor_text=editable_newlines(source,self.font.format),changed=source!=value,
                    full_width_conversion=conversion if convert else None,inserted_breaks=0,hyphenations=0,
                    break_character=self.font.format.break_char,breaks_supported=True,
                    wrapping_skipped='Conversion only; existing timing, glyph indices and breaks preserved.')

    def measure_dialogue(self,value,*,width=None,dialogue_mode='auto'):
        """Read-only geometry; queue timing/index restrictions do not hide text.

        Uses the original string (LF/CR are glyphs, not native breaks). This does
        not prepare executable queued text or assert appended-buffer semantics.
        """
        spec=self.dimensions(0x64,value=value,width=width,dialogue_mode=dialogue_mode);f=self.font.format
        parsed=f.ordinary(value,geometry_only=True);body,_=f.prepare(parsed['body'],unit_text=True)
        display = self.display_body(0x64, value, body, '')
        glyphs=self.font.layout(display,width=spec['native_width'],scale=spec['scale'],ruby=parsed['ruby'])
        count=max((g['line'] for g in glyphs),default=0)+1
        region=next((r for r in self.battle_regions(0x64,'',value,dialogue_mode) if r['capacity']==count),None)
        if region:spec=self.dimensions(0x64,value=value,width=width,dialogue_mode=dialogue_mode,battle_region=region)
        lines=['' for _ in range(count)];widths=[0]*count
        for g in glyphs:
            line=g['line'];lines[line]+=body[g['index']];widths[line]=max(widths[line],g['x']+int(g['advance']*spec['scale']))
        ruby_overflow=[]
        for begin,end,reading in parsed['ruby']:
            span=[g for g in glyphs if begin<=g['index']<end]
            if not span:continue
            extent=sum(int(g['advance']*spec['scale']) for g in span)
            reading_width=self.font.measure(reading,int(self.font.utility*self.font.ruby_scale))
            x=span[0]['x']+extent//2-reading_width//2
            if x<0 or x+reading_width>spec['width']:ruby_overflow.append(dict(begin=begin,end=end,left=x,right=x+reading_width))
        return dict(text=value,body=unicode_text(body),speaker=unicode_text(parsed['name']),
                    lines=[unicode_text(line) for line in lines],line_widths=widths,line_count=count,
                    ruby_overflow=ruby_overflow,contains_plain_newlines='\n' in value or '\r' in value,
                    timed_markers=len(parsed['markers']),measurement='original_command_text',**spec)

    def battle_regions(self,opcode,field,value,dialogue_mode):
        if not self.regions or (opcode!=0x3f2 and (opcode!=0x64 or self.resolve_mode(dialogue_mode)!='battle')):
            return []
        match=re.fullmatch(r'choices\[(\d+)\]\.label',field)
        control=int(match[1])-1 if match else None
        if control==-1:return []
        ruby=opcode==0x64 and bool(self.font.format.ordinary(value,geometry_only=True)['ruby'])
        return self.regions.rectangles(choice=opcode==0x3f2,control=control,ruby=ruby)

    def dimensions(self,opcode,*,field='',value='',width=None,dialogue_mode='auto',battle_region=None):
        f=self.font;authored=True
        dialogue_mode=self.resolve_mode(dialogue_mode)
        if opcode==0x64:
            default=f.width if dialogue_mode=='ordinary' else self.settings['battle']['width'];scale=f.scale
        elif opcode==0x3f2:default=self.settings['battle']['width'];scale=f.scale
        elif opcode==0x3f8:default=self.settings['approach']['result_width'];scale=self.settings['approach']['result_scale']
        else:
            default=None;authored=False
            scale={0x65:self.settings['selection']['scale'],0x3ec:self.settings['chapter_text']['scale'],
                   0x3f6:self.settings['approach']['scale'],0x3f9:self.settings['battle']['text_scale']}.get(opcode)
            if opcode==0x3f6 and '.children[' in field:scale=self.settings['selection']['scale']
        if scale is None:raise ValueError('This opcode has no editable text layout')
        width_source='authored_box'
        packed_width = None
        if opcode in {0x65, 0x3F6} and getattr(f, 'pair_spacing', None):
            from .choiceart import approach_metrics, make_label
            packed = make_label(f, value, int(f.utility * scale))
            if packed:
                metrics = getattr(f, 'approach_card_metrics', None)
                if metrics is None:
                    metrics = f.approach_card_metrics = approach_metrics(f.root, f.utility)
                _, default = metrics['child' if opcode == 0x65 or '.children[' in field else 'parent']
                packed_width = packed.width
                authored = True
                width_source = 'choice_card'
        if default is None:
            width_source='screen_geometry'
            def centered(points,offset=0):
                centers=[p[0]+offset for p in points if 0<p[0]+offset<960]
                if not centers:raise ValueError('No visible single-line text anchor')
                measured=f.measure(units(value),int(f.utility*scale))
                starts=[x-measured//2 for x in centers]
                if min(starts)<0:raise ValueError('Single-line text extends beyond the left screen edge')
                return int(min(960-x for x in starts))
            if opcode==0x3ec:
                points=self.settings['chapter_text']['positions'];match=re.fullmatch(r'texts\[([01])\]',field)
                points=[points[int(match[1])]] if match else points
                default=min(960-p[0] for p in points)
                from .choiceart import make_label
                packed=make_label(f,value,int(f.utility*scale),align='left')
                if packed:packed_width=packed.width
            elif opcode==0x65 or opcode==0x3f6 and '.children[' in field:
                env=self.settings['selection'];points=[p for table in env['points'] for p in table]
                if self.command and field:
                    path=field_path(field)
                    rows=self.command.args['choices'] if opcode==0x65 else self.command.args['parents'][path[1]]['children']
                    ordinal=path[1] if opcode==0x65 else path[3]
                    points=[env['points'][0 if len(rows)==2 else 1][ordinal]]
                default=centered(points,env['words'][4])
            elif opcode==0x3f6:
                env=self.settings['approach'];points=[p for table in env['points'][:2] for p in table]+[env['offset']]
                default=centered(points,env['text_offset'][0])
            elif opcode==0x3f9:
                env=self.settings['battle'];match=re.fullmatch(r'texts\[([01])\]',field);sides=[int(match[1])] if match else [0,1]
                from .choiceart import caption_panel, caption_panel_size, make_label
                limits=[]
                for side in sides:
                    size=int(f.utility*scale);panel_size=caption_panel_size(scale,side)
                    packed=make_label(f,value,size,panel_size=panel_size,panel_padding=env['padding'])
                    measure=packed.measure(panel_size) if packed else f.measure(units(value),panel_size)
                    base=env['text_positions'][side][0];left,panel,center=caption_panel(base,side,env['padding'],measure)
                    if left<0 or left+panel>960:raise ValueError('Single-line caption/panel extends beyond the screen; shorten it')
                    if packed:
                        packed_width=packed.width
                        offset,_=packed.bounds(size)
                        start=center-packed.measure(size)//2+offset
                    else:start=center-f.measure(units(value),size)//2
                    if start<max(0,left):raise ValueError('Single-line caption starts outside its panel')
                    limits.append(min(960,left+panel)-start)
                default=min(limits)
        if width is None and default<=0:raise ValueError('Single-line caption/panel extends beyond the screen; shorten it')
        native_width=default
        regions=self.battle_regions(opcode,field,value,dialogue_mode) if battle_region is None else []
        region=battle_region or max(regions,key=region_area,default=None)
        if region:default=min(default,region['width'])
        limit=default if width is None else min(default,width)
        if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=4096:raise ValueError('Wrap width must be 1–4096 game pixels')
        return dict(width=limit,scale=scale,authored_width=default if authored else None,dialogue_mode=dialogue_mode,
                    width_source='override' if width is not None else 'bubble_contour' if region else width_source,
                    native_width=native_width,region=region,packed_label_width=packed_width,
                    layout=('battle_dialogue' if dialogue_mode=='battle' else 'message_window') if opcode==0x64 else
                    {0x65:'ordinary_choice',0x3ec:'chapter_caption',0x3f2:'battle_choice',0x3f6:'approach_topic',
                     0x3f8:'approach_result',0x3f9:'battle_introduction'}[opcode])

    def check_box(self,opcode,field,line_count,spec):
        if opcode not in {0x3f2,0x3f8}:return
        if spec['region'] and line_count>spec['region']['capacity']:
            raise ValueError('Battle choice exceeds the safe bubble area; shorten it. Branch rows cannot be paginated.')
        if opcode==0x3f8:top=self.settings['approach']['result_origin'][1]
        else:
            ordinal=field_path(field)[1] if field else 1
            if ordinal==0:return
            e=self.settings['battle'];top=e['choice_positions'][ordinal-1][1]+e['choice_offsets'][int(line_count==1)][1]
        size=int(self.font.utility*spec['scale']);leading=int(self.font.height*spec['scale']+self.font.leading)
        if top<0 or top+(line_count-1)*leading+size>544:
            raise ValueError('Choice/result text extends off-screen; shorten it. Branch opcodes cannot be paginated.')

    def check_row_widths(self,glyphs,spec):
        """Measure rows drawn by the native wrapper against their visual bounds."""
        widths=[0]*(max((g['line'] for g in glyphs),default=-1)+1)
        for g in glyphs:
            if not chr(g['code']).isspace():
                widths[g['line']]=max(widths[g['line']],g['x']+int(g['advance']*spec['scale']))
        limits=spec.get('row_widths')
        if limits is not None:
            if len(widths)>len(limits):
                raise ValueError(f'Text needs {len(widths)} rows; this panel fits {len(limits)}.')
            for i,(width,limit) in enumerate(zip(widths,limits),1):
                if width>limit:raise ValueError(f'Text row {i} is {width}px wide; this row fits {limit}px.')
        return widths

    def projection(self,opcode,value,*,geometry_only=False):
        """Map prepared UTF16 body units back to exact raw string slices."""
        f=self.font.format;source=native_newlines(value,f)
        if '\0' in source:raise ValueError('Cannot format NUL-terminated/hidden text')
        parsed=f.ordinary(source,geometry_only=geometry_only) if opcode==0x64 else None
        body=parsed['body'] if parsed else f.prepare(source,font_tags=opcode in {0x3f2,0x3f8})[0]
        opening,closing=f.tokens[0][0],f.tokens[1][0];pairs=[];i=0;reading=False
        while i<len(source):
            if source[i]==opening:
                end=source.find(closing,i+1)
                if end<0:raise ValueError('Unterminated text control')
                tag=units(source[i+1:end]).upper()
                if opcode==0x64 and tag==f.following[9]:reading=True
                elif opcode==0x64 and units(source[i:end+1]).upper()==f.following[10]:reading=False
                i=end+1;continue
            if not reading:
                for c in units(source[i]):pairs.append((f.mapping.get(c,c),i,i+1))
            i+=1
        expected=(parsed['name'] if parsed else '')+body
        if ''.join(p[0] for p in pairs)!=expected and parsed:
            pairs=[p for p in pairs if p[0] not in f.following[2][:2]]
        if ''.join(p[0] for p in pairs)!=expected:raise ValueError('Cannot safely map this text/speaker form back to its source')
        if parsed:pairs=pairs[len(parsed['name']):]
        return source,body,pairs,parsed['ruby'] if parsed else []

    def wire_text(self, opcode, source, field):
        args = self.command.args if self.command is not None else {}
        return shape_script(source, opcode, args, field, self.font.format, getattr(self.font, 'pair_spacing', None),keyword_markup=True)

    def display_body(self, opcode, source, body, field):
        wire = self.wire_text(opcode, source, field)
        if wire == source:
            return body
        if opcode == 0x64:
            return self.font.format.ordinary(wire)['body']
        return self.font.format.prepare(wire, font_tags=opcode in {0x3F2, 0x3F8})[0]

    def wrap(self,opcode,value,*,field='',width=None,dialogue_mode='auto',hyphenate=False,full_width_latin=False,preserve_speaker=False,reflow=False):
        f=self.font.format
        timed=opcode==0x64 and bool(f.ordinary(native_newlines(value,f),geometry_only=reflow)['markers'])
        checked=reflow_breaks(value,f,collapse_padding=timed) if reflow and supports_breaks(opcode) else value
        try:
            options=dict(field=field,width=width,dialogue_mode=dialogue_mode,hyphenate=hyphenate,
                         full_width_latin=full_width_latin,preserve_speaker=preserve_speaker)
            if opcode==0x3F8 and self.project and (Path(self.project.root)/'env/env_approach.dat').is_file():
                from .composition import message_environment
                from .compositionmodes import approach_environment
                from .uipanel import panel_regions, result_contract
                from .uitext import get_catalog
                catalog=get_catalog(self.project)
                result=approach_environment(catalog.source('env/env_approach.dat'))
                cursors=message_environment(catalog.source('env/env_message_window.dat'))['cursors']
                contract=result_contract(result,cursors)
                panel=panel_regions(self.project,catalog,self.font,contract)[-1]
                return self._wrap(opcode,checked,original=value,panel=panel,**options)
            regions=self.battle_regions(opcode,field,checked,dialogue_mode)
            if regions:
                for region in regions:
                    try:packet=self._wrap(opcode,checked,original=value,battle_region=region,**options)
                    except ValueError:continue
                    if packet['line_count']==region['capacity']:return packet
                if opcode==0x3f2:
                    sizes=', '.join(f"{r['capacity']} × {r['width']}px" for r in regions)
                    raise ValueError(f'Choice text does not fit the battle bubble row layouts ({sizes}).')
                return self._wrap(opcode,checked,original=value,battle_region=max(regions,key=region_area),**options)
            return self._wrap(opcode,checked,original=value,**options)
        except ValueError as error:
            if not timed:raise
            result=self.convert_dialogue_width(value,width=width,dialogue_mode=dialogue_mode,preserve_speaker=preserve_speaker,convert=full_width_latin)
            result['fit_warning']=str(error)
            return result

    def _wrap(self,opcode,value,*,original,field,width,dialogue_mode,hyphenate,full_width_latin,preserve_speaker,panel=None,battle_region=None):
        conversion=None;style=None
        timed=opcode==0x64 and bool(self.font.format.ordinary(value)['markers'])
        if self.proportional and not supports_breaks(opcode):
            from .fontstyle import match_style,FIXED
            style=match_style(value,self.font,FIXED);value=style['text']
            if full_width_latin:conversion=dict(converted_characters=0,preserved_ascii='')
        elif full_width_latin or (self.normalize_script_font and self.proportional and measured_script_field(opcode, field)):
            conversion=full_width_text(value,self.font,controls=opcode in {0x64,0x3f2,0x3f8},
                                       preserve_speaker=opcode==0x64 and (preserve_speaker or self.proportional))
            value=conversion['text'];conversion={k:v for k,v in conversion.items() if k!='text'}
        spec=self.dimensions(opcode,field=field,value=value,width=width,dialogue_mode=dialogue_mode,battle_region=battle_region);f=self.font.format
        if panel:
            row_widths=[min(spec['width'], n) for n in panel['row_widths']]
            spec.update(width=row_widths[0],width_source='panel_alpha',
                        panel_capacity=panel['panel_capacity'],row_widths=row_widths)
        if not supports_breaks(opcode):
            source=native_field(opcode,value,f)
            if '\0' in source:raise ValueError('Cannot format NUL-terminated/hidden text')
            extent=spec.get('packed_label_width')
            if extent is None:extent=self.label_width(source,spec['scale'])
            if extent>spec['width']:raise ValueError(f"Single-line label/caption is {extent}px wide, exceeding {spec['width']}px; shorten it. This renderer does not support line breaks.")
            return dict(text=source,editor_text=source,changed=source!=original,full_width_conversion=conversion,inserted_breaks=0,line_count=1,
                        lines=[source],line_widths=[extent],break_character=None,breaks_supported=False,font_style=style,**spec)
        source,body,pairs,ruby=self.projection(opcode,value,geometry_only=timed);scale=spec['scale']
        def line_limit(index):
            if spec.get('row_widths') is None:return spec['width']
            if index>=len(spec['row_widths']):
                raise ValueError(f"Text exceeds the panel's {len(spec['row_widths'])} rows.")
            return spec['row_widths'][index]
        def advance(c):
            other=f.tokens[4][1] if c==f.tokens[4][0] else c
            return max(int(self.font.measure(c,self.font.utility)*scale),int(self.font.measure(other,self.font.utility)*scale))
        if spec['native_width']<advance(f.break_char):raise ValueError('Width is too narrow for the native line-break traversal')
        display = self.display_body(opcode, source, body, field)
        hyphen = full_width_text('-',self.font)['text'] if full_width_latin or self.proportional else '-'
        widths=[0 if c==f.break_char else advance(c) for c in display]
        prefix=[0]
        for n in widths:prefix.append(prefix[-1]+n)
        keyword_aliases=set((getattr(self.font,'pair_spacing',None) or {}).get('keyword_marks',{}).values())
        def span(a,b):
            extent = prefix[b]-prefix[a]
            if b > a and display[b-1] != body[b-1] and display[b-1] not in keyword_aliases:
                # A line break removes the following neighbor that supplied the variant.
                extent += advance(body[b-1]) - widths[b-1]
            return extent
        blocked={at for a,b,_ in ruby for at in range(a+1,b)}
        def allowed(at):
            if at in blocked:return False
            if 0<at<len(body):
                if pairs[at][1]==pairs[at-1][1]:return False  # UTF16 surrogate pair.
                if unicodedata.category(body[at]).startswith('M') or body[at]=='\u200d' or body[at-1]=='\u200d':return False
                if body[at] in f.following[4] or body[at-1] in f.following[5]:return False
                if unicodedata.category(body[at]) in {'Pe','Pf'} or unicodedata.category(body[at-1]) in {'Ps','Pi'}:return False
            return True
        def cjk(c):return (0x2e80<=ord(c)<=0xa4cf or 0xac00<=ord(c)<=0xd7af or 0xff00<=ord(c)<=0xffef) and not 0xff01<=ord(c)<=0xff5e
        def letter_before(at):
            at-=1
            while at>=0 and unicodedata.category(body[at]).startswith('M'):at-=1
            return at>=0 and body[at].isalpha()
        replacements=[];lines=[];start=0;hyphens=set()
        while start<len(body):
            limit=line_limit(len(lines))
            hard=body.find(f.break_char,start);end=len(body) if hard<0 else hard
            if start==end:lines.append((start,end));start=end+1;continue
            while span(start,end)>limit:
                i=start
                while i<end and span(start,i+1)<=limit:i+=1
                candidates=[];j=start
                while j<=i:
                    if body[j] in ' \t':
                        stop=j+1
                        while stop<end and body[stop] in ' \t':stop+=1
                        if j>start and span(start,j)<=limit and allowed(j) and allowed(stop):candidates.append((j,stop))
                        j=stop;continue
                    if j>start and (cjk(body[j]) or cjk(body[j-1])) and allowed(j):candidates.append((j,j))
                    j+=1
                if not candidates:
                    possible=[j for j in range(start+2,min(i+1,end-1))
                              if hyphenate and allowed(j) and letter_before(j) and body[j].isalpha()
                              and span(start,j)+advance(hyphen)<=limit]
                    if possible:
                        cut=possible[-1];hyphens.add(cut);lines.append((start,cut))
                        replacements.append((pairs[cut][1],pairs[cut][1],hyphen+f.break_char));start=cut;limit=line_limit(len(lines));continue
                    word=unicode_text(body[start:min(end,start+60)])
                    raise ValueError(f'Unbreakable word/ruby span exceeds {limit}px: {word!r}. Shorten it or add a deliberate break.')
                cut,resume=candidates[-1];lines.append((start,cut))
                if resume>cut:
                    # Remove separator characters individually; preserve any controls between them.
                    edits={ (pairs[k][1],pairs[k][2]) for k in range(cut,resume) }
                    for a,b in edits:replacements.append((a,b,f.break_char if a==pairs[cut][1] else ''))
                else:replacements.append((pairs[cut][1],pairs[cut][1],f.break_char))
                start=resume;limit=line_limit(len(lines))
            lines.append((start,end));start=end+1
        if not body or body.endswith(f.break_char):lines.append((len(body),len(body)))
        result=source
        if timed and replacements:
            from .textpadding import pad_breaks
            result=pad_breaks(self,source,replacements,lines,body,hyphens,hyphen,spec)
        else:
            for a,b,text in sorted(replacements,reverse=True):result=result[:a]+text+result[b:]
        # Reparse controls/ranges and reject formatting unsupported by the player.
        _,prepared,_,ranges=self.projection(opcode,result)
        if len(prepared)>65535:raise ValueError('Formatted text exceeds the native layout index limit')
        self.font.format.prepare(prepared,unit_text=True)
        display_prepared = self.display_body(opcode, result, prepared, field)
        actual=self.font.layout(display_prepared,width=spec['native_width'],scale=scale,ruby=ranges)
        expected=[line for line,(a,b) in enumerate(lines) for c in body[a:b]+(hyphen if b in hyphens else '') if not c.isspace()]
        if [g['line'] for g in actual if not chr(g['code']).isspace()]!=expected:
            raise ValueError('Formatted text does not reproduce its planned lines with the native layout')
        if timed and spec['region']:
            extent=max((g['x']+int(g['advance']*scale) for g in actual),default=0)
            half=spec['region']['width']/2
            if any(g['x']-extent/2 < -half or g['x']+int(g['advance']*scale)-extent/2 > half
                   for g in actual if not chr(g['code']).isspace()):
                raise ValueError('Timed padding would place visible glyphs outside the safe bubble rectangle')
        draw_widths=self.check_row_widths(actual,spec) if spec.get('row_widths') is not None else None
        self.check_box(opcode,field,len(lines),spec)
        return dict(text=result,editor_text=editable_newlines(result,f),changed=result!=original,full_width_conversion=conversion,
                    inserted_breaks=0 if timed else len(lines)-1-body.count(f.break_char),line_count=len(lines),
                    break_strategy='spaces' if timed else 'native',
                    hyphenations=len(hyphens),lines=[unicode_text(body[a:b])+(hyphen if b in hyphens else '') for a,b in lines],
                    line_widths=(draw_widths+[0]*(len(lines)-len(draw_widths)) if draw_widths is not None else
                                 [span(a,b)+(advance(hyphen) if b in hyphens else 0) for a,b in lines]),
                    break_character=f.break_char,breaks_supported=True,**spec)
