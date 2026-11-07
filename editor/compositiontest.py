"""Settled native developer test-menu captions; test scenes/media do not run."""
from .scriptcodec import Reader
from .composition import Composition,text_layer
from .compositioncommon import cached
from .imagecodec import ImageError


def test_environment(data):
    r=Reader(data);flags=r.take(3);labels=[r.string() for _ in range(r.count())]
    settings=[r.word() for _ in range(5)]
    if r.pos!=len(data):raise ImageError('Unexpected developer test environment tail')
    return dict(flags=flags,labels=labels,settings=settings)


def caption_position(index,size):return [100,100+24*index-size//2]


def test_layout(library,state,font):
    if font is None:raise ImageError('Original font is required')
    e=cached(library,'developer_test','env/env_test.dat',test_environment)
    out=Composition('Developer test menu',clear=(128,128,128,255),
        notes=['Native root test-menu captions only. No Live2D test, scene callbacks or debug state run.'])
    size=font.utility;selected=state.get('selected',0)
    if not 0<=selected<len(e['labels']):raise ImageError('Developer test selection outside caption table')
    for index,label in enumerate(e['labels']):
        x,y=caption_position(index,size)
        out.layers.append(text_layer('Test caption shadow '+str(index),label,[x+1,y+1],size,[0,0,0,255],font))
        out.layers.append(text_layer('Test caption '+str(index),label,[x,y],size,[255]*4,font))
        if index==selected:
            out.layers.append(text_layer('Test selection shadow','->',[77,y+1],size,[0,0,0,255],font))
            out.layers.append(text_layer('Test selection','->',[76,y],size,[255]*4,font))
    return out


ADAPTERS={'test':test_layout}
