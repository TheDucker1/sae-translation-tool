"""Nonmodal source browser and project PNG replacements; originals stay read-only."""
from collections import OrderedDict
import json
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QThread, Signal, QRectF
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QTableView, QHeaderView, QSplitter,
    QTabWidget, QPlainTextEdit, QListWidget, QListWidgetItem, QGraphicsView,
    QGraphicsScene, QFileDialog, QMessageBox, QCheckBox)
from .imageassets import build_catalog, extract_images
from .imagecodec import ImageCancelled
from .compositionrender import AssetResolver


class ImageJob(QThread):
    ready = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent); self.operation = operation

    def run(self):
        try:
            result = self.operation(self.progress.emit, self.isInterruptionRequested)
            if not self.isInterruptionRequested(): self.ready.emit(result)
        except ImageCancelled:
            pass
        except Exception as error:
            self.failed.emit(str(error))


class ImagesModel(QAbstractTableModel):
    HEADERS = ('Image', 'Category', 'Dimensions', 'Original format / order', 'Uses', 'Source / member indices', 'Status')

    def __init__(self, parent=None):
        super().__init__(parent); self.assets = []; self.replacements = {}

    def replace(self, assets):
        self.beginResetModel(); self.assets = assets; self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.assets)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        a = self.assets[index.row()]
        if role == Qt.DisplayRole:
            return (a.name.strip(), a.category, f'{a.width} × {a.height}' if a.width else '—',
                    f'{a.format} {a.order}', len(a.references), a.location, 'Project PNG' if a.id in self.replacements else a.status)[index.column()]
        if role == Qt.ToolTipRole:
            return a.error or f'{a.id}\n{a.consumer}'
        if role == Qt.UserRole:
            return a.id


class ImageFilter(QSortFilterProxyModel):
    def __init__(self, parent):
        super().__init__(parent); self.query = ''; self.category = ''; self.only_errors = False

    def filterAcceptsRow(self, row, parent):
        a = self.sourceModel().assets[row]
        if self.category and a.category != self.category: return False
        if self.only_errors and a.status == 'Ready': return False
        if not self.query: return True
        words = f'{a.name} {a.id} {a.category} {a.consumer} {a.format} {a.error} ' + ' '.join(
            f"script:{r['script']:03} command:{r['command']}" for r in a.references)
        return self.query.casefold() in words.casefold()


class ImageCanvas(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self)); self.image_item = None; self.region_item = None; self.fitting = True
        tile = QPixmap(32, 32); tile.fill(QColor('#afb2b8'))
        p = QPainter(tile); p.fillRect(0, 0, 16, 16, QColor('#d5d7db')); p.fillRect(16, 16, 16, 16, QColor('#d5d7db')); p.end()
        self.setBackgroundBrush(QBrush(tile)); self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)

    def clear(self):
        self.scene().clear(); self.image_item = None; self.region_item = None

    def display(self, image):
        self.clear(); self.image_item = self.scene().addPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(self.image_item.boundingRect()); self.fit()

    def fit(self):
        self.fitting = True
        if self.image_item: self.fitInView(self.image_item, Qt.KeepAspectRatio)

    def actual(self):
        self.fitting = False; self.resetTransform()

    def zoom(self, scale):
        self.fitting = False
        current = self.transform().m11()
        if .015 <= current * scale <= 64: self.scale(scale, scale)

    def wheelEvent(self, event):
        self.zoom(1.2 if event.angleDelta().y() > 0 else 1 / 1.2); event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fitting: self.fit()

    def region(self, rect):
        if self.region_item:
            self.scene().removeItem(self.region_item); self.region_item = None
        if rect and self.image_item:
            x, y, w, h = rect
            pen = QPen(QColor('#ff267f'), 2); pen.setCosmetic(True)
            self.region_item = self.scene().addRect(QRectF(x, y, w, h).normalized(), pen)


class ImageBrowser(QDialog):
    commandPicked = Signal(int, int)
    texturesChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle('Image assets — project PNG replacements'); self.resize(1430, 900)
        self.setModal(False); self.catalog = None; self.source = None; self.descriptions = {}
        self.generation = 0; self.job = None; self.job_kind = None; self.pending = None; self.deferred_decode = None
        self.selected_id = None; self.cache = OrderedDict(); self.cache_bytes = 0
        self.composition_panel = None; self.font = None; self.sample_text = ''; self.sample_speaker = -1; self.samples = {}
        self.project = None; self.replacements = {}; self.project_key = None
        outer = QVBoxLayout(self)
        top = QHBoxLayout(); self.search = QLineEdit(); self.search.setPlaceholderText('Search image, location, use or script:000…')
        self.search.textChanged.connect(self.refilter); top.addWidget(self.search, 3)
        self.categories = QComboBox(); self.categories.addItem('All categories', '')
        self.categories.currentIndexChanged.connect(self.refilter); top.addWidget(self.categories, 2)
        self.errors = QCheckBox('Unsupported / invalid'); self.errors.toggled.connect(self.refilter); top.addWidget(self.errors)
        source_order = QPushButton('Source order'); source_order.clicked.connect(lambda: self.table.sortByColumn(-1, Qt.AscendingOrder)); top.addWidget(source_order)
        self.reindex = QPushButton('Re-index'); self.reindex.clicked.connect(self.rebuild); top.addWidget(self.reindex)
        self.compose_button = QPushButton('UI compositions…'); self.compose_button.clicked.connect(self.show_compositions); top.addWidget(self.compose_button)
        self.cancel = QPushButton('Cancel'); self.cancel.clicked.connect(self.cancel_work); top.addWidget(self.cancel)
        outer.addLayout(top)
        self.note = QLabel('Load a game folder first.'); self.note.setWordWrap(True); outer.addWidget(self.note)
        split = QSplitter(Qt.Vertical); outer.addWidget(split, 1)
        self.model = ImagesModel(self); self.proxy = ImageFilter(self); self.proxy.setSourceModel(self.model)
        self.table = QTableView(); self.table.setModel(self.proxy); self.table.setSortingEnabled(True)
        self.table.sortByColumn(-1, Qt.AscendingOrder)
        self.table.setSelectionBehavior(QTableView.SelectRows); self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.setAlternatingRowColors(True); self.table.setWordWrap(False); self.table.verticalHeader().hide()
        header = self.table.horizontalHeader(); header.setSectionResizeMode(QHeaderView.Interactive)
        for col, width in enumerate((240, 165, 105, 210, 55, 280, 150)): self.table.setColumnWidth(col, width)
        header.setStretchLastSection(True); split.addWidget(self.table)
        self.table.selectionModel().currentChanged.connect(self.select_image)
        bottom = QSplitter(); split.addWidget(bottom); split.setSizes([330, 500])
        preview = QWidget(); pl = QVBoxLayout(preview); pl.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout(); self.image_note = QLabel('Select an image.'); bar.addWidget(self.image_note, 1)
        self.canvas = ImageCanvas()
        self.original = QCheckBox('Original pixels'); self.original.toggled.connect(self.refresh_pixels); bar.addWidget(self.original)
        for label, action in [('Fit', self.canvas.fit), ('1:1', self.canvas.actual), ('−', lambda: self.canvas.zoom(1 / 1.25)), ('+', lambda: self.canvas.zoom(1.25))]:
            button = QPushButton(label); button.clicked.connect(action); bar.addWidget(button)
        pl.addLayout(bar); pl.addWidget(self.canvas, 1); bottom.addWidget(preview)
        tabs = QTabWidget(); bottom.addWidget(tabs); bottom.setSizes([830, 560])
        self.details = QPlainTextEdit(); self.details.setReadOnly(True); tabs.addTab(self.details, 'Location / usage')
        self.regions = QListWidget(); self.regions.currentItemChanged.connect(self.show_region); tabs.addTab(self.regions, 'Atlas regions')
        self.uses = QListWidget(); self.uses.itemDoubleClicked.connect(self.open_use); tabs.addTab(self.uses, 'Script uses')
        self.coverage = QPlainTextEdit(); self.coverage.setReadOnly(True); tabs.addTab(self.coverage, 'Inventory / issues')
        foot = QHBoxLayout(); self.mode = QComboBox(); self.mode.addItem('Original bytes + PNG', 'both'); self.mode.addItem('Original bytes only', 'raw'); self.mode.addItem('PNG only', 'png'); foot.addWidget(self.mode)
        self.extract_selected = QPushButton('Extract selected…'); self.extract_selected.clicked.connect(lambda: self.extract(False)); foot.addWidget(self.extract_selected)
        self.extract_filtered = QPushButton('Extract filtered list…'); self.extract_filtered.clicked.connect(lambda: self.extract(True)); foot.addWidget(self.extract_filtered)
        self.import_png = QPushButton('Import PNG…'); self.import_png.clicked.connect(self.import_replacement); foot.addWidget(self.import_png)
        self.revert_png = QPushButton('Revert PNG'); self.revert_png.clicked.connect(self.revert_replacement); foot.addWidget(self.revert_png)
        self.save_png = QPushButton('Save viewed PNG…'); self.save_png.clicked.connect(self.save_viewed_png); foot.addWidget(self.save_png)
        foot.addStretch(); foot.addWidget(QLabel('Project only · extraction uses originals · no game reinjection'))
        close = QPushButton('Close'); close.clicked.connect(self.close); foot.addWidget(close); outer.addLayout(foot)
        self.update_buttons()

    def set_source(self, root, descriptions, font=None, sample_text='', sample_speaker=-1, samples=None):
        self.font = font; self.sample_text = sample_text; self.sample_speaker = sample_speaker
        self.samples = dict(samples or {})
        root = str(root)
        if self.source == root and self.catalog is not None:
            try: self.catalog.verify(); return
            except (ValueError, OSError): pass
        self.source = root; self.descriptions = descriptions; self.rebuild()

    def set_project(self, project):
        self.project = project; self.replacements = dict(project.texture_assets) if project else {}
        key = (tuple((name, value['png_sha256']) for name, value in sorted(self.replacements.items())), id(project.font_asset) if project else None,id(project.ui_text_assets) if project else None)
        self.model.replacements = self.replacements
        if key == self.project_key:self.update_buttons();return
        self.project_key = key
        if project and self.font:
            from .fontpatch import effective_font
            self.font = effective_font(project, self.font)
        self.refresh_pixels()
        if self.composition_panel:
            from .uitext import get_catalog
            ui=project.ui_text_assets if project else {}
            self.composition_panel.set_replacements(self.replacements,self.font,ui,get_catalog(project) if ui else None)

    def refresh_pixels(self, *_):
        self.cache.clear(); self.cache_bytes = 0
        if self.job_kind not in ('index', 'extract'):
            self.generation += 1; self.pending = None; self.deferred_decode = None
            if self.job:self.job.requestInterruption()
        self.model.dataChanged.emit(self.model.index(0, 0), self.model.index(max(0, self.model.rowCount()-1), 6))
        self.selected_id = None
        if self.catalog:self.select_image()
        self.update_buttons()

    def invalidate(self):
        if self.composition_panel:self.composition_panel.invalidate()
        self.generation += 1; self.pending = None; self.deferred_decode = None; self.catalog = None; self.source = None
        self.cache.clear(); self.cache_bytes = 0; self.selected_id = None
        if self.job: self.job.requestInterruption()
        self.model.replace([]); self.canvas.clear(); self.details.clear(); self.regions.clear(); self.uses.clear()
        self.coverage.clear(); self.note.setText('Source changed. Reopen Images after Load game completes.'); self.update_buttons()

    def rebuild(self):
        if not self.source: return
        if self.composition_panel:self.composition_panel.invalidate()
        self.generation += 1; self.deferred_decode = None; self.cache.clear(); self.cache_bytes = 0; self.selected_id = None
        self.catalog = None; self.model.replace([]); self.canvas.clear(); self.details.clear(); self.regions.clear(); self.uses.clear()
        self.note.setText('Indexing all supported image containers…')
        root, descriptions = self.source, self.descriptions
        self.enqueue('index', None, lambda progress, cancel: build_catalog(root, descriptions, progress, cancel), interrupt=True)

    def enqueue(self, kind, key, operation, interrupt=False):
        request = (kind, key, operation, self.generation)
        if self.job:
            if kind == 'decode' and self.pending and self.pending[0] in ('index', 'extract'):
                self.deferred_decode = request; return
            self.pending = request
            if interrupt or self.job_kind == 'decode': self.job.requestInterruption()
            self.update_buttons()
            return
        self.start_job(request)

    def start_job(self, request):
        kind, key, operation, generation = request
        if generation != self.generation: return
        self.job_kind = kind; self.job = ImageJob(operation, self)
        self.job.ready.connect(lambda data: self.result(kind, key, generation, data))
        self.job.failed.connect(lambda message: self.failure(kind, key, generation, message))
        self.job.progress.connect(lambda message: self.note.setText(message) if generation == self.generation else None)
        self.job.finished.connect(self.job_finished); self.job.start(); self.update_buttons()

    def result(self, kind, key, generation, result):
        if generation != self.generation: return
        if kind == 'index':
            self.catalog = result; self.model.replace(result.assets)
            self.categories.blockSignals(True); self.categories.clear(); self.categories.addItem('All categories', '')
            for category in sorted({a.category for a in result.assets}): self.categories.addItem(category, category)
            self.categories.blockSignals(False); self.refilter()
            self.coverage.setPlainText(json.dumps(result.summary(), ensure_ascii=False, indent=2))
            self.note.setText(f'{len(result.assets):,} images indexed · {len(result.issues)} traversal/metadata issues · select a row to decode. Source files remain read-only.')
            if self.proxy.rowCount(): self.table.selectRow(0)
        elif kind == 'decode':
            size = result.sizeInBytes()
            while self.cache and (self.cache_bytes + size > 64 * 1024 * 1024 or len(self.cache) >= 32):
                _, old = self.cache.popitem(last=False); self.cache_bytes -= old.sizeInBytes()
            if size <= 64 * 1024 * 1024:
                self.cache[key] = result; self.cache_bytes += size
            if key == self.selected_id:
                self.canvas.display(result); self.image_note.setText(f'{result.width()} × {result.height()} · wheel to zoom, drag to pan')
                self.show_region(self.regions.currentItem())
        else:
            self.note.setText(f"Extracted {result['count']} images to {result['path']} (manifest.json included).")

    def failure(self, kind, key, generation, message):
        if generation != self.generation: return
        if kind == 'decode':
            if key == self.selected_id: self.canvas.clear(); self.image_note.setText('Preview unavailable: ' + message)
        else:
            self.note.setText(message)
            QMessageBox.warning(self, 'Image operation', message)

    def job_finished(self):
        old = self.job; self.job = None; self.job_kind = None
        if old: old.deleteLater()
        pending, self.pending = self.pending, None
        if pending is None:
            pending, self.deferred_decode = self.deferred_decode, None
        if pending: self.start_job(pending)
        elif old and old.isInterruptionRequested() and self.source:
            self.note.setText('Image operation cancelled. Re-index or select an image to continue. Original data unchanged.')
            self.selected_id = None
        self.update_buttons()

    def cancel_work(self):
        self.pending = None; self.deferred_decode = None
        if self.job: self.job.requestInterruption()
        self.note.setText('Cancelling image operation…')

    def update_buttons(self):
        self.cancel.setEnabled(self.job is not None)
        extracting = self.job_kind == 'extract' or self.pending is not None and self.pending[0] == 'extract'
        self.reindex.setEnabled(bool(self.source) and not extracting)
        enabled = self.catalog is not None and self.job_kind != 'index' and not extracting
        self.extract_selected.setEnabled(enabled); self.extract_filtered.setEnabled(enabled)
        self.compose_button.setEnabled(self.catalog is not None)
        ready = enabled and self.selected_id in self.catalog.by_id if self.catalog else False
        self.import_png.setEnabled(ready and self.catalog.by_id[self.selected_id].status == 'Ready')
        self.revert_png.setEnabled(ready and self.selected_id in self.replacements)
        self.save_png.setEnabled(ready)

    def refilter(self, *_):
        self.proxy.beginFilterChange()
        self.proxy.query = self.search.text().strip(); self.proxy.category = self.categories.currentData() or ''
        self.proxy.only_errors = self.errors.isChecked(); self.proxy.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def selected_ids(self, all_filtered=False):
        rows = range(self.proxy.rowCount()) if all_filtered else sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.proxy.index(row, 0).data(Qt.UserRole) for row in rows]

    def select_image(self, *_):
        if not self.catalog: return
        index = self.table.currentIndex()
        if not index.isValid(): return
        key = index.data(Qt.UserRole)
        if key == self.selected_id: return
        self.selected_id = key; asset = self.catalog.by_id[key]
        self.update_buttons()
        self.canvas.clear(); self.image_note.setText('Decoding ' + asset.name.strip() + '…')
        chain = '\n\n'.join(
            f"[{step['index']}] {step['name']}\n"
            f"  {step['container']} · {step['compression']} · offset 0x{step['offset']:X} in {step['offset_space']}\n"
            f"  logical {step['logical_size']:,} bytes · physical {step['physical_size']:,} bytes" +
            (f" · kind {step['kind']}" if 'kind' in step else '') for step in asset.chain)
        self.details.setPlainText(f'{asset.name}\n{asset.category}\n{asset.consumer}\n\n'
            f'{asset.width} × {asset.height} · {asset.format} · {asset.order}\n'
            f'{asset.status}' + (f': {asset.error}' if asset.error else '') + '\n\n'
            f'Identity: {asset.id}\nDecoded member: {asset.size:,} bytes\n'
            f'Known regions: {len(asset.regions)} · literal script uses: {len(asset.references)}\n\n'
            f'Source: {asset.source}\n{chain}\n\n'
            'Nested offsets are relative to each decoded parent, not absolute source-file offsets.\n'
            'Names retain original spaces. Static uses refer to original scripts; dynamic and native uses may be indirect.')
        if key in self.replacements:
            from .textureassets import summary
            self.details.appendPlainText('\n\nProject PNG replacement (saved inside editor project):\n' + json.dumps(summary(self.replacements[key]), indent=2))
        from .gxtwriter import constraints
        self.details.appendPlainText('\n\nGame export constraints (checked before writing):\n' + json.dumps(constraints(asset), indent=2))
        self.regions.clear(); self.uses.clear()
        item = QListWidgetItem('Whole texture'); item.setData(Qt.UserRole, None); self.regions.addItem(item)
        for region in asset.regions:
            item = QListWidgetItem(f"{region['label']} · {region['rect']}"); item.setData(Qt.UserRole, region); self.regions.addItem(item)
        self.regions.setCurrentRow(0)
        for row in asset.references:
            item = QListWidgetItem(f"{row['script']:03} / command {row['command']} · {row['use']}")
            item.setData(Qt.UserRole, row); self.uses.addItem(item)
        if not asset.references:
            self.uses.addItem('No literal script reference mapped. Native/indirect/dynamic uses may exist.')
        try: self.catalog.verify()
        except (ValueError, OSError) as error:
            self.image_note.setText(str(error)); return
        if key in self.cache:
            self.cache.move_to_end(key); self.canvas.display(self.cache[key]); self.image_note.setText(f'{asset.width} × {asset.height} · wheel to zoom, drag to pan')
        else:
            resolver = AssetResolver(self.catalog, {} if self.original.isChecked() else self.replacements)
            self.enqueue('decode', key, lambda progress, cancel: resolver.image(key, cancel))

    def editable_project(self):
        owner = self.parent()
        if owner and hasattr(owner, 'ensure_project'):
            if not owner.ensure_project():return None
            self.set_project(owner.project)
        return self.project

    def import_replacement(self):
        project = self.editable_project()
        if not project or not self.selected_id:return
        revision, identity = project.revision, self.selected_id
        path, _ = QFileDialog.getOpenFileName(self, 'Import same-size lossless PNG into project', '', 'PNG (*.png)')
        if not path:return
        try:
            if self.project is not project or project.revision != revision:raise ValueError('Project changed during import; retry')
            from .textureassets import read_png
            if project.set_texture(identity, read_png(path), self.catalog):self.texturesChanged.emit(revision);self.set_project(project)
        except (ValueError, OSError) as error:QMessageBox.warning(self, 'PNG import', str(error))

    def revert_replacement(self):
        project = self.editable_project()
        if not project or not self.selected_id:return
        revision = project.revision
        try:project.remove_texture(self.selected_id);self.texturesChanged.emit(revision);self.set_project(project)
        except (ValueError, OSError) as error:QMessageBox.warning(self, 'Revert PNG', str(error))

    def save_viewed_png(self):
        if not self.catalog or not self.selected_id:return
        from .textureassets import png_bytes, encode_png, write_png
        identity = self.selected_id; replacement = self.replacements.get(identity) if not self.original.isChecked() else None
        path, _ = QFileDialog.getSaveFileName(self, 'Write PNG copy to a NEW file', '', 'PNG (*.png)')
        if not path:return
        try:
            data = png_bytes(replacement) if replacement else encode_png(self.catalog.decode(identity))
            write_png(path, data, self.catalog.root);self.note.setText('PNG copy saved. Original game files unchanged.')
        except (ValueError, OSError) as error:QMessageBox.warning(self, 'Save PNG', str(error))

    def show_region(self, item, *_):
        region = item.data(Qt.UserRole) if item else None
        self.canvas.region(region['rect'] if region else None)
        if region:
            item.setToolTip(json.dumps(region, ensure_ascii=False, indent=2))

    def open_use(self, item):
        row = item.data(Qt.UserRole)
        if row: self.commandPicked.emit(row['script'], row['command'])

    def extract(self, all_filtered=False):
        ids = self.selected_ids(all_filtered)
        if not ids:
            QMessageBox.information(self, 'Extract images', 'Select one or more images first.'); return
        destination = QFileDialog.getExistingDirectory(self, 'Choose a separate EMPTY extraction folder')
        if not destination: return
        catalog, mode = self.catalog, self.mode.currentData()
        self.enqueue('extract', None, lambda progress, cancel: extract_images(catalog, ids, destination, mode, progress, cancel))

    def shutdown(self):
        if self.composition_panel and not self.composition_panel.shutdown(): return False
        self.pending = None; self.deferred_decode = None
        if self.job:
            self.job.requestInterruption()
            if not self.job.wait(1500): return False
        return True

    def show_compositions(self):
        if self.catalog is None:return
        if self.composition_panel is None:
            from .compositionview import CompositionBrowser
            self.composition_panel=CompositionBrowser(self)
            self.composition_panel.assetPicked.connect(self.focus_asset)
        focus=self.catalog.by_id.get(self.selected_id)
        from .uitext import get_catalog
        ui=self.project.ui_text_assets if self.project else {}
        self.composition_panel.set_context(self.catalog,self.font,self.sample_text,focus,self.sample_speaker,self.samples,self.replacements,ui,get_catalog(self.project) if ui else None)
        self.composition_panel.show();self.composition_panel.raise_();self.composition_panel.activateWindow()

    def focus_asset(self,identity):
        if self.catalog is None or identity not in self.catalog.by_id:return
        self.categories.setCurrentIndex(0);self.errors.setChecked(False);self.search.setText(identity)
        for row in range(self.proxy.rowCount()):
            index=self.proxy.index(row,0)
            if index.data(Qt.UserRole)==identity:
                self.table.setCurrentIndex(index);self.table.selectRow(row);self.table.scrollTo(index);break
        self.raise_();self.activateWindow()

    def closeEvent(self, event):
        # Hiding the browser preserves its index/cache. A worker is always owned
        # until completion; the parent explicitly cancels/joins on application exit.
        if self.job: self.cancel_work()
        super().closeEvent(event)
