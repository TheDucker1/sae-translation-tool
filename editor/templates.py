"""Shared Python command templates for GUI and MCP authoring."""
from copy import deepcopy


def template(op,target):
    ref={'$ref':target}
    if op==0x64:return dict(route=0,selector=0,voice=-1,speaker=-1,text='New dialogue',completion=0,lane=0)
    if op in {0x65,0x3f2}:return dict(duration=0,choices=[dict(target=ref,label='New choice',preview=-1,extras=['0'] if op==0x3f2 else [])])
    if op==0x3f6:return dict(parents=[dict(label='New topic',condition='1',children=[dict(target=ref,label='New choice')])])
    if op==0x3f8:return dict(required_gauge=50,outcomes=[dict(target=deepcopy(ref),text=label,voice=-1) for label in ('Success','Failure')])
    if op==0x3f9:return dict(texts=['First caption','Second caption'])
    if op==0x3ec:return dict(chapter=0,texts=['Chapter title','Subtitle'])
    raise ValueError('Not a text opcode')
