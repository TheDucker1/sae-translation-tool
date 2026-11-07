from __future__ import annotations

import json
import hashlib
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QTimer, QSettings, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QImage, QPen, QFont, QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QSplitter, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit, QFileDialog, QTableView,
    QHeaderView, QTabWidget, QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QGroupBox,
    QSpinBox, QDoubleSpinBox, QCheckBox, QFormLayout, QMessageBox, QListWidget,
    QListWidgetItem, QScrollArea, QInputDialog,QProgressDialog)
from PySide6.QtWidgets import QMenu

from .engine import Session, ROOT, NAMES, BOUNDARIES, BRANCHES, TEXT_OPS, Analysis, summary, category, branch_options, prepare_condition, text_fields
from .routes import RouteBook
from .flowmodel import script_diagram, file_diagram
from .flowview import FlowPanel
from .opcodeview import OpcodeReference, browser, help_markdown,TEXT_TEMPLATE_MIME
from .gameexport import export_game,ExportCancelled
from .document import Project,EditError,Diagnostic
from .editview import TextCommandDialog,RefPicker
from .scriptcodec import reference_paths

COLORS = {'Text': '#74ccb8', 'Flow': '#d9ad66', 'Actor': '#ae9be8',
          'Audio / movie': '#76acd9', 'Gameplay': '#dc8ba3', 'Scene': '#9ca7b7'}


def load_ui_fonts():
    # Offscreen Qt does not enumerate Windows fonts. Register the same local
    # faces explicitly so automatic screenshots exercise readable UI too.
    if not QFontDatabase.families():
        import os
        fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        for name in ('segoeui.ttf', 'consola.ttf', 'YuGothR.ttc'):
            QFontDatabase.addApplicationFont(str(fonts / name))


class Loader(QThread):
    ready = Signal(dict)
    failed = Signal(str)

    def __init__(self, session, path):
        super().__init__(); self.session, self.path = session, path

    def run(self):
        try: self.ready.emit(self.session.call('open', path=self.path))
        except Exception as e: self.failed.emit(str(e))


class GameExporter(QThread):
    progress=Signal(str)

    def __init__(self,project,destination):
        super().__init__();self.project=project;self.destination=destination;self.result=None;self.error='';self.cancelled=False

    def run(self):
        try:self.result=export_game(self.project,self.destination,self.progress.emit,self.isInterruptionRequested)
        except ExportCancelled:self.cancelled=True
        except Exception as e:self.error=str(e)


class CommandFilter(QSortFilterProxyModel):
    text_only=False
    def filterAcceptsRow(self,row,parent):
        if self.text_only and self.sourceModel().rows[row]['opcode'] not in TEXT_OPS:return False
        return super().filterAcceptsRow(row,parent)

    def only_text(self,enabled):
        self.text_only=enabled;self.invalidateFilter()


class CommandTable(QTableView):
    templateDropped=Signal(int,int,bool)
    def __init__(self):
        super().__init__();self.setAcceptDrops(True);self.setDropIndicatorShown(True);self.setDragDropMode(QTableView.DropOnly);self.drop_y=None
    def template_code(self,event):
        try:
            code=int(bytes(event.mimeData().data(TEXT_TEMPLATE_MIME)).decode('ascii'))
            return code if code in TEXT_OPS else None
        except (ValueError,UnicodeError):return None
    def dragEnterEvent(self,event):
        if event.mimeData().hasFormat(TEXT_TEMPLATE_MIME) and self.template_code(event) is not None:event.acceptProposedAction()
        else:event.ignore()
    def dragMoveEvent(self,event):
        self.dragEnterEvent(event)
        if event.isAccepted():
            point=event.position().toPoint();index=self.indexAt(point)
            if index.isValid():rect=self.visualRect(index);self.drop_y=rect.bottom() if point.y()>rect.center().y() else rect.top()
            else:self.drop_y=self.viewport().height()-2
            self.viewport().update()
    def dragLeaveEvent(self,event):self.drop_y=None;self.viewport().update();event.accept()
    def paintEvent(self,event):
        super().paintEvent(event)
        if self.drop_y is not None:
            painter=QPainter(self.viewport());painter.setPen(QPen(QColor('#8de6cc'),3));painter.drawLine(0,self.drop_y,self.viewport().width(),self.drop_y);painter.end()
    def dropEvent(self,event):
        code=self.template_code(event)
        if code is None:event.ignore();return
        position=event.position().toPoint();index=self.indexAt(position);row=index.row() if index.isValid() else -1
        after=index.isValid() and position.y()>self.visualRect(index).center().y();event.acceptProposedAction();self.drop_y=None;self.viewport().update()
        QTimer.singleShot(0,lambda:self.templateDropped.emit(row,code,after))


class Commands(QAbstractTableModel):
    HEADERS = ['#', 'Command', 'Arguments / text']

    def __init__(self):
        super().__init__(); self.rows = []; self.current = -1

    def rowCount(self, parent=QModelIndex()): return 0 if parent.isValid() else len(self.rows)
    def columnCount(self, parent=QModelIndex()): return len(self.HEADERS)
    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole: return self.HEADERS[section]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        c = self.rows[index.row()]
        if role == Qt.DisplayRole:
            if index.column()==0:return f"{'▶ ' if index.row() == self.current else ''}{c['index']:04}"
            if index.column()==1:return f"{'TXT · ' if c['opcode'] in TEXT_OPS else ''}{NAMES.get(c['opcode']) or 'Opcode'} · {c['opcode']:04X}"
            return self.summaries.get(c['index'],'')
        if role == Qt.ForegroundRole and index.column() == 1: return QColor(COLORS['Text' if c['opcode'] in TEXT_OPS else category(c['opcode'])])
        if role == Qt.BackgroundRole and index.row() == self.current: return QColor('#263e43')
        if role == Qt.ToolTipRole: return json.dumps(c['args'], ensure_ascii=False, indent=2)

    def replace(self, rows):
        self.summaries={c['index']:summary(c) for c in rows}
        self.beginResetModel(); self.rows = rows; self.current = -1; self.endResetModel()

    def mark(self, current):
        if current==self.current:return
        old = self.current; self.current = current
        for row in {old, current}:
            if 0 <= row < len(self.rows): self.dataChanged.emit(self.index(row, 0), self.index(row, 2))


class Preview(QWidget):
    advance = Signal()
    choice_input = Signal(dict)

    def __init__(self, session):
        super().__init__(); self.session = session; self.view = {}; self.glyph_cache = {}; self.tints = {}
        self.setMinimumSize(480, 272); self.setToolTip('Click to advance dialogue • coordinates are the original 960 × 544 stage')

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(720, 408)

    def mousePressEvent(self, event):
        scale=min(self.width()/960,self.height()/544)
        x=(event.position().x()-(self.width()-960*scale)/2)/scale
        y=(event.position().y()-(self.height()-544*scale)/2)/scale
        for choice in reversed(self.view.get('choices',[])):
            rect=choice.get('rect')
            if rect and rect[0]<=x<=rect[0]+rect[2] and rect[1]<=y<=rect[1]+rect[3]:
                if choice['enabled']:self.choice_input.emit(choice['action'])
                return
        if not self.view.get('choices'):self.advance.emit()

    def clear(self): self.view = {}; self.glyph_cache.clear(); self.tints.clear(); self.update()

    def image(self, code, rgb):
        key = code, tuple(rgb)
        if key in self.tints: return self.tints[key]
        if code not in self.glyph_cache:
            data = self.session.call('glyph', code=code)
            if data.get('missing'): self.glyph_cache[code] = None
            else:
                raw = bytes.fromhex(data['rgba'])
                img = QImage(raw, data['width'], data['height'], data['width'] * 4, QImage.Format_RGBA8888).copy()
                self.glyph_cache[code] = (img, data['bitmap'],data.get('source',[0,0,data['width'],data['height']]))
        cached = self.glyph_cache[code]
        if cached is None: return None
        img, bitmap, source = cached
        if bitmap:
            # Cached symbol atlases retain RGB; generated glyphs supply alpha.
            tinted = img.convertToFormat(QImage.Format_RGBA8888)
            raw = bytearray(tinted.constBits())
            for i in range(0, len(raw), 4):
                for channel in range(3): raw[i+channel] = raw[i+channel] * rgb[channel] // 255
            tinted = QImage(bytes(raw), img.width(), img.height(), img.width()*4, QImage.Format_RGBA8888).copy()
        else:
            tinted = img.copy(); painter = QPainter(tinted)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(tinted.rect(), QColor(*rgb)); painter.end()
        self.tints[key] = tinted
        return tinted

    def paintEvent(self, event):
        from PySide6.QtCore import QRectF
        p = QPainter(self); p.fillRect(self.rect(), QColor('#101720'))
        scale = min(self.width()/960, self.height()/544)
        p.translate((self.width()-960*scale)/2, (self.height()-544*scale)/2); p.scale(scale, scale)
        p.setClipRect(QRectF(0,0,960,544)); p.fillRect(0,0,960,544,QColor('#d8e0e3'))
        p.setPen(QPen(QColor('#c0cccf'),1))
        for x in range(0,961,80): p.drawLine(x,0,x,544)
        for y in range(0,545,68): p.drawLine(0,y,960,y)
        p.setRenderHint(QPainter.Antialiasing); p.setFont(QFont('Segoe UI',11))
        p.setPen(QColor('#60747c')); p.drawText(22,30,'SCENE PREVIEW  ·  art / audio are placeholders')
        if not self.view:
            p.setFont(QFont('Segoe UI',22)); p.drawText(QRectF(0,170,960,100),Qt.AlignCenter,'Open your game’s USRDIR to begin')
            p.end(); return
        for actor in self.view.get('actors',[]):
            if not actor['visible'] or not actor['color'][3]: continue
            factor=max(.05,actor['scale']/100); x,y=actor['x'],actor['y']
            p.setOpacity(actor['color'][3]/255); color=QColor.fromHsl((actor['id']*65+170)%360,90,140)
            p.setPen(QPen(color.darker(130),3)); p.setBrush(color)
            p.drawRoundedRect(QRectF(x-70*factor,y+55*factor,140*factor,270*factor),55*factor,55*factor)
            p.drawEllipse(QRectF(x-40*factor,y-10*factor,80*factor,85*factor))
            p.setPen(Qt.white); p.drawText(QRectF(x-90,y+130,180,65),Qt.AlignCenter,f"Actor {actor['id']}\npose {actor['pose']} · face {actor['face']}")
        p.setOpacity(1)
        if self.view.get('messages'):
            p.setPen(QPen(QColor('#f4f6f6'),2)); p.setBrush(QColor(255,255,255,225)); p.drawRoundedRect(QRectF(64,386,842,156),20,20)
            p.setPen(Qt.NoPen); p.setBrush(QColor('#b6cdd1')); p.drawRoundedRect(QRectF(75,349,220,38),15,15)
        for panel in self.view.get('panels',[]):
            p.setPen(QPen(QColor('#8fa6b0'),1));p.setBrush(QColor(38,54,67,225) if panel['dark'] else QColor(255,255,255,235))
            p.drawRoundedRect(QRectF(*panel['rect']),10,10)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        for g in self.view.get('glyphs',[]):
            if not g['color'][3]: continue
            try: image=self.image(g['code'],g['color'][:3])
            except RuntimeError: image=None
            if image is not None:
                p.setOpacity(g['color'][3]/255); p.drawImage(QRectF(*g['rect']),image,QRectF(*self.glyph_cache[g['code']][2]))
        p.setOpacity(1); p.end()


class Window(QMainWindow):
    def __init__(self, usrdir=None, script=0):
        super().__init__(); load_ui_fonts(); self.setWindowTitle('Saekano Script Studio — text editor'); self.resize(1500,930)
        self.session=Session(); self.scripts=[]; self.script_id=-1; self.commands=[]; self.view={}; self.playing=False; self.target=None
        self.start_script=script; self.settings=QSettings('SaekanoLocal','ScriptStudioPoC'); self.rewind_points=[0]; self.branch_signature=None
        self.routes=RouteBook();self.script_cache={};self.seek_origin=None;self.target_phase='before';self.seek_steps=0;self.state_origin='Fresh file entry';self.file_signature=None
        self.project=None;self.project_path=None;self.preview_revision=None;self.diagnostics=[]
        self.project_disk_hash=None;self.interaction_revision=uuid.uuid4().hex
        self.mcp_panel=None;self.mcp_workspace=None;self.export_worker=None;self.export_remote=False;self.image_panel=None;self.ui_text_panel=None
        self.model=Commands(); self.proxy=CommandFilter(self); self.proxy.setSourceModel(self.model); self.proxy.setDynamicSortFilter(False); self.proxy.setFilterKeyColumn(-1); self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        central=QWidget(); self.setCentralWidget(central); outer=QVBoxLayout(central); outer.setContentsMargins(16,14,16,10)
        top=QHBoxLayout(); title=QLabel('SCRIPT STUDIO'); title.setStyleSheet('font-size:21px;font-weight:700;letter-spacing:2px'); top.addWidget(title)
        top.addStretch(); self.folder=QLineEdit(usrdir or self.settings.value('usrdir',str(ROOT.parent/'GAMEFILE/USRDIR'))); self.folder.setPlaceholderText('Original USRDIR folder (read-only)'); top.addWidget(self.folder,2)
        self.browse=QPushButton('Browse…'); self.browse.clicked.connect(self.browse_folder); top.addWidget(self.browse)
        self.open_button=QPushButton('Load game'); self.open_button.setObjectName('primary'); self.open_button.clicked.connect(self.load_game); top.addWidget(self.open_button); outer.addLayout(top)
        self.mcp_button=QPushButton('MCP…');self.mcp_button.clicked.connect(self.show_mcp_panel);top.addWidget(self.mcp_button)
        self.fit_button=QPushButton('Auto-fit text…');self.fit_button.clicked.connect(self.auto_fit_text);top.addWidget(self.fit_button)
        self.images_button=QPushButton('Images…');self.images_button.clicked.connect(self.show_images);top.addWidget(self.images_button)
        self.ui_text_button=QPushButton('UI text…');self.ui_text_button.clicked.connect(self.show_ui_text);top.addWidget(self.ui_text_button)
        bar=QHBoxLayout(); self.selector=QComboBox(); self.selector.setMinimumWidth(280); self.selector.currentIndexChanged.connect(self.select_script); bar.addWidget(self.selector)
        for label,action in [('Restart',self.restart),('Rewind',self.rewind),('▶ Play',self.play),('Step',self.step_command),('Preview here',self.jump_selected),('Run forward',self.run_to_selected)]:
            b=QPushButton(label); b.clicked.connect(action); bar.addWidget(b)
            if label=='▶ Play': self.play_button=b
        self.seek_phase=QComboBox();self.seek_phase.addItems(['Before','After']);self.seek_phase.setToolTip('Recover before Start or completed-before-dispatch state');bar.addWidget(self.seek_phase)
        self.cancel_seek=QPushButton('Cancel seek');self.cancel_seek.clicked.connect(self.cancel_preview_seek);self.cancel_seek.hide();bar.addWidget(self.cancel_seek)
        self.speed=QComboBox(); self.speed.addItems(['1×','4×','20×']); bar.addWidget(self.speed)
        self.auto=QCheckBox('Auto-advance text'); self.auto.setChecked(True); bar.addWidget(self.auto); outer.addLayout(bar)
        self.state_line=QLabel('Load a game folder. Nothing writes into game files.'); self.state_line.setObjectName('state'); outer.addWidget(self.state_line)
        editbar=QHBoxLayout();editbar.addWidget(QLabel('TEXT COMMANDS'))
        for label,action in [('Add before',lambda:self.edit_text('before')),('Add after',lambda:self.edit_text('after')),('Edit',lambda:self.edit_text('edit')),('Replace',lambda:self.edit_text('replace')),('Delete',self.delete_text),('Undo',self.undo_edit),('Redo',self.redo_edit),('Validate',self.validate_project),('Save project',self.save_project),('Open project',self.open_project),('Export game…',self.export_game)]:
            button=QPushButton(label);button.clicked.connect(action);editbar.addWidget(button)
        outer.addLayout(editbar)
        splitter=QSplitter(); outer.addWidget(splitter,1)
        left=QWidget(); ll=QVBoxLayout(left); ll.setContentsMargins(0,0,8,0)
        self.preview=Preview(self.session); self.preview.advance.connect(self.step_command);self.preview.choice_input.connect(self.select_text_option); ll.addWidget(self.preview,5)
        self.policy=QLabel('Scenario simulator · silent character clock · command state retained · no game saves'); self.policy.setWordWrap(True); ll.addWidget(self.policy)
        self.branch_box=QGroupBox('Branch / choice controls'); branch_outer=QVBoxLayout(self.branch_box)
        branch_scroll=QScrollArea(); branch_scroll.setWidgetResizable(True); branch_scroll.setMaximumHeight(180); branch_scroll.setMinimumHeight(64)
        branch_content=QWidget(); self.branch_layout=QVBoxLayout(branch_content); self.branch_note=QLabel('Choices appear here when execution reaches a branch.'); self.branch_note.setWordWrap(True); self.branch_layout.addWidget(self.branch_note)
        branch_scroll.setWidget(branch_content); branch_outer.addWidget(branch_scroll); ll.addWidget(self.branch_box)
        self.branch_box.hide()
        debug=QGroupBox('Debug state — explicit sandbox overrides'); form=QVBoxLayout(debug)
        row=QHBoxLayout(); self.bank=QComboBox(); self.bank.addItems(['L','G','battle','approach']); row.addWidget(self.bank)
        self.variable=QSpinBox(); self.variable.setRange(0,1023); row.addWidget(self.variable); self.value=QSpinBox(); self.value.setRange(-32768,32767); row.addWidget(self.value)
        set_button=QPushButton('Apply state'); set_button.clicked.connect(self.set_state); row.addWidget(set_button); form.addLayout(row)
        self.debug_routes=QCheckBox('Include recorded debug states in Preview here');self.debug_routes.setToolTip('Keeps debug/sandbox provenance visible; disabled by default.');form.addWidget(self.debug_routes)
        self.variables=QPlainTextEdit(); self.variables.setReadOnly(True);self.variables.setMaximumHeight(160);form.addWidget(self.variables)
        forced=QGroupBox('Forced branches — sandbox');self.forced_layout=QVBoxLayout(forced)
        self.forced_note=QLabel('Run to a branch to prepare a condition or force an outcome.');self.forced_note.setWordWrap(True);self.forced_layout.addWidget(self.forced_note);form.addWidget(forced)
        splitter.addWidget(left)
        right=QWidget(); rl=QVBoxLayout(right); rl.setContentsMargins(8,0,0,0)
        self.workspace_tabs=QTabWidget();rl.addWidget(self.workspace_tabs,4)
        self.workspace_tabs.tabBar().setAcceptDrops(True);self.workspace_tabs.tabBar().setChangeCurrentOnDrag(True)
        command_page=QWidget();cl=QVBoxLayout(command_page);cl.setContentsMargins(0,4,0,0);self.workspace_tabs.addTab(command_page,'Commands')
        searchrow=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText('Search commands, text or arguments…  Ctrl+F'); self.search.textChanged.connect(self.proxy.setFilterFixedString); searchrow.addWidget(self.search)
        self.go=QSpinBox(); self.go.setPrefix('# '); self.go.setMaximum(999999); searchrow.addWidget(self.go); go_button=QPushButton('Find'); go_button.clicked.connect(lambda:self.select_command(self.go.value())); searchrow.addWidget(go_button); cl.addLayout(searchrow)
        self.follow=QCheckBox('Follow execution'); self.follow.setChecked(True); searchrow.addWidget(self.follow)
        self.text_only=QCheckBox('Text only');self.text_only.toggled.connect(self.proxy.only_text);searchrow.addWidget(self.text_only)
        self.table=CommandTable();self.table.templateDropped.connect(self.drop_text_template); self.table.setModel(self.proxy); self.table.setSelectionBehavior(QTableView.SelectRows); self.table.setSelectionMode(QTableView.SingleSelection); self.table.setAlternatingRowColors(True); self.table.setSortingEnabled(False); self.table.verticalHeader().hide(); self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Fixed); self.table.setColumnWidth(0,80); self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Interactive); self.table.setColumnWidth(1,205); self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
        self.table.selectionModel().selectionChanged.connect(self.inspect); self.table.doubleClicked.connect(self.jump_selected); cl.addWidget(self.table,1)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu);self.table.customContextMenuRequested.connect(self.command_menu)
        self.script_flow=FlowPanel();self.workspace_tabs.addTab(self.script_flow,'Script flow');self.script_flow.picked.connect(self.graph_pick);self.script_flow.activated.connect(self.graph_activate);self.script_flow.rebuild.connect(self.rebuild_script_flow)
        self.file_flow=FlowPanel(files=True);self.workspace_tabs.addTab(self.file_flow,'Files');self.file_flow.activated.connect(self.graph_open_file);self.file_flow.rebuild.connect(self.rebuild_file_flow);self.workspace_tabs.currentChanged.connect(self.graph_tab_changed)
        self.opcode_reference=OpcodeReference();self.workspace_tabs.addTab(self.opcode_reference,'Opcode reference')
        self.opcode_reference.list.dragStarted.connect(self.pause)
        tabs=QTabWidget();self.inspector_tabs=tabs;text_page=QWidget();tl=QVBoxLayout(text_page);self.translation_text=QPlainTextEdit();self.translation_text.setReadOnly(True);tl.addWidget(self.translation_text);copy=QPushButton('Copy text (preserve markup)');copy.clicked.connect(self.copy_text);tl.addWidget(copy);tabs.addTab(text_page,'Translation text')
        self.opcode_help=browser();self.opcode_help.setMarkdown(help_markdown(None));tabs.addTab(self.opcode_help,'Opcode help')
        self.flow=QListWidget(); self.flow.itemDoubleClicked.connect(self.navigate_edge); tabs.addTab(self.flow,'Flow / references')
        advanced=QTabWidget();self.advanced_tabs=advanced
        self.inspector=QPlainTextEdit(); self.inspector.setReadOnly(True); advanced.addTab(self.inspector,'Arguments')
        self.logical_state=QPlainTextEdit();self.logical_state.setReadOnly(True);advanced.addTab(self.logical_state,'Scenario state')
        debug_scroll=QScrollArea();debug_scroll.setWidgetResizable(True);debug_scroll.setWidget(debug);advanced.addTab(debug_scroll,'Debug overrides')
        self.trace=QPlainTextEdit(); self.trace.setReadOnly(True); self.trace.document().setMaximumBlockCount(400); advanced.addTab(self.trace,'Execution trace')
        validation=QWidget();vl=QVBoxLayout(validation);self.validation_note=QLabel('Validate indexes all script references. Editing changes an editor project, never original archives.');self.validation_note.setWordWrap(True);vl.addWidget(self.validation_note)
        self.validation_list=QListWidget();self.validation_list.itemDoubleClicked.connect(self.navigate_diagnostic);vl.addWidget(self.validation_list)
        fix=QPushButton('Retarget selected broken reference…');fix.clicked.connect(self.fix_reference);vl.addWidget(fix);self.validation_tab=tabs.addTab(validation,'Validation')
        tabs.addTab(advanced,'Advanced')
        rl.addWidget(tabs,2); splitter.addWidget(right); splitter.setSizes([750,750])
        self.statusBar().showMessage('Edit text commands, save an editor project or export patched game data into a separate folder. Originals stay read-only.')
        self.timer=QTimer(self); self.timer.setInterval(33); self.timer.timeout.connect(self.tick)
        for key,action in [('Ctrl+F',self.focus_search),('F5',self.play),('F10',self.step_command),('Ctrl+O',self.browse_folder),('Ctrl+G',self.focus_number)]: QShortcut(QKeySequence(key),self.centralWidget(),activated=action)
        for key,action in [('Ctrl+S',self.save_project),('Ctrl+Z',self.undo_edit),('Ctrl+Shift+Z',self.redo_edit)]:QShortcut(QKeySequence(key),self.centralWidget(),activated=action)
        self.setStyleSheet(STYLE)
        if usrdir: QTimer.singleShot(0,self.load_game)

    def browse_folder(self):
        path=QFileDialog.getExistingDirectory(self,'Select original USRDIR',self.folder.text())
        if path: self.folder.setText(path); self.load_game()

    def load_game(self):
        if not self.confirm_project_discard():return
        if self.mcp_panel and not self.mcp_panel.shutdown():self.statusBar().showMessage('MCP is stopping; retry loading after it finishes.');return
        self.pause(); path=str(Path(self.folder.text()).expanduser().resolve()); self.preview.clear()
        if not Path(path,'resource.dat').is_file(): self.problem('Select the USRDIR folder containing resource.dat.'); return
        if self.image_panel:self.image_panel.invalidate()
        self.state_line.setText('Loading original scripts and text settings…'); self.centralWidget().setEnabled(False); self.view={}
        self.worker=Loader(self.session,path); self.worker.ready.connect(self.loaded); self.worker.failed.connect(self.load_failed); self.worker.start()

    def loaded(self,data):
        self.project=None;self.project_path=None;self.project_disk_hash=None;self.preview_revision=None;self.diagnostics=[]
        self.routes=RouteBook();self.script_cache={};self.file_signature=None;self.seek_origin=None;self.cancel_seek.hide()
        self.centralWidget().setEnabled(True); self.scripts=data['scripts']; self.settings.setValue('usrdir',self.folder.text())
        self.selector.blockSignals(True); self.selector.clear()
        for s in self.scripts: self.selector.addItem(f"{s['id']:03}  {s['name'].strip(chr(0))}  ·  {s['count']} commands",s['id'])
        self.selector.setCurrentIndex(max(0,min(self.start_script,len(self.scripts)-1))); self.selector.blockSignals(False); self.select_script(); self.statusBar().showMessage(f'{len(self.scripts)} scripts imported read-only. Double-click previews through recorded-route replay or fresh-entry execution.')

    def load_failed(self,message):
        self.centralWidget().setEnabled(True); self.script_id=-1; self.commands=[]; self.model.replace([]); self.problem(message)

    def select_script(self,*_):
        if self.selector.currentData() is None:return
        self.pause()
        try:
            if self.view:self.routes.capture(self.session)
            self.install_script(int(self.selector.currentData()));self.search.clear();self.restart();self.select_command(0)
        except Exception as e: self.problem(str(e))

    def install_script(self,script):
        self.script_id=script
        if self.project is not None and self.preview_revision!=self.project.revision:
            self.commands=self.project.display(script);self.analysis=Analysis([]);self.analysis.incoming={i:[] for i in range(len(self.commands))};self.analysis.outgoing={i:[] for i in range(len(self.commands))};self.analysis.entry_possible=set()
            self.model.replace(self.commands);self.script_flow.set_diagram(script_diagram(script,[],self.analysis));self.script_flow.note.setText('Invalid/unvalidated draft: flow and preview blocked. See Validation.');return
        if script not in self.script_cache:self.script_cache[script]=self.session.call('script',id=script)
        data=self.script_cache[script];self.commands=data['commands'];self.analysis=Analysis(self.commands,data.get('flow'));self.model.replace(self.commands)
        if self.project is not None:
            for row,command in zip(self.commands,self.project.scripts[script].commands):row['uid']=command.uid;row['original_index']=command.original_index
        self.rebuild_script_flow();self.file_signature=None
        if self.workspace_tabs.currentIndex()==2:self.rebuild_file_flow()

    def rebuild_script_flow(self):
        if not self.preview_available(False):return
        if self.commands:
            self.script_flow.set_diagram(script_diagram(self.script_id,self.commands,self.analysis,self.script_flow.detail.isChecked()))
            base='Potential flow · click to inspect · double-click to replay · Ctrl+wheel to zoom'
            self.script_flow.note.setText(base+(f' · {len(self.analysis.errors)} unresolved/analysis issue(s)' if self.analysis.errors else ''))
            self.script_flow.note.setToolTip('\n'.join(self.analysis.errors))

    def focus_search(self):
        panel=self.script_flow if self.workspace_tabs.currentIndex()==1 else self.file_flow if self.workspace_tabs.currentIndex()==2 else self.opcode_reference if self.workspace_tabs.currentIndex()==3 else self
        panel.search.setFocus()

    def focus_number(self):
        self.workspace_tabs.setCurrentIndex(0);self.go.setFocus()

    def rebuild_file_flow(self):
        signature=self.script_id,self.file_flow.detail.isChecked()
        if self.scripts and signature!=self.file_signature:
            self.file_flow.set_diagram(file_diagram(self.scripts,self.script_id,self.file_flow.detail.isChecked()));self.file_signature=signature
            self.file_flow.select(f'f{self.script_id}',True)

    def graph_tab_changed(self,index):
        if index==2:self.rebuild_file_flow()
        elif index==1:
            selected=self.selected()
            if selected is not None:self.script_flow.select(self.script_flow.diagram.command_cards.get(selected),True)

    def graph_pick(self,card):
        if card.commands:self.select_command(card.commands[0])

    def graph_activate(self,card):
        if card.commands:self.select_command(card.commands[0]);self.jump_selected()
        elif card.script is not None and card.script>=0:self.graph_open_file(card)

    def graph_open_file(self,card):
        if card.script is None or card.script<0:return
        index=self.selector.findData(card.script)
        if index>=0:self.selector.setCurrentIndex(index);self.workspace_tabs.setCurrentIndex(1)

    def preview_available(self,report=True):
        valid=self.project is None or self.preview_revision==self.project.revision
        if not valid and report:self.statusBar().showMessage('Preview blocked: current project revision has validation errors or has not been parsed. See Validation.')
        return valid

    def ensure_project(self):
        if self.project is not None:return True
        if not self.scripts:self.problem('Load original USRDIR first.');return False
        self.pause();self.statusBar().showMessage('Indexing all original script records and typed references for editing…');self.statusBar().repaint();QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.project=Project.from_import(self.session.call('project'),self.scripts,self.folder.text());self.preview_revision=self.project.revision
            return True
        except Exception as e:self.problem(str(e));return False
        finally:QApplication.restoreOverrideCursor()

    def show_diagnostics(self,issues):
        self.diagnostics=issues;self.validation_list.clear();locations=self.project.locations() if self.project else {}
        for diagnostic in issues:
            position=locations.get(diagnostic.command,(diagnostic.script,'?'))
            field=f' {diagnostic.path}' if diagnostic.path else ''
            item=QListWidgetItem(f"{diagnostic.severity.upper()}  file {diagnostic.script} / #{position[1]}{field}  {diagnostic.message}");item.setToolTip(item.text());item.setData(Qt.UserRole,diagnostic);self.validation_list.addItem(item)
        errors=sum(d.severity=='error' for d in issues);warnings=len(issues)-errors
        self.validation_note.setText(f'{errors} error(s), {warnings} warning(s). Preview blocked until errors are fixed.' if errors else f'Parsing/reference checks passed ({warnings} warnings). State-dependent reachability, resource/audio compatibility and missing preview hosts remain runtime concerns. Originals unchanged.')

    def validate_project(self,*_,apply=True,known_valid=False):
        if not self.ensure_project():return False
        self.pause();self.project.preview_issues=[];issues=[] if known_valid else self.project.validate();result=None
        needs_apply=apply and self.preview_revision!=self.project.revision
        if not issues:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                result=self.session.call('revision',**self.project.revision_request(self.script_id,needs_apply,True))
                self.project.preview_issues=result['issues'];issues=self.project.validate() if result['issues'] else []
            except Exception as e:issues=[Diagnostic(self.script_id,None,'Python revision rejected: '+str(e))]
            finally:QApplication.restoreOverrideCursor()
        warnings=[]
        if result:
            for item in result.get('warnings',[]):
                script=self.project.scripts[item['script']];i=item.get('command',-1)
                warnings.append(Diagnostic(script.id,script.commands[i].uid if 0<=i<len(script.commands) else None,item['message'],'warning'))
        self.show_diagnostics(issues+warnings)
        if issues:
            self.branch_box.setEnabled(False)
            self.preview_revision=None;self.view={};self.preview.clear();self.state_line.setText('INVALID PROJECT DRAFT — preview blocked. See Validation.');self.inspector_tabs.setCurrentIndex(self.validation_tab)
        elif needs_apply:
            self.branch_box.setEnabled(True)
            self.preview_revision=self.project.revision;self.routes=RouteBook();self.rewind_points=[0];self.seek_origin=None;self.cancel_seek.hide();self.target=None;self.script_cache={};self.state_origin='Edited project / fresh entry'
            self.install_script(self.script_id);self.update_view(result['view'])
        return not issues

    def edited(self,sid,uid=None,known_valid=False):
        self.pause();self.routes=RouteBook();self.rewind_points=[0];self.seek_origin=None;self.cancel_seek.hide();self.target=None;self.view={};self.preview.clear();self.preview_revision=None
        self.scripts=self.project.summaries();self.file_signature=None;self.script_cache={}
        self.selector.blockSignals(True)
        for i,s in enumerate(self.scripts):self.selector.setItemText(i,f"{s['id']:03}  {s['name']} · {s['count']} commands")
        self.selector.setCurrentIndex(self.selector.findData(sid))
        self.selector.blockSignals(False);self.script_id=sid
        self.validate_project(known_valid=known_valid);self.install_script(sid)
        rows=self.project.scripts[sid].commands
        index=next((i for i,c in enumerate(rows) if c.uid==uid),0)
        if rows:self.select_command(index)
        if self.workspace_tabs.currentIndex()==2:self.rebuild_file_flow()
        self.setWindowTitle('Saekano Script Studio — edited project'+(' *' if self.project.saved_revision!=self.project.revision else ''))
        if self.image_panel:self.image_panel.set_project(self.project)
        if self.ui_text_panel:self.ui_text_panel.set_project(self.project)

    def textures_edited(self,previous_revision):
        if self.preview_revision==previous_revision:self.preview_revision=self.project.revision
        if self.image_panel:self.image_panel.set_project(self.project)
        if self.ui_text_panel:self.ui_text_panel.set_project(self.project)
        self.setWindowTitle('Saekano Script Studio — texture project'+(' *' if self.project.saved_revision!=self.project.revision else ''))
        self.statusBar().showMessage('Project texture updated; save the project to keep it. Game files and scenario state unchanged.')

    def drop_text_template(self,row,opcode,after):
        if row>=0:
            source=self.proxy.mapToSource(self.proxy.index(row,0));self.select_command(source.row())
        else:self.table.clearSelection()
        self.edit_text('after' if after else 'before',opcode)

    def edit_text(self,mode,opcode=None):
        self.pause();index=self.selected()
        if not self.ensure_project():return
        sid=self.script_id;script=self.project.scripts[sid]
        if index is None:index=len(script.commands)
        if mode in {'edit','replace'} and (index>=len(script.commands) or script.commands[index].opcode not in TEXT_OPS):self.problem('Select a text-bearing opcode to edit/replace.');return
        project,revision=self.project,self.project.revision
        dialog=TextCommandDialog(self.project,sid,index,'add_'+mode if mode in {'before','after'} else mode,self)
        if opcode is not None:dialog.kinds.setCurrentIndex(dialog.kinds.findData(opcode))
        if not dialog.exec():return
        try:
            self.guard_edit_snapshot(project,revision)
            if mode in {'before','after'}:uid=self.project.add(sid,min(index+int(mode=='after'),len(script.commands)),dialog.opcode,dialog.args)
            else:uid=script.commands[index].uid;self.project.replace(sid,uid,dialog.opcode,dialog.args)
            self.edited(sid,uid)
        except Exception as e:self.problem(str(e))

    def delete_text(self,*_):
        self.pause();index=self.selected()
        if index is None or not self.ensure_project():return
        sid=self.script_id;script=self.project.scripts[sid];command=script.commands[index]
        project,revision=self.project,self.project.revision
        if command.opcode not in TEXT_OPS:self.problem('Only text-bearing opcodes can be deleted in this stage.');return
        inbound=[r for r in self.project.inbound(command.uid) if r[1]!=command.uid];target=None
        if inbound:
            choices=[('Keep unresolved — preview will be blocked',None)]+[(f'#{i} · {NAMES.get(c.opcode,hex(c.opcode))} · {c.uid}',c.uid) for i,c in enumerate(script.commands) if c.uid!=command.uid]
            message=f'{len(inbound)} incoming reference(s) target this block. Choose an explicit replacement or retain diagnostics.\n'+'\n'.join(f'{source}: {path}' for _,source,path in inbound[:8])
            label,ok=QInputDialog.getItem(self,'Delete referenced block',message,[s for s,_ in choices],0,False)
            if not ok:return
            target=dict(choices)[label]
        try:self.guard_edit_snapshot(project,revision);self.project.delete(sid,command.uid,target);self.edited(sid,script.commands[min(index+1,len(script.commands)-1)].uid if len(script.commands)>1 else None)
        except Exception as e:self.problem(str(e))

    def undo_edit(self,*_):
        if self.project and self.project.undo_stack:
            key,revision=self.project.scenario_key(),self.project.revision;self.project.undo()
            if key==self.project.scenario_key():self.textures_edited(revision)
            else:self.edited(self.script_id)

    def auto_fit_text(self):
        self.pause()
        if not self.ensure_project():return
        from .cleanupview import AutoFitDialog
        from .textcleanup import apply_cleanup
        project,revision=self.project,self.project.revision;dialog=AutoFitDialog(self)
        if not dialog.exec() or not dialog.plan:return
        try:
            self.guard_edit_snapshot(project,revision);result=apply_cleanup(project,dialog.plan,dialog.selected_commands())
            if result['changes'] or result.get('ui_fields') or result.get('font_changed'):
                first=result['changes'][0] if result['changes'] else dict(script_id=self.script_id,command_id=None)
                self.edited(first['script_id'],first['command_id'],known_valid=True)
                self.statusBar().showMessage(f"Auto-fit applied to {len(result['changes'])} command(s) and {len(result.get('ui_fields',[]))} UI fields; inserted {result['inserted_commands']}. "+('Font asset updated. ' if result.get('font_changed') else '')+'Undo restores the batch.')
        except (ValueError,RuntimeError) as error:self.problem(str(error))

    def redo_edit(self,*_):
        if self.project and self.project.redo_stack:
            key,revision=self.project.scenario_key(),self.project.revision;self.project.redo()
            if key==self.project.scenario_key():self.textures_edited(revision)
            else:self.edited(self.script_id)

    def navigate_diagnostic(self,item):
        diagnostic=item.data(Qt.UserRole)
        if not diagnostic or not self.project:return
        if diagnostic.script in self.project.scripts:
            self.selector.setCurrentIndex(self.selector.findData(diagnostic.script))
            index=next((i for i,c in enumerate(self.project.scripts[diagnostic.script].commands) if c.uid==diagnostic.command),0);self.select_command(index)

    def fix_reference(self):
        item=self.validation_list.currentItem();diagnostic=item.data(Qt.UserRole) if item else None
        if not diagnostic or not diagnostic.command:self.problem('Select a command-reference diagnostic, or edit the text/add a command/Undo as appropriate.');return
        script=self.project.scripts[diagnostic.script];path=diagnostic.path
        project,revision=self.project,self.project.revision
        if not path:
            command=next(c for c in script.commands if c.uid==diagnostic.command);paths=reference_paths(command.opcode,command.args)
            if not paths:self.problem('This command has no branch references. Edit its text/arguments or Undo.');return
            field,ok=QInputDialog.getItem(self,'Choose reference field','Select the boundary/destination to repair.',[str(p) for p in paths],0,False)
            if not ok:return
            path=paths[[str(p) for p in paths].index(field)]
        choices=[(f'#{i} · {c.uid}',c.uid) for i,c in enumerate(script.commands)]
        label,ok=QInputDialog.getItem(self,'Retarget reference',f'{diagnostic.command}: {path}',[s for s,_ in choices],0,False)
        if ok:
            try:self.guard_edit_snapshot(project,revision);self.project.retarget(script.id,diagnostic.command,path,dict(choices)[label]);self.edited(script.id,diagnostic.command)
            except Exception as e:self.problem(str(e))

    def save_project(self,*_):
        if not self.ensure_project():return
        project,revision=self.project,self.project.revision
        path,_=QFileDialog.getSaveFileName(self,'Save editable project',self.project_path or str(ROOT/'translation.saekano.json'),'Saekano editor project (*.saekano.json)')
        if not path:return
        try:
            self.guard_edit_snapshot(project,revision)
            if self.project_path and Path(path).resolve()==Path(self.project_path).resolve() and self.project_disk_hash and Path(path).exists() and self.file_hash(path)!=self.project_disk_hash:
                raise ValueError('Project changed on disk; reopen it or save to another filename. No file overwritten.')
            self.project.save(path);self.project_path=path;self.project_disk_hash=self.file_hash(path)
            if self.mcp_workspace:self.mcp_workspace.remember_gui_file()
            self.statusBar().showMessage('Editor project saved; original archives unchanged.');self.setWindowTitle('Saekano Script Studio — '+Path(path).name)
        except Exception as e:self.problem(str(e))

    def open_project(self,*_):
        self.pause()
        if not self.confirm_project_discard() or not self.ensure_project():return
        project,revision=self.project,self.project.revision
        path,_=QFileDialog.getOpenFileName(self,'Open editable project',str(ROOT),'Saekano editor project (*.saekano.json);;JSON (*.json)')
        if not path:return
        try:
            self.guard_edit_snapshot(project,revision);stamp=self.file_hash(path);loaded=Project.load(path,self.project)
            if stamp!=self.file_hash(path):raise ValueError('Project file changed while opening; retry.')
            self.project=loaded;self.project_path=path;self.project_disk_hash=stamp;self.edited(self.script_id)
        except Exception as e:self.problem(str(e))

    def export_game(self,*_):
        self.pause()
        if self.export_worker is not None or not self.ensure_project():return
        if not self.preview_available():return
        destination=QFileDialog.getExistingDirectory(self,'Export patched USRDIR — choose an empty folder',str(ROOT))
        if not destination:return
        self.start_export(destination)

    def start_export(self,destination,remote=False):
        if self.export_worker is not None:raise ValueError('An export is already running')
        self.pause();self.export_remote=remote
        self.export_worker=GameExporter(self.project,destination)
        self.export_progress=QProgressDialog('Validating and preparing game export…','Cancel',0,0,self)
        self.export_progress.setWindowTitle('Export game');self.export_progress.setWindowModality(Qt.WindowModal)
        self.export_progress.setMinimumDuration(0);self.export_progress.setAutoClose(False)
        self.export_progress.canceled.connect(self.export_worker.requestInterruption)
        self.export_worker.progress.connect(self.export_progress.setLabelText)
        self.export_worker.finished.connect(self.export_finished)
        self.centralWidget().setEnabled(False);self.export_progress.show();self.export_worker.start()

    def export_finished(self):
        worker=self.export_worker;self.export_worker=None
        self.export_progress.close();self.centralWidget().setEnabled(True)
        if self.export_remote:
            state='cancelled' if worker.cancelled else 'failed' if worker.error else 'complete'
            if self.mcp_workspace and self.mcp_workspace.export_status:
                self.mcp_workspace.export_status.update(state=state,error=worker.error)
                if worker.result:self.mcp_workspace.export_status['result']={key:worker.result[key] for key in ('path','changed_scripts','changed_textures','changed_ui_text','requires_fresh_progress','output_hashes')}
            self.statusBar().showMessage('Agent export '+state+(': '+worker.error if worker.error else ''))
            if self.mcp_panel:self.mcp_panel.log.appendPlainText('Export '+state)
            worker.deleteLater();return
        if worker.cancelled:self.statusBar().showMessage('Export cancelled. Original data and existing output unchanged.')
        elif worker.error:self.problem('Export failed: '+worker.error)
        else:
            result=worker.result;message=f"Separate patched USRDIR exported to:\n{result['path']}\n\n{len(result['changed_scripts'])} modified script(s), {result['changed_textures']} texture(s), {result['changed_ui_text']} UI text field(s). Original files remain unchanged."
            if result['requires_fresh_progress']:message+='\n\nUse fresh saves/history; existing progress was not migrated.'
            self.statusBar().showMessage('Game export complete: '+result['path']);QMessageBox.information(self,'Export complete',message)
        worker.deleteLater()

    def confirm_project_discard(self):
        if self.project is None or self.project.saved_revision==self.project.revision:return True
        result=QMessageBox.question(self,'Unsaved editor project','Save project changes before leaving?',QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Save)
        if result==QMessageBox.Cancel:return False
        if result==QMessageBox.Save:self.save_project();return self.project.saved_revision==self.project.revision
        return True

    def copy_text(self):
        i=self.selected()
        if i is not None:
            fields=text_fields(self.commands[i]);QApplication.clipboard().setText('\n\n'.join(value for _,value in fields))
            self.statusBar().showMessage(f'Copied {len(fields)} original text field(s), including markup.')

    def command_menu(self,position):
        index=self.table.indexAt(position)
        if index.isValid():self.table.selectRow(index.row())
        menu=QMenu(self);menu.addAction('Preview here (replay)',self.jump_selected);menu.addAction('Copy original text',self.copy_text)
        menu.addSeparator();menu.addAction('Add text before…',lambda:self.edit_text('before'));menu.addAction('Add text after…',lambda:self.edit_text('after'));menu.addAction('Edit text opcode…',lambda:self.edit_text('edit'));menu.addAction('Replace text opcode…',lambda:self.edit_text('replace'));menu.addAction('Delete text opcode…',self.delete_text)
        menu.addSeparator();menu.addAction('DEBUG: Sandbox jump — keeps unrelated state',self.sandbox_jump_selected)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def selected(self):
        rows=self.table.selectionModel().selectedRows()
        return self.proxy.mapToSource(rows[0]).row() if rows else None

    def select_command(self,index):
        if not 0<=index<len(self.commands):return
        source=self.model.index(index,0); mapped=self.proxy.mapFromSource(source)
        if not mapped.isValid():self.search.clear();self.text_only.setChecked(False);mapped=self.proxy.mapFromSource(source)
        self.table.selectRow(mapped.row()); self.table.scrollTo(mapped,QTableView.PositionAtCenter)

    def inspect(self,*_):
        self.interaction_revision=uuid.uuid4().hex
        i=self.selected()
        if i is None:return
        c=self.commands[i]; self.inspector.setPlainText(json.dumps(c,ensure_ascii=False,indent=2)); self.flow.clear()
        self.opcode_reference.show_command(c);self.opcode_help.setMarkdown(help_markdown(c))
        fields=text_fields(c);self.translation_text.setPlainText('\n\n'.join(f'{path}\n{value}' for path,value in fields) if fields else 'No modifiable scenario text in this command.\nPresentation and variable fields remain in Arguments.')
        if self.script_flow.diagram:self.script_flow.select(self.script_flow.diagram.command_cards.get(i))
        for e in self.analysis.outgoing[i]:
            destination='unresolved profile' if e.script==-3 else 'end' if e.script is not None and e.script<0 else f'script {e.script}:#{e.target}' if e.script is not None else f'#{e.target}'
            item=QListWidgetItem(f"→ {destination}   {e.label.replace(chr(0),'')}"); item.setData(Qt.UserRole,(e.script,e.target)); self.flow.addItem(item)
        for e in self.analysis.incoming[i]:
            item=QListWidgetItem(f'← #{e.source}   {e.label}');item.setData(Qt.UserRole,(None,e.source));self.flow.addItem(item)
        if not self.flow.count():self.flow.addItem('No statically indexed edges here.')
        self.statusBar().showMessage(f"Selected #{i} · {category(c['opcode'])} · {len(self.analysis.edges)} indexed edges · {len(self.analysis.errors)} analysis issues")

    def navigate_edge(self,item):
        value=item.data(Qt.UserRole)
        if value is None:return
        script,index=value
        if script is not None:
            if script<0:return
            self.selector.setCurrentIndex(script)
        self.select_command(index)

    def update_view(self,view):
        self.interaction_revision=uuid.uuid4().hex
        old=(self.view.get('script'),self.view.get('command'),self.view.get('boundary'))
        self.view=view; self.preview.view=view; self.preview.update()
        self.rewind_points=[n for n in self.rewind_points if n <= view['history']]
        if old[:2] != (view['script'],view['command']) and view['history'] not in self.rewind_points:
            self.rewind_points.append(view['history'])
        if old[:2] != (view['script'],view['command']): self.revealed_at=None
        if view.get('text_waiting') and view.get('text_ready') and getattr(self,'revealed_at',None) is None:
            self.revealed_at=view['time']
        if view['script']!=self.script_id:
            self.install_script(view['script']);self.selector.blockSignals(True);self.selector.setCurrentIndex(self.selector.findData(self.script_id));self.selector.blockSignals(False)
        self.model.mark(view['command']); boundary=BOUNDARIES[view['boundary']]
        self.script_flow.mark_command(view['command'])
        if self.playing and self.follow.isChecked() and old[:2]!=(view['script'],view['command']):self.select_command(view['command'])
        self.state_line.setText(f"{'DEBUG-ALTERED / ' if view['sandbox'] else ''}{self.state_origin}   ·   script {view['script']} / #{view['command']}   ·   {boundary}   ·   {view['time']/1000:.2f}s   ·   {view['mode']}")
        self.variables.setPlainText(f"Battle gauge: {view['battle']}   Approach gauge: {view['approach']}\n"+'   '.join(f'{k}[{i}]={v}' for k,i,v in view['variables'])+'\nUnlisted variables = 0. No persistent game state is imported.')
        self.logical_state.setPlainText(json.dumps(view.get('logic',{}),ensure_ascii=False,indent=2))
        self.policy.setText(view.get('preview_policy','Scenario simulator')+f" · {view.get('omitted_count',0)} presentation request(s) suppressed")
        self.policy.setToolTip('\n'.join(f"{x['script']}/#{x['command']} {x['opcode']:04X}: {x['reason']}" for x in view.get('omitted',[])))
        if old!=(view['script'],view['command'],view['boundary']):self.trace.appendPlainText(f"{view['time']:>7}ms  {view['script']}/{view['command']}  {NAMES.get(view['opcode'],hex(view['opcode']))}  {boundary}")
        self.refresh_branches()
        if view['error']:self.pause();self.statusBar().showMessage('Preview stopped: '+view['error']);self.branch_note.setText('Dependency / state gate: '+view['error']+'\nUse debug state or an explicitly labeled sandbox jump. This command was not silently completed.')

    def refresh_branches(self):
        visible=self.view.get('choices',[])
        signature=(self.view.get('script'),self.view.get('command'),self.view.get('opcode'),self.view.get('boundary'),
                   tuple((c['label'],str(c['action']),c['enabled'],c.get('selected')) for c in visible),self.view.get('text_note'))
        if signature==self.branch_signature:return
        self.branch_signature=signature
        for layout in (self.branch_layout,self.forced_layout):
            while layout.count()>1:
                item=layout.takeAt(1)
                if item.widget():item.widget().deleteLater()
        c={'opcode':self.view.get('opcode',-1),'args':self.view.get('args',{})}
        options=branch_options(c)
        self.forced_note.setText('Force an authored branch (sandbox). State repairs appear in the trace.' if options else 'No forced choice at the current execution position.')
        self.branch_box.setVisible(bool(visible or self.view.get('text_note')))
        if visible:
            self.branch_note.setText(self.view.get('text_note') or 'Choose normally here or click the text in the preview. Authored ordinals are preserved.')
        elif self.view.get('text_kind'):
            self.branch_note.setText(self.view.get('text_note') or 'Review this text, then Step or click the preview to continue.')
        for choice in visible:
            normal=QPushButton(choice['label'][:130]);normal.setToolTip(choice.get('reason') or choice['label'])
            normal.setEnabled(choice['enabled']);normal.clicked.connect(lambda checked=False,a=choice['action']:self.select_text_option(a));self.branch_layout.addWidget(normal)
        for label,parent,child in options:
            b=QPushButton('Force: '+label[:130]);b.setToolTip(label);b.clicked.connect(lambda checked=False,p=parent,ch=child:self.choose(p,ch));self.forced_layout.addWidget(b)
        if c['opcode']==1:
            self.forced_note.setText('Prepare variables to satisfy the original expression, then Step. No script bytes are changed.')
            for truth in (True,False):
                b=QPushButton(f'Make condition {str(truth).lower()}');b.clicked.connect(lambda checked=False,t=truth:self.condition(t));self.forced_layout.addWidget(b)

    def problem(self,message):self.pause();self.state_line.setText('Error: '+message);QMessageBox.warning(self,'Script Studio',message)
    def execute(self,op,**args):
        if not self.preview_available():return None
        try:self.update_view(self.session.call(op,**args));return self.view
        except Exception as e:self.problem(str(e));return None
    def restart(self):
        if self.script_id<0:return
        if self.view:self.routes.capture(self.session)
        self.pause();self.target=None;self.seek_origin=None;self.cancel_seek.hide();self.rewind_points=[0];self.trace.clear();self.state_origin=f'Fresh entry file {self.script_id} (no prior-file state)';self.execute('reset',script=self.script_id)
    def rewind(self):
        if self.view:
            self.routes.capture(self.session);self.pause();self.target=None
            previous=[n for n in self.rewind_points if n < self.view['history']]
            self.execute('rewind',count=previous[-1] if previous else 0)
    def jump_selected(self,*_):
        """Default navigation never performs a raw cursor/state splice."""
        if not self.preview_available():return
        index=self.selected()
        if index is None or not self.view:return
        self.pause()
        try:
            current=self.routes.capture(self.session);phase=self.seek_phase.currentText().lower()
            matches=self.routes.find(self.script_id,index,phase,self.debug_routes.isChecked())
            if matches:
                if len(matches)>1:
                    labels=[f"Route {t.number} · entry file {t.entry} · {v['phase']} · {v['time']/1000:.2f}s · action {v['count']}"+(' · DEBUG state' if v['sandbox'] else '') for t,v in matches]
                    label,ok=QInputDialog.getItem(self,'Incoming route / state','Select an observed visit. Different routes may carry different state.',labels,0,False)
                    if not ok:return
                    tape,visit=matches[labels.index(label)]
                else:tape,visit=matches[0]
                view=self.routes.restore(self.session,tape,visit['count'],dict(script=visit['script'],command=visit['command'],phase=phase))
                self.target=None;self.seek_origin=None;self.cancel_seek.hide();self.state_origin=f'Replayed route {tape.number}, entry file {tape.entry}'
                self.update_view(view);self.trace.appendPlainText(f'REPLAY RESTORE route {tape.number} · {phase} #{index} · action {visit["count"]}');return
            # No observed state: execute from a defined fresh file entry. Never
            # guess variables from static edges or keep an unrelated scene.
            origin_count=self.view['history'];expected={k:self.view[k] for k in ('script','command','boundary')}
            if self.view['error']:
                safe=[v for v in current.visits if v['count']<=origin_count]
                if safe:origin_count=safe[-1]['count'];expected={k:safe[-1][k] for k in ('script','command','phase')}
            origin=current,origin_count,expected
            target_script=self.script_id;self.restart();self.seek_origin=origin;self.cancel_seek.show()
            self.target=(target_script,index);self.target_phase=phase;self.seek_steps=0;self.state_origin=f'Replaying fresh file {target_script} (no prior-file state)'
            self.statusBar().showMessage('No recorded visit. Executing from fresh entry; choices and missing services stop the seek. Cancel restores the prior valid position.')
            self.play(force=True)
        except Exception as e:self.problem(str(e))

    def sandbox_jump_selected(self,*_):
        if not self.preview_available():return
        index=self.selected()
        if index is not None:
            self.routes.capture(self.session);self.pause();self.target=None;self.seek_origin=None;self.cancel_seek.hide();self.state_origin='UNSAFE sandbox splice: skipped setup';self.execute('jump',target=index)

    def cancel_preview_seek(self):
        if not self.seek_origin:return
        self.pause();tape,count,expected=self.seek_origin
        try:
            view=self.routes.restore(self.session,tape,count,expected);self.target=None;self.seek_origin=None;self.cancel_seek.hide();self.state_origin=f'Restored prior route {tape.number}';self.update_view(view)
        except Exception as e:self.problem(str(e))

    def target_reached(self):
        if self.view.get('error') or self.target!=(self.view.get('script'),self.view.get('command')):return False
        return self.view['boundary']==4 if self.target_phase=='after' else self.view['boundary'] in {0,5,6}

    def finish_target(self):
        self.pause();self.routes.capture(self.session);self.target=None;self.seek_origin=None;self.cancel_seek.hide()
        self.state_origin=self.state_origin.replace('Replaying fresh file','Reached from fresh file')
        if self.view:self.update_view(self.view)
        self.statusBar().showMessage('Recovered '+self.target_phase+' command state by executing/replaying a defined route.')
    def run_to_selected(self):
        index=self.selected()
        if index is not None:self.target=(self.script_id,index);self.target_phase=self.seek_phase.currentText().lower();self.seek_steps=0;self.play(force=True)
    def play(self,checked=False,force=False):
        if not self.preview_available():return
        if self.playing and not force:self.pause();return
        if not self.view:return
        self.interaction_revision=uuid.uuid4().hex;self.playing=True;self.play_button.setText('Ⅱ Pause');self.timer.start()
    def pause(self):
        if self.playing:self.interaction_revision=uuid.uuid4().hex
        self.playing=False;self.play_button.setText('▶ Play');self.timer.stop()
    def step_command(self):
        if not self.view:return
        self.pause();start=(self.view['script'],self.view['command'])
        try:
            for _ in range(500):
                view=self.session.call('step',dt=16,advance=True)
                if view['error'] or view['choices'] or (view.get('text_waiting') and view.get('text_ready')) or view['boundary'] in {4,7} or (view['script'],view['command'])!=start:break
            self.update_view(view)
        except Exception as e:self.problem(str(e))
    def tick(self):
        if not self.playing:return
        if not self.preview_available(False) or not self.view:return
        try:
            for i in range(6):
                if self.target_reached():self.finish_target();return
                if self.target is not None and self.seek_steps>=20000:
                    self.pause();self.statusBar().showMessage('Seek stopped at its work budget; target not reached. Inspect the route or Cancel seek.');return
                if self.view.get('choices') and self.view['boundary']!=4:self.pause();return
                revealed=getattr(self,'revealed_at',None)
                advance=True if self.seek_origin is not None else self.auto.isChecked() and revealed is not None and self.view['time']-revealed>=900
                elapsed=(250 if self.seek_origin is not None else 33*[1,4,20][self.speed.currentIndex()]) if i==0 else 0
                view=self.session.call('step',dt=elapsed,advance=advance);self.seek_steps+=1
                self.update_view(view)
                if view['error'] or view['boundary']==7 or view.get('choices') or (view['opcode']==0x3f6 and view.get('text_waiting')):self.pause();return
        except Exception as e:self.problem(str(e))
    def choose(self,parent,child):
        self.pause();view=self.execute('choose',choice=parent,child=child)
        if view:self.trace.appendPlainText('FORCE BRANCH — presentation bypassed; state repairs: '+json.dumps(view['repairs'],ensure_ascii=False))
    def choose_normally(self,parent):
        self.select_text_option(dict(choice=parent))

    def select_text_option(self,action):
        if not self.preview_available():return
        self.pause()
        try:
            if self.view['boundary'] in {0,5,6}:self.update_view(self.session.call('step',dt=16))
            self.update_view(self.session.call('step',**action,dt=16))
            if self.target is not None and not self.view['error'] and self.view['boundary'] in {4,5,6}:self.play(force=True)
        except Exception as e:self.problem(str(e))
    def condition(self,truth):
        self.pause()
        try:
            view=prepare_condition(self.session,truth);self.update_view(view);self.trace.appendPlainText('CONDITION STATE: '+json.dumps(view['repairs'],ensure_ascii=False))
        except Exception as e:self.problem(str(e))
    def set_state(self):self.pause();self.execute('set',kind=self.bank.currentText(),index=self.variable.value(),value=self.value.value())
    def closeEvent(self,event):
        self.pause()
        if self.export_worker is not None:
            self.export_worker.requestInterruption();self.statusBar().showMessage('Cancelling export; close again after staging cleanup completes.');event.ignore();return
        if not self.confirm_project_discard():event.ignore();return
        if self.mcp_panel and not self.mcp_panel.shutdown():event.ignore();return
        if self.image_panel and not self.image_panel.shutdown():
            self.statusBar().showMessage('Cancelling image operation; close again after it finishes.');event.ignore();return
        if hasattr(self,'worker') and self.worker.isRunning():self.worker.wait()
        super().closeEvent(event)

    @staticmethod
    def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def guard_edit_snapshot(self,project,revision):
        if self.export_worker is not None or not self.centralWidget().isEnabled():
            raise ValueError('GUI is loading/exporting; retry editing after it finishes')
        if self.project is not project or self.project.revision!=revision:
            raise ValueError('GUI edit is stale because the project changed. Nothing applied; reopen the editor for the current command.')

    def show_mcp_panel(self):
        if self.mcp_panel is None:
            try:
                from .live_mcp import McpPanel
                self.mcp_panel=McpPanel(self)
            except ImportError as error:self.problem('Install the optional MCP dependencies with setup-mcp.ps1: '+str(error));return
        self.mcp_panel.show();self.mcp_panel.raise_();self.mcp_panel.activateWindow()

    def show_ui_text(self):
        if not self.ensure_project():return
        self.pause()
        try:
            if self.ui_text_panel is None:
                from .uitextview import UiTextBrowser
                self.ui_text_panel=UiTextBrowser(self)
                self.ui_text_panel.textChanged.connect(lambda previous:self.edited(self.script_id))
            self.ui_text_panel.set_project(self.project,force=True);self.ui_text_panel.show();self.ui_text_panel.raise_()
        except (ValueError,OSError) as error:self.problem(str(error))

    def show_images(self):
        if not self.session.original:self.problem('Load a game folder first.');return
        self.pause()
        if self.image_panel is None:
            from .imageview import ImageBrowser
            self.image_panel=ImageBrowser(self)
            self.image_panel.commandPicked.connect(self.inspect_image_use)
            self.image_panel.texturesChanged.connect(self.textures_edited)
        selected=self.table.currentIndex()
        command=self.commands[self.proxy.mapToSource(selected).row()] if selected.isValid() and self.commands else None
        sample=command if command and command['opcode']==0x64 else next((c for c in self.commands if c['opcode']==0x64),None)
        examples={}
        choice=command if command and command['opcode']==0x65 else next((c for c in self.commands if c['opcode']==0x65),None)
        if choice:examples['choices']='\n'.join(row['label'] for row in choice['args']['choices'])
        approach=command if command and command['opcode']==0x3f6 else next((c for c in self.commands if c['opcode']==0x3f6),None)
        if approach:examples['profile:topics']='\n'.join(' | '.join([row['label']]+[child['label'] for child in row['children']]) for row in approach['args']['parents'])
        result=command if command and command['opcode']==0x3f8 else next((c for c in self.commands if c['opcode']==0x3f8),None)
        if result:examples['profile:result_text']=result['args']['outcomes'][0]['text']
        versus=command if command and command['opcode']==0x3f9 else next((c for c in self.commands if c['opcode']==0x3f9),None)
        if versus:
            for side,value in enumerate(versus['args']['texts']):examples['battle:caption_'+str(side)]=value
        battle_choice=command if command and command['opcode']==0x3f2 else next((c for c in self.commands if c['opcode']==0x3f2),None)
        if battle_choice:
            from .progression import track_number
            examples['battle:choices']='\n'.join(row['label'] for row in battle_choice['args']['choices'][1:])
            for i,row in enumerate(battle_choice['args']['choices'][1:]):
                kind=track_number(row['extras'][0]) if row['extras'] else 0
                examples['battle:type_'+str(i)]=kind if 0<=kind<=2 else 3
        entry=next((c for c in self.commands if c['opcode']==0x3ef),None)
        if entry:
            for side in range(2):examples['battle:side_'+str(side)]=entry['args']['side'+str(side)+'_group']
        chapter=command if command and command['opcode']==0x3ec else next((c for c in self.commands if c['opcode']==0x3ec),None)
        if chapter:examples['calendar']='\n'.join(chapter['args']['texts']);examples['system']=chapter['args']['texts'][-1]
        retained=[];budget=4096
        for c in self.commands:
            if c['opcode']!=0x64:continue
            value=c['args']['text']
            if len(value)+1>budget or len(retained)>=12:break
            retained.append(value);budget-=len(value)+1
        examples['backlog']='\n'.join(retained)
        self.image_panel.set_source(self.session.root,self.session.descriptions,self.session.text,
                                    sample['args']['text'] if sample else '',sample['args']['speaker'] if sample else -1,examples)
        self.image_panel.set_project(self.project)
        self.image_panel.show();self.image_panel.raise_();self.image_panel.activateWindow()

    def inspect_image_use(self,script,original_index):
        self.pause();index=original_index
        if self.project is not None:
            index=next((i for i,c in enumerate(self.project.scripts[script].commands)
                        if c.original_index==original_index),None)
            if index is None:self.problem('That original command was removed from the current project.');return
        self.selector.setCurrentIndex(self.selector.findData(script));self.select_command(index)
        self.workspace_tabs.setCurrentIndex(0)


STYLE='''
QMainWindow,QWidget {background:#19212c;color:#e4eaf0;font:10pt "Segoe UI";}
QLabel#state {background:#22323c;padding:10px;border-radius:5px;color:#b6d8db;}
QPushButton {background:#2a3747;border:1px solid #3a4a60;border-radius:5px;padding:7px 11px;}
QPushButton:hover {background:#364a5d;} QPushButton#primary {background:#327d79;}
QLineEdit,QSpinBox,QComboBox {background:#101923;border:1px solid #38485b;border-radius:4px;padding:6px;}
QTableView {background:#131d28;alternate-background-color:#172330;gridline-color:#243141;selection-background-color:#35566b;border:1px solid #303f52;}
QHeaderView::section {background:#263445;color:#c5d5e4;padding:7px;border:0;}
QPlainTextEdit,QListWidget {background:#101923;border:1px solid #303f52;font:10pt "Cascadia Mono";}
QGroupBox {border:1px solid #354457;border-radius:5px;margin-top:12px;padding-top:13px;}
QGroupBox::title {subcontrol-origin:margin;left:10px;padding:0 5px;color:#91b5c5;}
QTabBar::tab {background:#263445;padding:8px 14px;} QTabBar::tab:selected{background:#365165;}
QSplitter::handle {background:#354557;width:4px;} QToolTip {background:#203243;color:#edf4f5;}
'''
