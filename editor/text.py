"""Python text controls, validation, authored layout and glyph presentation.

Ports the editor-relevant textreveal/messagedraw/font semantics. Qt is the font
rasterizer; no engine DLL is loaded. Scene/window art remains procedural.
"""
import math
import re
import struct
from pathlib import Path
from .scriptcodec import Reader


TIMED_BREAK_ERROR = ('Timed SP QUE dialogue cannot contain explicit line breaks in the current game player; '
                     'replace line breaks with spaces, keeping the SP QUE directive.')


def units(value):
    raw = value.encode('utf-16-le')
    return ''.join(map(chr, struct.unpack('<'+'H'*(len(raw)//2),raw)))


def unicode_text(value):
    return b''.join(struct.pack('<H',ord(c)) for c in value).decode('utf-16-le')


def color(value): return [value>>16&255,value>>8&255,value&255,value>>24&255]


class TextFormat:
    def __init__(self, data):
        r = Reader(data); r.take(3)
        self.tokens = [units(r.string()) for _ in range(6)]
        maps = [units(r.string()) for _ in range(r.count())]
        self.following = [units(r.string()) for _ in range(27)]
        if len(maps)<2 or len(maps[0])!=len(maps[1]) or not self.following[3]:
            raise ValueError('Invalid text character map/line break')
        self.mapping = {}
        for a,b in zip(maps[0],maps[1]): self.mapping.setdefault(a,b)
        self.break_char = self.following[3][0]

    def normalize(self, text):
        return ''.join(self.mapping.get(c,c) for c in text.split('\0',1)[0]).split('\0',1)[0]

    def split(self, text):
        text = self.normalize(text)
        if any(c in self.tokens[2] for c in text): raise ValueError('Unparsed ordinary inline directive')
        quote = text.find(self.following[1]); name = text[:quote] if quote >= 0 else ''
        if name and len(name)+1<len(text) and text[len(name)+1] in self.following[0][:2]:
            text = ''.join(c for c in text if c not in self.following[2][:2])
        return dict(name=name, body=text[len(name):], ruby=[], keywords=[], markers=[])

    def ordinary(self, value, *, geometry_only=False):
        source = units(value)
        if len(source)>1024*1024: raise ValueError('Message exceeds input budget')
        source = source.split('\0',1)[0]
        if not any(c in self.tokens[2] for c in source): return self.split(source)
        f = self.following; opening,closing = self.tokens[0][0],self.tokens[1][0]
        aside = None; quote = source.find(f[1])
        if quote>0 and quote+1<len(source) and source[quote+1] in f[0][:2]:
            aside=source[:quote]; source=''.join(c for c in source if c not in f[2][:2])
        plain=''; cursor=0; ruby=[]; keywords=[]; markers=[]; base=None; keyword=None
        def native_number(word):
            n=0
            for c in word:
                if '0'<=c<='9': n=(n*10+ord(c)-48)&0xffffffff
            n=(-n if '-' in word else n)&0xffffffff
            return n if n<0x80000000 else n-0x100000000
        while cursor<len(source):
            c=source[cursor]
            if c==closing: raise ValueError('Unmatched inline closing delimiter')
            if c!=opening: plain+=c;cursor+=1;continue
            end=source.find(closing,cursor+1)
            if end<0: raise ValueError('Unterminated inline directive')
            tag=source[cursor+1:end].translate(str.maketrans('abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
            if tag==f[8]:
                if base is not None: raise ValueError('Nested ruby base')
                base=len(plain)
            elif tag==f[9]:
                if base is None or base==len(plain): raise ValueError('Ruby reading has no base')
                close=source.find(f[10],end+1)
                if close<0: raise ValueError('Unclosed ruby reading')
                ruby.append([base,len(plain),self.normalize(source[end+1:close])]);base=None
                cursor=close+len(f[10]);continue
            elif tag.startswith(f[11]+' '):
                match=re.fullmatch(r'KEYWORD[ \t\r\n]+=[ \t\r\n]+([0-9]+)',tag)
                if keyword is not None or not match or int(match[1])>=1024: raise ValueError('Invalid keyword syntax/index')
                keyword=[len(plain.replace(self.break_char,'')),None,int(match[1])]
            elif tag==f[12]:
                if keyword is None: raise ValueError('Keyword close without start')
                keyword[1]=len(plain.replace(self.break_char,''));keywords.append(keyword);keyword=None
            else:
                prefix=f[15]+' '; command=tag[len(prefix):] if tag.startswith(prefix) else ''
                parts=command.split(f[16])
                if len(parts)!=3 or parts[0]!=f[18] or ' ' in command: raise ValueError('Unsupported ordinary inline directive')
                lane,time=native_number(parts[1]),native_number(parts[2])
                if not 0<=lane<5 or time<0: raise ValueError('Inline queue lane/time outside range')
                markers.append([len(plain)-1,lane,time])
            cursor=end+1
        parsed=self.split(plain)
        if aside is not None:
            parsed['name']=self.normalize(aside);parsed['body']=parsed['body'][len(parsed['name']):]
        if base is not None: raise ValueError('Ruby base has no reading')
        if keyword is not None: raise ValueError('Unclosed keyword range')
        name_len=len(parsed['name'])
        if len(parsed['body'])!=len(plain)-name_len: raise ValueError('Inline controls with aside stripping are unsupported')
        for ranges in (ruby,keywords):
            for span in ranges:
                if span[0]<name_len or span[1]<span[0]: raise ValueError('Text range overlaps speaker name')
                span[0]-=name_len;span[1]-=name_len
        before=time=0;glyph_count=len(parsed['body'].replace(self.break_char,''))
        if markers and self.break_char in parsed['body'] and not geometry_only:
            raise ValueError(TIMED_BREAK_ERROR)
        for marker in markers:
            marker[0]-=name_len
            if not geometry_only and (not before<=marker[0]<glyph_count or marker[2]<time): raise ValueError('Invalid or nonmonotonic text queue marker')
            before,time=marker[0],marker[2]
        parsed.update(ruby=ruby,keywords=keywords,markers=markers)
        return parsed

    def prepare(self, value, font_tags=False, unit_text=False):
        source=value if unit_text else units(value)
        if len(source)>1024*1024: raise ValueError('Text exceeds input budget')
        source=self.normalize(source);plain='';colors=[];opened=None;cursor=0
        f=self.following;opening,closing=self.tokens[0][0],self.tokens[1][0]
        prefix=f[6]+' '+f[20]+f[23]+'#'
        if not any(c in self.tokens[2] for c in source): plain=source
        else:
            if not font_tags: raise ValueError('Inline text directives require their parser')
            while cursor<len(source):
                c=source[cursor]
                if c==opening:
                    end=source.find(closing,cursor+1)
                    if end<0: raise ValueError('Unterminated font directive')
                    tag=source[cursor+1:end];glyph=len(plain.replace(self.break_char,''))
                    if tag==f[7]:
                        if opened is None: raise ValueError('Font close without color range')
                        colors.append([opened[0],glyph,opened[1]]);opened=None
                    elif tag.startswith(prefix) and re.fullmatch('[0-9a-fA-F]{6}',tag[len(prefix):]):
                        if opened is not None: raise ValueError('Nested font directives')
                        digits=tag[len(prefix):]
                        opened=(glyph,[int(digits[i:i+2],16) for i in (0,2,4)])
                    else: raise ValueError('Unsupported font directive')
                    cursor=end+1;continue
                if c==closing: raise ValueError('Unmatched font closing delimiter')
                plain+=c;cursor+=1
            if opened is not None: raise ValueError('Unclosed font color range')
        if len(plain.replace(self.break_char,''))>65535: raise ValueError('Text exceeds 65535 glyph limit')
        return plain,colors

    def validate(self, op, args):
        from .engine import text_fields
        if op==0x64:
            parsed=self.ordinary(args['text']);body,_=self.prepare(parsed['body'],unit_text=True)
            if len(body)>65535:raise ValueError('Message exceeds layout index limit')
        else:
            for _,value in text_fields(dict(opcode=op,args=args)):
                self.prepare(value,font_tags=op in {0x3f2,0x3f8})


class TextPresentation:
    def __init__(self, root, *, font_asset=None):
        root=Path(root);self.root=root; read=lambda name:(root/'env'/name).read_bytes()
        self.format=TextFormat(read('env_string_format.dat'))
        r=Reader(read('env_config.dat'));r.take(3)
        self.factors=[r.word('f') for _ in range(r.count())]
        self.intervals=[r.word() for _ in range(r.count())]
        self.auto_delays=[r.word('i') for _ in range(r.count())]
        self.utility=struct.unpack_from('<i',read('env_game_utility.dat'),3)[0]
        r=Reader(read('env_global.dat'));r.take(3)
        for _ in range(4):r.string()
        r.take(8)
        for _ in range(9):r.string()
        self.height=r.word()
        data=read('env_message_window.dat');frame=Reader(data);frame.take(15+2)
        alignment,x,y,_,_,w,h=[frame.word('i') for _ in range(7)]
        self.message_bounds=[x-(w//2 if alignment%3==1 else w if alignment%3==2 else 0),
                             y-(h//2 if alignment//3==1 else h if alignment//3==2 else 0),w,h]
        r=Reader(data)
        r.take(3+3*4+2*34+16+14*34+4+3*34+16+8)
        r.take(r.count()*4);r.take(8);r.take(4);self.travel=r.word('i')
        self.origin=[r.word('i'),r.word('i')];self.width=r.word('i')
        r.take(2);self.name_origin=[r.word('i'),r.word('i')]
        r.take(6*4);r.word('f');r.word('f');self.leading=r.word('i')
        self.ruby_y=r.word('i');self.ruby_scale=r.word('f');self.ruby_shadow=color(r.word())
        r.take(8);default=r.word();scales=[r.word('f') for _ in range(r.count())]
        self.scale=scales[default];self.name_scale=r.word('f')
        self.name_color=color(r.word());r.word();self.unread=color(r.word());self.read=color(r.word())
        self.keyword_colors=[color(r.word()),color(r.word())]
        data=font_asset if font_asset is not None else (root/'Font.gsf').read_bytes();r=Reader(data)
        if r.take(4)!=b'FONT' or r.word()!=0:raise ValueError('Unsupported GSF font')
        count,size=r.word(),r.word()
        if size!=len(data) or not 2<=count<=258:raise ValueError('Invalid GSF extent')
        sections=[(r.word(),r.word()) for _ in range(count)]
        previous=16+count*8
        for at,n in sections:
            if at<previous or at+n>len(data):raise ValueError('GSF section outside font')
            previous=at+n
        self.cached={};self.atlases=[data[a:a+n] for a,n in sections[:-2]]
        at,n=sections[-2]
        for offset in range(at,at+n,10):
            code,atlas,x,y,width,height=struct.unpack_from('<4H2B',data,offset)
            self.cached[chr(code)]=(atlas,x,y,width,height);self.bitmap_height=height
        at,n=sections[-1];chars=Reader(data[at:at+n]);length=chars.word()
        if length!=n-4 or chars.word('H')!=0xfeff:raise ValueError('Invalid GSF characters')
        self.charset=set(chars.take(n-6).decode('utf-16-le'))-set('"\r\n')
        self.font_data=(root/'DFHSR4.TTC').read_bytes();self.raw_font=None;self.glyph_cache={};self.atlas_cache={}

    def measure(self, text, pixels):
        width=0;scale=pixels/36 if pixels else 1
        for c in text:
            cached=self.cached.get(c);base=cached[3] if cached else 36
            half=0x20<=ord(c)<=0x7e or 0xff61<=ord(c)<=0xffa0
            width=int(width+base*scale*(.5 if half else 1)+(1 if cached and not half else 0))
        return width

    def layout(self, text, width=None, scale=None, ruby=()):
        width=self.width if width is None else width;scale=self.scale if scale is None else scale
        f=self.format;lines=[];start=0;x=0;i=0;budget=len(text)*4+32
        while i<len(text):
            budget-=1
            if budget<0:raise ValueError('Text cannot fit layout width')
            c=f.tokens[4][1] if text[i]==f.tokens[4][0] else text[i]
            glyph_width=int(self.measure(c,self.utility)*scale)
            explicit=text[i]==f.break_char
            if explicit:lines.append((start,i));start=i+1;x=0
            if x+glyph_width>width:
                split=i
                while split>start+1 and text[split] in f.following[4]:split-=1
                before=max(0,split-1);end=before
                while end>start+1 and text[end] in f.following[5]:end-=1
                if end!=before:split=end+1
                for begin,end,_ in ruby:
                    if begin<=split<end:
                        split=begin
                        if split==start and i>start:raise ValueError('Ruby base span exceeds line width')
                        break
                lines.append((start,split));start=split;i=split;x=0
            if not explicit:x+=glyph_width
            i+=1
        if start<len(text):lines.append((start,len(text)))
        glyphs=[];leading=int(self.height*scale+self.leading)
        for line,(begin,end) in enumerate(lines):
            x=0
            for index in range(begin,end):
                c=text[index];advance=self.measure(c,self.utility)
                glyphs.append(dict(code=ord(c),x=x,y=line*leading,index=index,line=line,advance=advance))
                x+=int(advance*scale)
        return glyphs

    def validate(self, op, args):
        self.format.validate(op,args)

    def glyph(self, code):
        """Rasterize original TTC through Qt, only on the GUI thread."""
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QRawFont,QImage,QPainter,QColor,QGlyphRun,QFont
        from PySide6.QtCore import QPointF
        if code in self.glyph_cache:return self.glyph_cache[code]
        if chr(code) in self.cached:
            atlas,x,y,width,_=self.cached[chr(code)];height=self.bitmap_height
            if atlas not in self.atlas_cache:self.atlas_cache[atlas]=font_atlas(self.atlases[atlas])
            atlas_width,atlas_height,pixels=self.atlas_cache[atlas]
            if x+width>atlas_width or y+height>atlas_height:raise ValueError('Font glyph outside atlas')
            raw=b''.join(pixels[((y+row)*atlas_width+x)*4:((y+row)*atlas_width+x+width)*4] for row in range(height))
            result=dict(width=width,height=height,rgba=raw.hex(),bitmap=True)
            self.glyph_cache[code]=result;return result
        if chr(code) not in self.charset and chr(code) not in self.cached:return {'missing':True}
        if self.raw_font is None:
            self.raw_font=QRawFont();self.raw_font.loadFromData(QByteArray(self.font_data),36*12.15/22*128/72,QFont.PreferDefaultHinting)
            if not self.raw_font.isValid():raise ValueError('Qt cannot open original TTC font')
        font=self.raw_font;indices=font.glyphIndexesForString(chr(code))
        if not indices or indices[0]==0:return {'missing':True}
        advances=font.advancesForGlyphIndexes(indices);width=max(1,math.ceil(advances[0].x()));height=36
        image=QImage(width,height,QImage.Format_RGBA8888);image.fill(0)
        run=QGlyphRun();run.setRawFont(font);run.setGlyphIndexes(indices)
        # Match nominal-cell baseline convention; Qt's outline rasterizer may
        # differ slightly from the PC engine's FreeType grayscale hinting.
        run.setPositions([QPointF(0,math.ceil(font.ascent()))])
        painter=QPainter(image);painter.setPen(QColor('white'));painter.drawGlyphRun(QPointF(0,0),run);painter.end()
        result=dict(width=width,height=height,rgba=bytes(image.constBits()).hex(),bitmap=False)
        self.glyph_cache[code]=result;return result


def font_atlas(data):
    """Original GSF P8 GXT atlas only; no scene-art importer."""
    def word(at):return struct.unpack_from('<I',data,at)[0]
    if len(data)<64 or word(0)!=0x00545847 or word(4)!=0x10000003 or word(8)!=1:
        raise ValueError('Unsupported font GXT header')
    begin,size=word(12),word(16);pixel_begin,pixel_size=word(32),word(36)
    dimensions=word(56);width,height=dimensions&65535,dimensions>>16
    order,fmt=word(48),word(52);swizzled=order==0
    if order not in {0,0x60000000} or fmt not in {0x95001000,0x95005000} or word(60)!=1:
        raise ValueError('Unsupported font GXT layout')
    count=width*height;palette_begin=begin+size-1024
    stride=width if swizzled or pixel_size==count else (width+7)&~7
    if not width or not height or count>64*1024*1024 or begin<64 or pixel_begin!=begin or stride*height!=pixel_size or begin+size>len(data):
        raise ValueError('Invalid font atlas extent')
    if palette_begin not in {pixel_begin+pixel_size,(pixel_begin+pixel_size+63)&~63}:
        raise ValueError('Invalid font palette extent')
    palette=[bytes((data[palette_begin+i*4+2],data[palette_begin+i*4+1],data[palette_begin+i*4],
                   data[palette_begin+i*4+3] if fmt==0x95001000 else 255)) for i in range(256)]
    pixels=bytearray(count*4)
    if swizzled:
        if width&(width-1) or height&(height-1):raise ValueError('Font swizzle requires power-of-two dimensions')
        def compact(value):
            value&=0x55555555;value=(value^(value>>1))&0x33333333
            value=(value^(value>>2))&0x0f0f0f0f;value=(value^(value>>4))&0x00ff00ff
            return (value^(value>>8))&65535
        minimum=min(width,height);k=minimum.bit_length()-1
        for i in range(count):
            even,odd=compact(i),compact(i>>1);block=i>>(2*k)<<(2*k)
            if height<width:
                j=block|((odd&(minimum-1))<<k)|(even&(minimum-1));x,y=j//height,j%height
            else:
                j=block|((even&(minimum-1))<<k)|(odd&(minimum-1));x,y=j%width,j//width
            at=(y*width+x)*4;pixels[at:at+4]=palette[data[pixel_begin+i]]
    else:
        for y in range(height):
            for x in range(width):
                at=(y*width+x)*4;pixels[at:at+4]=palette[data[pixel_begin+y*stride+x]]
    return width,height,bytes(pixels)
