"""Source-defined UI string spans and quoted catalogue token spans, not byte guesses."""
from dataclasses import dataclass
import re
import struct
from .scriptcodec import Reader, STRING_OBSERVER, string


def ui_string(reader,role):
    previous=getattr(reader,'ui_role','UI text');reader.ui_role=role
    try:return reader.string()
    finally:reader.ui_role=previous


def help_text(data):
    r=Reader(data);r.take(3+8+32+4)
    def items(role):
        for index in range(r.count()):
            r.take(4);r.ui_role=f'{role} / item {index}';r.string()
    def rows(role):
        for index in range(r.count()):items(f'{role} / row {index}')
    r.take(16);items('Common');r.take(16);rows('Settings');r.take(16);rows('Save / load')
    r.take(16);items('Extras menu')
    for role in ('CG gallery','Music gallery'):r.take(16);rows(role)
    rows('Movies');r.take(16);rows('Battle replay')
    rows('Scenario navigation');items('Scenario confirmation');items('Scenario tools');rows('Scenario skip')
    if r.pos!=len(data):raise ValueError('Unexpected button-help environment tail')
    return r.pos


def global_text(data):
    r=Reader(data);r.take(3)
    for _ in range(4):r.string()
    r.take(8)
    for _ in range(9):r.string()
    r.take(30*4)
    def records(n):r.take(r.count()*n*4)
    records(6);r.take(8*4);records(6);r.take(4*4);records(1)
    for _ in range(r.count()):r.string()
    r.string();r.take(8)
    for _ in range(3):r.string()
    return r.pos


def script_text(data):
    r=Reader(data);r.take(3+16+34)
    for stride in (34,4):r.take(r.count()*stride)
    r.take(68);r.take(r.count()*8);r.take(34+20);r.string()
    r.take(12+16+4+4)
    for _ in range(r.count()):
        r.string()
        for _ in range(r.count()):r.take(4);r.string();r.take(4)
    r.take(15*4)
    for _ in range(3):ui_string(r,'dialog prompt')
    r.string()  # Clear-save description; following feature flags retained.
    return r.pos


def save_text(data):
    r=Reader(data);r.take(3)
    for _ in range(56):r.string()
    if r.pos!=len(data):raise ValueError('Unexpected save-manager environment tail')


def keyword_text(data):
    r=Reader(data);r.take(3);r.take(r.count()*4)
    for _ in range(r.count()):r.take(4);r.string()
    if r.pos!=len(data):raise ValueError('Unexpected keyword table tail')


def first_text(data):
    r=Reader(data);r.take(3+16)
    for _ in range(r.count()):r.take(12);r.take(r.count()*4)
    for _ in range(3):r.string()
    if r.pos!=len(data):raise ValueError('Unexpected startup environment tail')


def debug_text(data):
    r=Reader(data);r.take(3+20+8+11+1+9*4)
    for _ in range(4):r.string()
    if r.pos!=len(data):raise ValueError('Unexpected debug environment tail')


def test_text(data):
    r=Reader(data);r.take(3)
    for _ in range(r.count()):r.string()
    r.take(5*4)
    if r.pos!=len(data):raise ValueError('Unexpected test environment tail')


def parsers():
    from .composition import title_environment,system_environment
    from .compositioncommon import dialog_environment
    from .compositionlists import slot_environment,backlog_environment
    from .compositionsettings import settings_environment
    from .compositionextras import extras_environment
    from .compositionmodes import profile_environment
    from .compositionbattle import battle_environment
    from .text import TextFormat
    return dict(env_help_mgr=help_text,env_global=global_text,env_script=script_text,
        env_save_manager=save_text,env_scene_title=title_environment,env_system_menu=system_environment,
        env_dialog=dialog_environment,env_saveload=slot_environment,env_backlog=backlog_environment,
        env_option=settings_environment,env_omake=extras_environment,env_otaku_mode=profile_environment,
        env_tukkomi=battle_environment,env_string_format=TextFormat,env_first=first_text,
        env_debug=debug_text,env_test=test_text,env_keyword=keyword_text)


@dataclass(frozen=True)
class Span:
    start:int
    end:int
    text:str
    encoding:str='counted-utf16'
    role:str='UI text'
    editable:bool=True
    reason:str=''
    bounds:tuple=()


def counted_spans(data,parser):
    spans={}
    def observe(reader,start,end,value):
        if bytes(reader.data)!=data:raise ValueError('UI parser read from an untracked sub-buffer')
        spans[start]=Span(start,end,value,role=getattr(reader,'ui_role','UI text'))
    token=STRING_OBSERVER.set(observe)
    try:result=parser(data)
    finally:STRING_OBSERVER.reset(token)
    result_spans=[spans[k] for k in sorted(spans)]
    if getattr(parser,'__name__','')=='profile_environment':
        # Append, rather than sort into strings: existing translation IDs stay stable.
        at=result['columns_offset'];columns=result['columns']
        result_spans.append(Span(at,at+4,str(columns),encoding='layout-u32',
            role='Profile tips column limit',bounds=(columns,columns*2)))
    return result_spans


def table_spans(data,encoding,separator,kind):
    """Native quote/doubled-quote and CRLF row semantics, preserving raw ranges."""
    text=data.decode(encoding);position=0;row=[];rows=[]
    while position<len(text):
        start=position;value=''
        while position<len(text):
            ch=text[position]
            if ch=='"':
                position+=1
                while position<len(text):
                    ch=text[position];position+=1
                    if ch=='"':
                        if position==len(text) or text[position]!='"':break
                        position+=1
                    value+=ch
            elif ch in (separator,'\r','\n'):break
            else:value+=ch;position+=1
        row.append((start,position,value))
        if position==len(text):rows.append(row);break
        delimiter=text[position];position+=1
        if delimiter=='\r' and position<len(text) and text[position]=='\n':
            position+=1;rows.append(row);row=[]
        if position==len(text) and row:rows.append(row)
    offsets=[0]
    for ch in text:offsets.append(offsets[-1]+len(ch.encode(encoding)))
    result=[]
    for index,row in enumerate(rows):
        first=row[0][2].lstrip('\ufeff') if row else ''
        if first!='ON':continue
        columns=(3,4) if kind=='profile_items' else (10,) if kind=='profile_responses' and len(row)>1 and row[1][2]=='DATA' else (1,) if kind=='cg_titles' else ()
        for column in columns:
            if column>=len(row):raise ValueError('Truncated '+kind+' catalogue row')
            a,b,value=row[column]
            role=f'{kind} row {index}, '+({3:'name',4:'description',10:'response',1:'title'}[column])
            result.append(Span(offsets[a],offsets[b],value,encoding+' table '+separator,role))
    return result


PRINTF=re.compile(r'%(?:%|(?:\d+\$)?[-+ #0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|ll|[hlLzjt])?[diuoxXfFeEgGaAcCsSpn])')


def encode_span(span,text):
    if not isinstance(text,str):raise ValueError('UI text must be a string')
    if not span.editable:raise ValueError(span.reason or 'Protected non-display field')
    original=span.text.split('\0',1)[0]
    if span.encoding=='layout-u32':
        if not re.fullmatch(r'[0-9]{1,4}',text) or not span.bounds[0]<=int(text)<=span.bounds[1]:
            raise ValueError(f'Layout column limit must be {span.bounds[0]}–{span.bounds[1]}')
        return struct.pack('<I',int(text))
    if span.role.startswith('cg_titles') and not text:raise ValueError('CG title cannot be empty: native loading would drop its gallery entry')
    if '\0' in text:raise ValueError('Do not insert NUL in UI text')
    if len(text.encode('utf-16-le'))>8192:raise ValueError('UI text exceeds4096 UTF16-unit editing limit')
    if PRINTF.findall(original)!=PRINTF.findall(text):raise ValueError('Keep format placeholders in their original order and spelling')
    if PRINTF.findall(original) and '%' in PRINTF.sub('',text):raise ValueError('Unrecognized format directive; use %% for a literal percent')
    for token in re.findall(r'≪[^≫]*≫|[①-⑳]',original):
        if original.count(token)!=text.count(token):raise ValueError('Keep control/button token '+token)
    if span.role=='button choices' and original.count('＿')!=text.count('＿'):
        raise ValueError('Keep the authored ＿ button-label separators')
    # Terminators/opaque suffix are retained, never shown as translator text.
    suffix=span.text[len(original):];value=text+suffix
    if span.encoding=='counted-utf16':return string(value)
    encoding,_,separator=span.encoding.split(' ',2)
    # Quote the entire edited token; native tokenizers unescape doubled quotes.
    return ('"'+value.replace('"','""')+'"').encode(encoding)


def rewrite(data,spans,replacements):
    out=bytearray(data)
    if any(type(i)!=int or not 0<=i<len(spans) for i in replacements):raise ValueError('UI text field outside original schema')
    for index,text in sorted(replacements.items(),key=lambda item:spans[item[0]].start,reverse=True):
        span=spans[index];encoded=encode_span(span,text)
        out[span.start:span.end]=encoded
    return bytes(out)
