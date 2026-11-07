"""Human browser/editor for the same non-script text fields exposed through MCP."""
import json
from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLineEdit,QCheckBox,QPushButton,
    QTableWidget,QTableWidgetItem,QHeaderView,QSplitter,QPlainTextEdit,QLabel,QAbstractItemView)
from .uitext import get_catalog


class UiTextBrowser(QDialog):
    textChanged=Signal(str)

    def __init__(self,parent):
        super().__init__(parent);self.owner=parent;self.setWindowTitle('UI text — environments and catalogues');self.resize(1250,850)
        self.project=None;self.catalog=None;self.identity=None;self.expected='';self.revision=None
        layout=QVBoxLayout(self);bar=QHBoxLayout();layout.addLayout(bar)
        self.search=QLineEdit();self.search.setPlaceholderText('Search original/current text, source, category or field ID');bar.addWidget(self.search,1)
        self.protected=QCheckBox('Show protected fields');bar.addWidget(self.protected)
        refresh=QPushButton('Refresh');refresh.clicked.connect(self.refresh);bar.addWidget(refresh)
        self.search.textChanged.connect(self.populate);self.protected.toggled.connect(self.populate)
        split=QSplitter(Qt.Vertical);layout.addWidget(split,1)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Category / role','Source / field','Original','Current'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for col,width in enumerate((200,280,340,340)):self.table.setColumnWidth(col,width)
        self.table.itemSelectionChanged.connect(self.selected);split.addWidget(self.table)
        lower=QSplitter();split.addWidget(lower);split.setSizes([400,350])
        self.details=QPlainTextEdit();self.details.setReadOnly(True);lower.addWidget(self.details)
        self.edit=QPlainTextEdit();self.edit.setPlaceholderText('Translation; preserve format/control tokens');lower.addWidget(self.edit)
        footer=QHBoxLayout();layout.addLayout(footer)
        self.apply=QPushButton('Apply field');self.apply.clicked.connect(self.commit);footer.addWidget(self.apply)
        self.revert=QPushButton('Revert field');self.revert.clicked.connect(lambda:self.commit(True));footer.addWidget(self.revert)
        match=QPushButton('Match font in draft');match.clicked.connect(self.match_font);footer.addWidget(match)
        preview=QPushButton('Preview field…');preview.clicked.connect(self.preview_field);footer.addWidget(preview)
        self.note=QLabel();self.note.setWordWrap(True);footer.addWidget(self.note,1)

    def refresh(self):
        try:self.set_project(self.owner.project,force=True)
        except (ValueError,OSError) as error:self.note.setText(str(error))

    def set_project(self,project,force=False):
        if project is None:self.project=None;self.table.setRowCount(0);return
        dirty=self.identity is not None and self.edit.toPlainText()!=self.expected
        if not force and dirty and self.revision!=project.revision:
            self.note.setText('Project changed. Draft retained; reselect/Refresh to reload. A stale Apply will be rejected.');return
        self.project=project;self.catalog=get_catalog(project);self.populate()

    def populate(self,*_):
        if self.project is None:return
        selected=self.identity;query=self.search.text().casefold();rows=[]
        for identity,f in self.catalog.fields.items():
            current=self.project.ui_text_assets.get(identity,{}).get('text',f['original'])
            if not self.protected.isChecked() and not f['editable']:continue
            if query not in ' '.join((identity,f['category'],f['role'],f['renderer'],f['fit_policy'],f['original'],current)).casefold():continue
            rows.append((identity,f,current))
        self.table.blockSignals(True);self.table.setRowCount(len(rows));chosen=0
        for row,(identity,f,current) in enumerate(rows):
            if identity==selected:chosen=row
            values=(f['category']+' / '+f['role'],identity,f['original'],current)
            for column,value in enumerate(values):
                item=QTableWidgetItem(value);item.setData(Qt.UserRole,identity);self.table.setItem(row,column,item)
        self.table.blockSignals(False)
        summary=self.catalog.summary();self.note.setText(f"{len(rows)} shown / {summary['fields']} fields; {len(self.project.ui_text_assets)} edited. {len(summary['issues'])} inventory issue(s).")
        if rows:self.table.selectRow(chosen)
        self.selected()

    def selected(self):
        items=self.table.selectedItems()
        if not items:self.identity=None;self.apply.setEnabled(False);self.revert.setEnabled(False);return
        self.identity=items[0].data(Qt.UserRole);f=self.catalog.fields[self.identity]
        self.expected=self.project.ui_text_assets.get(self.identity,{}).get('text',f['original']);self.revision=self.project.revision
        self.edit.setPlainText(self.expected);self.edit.setReadOnly(not f['editable'])
        self.apply.setEnabled(f['editable']);self.revert.setEnabled(self.identity in self.project.ui_text_assets)
        self.note.setText(f.get('font_guidance','')+' Fit coverage: '+f['fit_policy']+'.')
        self.details.setPlainText(json.dumps(f,ensure_ascii=False,indent=2)+'\n\nInventory coverage / issues:\n'+json.dumps(self.catalog.summary(),ensure_ascii=False,indent=2))

    def commit(self,revert=False):
        if self.identity is None:return
        try:
            self.owner.guard_edit_snapshot(self.project,self.revision)
            text=self.catalog.fields[self.identity]['original'] if revert else self.edit.toPlainText()
            previous=self.project.revision
            if self.project.set_ui_texts([(self.identity,self.expected,text)]):
                self.expected=text;self.revision=self.project.revision;self.textChanged.emit(previous)
            self.set_project(self.project,force=True)
        except (ValueError,RuntimeError,OSError) as error:self.note.setText(str(error))

    def match_font(self):
        if self.identity is None:return
        try:
            from .fontstyle import ui_proposal
            proposal=ui_proposal(self.project,self.identity,self.edit.toPlainText(),None)
            self.edit.setPlainText(proposal['text']);self.note.setText(proposal['note']+' Apply field to save this draft.')
        except (ValueError,KeyError,OSError) as error:self.note.setText(str(error))

    def preview_field(self):
        if self.identity is None:return
        try:
            from .uipreview import show_ui_preview
            self.owner.guard_edit_snapshot(self.project,self.revision)
            plan=None;draft=self.edit.toPlainText()
            if draft!=self.expected:
                from .fontstyle import ui_proposal
                text=ui_proposal(self.project,self.identity,draft,None)['text']
                plan=dict(revision=self.revision,ui_changes=[dict(field_id=self.identity,after_text=text)])
            show_ui_preview(self.owner,self.project,self.identity,plan=plan)
        except (ValueError,RuntimeError,OSError) as error:self.note.setText(str(error))
