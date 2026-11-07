"""Read only the authored environment fields used by the Python preview.

Counted records are walked by their format, never by corpus-specific offsets.
References: gauge.cpp, chapter.cpp, uisprite.cpp.
"""
from .scriptcodec import Reader
from .text import color


def table(reader,stride):reader.take(reader.count()*stride)


def points(reader):return [[reader.word('i'),reader.word('i')] for _ in range(reader.count())]


def sprite(reader,legacy=True):
    parameter=reader.word('h' if legacy else 'i')
    values=[reader.word('i') for _ in range(7)];rgba=color(reader.word())
    return dict(parameter=parameter,alignment=values[0],x=values[1],y=values[2],sx=values[3],sy=values[4],
                width=values[5],height=values[6],color=rgba)


def selection(data):
    r=Reader(data);r.take(3);font=r.word('H');r.take(16+12)
    sprites=[sprite(r,False) for _ in range(3)]
    tables=[points(r),points(r)];words=[r.word('i') for _ in range(6)]
    scale=r.word('f');colors=[color(r.word()),color(r.word())]
    return dict(font=font,sprites=sprites,points=tables,words=words,scale=scale,colors=colors)


def battle(data):
    r=Reader(data);r.take(15);minimum=r.word('i');thresholds=r.count()
    if not thresholds:raise ValueError('Empty battle threshold table')
    neutral=r.word('i');r.take((thresholds-1)*4)
    r.take(34+8*4+4*34)
    name_scale,text_scale=r.word('f'),r.word('f')
    name_positions,name_sizes=points(r),points(r)
    name_offsets=[r.word('i') for _ in range(r.count())]
    names=[r.string() for _ in range(r.count())]
    text_positions=points(r);padding=r.word('i')
    colors=[color(r.word()) for _ in range(r.count())]
    r.take(4);positions=[[r.word('i'),r.word('i')] for _ in range(2)]
    bubble=sprite(r);scale=r.word('f');line_offsets=[[r.word('i'),r.word('i')] for _ in range(2)]
    width=r.word('i');r.take(5*34)
    for _ in range(r.count()):table(r,8)
    r.take(2*34+4+34+12);table(r,4);r.take(34+16+3*34)
    r.take(2*34+4);table(r,16);table(r,8);r.take(2*34+8)
    table(r,16);table(r,16)
    for _ in range(4):table(r,8)
    settings=[r.word('i') for _ in range(13)]
    duration=r.word('i');display=r.word('i');x_per_point=r.word('i');scale_per_point=r.word('f')
    r.take(16);choice_positions=points(r);table(r,34);card_scale=r.word('f')
    choice_offsets=[[r.word('i'),r.word('i')] for _ in range(2)]
    pulses=[[r.word('f'),r.word('f'),r.word('i')] for _ in range(3)];labels=[r.string() for _ in range(r.count())]
    label_positions=points(r);label_scale=r.word('f')
    if not 0<=minimum<=50 or duration<0:raise ValueError('Invalid battle gauge settings')
    return dict(minimum=minimum,neutral=neutral,duration=duration,display=display,x=x_per_point,
                scale=scale_per_point,positions=positions,line_offsets=line_offsets,width=width,
                bubble=bubble,bubble_scale=scale,versus=settings,name_scale=name_scale,text_scale=text_scale,
                name_positions=name_positions,name_sizes=name_sizes,name_offsets=name_offsets,names=names,
                text_positions=text_positions,padding=padding,colors=colors,choice_positions=choice_positions,
                choice_offsets=choice_offsets,labels=labels,label_positions=label_positions,label_scale=label_scale,
                choice_reveal=settings[3],card_scale=card_scale,pulses=pulses)


def approach(data):
    r=Reader(data);r.take(15+6*34+16);table(r,34)
    parent_sprites=[sprite(r),sprite(r)];text_offset=[r.word('i'),r.word('i')];sprite(r)
    hit=[r.word('i') for _ in range(4)]
    table(r,34);table(r,34);table(r,16)
    tables=[points(r),points(r)];selected_offset=r.word('i')
    tables.extend(points(r) for _ in range(4))
    colors=[color(r.word())];text_scale=r.word('f');colors.extend(color(r.word()) for _ in range(2))
    rects=[[r.word('i') for _ in range(4)] for _ in range(2)];offset=[r.word('i'),r.word('i')]
    scroll_distance,scroll_duration=r.word('i'),r.word('i')
    r.take(4*34);result_origin=[r.word('i'),r.word('i')];result_width=r.word('i');result_scale=r.word('f')
    r.take(6*34)
    duration,particle_min,particle_max,count=(r.word('i') for _ in range(4))
    if duration<0 or particle_min<=0 or particle_max<particle_min or not 0<=count<=10000:
        raise ValueError('Invalid approach gauge settings')
    return dict(duration=duration,particle_min=particle_min,particle_max=particle_max,particles=count,
                parent_sprites=parent_sprites,text_offset=text_offset,hit=hit,points=tables,
                selected_offset=selected_offset,colors=colors,scale=text_scale,rects=rects,offset=offset,
                scroll_distance=scroll_distance,scroll_duration=scroll_duration,
                result_origin=result_origin,result_width=result_width,result_scale=result_scale)


def chapter(data):
    r=Reader(data);r.take(3+16+34)
    table(r,34);table(r,4);r.take(68);table(r,8);r.take(34+20)
    r.string();r.take(12+16+4);duration=r.word('i')
    if duration<0:raise ValueError('Negative chapter transition duration')
    return duration


def chapter_text(data):
    r=Reader(data);r.take(3+16+34)
    table(r,34);table(r,4);r.take(68);table(r,8);r.take(34+20)
    r.string();r.take(12)
    positions=[[r.word('i'),r.word('i')] for _ in range(2)];scale=r.word('f')
    return dict(positions=positions,scale=scale)
