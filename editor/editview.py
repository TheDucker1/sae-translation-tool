"""Typed text-command forms. Reference pickers store stable IDs, not numbers."""
from copy import deepcopy
import json,re
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QGroupBox,
    QLabel,QLineEdit,QPlainTextEdit,QComboBox,QPushButton,QScrollArea,QWidget,QDialogButtonBox,QSpinBox,QCheckBox)
from .engine import TEXT_OPS,text_fields
from .opcodes import CATALOG
from . import scriptcodec as codec
from .templates import template
from .textlayout import TextLayoutService,editable_newlines,normalize_arguments,is_text_field,supports_breaks,field_path
from .fontpatch import effective_font


class RefPicker(QComboBox):
    def __init__(self,script,value,exclude=None):
        super().__init__()
        for i,c in enumerate(script.commands):
            if c.uid!=exclude:self.addItem(f'#{i} · {CATALOG[c.opcode].name if c.opcode in CATALOG else hex(c.opcode)} · {c.uid}',{'$ref':c.uid})
        found=next((i for i in range(self.count()) if self.itemData(i)==value),None)
        if found is None:self.addItem('UNRESOLVED: '+str(value),value);found=self.count()-1
        self.setCurrentIndex(found)
    def value(self):return deepcopy(self.currentData())


class FormValue(QWidget):
    def __init__(self,value,path,owner):
        super().__init__();self.path=path;self.owner=owner;layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        if path and owner.opcode==0x65 and path[-1] in {'duration','preview'}:
            layout.addWidget(QLabel(str(value)+' (decoder default; not serialized)'));self.read=lambda:deepcopy(value)
        elif isinstance(value,dict) and '$ref' in value:
            self.input=RefPicker(owner.script,value);layout.addWidget(self.input);self.read=self.input.value
        elif isinstance(value,dict):
            form=QFormLayout();layout.addLayout(form);self.children_values={}
            for key,v in value.items():
                child=FormValue(v,path+(key,),owner);self.children_values[key]=child
                label=QLabel(key);hint=owner.hint(path+(key,));label.setToolTip(hint);child.setToolTip(hint);form.addRow(label,child)
            self.read=lambda:{key:child.read() for key,child in self.children_values.items()}
        elif isinstance(value,list):
            if path[-1]=='extras':
                text=QPlainTextEdit(json.dumps(value,ensure_ascii=False));text.setReadOnly(True);text.setMaximumHeight(65);layout.addWidget(QLabel('Protected auxiliary strings (preserved)'));layout.addWidget(text);self.read=lambda:deepcopy(value)
            else:
                self.rows=[];self.row_layout=QVBoxLayout();layout.addLayout(self.row_layout)
                self.mutable=path[-1] in {'choices','parents','children'}
                for v in value:self.append(v)
                if self.mutable:
                    button=QPushButton('Add '+str(path[-1]).rstrip('s'));button.clicked.connect(self.add_row);layout.addWidget(button)
                self.read=lambda:[child.read() for box,child in self.rows]
        elif isinstance(value,str):
            if path[-1] in {'condition'}:
                self.input=QLineEdit(value);layout.addWidget(self.input);self.read=self.input.text
            else:
                translated=is_text_field(owner.opcode,path)
                multiline=translated and supports_breaks(owner.opcode)
                self.input=QPlainTextEdit(editable_newlines(value,owner.formatter) if multiline else value);self.input.setMinimumHeight(75);self.input.setMaximumHeight(135);layout.addWidget(self.input);self.read=self.input.toPlainText
                if translated and owner.text_layout:
                    row=QHBoxLayout();wrap=QPushButton('Wrap words' if multiline else 'Check fit');row.addWidget(wrap)
                    note=QLabel('Enter = game line break' if multiline else 'Single line; authored screen position determines fit');note.setWordWrap(True);row.addWidget(note,1);layout.addLayout(row)
                    def format_text():
                        try:
                            result=owner.text_layout.wrap(owner.opcode,self.input.toPlainText(),field='.'.join(str(p) if not isinstance(p,int) else f'[{p}]' for p in self.path).replace('.[','['),width=owner.wrap_width.value() or None,dialogue_mode=owner.dialogue_mode.currentData(),full_width_latin=owner.full_width.isChecked() or owner.proportional_font and supports_breaks(owner.opcode),preserve_speaker=owner.proportional_font)
                            self.input.selectAll();self.input.insertPlainText(result['editor_text'])
                            note.setText(f"{result['line_count']} line(s), widest {max(result['line_widths'],default=0)}/{result['width']}px");owner.error.clear()
                        except ValueError as error:owner.error.setText(str(error))
                    wrap.clicked.connect(format_text)
        elif isinstance(value,(int,bool)):
            self.input=QLineEdit(str(int(value)));layout.addWidget(self.input)
            def integer():
                text=self.input.text().strip()
                if not re.fullmatch(r'-?\d+',text):raise ValueError(f'{path}: integer required')
                return int(text)
            self.read=integer
        else:raise ValueError(f'Unsupported field type at {path}')

    def append(self,value):
        box=QGroupBox(str(self.path[-1])+' entry');layout=QVBoxLayout(box);child=FormValue(value,self.path+(len(self.rows),),self.owner);layout.addWidget(child)
        self.rows.append((box,child));self.row_layout.addWidget(box)
        if self.mutable:
            remove=QPushButton('Remove this entry');layout.addWidget(remove)
            def remove_row():self.rows.remove((box,child));self.row_layout.removeWidget(box);box.deleteLater()
            remove.clicked.connect(remove_row)

    def add_row(self):
        key=self.path[-1];ref={'$ref':self.owner.default_target}
        if key=='choices':v=dict(target=ref,label='New choice',preview=-1,extras=['0'] if self.owner.opcode==0x3f2 else [])
        elif key=='children':v=dict(target=ref,label='New choice')
        else:v=dict(label='New topic',condition='1',children=[dict(target=ref,label='New choice')])
        self.append(v)


class TextCommandDialog(QDialog):
    def __init__(self,project,sid,index,mode='edit',parent=None):
        super().__init__(parent);self.script=project.scripts[sid];self.mode=mode;self.resize(820,780);self.formatter=project.text_format
        self.proportional_font=bool(project.font_asset)
        session=getattr(parent,'session',None);self.text_layout=TextLayoutService(effective_font(project,session.text),session.settings) if session and session.text else None
        self.command=self.script.commands[index] if index<len(self.script.commands) else None
        following=index if mode=='add_before' else index+1
        self.default_target=self.script.commands[min(following,len(self.script.commands)-1)].uid if self.script.commands else f'self:{sid}'
        self.setWindowTitle(mode.title()+' text opcode — project only')
        layout=QVBoxLayout(self);self.kinds=QComboBox()
        for code in sorted(TEXT_OPS):self.kinds.addItem(f'{code:04X} · {CATALOG[code].name}',code)
        code=self.command.opcode if self.command and self.command.opcode in TEXT_OPS else 0x64
        self.kinds.setCurrentIndex(self.kinds.findData(code));self.kinds.setEnabled(mode!='edit');layout.addWidget(self.kinds)
        self.note=QLabel('Multiline text: Enter becomes a game break; Wrap words uses game metrics and keeps existing breaks. Single-line labels: Check fit. Targets bind to stable IDs.');self.note.setWordWrap(True);layout.addWidget(self.note)
        row=QHBoxLayout();self.dialogue_mode=QComboBox();self.dialogue_mode.addItem('Message window','ordinary');self.dialogue_mode.addItem('Battle dialogue','battle');row.addWidget(self.dialogue_mode)
        row.addWidget(QLabel('Wrap width (game px):'));self.wrap_width=QSpinBox();self.wrap_width.setRange(0,4096);self.wrap_width.setSpecialValueText('Authored width');row.addWidget(self.wrap_width);layout.addLayout(row)
        self.full_width=QCheckBox('Full-width Latin when using Wrap words / Check fit');layout.addWidget(self.full_width)
        if self.proportional_font:
            info=QLabel('Proportional font selected: Apply fits multiline text using its bitmap aliases; speaker text is preserved.');info.setWordWrap(True);layout.addWidget(info)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);layout.addWidget(self.scroll,1)
        self.error=QLabel();self.error.setWordWrap(True);self.error.setStyleSheet('color:#f6b19e');layout.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(self.apply);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.kinds.currentIndexChanged.connect(self.rebuild);self.rebuild()

    @property
    def opcode(self):return self.kinds.currentData()

    def hint(self,path):
        key='.'.join(str(p) if not isinstance(p,int) else '[]' for p in path).replace('.[]','[]')
        spec=next((f for f in CATALOG[self.opcode].fields if f.key==key),None)
        return f'{spec.type}: {spec.meaning}' if spec else 'See Opcode reference for conditional layout and protected fields.'

    def rebuild(self,*_):
        self.dialogue_mode.setEnabled(self.opcode==0x64)
        if self.mode in {'edit','replace'} and self.command and self.opcode==self.command.opcode:value=deepcopy(self.command.args)
        else:value=template(self.opcode,self.default_target)
        self.form=FormValue(value,(),self);self.scroll.setWidget(self.form)

    def apply(self):
        try:
            values=self.form.read()
            if self.proportional_font and supports_breaks(self.opcode) and self.text_layout:
                for key,value in text_fields(dict(opcode=self.opcode,args=values)):
                    packet=self.text_layout.wrap(self.opcode,value,field=key,width=self.wrap_width.value() or None,dialogue_mode=self.dialogue_mode.currentData(),full_width_latin=True,preserve_speaker=True)
                    codec.put(values,field_path(key),packet['text'])
            self.args=normalize_arguments(self.opcode,values,self.formatter)
            # Check encoder shape/ranges without treating reference IDs as ints.
            projected=deepcopy(self.args)
            for path in codec.reference_paths(self.opcode,projected):codec.put(projected,path,0)
            codec.encode_text(self.opcode,projected)
        except (ValueError,KeyError,TypeError) as e:self.error.setText(str(e));return
        self.accept()
