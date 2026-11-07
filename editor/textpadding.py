"""Native automatic-wrap padding for timed messages that reject break markers."""
import math
import re


def pad_breaks(service,source,replacements,lines,body,hyphens,spec):
    font=service.font;formatter=font.format
    planned=[body[a:b]+('-' if b in hyphens else '') for a,b in lines]
    expected=[(ord(c),line) for line,text in enumerate(planned) for c in text if not c.isspace()]
    events=[(a,b,text) for a,b,text in sorted(replacements) if formatter.break_char in text]
    padding={a:1 for a,_,_ in events}
    step=int(font.measure(' ',font.utility)*spec['scale'])
    if step<=0:raise ValueError('Current font has no measurable padding space')
    maximum=math.ceil(spec['native_width']/step)+3

    def render():
        result=source
        for a,b,text in sorted(replacements,reverse=True):
            if formatter.break_char in text:text=text.replace(formatter.break_char,' '*padding[a])
            result=result[:a]+text+result[b:]
        parsed=formatter.ordinary(result);prepared,_=formatter.prepare(parsed['body'],unit_text=True)
        glyphs=font.layout(prepared,spec['native_width'],spec['scale'],ruby=parsed['ruby'])
        return result,glyphs

    for index,(at,_,_) in enumerate(events):
        _,glyphs=render()
        prefix=sum(not c.isspace() for text in planned[:index+1] for c in text)
        word=re.match(r'\s*(\S+)',planned[index+1])
        through=prefix+(len(word[1]) if word else 0)
        visible=[g for g in glyphs if not chr(g['code']).isspace()]
        previous=visible[prefix-1] if prefix else None
        cursor=previous['x']+int(previous['advance']*spec['scale']) if previous else 0
        estimate=max(1,(spec['native_width']-cursor)//step)
        # Try the measured remainder first, then neighboring integer space counts.
        for count in sorted(range(1,maximum+1),key=lambda n:abs(n-estimate)):
            padding[at]=count
            result,glyphs=render()
            actual=[(g['code'],g['line']) for g in glyphs if not chr(g['code']).isspace()]
            if actual[:through]==expected[:through]:break
        else:raise ValueError('No space padding reproduces this timed word/ruby boundary with the current font')
    result,glyphs=render()
    if [(g['code'],g['line']) for g in glyphs if not chr(g['code']).isspace()]!=expected:
        raise ValueError('Space padding does not reproduce the complete timed layout')
    before=formatter.ordinary(source);after=formatter.ordinary(result)
    if [m[1:] for m in before['markers']]!=[m[1:] for m in after['markers']]:
        raise ValueError('Space padding would change queue directives')
    return result
