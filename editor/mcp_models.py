"""Strict bounded MCP arguments; optional MCP dependencies stay out of the GUI."""
from typing import Annotated,Any,Literal
from pydantic import BaseModel,ConfigDict,Field

Id=Annotated[str,Field(min_length=1,max_length=128)]
Index=Annotated[int,Field(ge=0,strict=True)]
Limit=Annotated[int,Field(ge=1,le=100,strict=True)]


class StrictModel(BaseModel):model_config=ConfigDict(extra='forbid',strict=True)


class TranslationEdit(StrictModel):
    script_id:Index
    command_id:Id
    field:Annotated[str,Field(min_length=1,max_length=128)]
    expected_text:Annotated[str,Field(max_length=1048576)]
    translation:Annotated[str,Field(max_length=131070)]
    wrap_words:bool=False
    full_width_latin:bool=False
    layout_width:Annotated[int,Field(ge=1,le=4096,strict=True)]|None=None
    dialogue_mode:Literal['ordinary','battle']='ordinary'


class CommandEdit(StrictModel):
    action:Literal['insert_before','insert_after','replace','delete']
    script_id:Index
    command_id:Id
    opcode:Literal[0x64,0x65,0x3ec,0x3f2,0x3f6,0x3f8,0x3f9]|None=None
    arguments:dict[str,Any]|None=None
    replacement_id:Id|None=None


class PreviewInput(StrictModel):
    dt_ms:Annotated[int,Field(ge=0,le=60000)]=16
    advance:bool=False
    reveal:bool=False
    skip:bool=False
    choice:Index|None=None
    parent:Index|None=None
    child:Index|None=None
    back:bool=False
    timeout:bool=False
    service_complete:bool=False
    profile_ordinal:Index|None=None
    profile_event:Index|None=None
    confirm_profile:bool=False
    cancel_profile:bool=False
    flush_lanes:bool=False


class BankEdit(StrictModel):
    kind:Literal['L','G','battle','approach']
    index:Index=0
    value:Annotated[int,Field(ge=-32768,le=32767,strict=True)]
