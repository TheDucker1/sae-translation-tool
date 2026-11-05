"""Searchable reference browser and selected-command help. Entirely read-only."""
import json
from PySide6.QtCore import Qt, QMimeData,Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QSplitter,QListWidget,QListWidgetItem,QLineEdit,QTextBrowser,QCheckBox,QLabel
from .opcodes import CATALOG,markdown
from .engine import TEXT_OPS

TEXT_TEMPLATE_MIME='application/x-saekano-text-opcode'


class TemplateList(QListWidget):
    dragStarted=Signal()
    def startDrag(self,actions):
        item=self.currentItem()
        if item is None or item.data(Qt.UserRole) not in TEXT_OPS:return
        self.dragStarted.emit();mime=QMimeData();mime.setData(TEXT_TEMPLATE_MIME,str(item.data(Qt.UserRole)).encode('ascii'));drag=QDrag(self);drag.setMimeData(mime);drag.exec(Qt.CopyAction)


def current_markdown(command,technical=False):
    if not command:return ''
    # Raw source text stays runtime-only; never included in generated reference.
    result='\n## Selected instance\n\n'+f"Command #{command['index']}. Use Edit for text/choices; read-only arguments are under Advanced.\n"
    if technical:
        result+=f"\nOffset {command.get('offset','?')} · size {command.get('size','?')}\n\n"+'```json\n'+json.dumps(command['args'],ensure_ascii=False,indent=2)+'\n```\n\nDecoded default fields may be present even when absent from wire. Follow the conditional layout above.\n'
    return result


def help_markdown(command,technical=False):
    if command is None:return '# Opcode help\n\nSelect a command for behavior, parameter meanings and values.'
    op=CATALOG.get(command['opcode'])
    if op is None:return f"# Unknown opcode 0x{command['opcode']:04X}\n\nNo documented contract. Preserve raw bytes; do not guess argument meanings.\n"+current_markdown(command)
    return markdown(op,technical)+current_markdown(command,technical)


def browser():
    view=QTextBrowser();view.setOpenExternalLinks(False)
    return view


class OpcodeReference(QWidget):
    def __init__(self):
        super().__init__();self.command=None;self.code=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,4,0,0)
        row=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Search opcode, name, behavior or parameter…');self.search.textChanged.connect(self.filter);row.addWidget(self.search)
        self.follow=QCheckBox('Follow selection');self.follow.setChecked(True);self.follow.toggled.connect(lambda enabled:self.show_command(self.command) if enabled else None);row.addWidget(self.follow);layout.addLayout(row)
        self.technical=QCheckBox('Technical details');self.technical.toggled.connect(lambda _:self.browse(self.list.currentItem()));row.addWidget(self.technical)
        split=QSplitter();layout.addWidget(split,1);self.list=TemplateList();self.list.setDragEnabled(True);self.list.setMinimumWidth(175);split.addWidget(self.list);self.document=browser();split.addWidget(self.document);split.setSizes([190,550])
        self.list.currentItemChanged.connect(self.browse)
        for code,op in sorted(CATALOG.items()):
            item=QListWidgetItem(f'{code:04X}  {op.name}'+('' if op.used else ' [unused]'));item.setData(Qt.UserRole,code);item.setToolTip(op.behavior);self.list.addItem(item)
        note=QLabel(f'{sum(o.used for o in CATALOG.values())} used families · {len(CATALOG)} registrations · drag text opcodes onto Commands to add');note.setWordWrap(True);layout.addWidget(note)
        self.list.setCurrentRow(0)

    def filter(self,text):
        query=text.casefold().strip()
        for i in range(self.list.count()):
            item=self.list.item(i);op=CATALOG[item.data(Qt.UserRole)]
            searchable=f'{op.code:04x} 0x{op.code:x} {op.code} {op.name} {op.behavior} '+ ' '.join(p.key+' '+p.meaning for p in op.fields)
            item.setHidden(query not in searchable.casefold())

    def browse(self,item,*_):
        if item is None:return
        self.code=item.data(Qt.UserRole);op=CATALOG[self.code]
        current=self.command if self.command and self.command['opcode']==self.code else None
        technical=self.technical.isChecked()
        self.document.setMarkdown(markdown(op,technical)+current_markdown(current,technical))

    def show_command(self,command):
        self.command=command
        if self.follow.isChecked() and command and command['opcode'] in CATALOG:
            self.search.clear()
            for i in range(self.list.count()):
                item=self.list.item(i)
                if item.data(Qt.UserRole)==command['opcode']:
                    self.list.setCurrentItem(item);self.list.scrollToItem(item);break
        self.browse(self.list.currentItem())
