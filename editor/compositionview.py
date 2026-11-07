"""Read-only layout snapshots using the same image catalog as the asset browser."""
from dataclasses import asdict
import json
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QSplitter, QLabel, QPushButton, QComboBox, QSpinBox, QCheckBox, QPlainTextEdit,
    QListWidget, QListWidgetItem, QTabWidget, QScrollArea)
from PySide6.QtCore import Signal
from .composition import FAMILIES, IMPLEMENTED_FAMILIES, EnvironmentLibrary, Layer, walk_layers
from .compositioncommon import PARAMETERS, cached, dialog_environment, calendar_environment
from .compositionlists import PARAMETERS as LIST_PARAMETERS, backlog_environment
from .compositionsettings import PARAMETERS as SETTINGS_PARAMETERS, settings_environment, parameter_visible
from .compositionextras import PARAMETERS as EXTRAS_PARAMETERS, preview_limits as extras_limits, parameter_visible as extras_parameter_visible
from .compositionmodes import PARAMETERS as MODE_PARAMETERS, preview_limits as mode_limits, parameter_visible as mode_parameter_visible
from .compositionbattle import PARAMETERS as BATTLE_PARAMETERS, parameter_visible as battle_parameter_visible, battle_environment
from .compositionrender import AssetResolver, TextureLoader, FontConsumer, render_composition
from .imageview import ImageCanvas, ImageJob


class CompositionBrowser(QDialog):
    assetPicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle('UI compositions — read-only'); self.resize(1450, 900)
        self.catalog = None; self.library = None; self.font = None; self.font_consumer = None; self.loader = None
        self.job = None; self.pending = None; self.generation = 0; self.composition = None
        self.parameters = {}; self.family_text = {}; self.last_family = None
        self.replacements = {}
        outer = QVBoxLayout(self)
        note = QLabel('Preview UI layouts with current assets. Controls change this snapshot only; game/project state is untouched.')
        note.setWordWrap(True); outer.addWidget(note)
        split = QSplitter(); outer.addWidget(split, 1)
        controls = QWidget(); form = QFormLayout(controls); self.form = form
        control_scroll = QScrollArea(); control_scroll.setWidgetResizable(True); control_scroll.setWidget(controls)
        control_scroll.setMinimumWidth(290); control_scroll.setMaximumWidth(380); split.addWidget(control_scroll)
        self.family = QComboBox()
        for key, label, status in FAMILIES:
            self.family.addItem(label + (' · pending' if status.startswith('Pending') else ''), key)
            self.family.setItemData(self.family.count() - 1, status, Qt.ToolTipRole)
        form.addRow('UI family', self.family)
        self.selected = QSpinBox(); self.selected.setRange(0, 4); form.addRow('Selected row', self.selected)
        self.variant = QSpinBox(); self.variant.setRange(0, 3); form.addRow('Title variant', self.variant)
        self.progress = QSpinBox(); self.progress.setRange(0, 100); self.progress.setValue(100); form.addRow('Layout sample %', self.progress)
        self.angle = QSpinBox(); self.angle.setRange(0, 359); form.addRow('Ring / Auto angle', self.angle)
        self.speaker = QSpinBox(); self.speaker.setRange(-1, 8); self.speaker.setSpecialValueText('No nameplate'); self.speaker.setValue(0); form.addRow('Speaker plate ID', self.speaker)
        self.opacity = QSpinBox(); self.opacity.setRange(0, 11); self.opacity.setValue(11); form.addRow('Window opacity', self.opacity)
        self.chapter = QSpinBox(); self.chapter.setRange(-1, 99); self.chapter.setSpecialValueText('No chapter panel'); self.chapter.setValue(0); form.addRow('Chapter palette', self.chapter)
        self.press_start = QCheckBox('Press-start layout'); self.skip = QCheckBox('Skip active')
        self.auto = QCheckBox('Auto active'); self.cursor = QCheckBox('Advance cursor'); self.cursor.setChecked(True)
        for control in (self.press_start, self.skip, self.auto, self.cursor): form.addRow(control)
        self.backdrop = QComboBox(); form.addRow('Context backdrop', self.backdrop)
        self.original = QCheckBox('Use original textures'); form.addRow(self.original)
        self.original.toggled.connect(lambda: self.set_replacements(self.replacements))
        self.text = QPlainTextEdit(); self.text.setPlaceholderText('Preview text; never modifies script text'); self.text.setMaximumHeight(150); form.addRow('Sample text', self.text)
        self.extra_host = QWidget(); self.extra_form = QFormLayout(self.extra_host); self.extra_form.setContentsMargins(0, 0, 0, 0); form.addRow(self.extra_host)
        buttons = QHBoxLayout(); refresh = QPushButton('Refresh layouts'); refresh.clicked.connect(self.refresh)
        cancel = QPushButton('Cancel'); cancel.clicked.connect(self.cancel_work); buttons.addWidget(refresh); buttons.addWidget(cancel); form.addRow(buttons)
        self.status = QLabel('Open from Images after loading a game.'); self.status.setWordWrap(True); form.addRow(self.status)
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0); split.addWidget(right)
        row = QHBoxLayout()
        self.canvas = ImageCanvas()
        for label, action in [('Fit', self.canvas.fit), ('1:1', self.canvas.actual)]:
            button = QPushButton(label); button.clicked.connect(action); row.addWidget(button)
        row.addStretch(); row.addWidget(QLabel('960 × 544 · select layer to outline · double-click to inspect source'))
        rl.addLayout(row)
        inner = QSplitter(Qt.Vertical); rl.addWidget(inner, 1); inner.addWidget(self.canvas)
        lower = QSplitter(); inner.addWidget(lower); inner.setSizes([550, 250])
        self.layers = QListWidget(); self.layers.currentItemChanged.connect(self.inspect_layer)
        self.layers.itemDoubleClicked.connect(self.inspect_source); lower.addWidget(self.layers)
        tabs = QTabWidget(); lower.addWidget(tabs)
        self.details = QPlainTextEdit(); self.details.setReadOnly(True); tabs.addTab(self.details, 'Layer')
        self.notes = QPlainTextEdit(); self.notes.setReadOnly(True); tabs.addTab(self.notes, 'Coverage / diagnostics')
        self.coverage = QPlainTextEdit(); self.coverage.setReadOnly(True)
        self.coverage.setPlainText('\n\n'.join(label + '\n' + status for _, label, status in FAMILIES))
        tabs.addTab(self.coverage, 'UI families'); lower.setSizes([450, 550]); split.setSizes([320, 1130])
        close = QPushButton('Close'); close.clicked.connect(self.close); outer.addWidget(close, alignment=Qt.AlignRight)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(120); self.timer.timeout.connect(self.rebuild)
        self.family.currentIndexChanged.connect(self.configure_family)
        for spin in (self.selected, self.variant, self.progress, self.angle, self.speaker, self.opacity, self.chapter): spin.valueChanged.connect(self.changed)
        for check in (self.press_start, self.skip, self.auto, self.cursor): check.toggled.connect(self.changed)
        self.backdrop.currentIndexChanged.connect(self.changed); self.text.textChanged.connect(self.changed)

    def set_context(self, catalog, font, sample_text='', focus=None, sample_speaker=-1, samples=None, replacements=None, ui_text_assets=None,ui_text_catalog=None,*,defer=False):
        self.invalidate()
        self.catalog = catalog; self.font = font; self.font_consumer = FontConsumer(font) if font else None
        self.replacements = dict(replacements or {})
        self.ui_text_assets=dict(ui_text_assets or {});self.ui_text_catalog=ui_text_catalog
        self.library = EnvironmentLibrary(catalog.root, catalog=catalog,ui_text_assets=self.ui_text_assets,ui_text_catalog=ui_text_catalog); self.loader = TextureLoader(AssetResolver(catalog, {} if self.original.isChecked() else self.replacements))
        self.backdrop.blockSignals(True); self.backdrop.clear(); self.backdrop.addItem('Neutral matte', None)
        for a in catalog.assets:
            if a.source == 'resource.dat' and len(a.route) == 2 and a.route[0] in (5, 9) and a.status == 'Ready':
                self.backdrop.addItem(f'{a.name.strip()} · {a.id}', a.id)
        self.backdrop.blockSignals(False)
        self.family_text = dict(samples or {}); self.family_text.setdefault('message', sample_text[:4096]); self.last_family = None
        self.speaker.setValue(sample_speaker)
        key = 'message'
        if focus and focus.source == 'first.dat' and focus.route and focus.route[0] == 1:
            key = 'slots' if focus.route[-1] in (2, 6, 10, 11, 18) else 'dialogs'
        if focus and focus.source == 'resource.dat' and focus.route:
            bank = focus.route[0]
            key = {15: 'title', 13: 'system', 16: 'battle', 3: 'profile', 2: 'extras'}.get(bank, 'message')
            if bank == 15 and focus.route[-1] <= 62: key = 'extras'
            if bank == 1:
                if focus.route[-1] in (4, 5, 6, 50): key = 'calendar'
                elif focus.route[-1] in (18, 19, 20): key = 'choices'
                elif 33 <= focus.route[-1] <= 40: key = 'backlog'
            if bank == 15:
                self.press_start.setChecked(focus.route[-1] in (73, 77, 78, 79, 80))
                if focus.route[-1] in (72, 81, 76, 75): self.variant.setValue((72, 81, 76, 75).index(focus.route[-1]))
            if bank == 13 and 7 <= focus.route[-1] <= 21:
                self.selected.setValue((focus.route[-1] - 7) % 5)
            if bank == 13 and 62 <= focus.route[-1] <= 72: key = 'slots'
            if bank == 13 and 25 <= focus.route[-1] <= 61: key = 'settings'
            if bank == 1 and 41 <= focus.route[-1] <= 49: self.speaker.setValue(focus.route[-1] - 41)
        self.family.setCurrentIndex(self.family.findData(key)); self.configure_family(); self.timer.stop()
        if not defer:self.rebuild()

    def set_replacements(self, replacements, font=None,ui_text_assets=None,ui_text_catalog=None):
        self.replacements = dict(replacements)
        if font is not None:self.font = font
        if not self.catalog:return
        if ui_text_assets is not None:self.ui_text_assets=dict(ui_text_assets);self.ui_text_catalog=ui_text_catalog
        self.library=EnvironmentLibrary(self.catalog.root,catalog=self.catalog,ui_text_assets=getattr(self,'ui_text_assets',{}),ui_text_catalog=getattr(self,'ui_text_catalog',None))
        self.loader = TextureLoader(AssetResolver(self.catalog, {} if self.original.isChecked() else replacements))
        self.font_consumer = FontConsumer(self.font) if self.font else None
        self.rebuild()

    def configure_family(self, *_):
        key = self.family.currentData()
        if self.last_family is not None and key != self.last_family:
            self.family_text[self.last_family] = self.text.toPlainText()
        if key != self.last_family:
            defaults = {'message': '', 'system': 'Chapter preview', 'choices': 'Choice 1\nChoice 2',
                        'calendar': 'Chapter preview\nSubtitle preview', 'dialogs': 'Preview prompt',
                        'slots': 'Preview chapter\nPreview dialogue', 'backlog': 'Sample dialogue1\nSample dialogue2\nSample dialogue3'}
            self.text.blockSignals(True); self.text.setPlainText(self.family_text.get(key, defaults.get(key, ''))); self.text.blockSignals(False)
            self.last_family = key
        self.selected.setMaximum(59 if key == 'slots' else 199 if key == 'backlog' else 3 if key == 'title' else 4)
        self.selected.setMinimum(-1 if key in ('choices', 'dialogs') else 0)
        self.selected.setSpecialValueText('No focus')
        for widget in (self.variant, self.press_start): widget.setEnabled(key == 'title')
        for widget in (self.speaker, self.opacity, self.skip, self.auto, self.cursor): widget.setEnabled(key == 'message')
        self.selected.setEnabled(key in ('title', 'system', 'choices', 'dialogs', 'slots', 'backlog', 'settings', 'extras', 'profile')); self.progress.setEnabled(key in ('title', 'message', 'choices', 'dialogs'))
        self.chapter.setEnabled(key in ('system', 'calendar')); self.backdrop.setEnabled(key != 'title'); self.text.setEnabled(key != 'title')
        common = {
            self.selected: key in ('title', 'system', 'choices', 'dialogs', 'slots', 'backlog', 'settings', 'extras', 'profile'), self.variant: key == 'title',
            self.press_start: key == 'title', self.progress: key in ('title', 'message', 'choices', 'dialogs'),
            self.angle: key in ('title', 'message'), self.speaker: key == 'message', self.opacity: key == 'message',
            self.chapter: key in ('system', 'calendar'), self.skip: key == 'message', self.auto: key == 'message',
            self.cursor: key in ('message', 'profile'), self.text: key not in ('title', 'settings', 'extras', 'profile', 'battle'), self.backdrop: key != 'title'}
        self.cursor.setEnabled(key in ('message', 'profile'))
        for widget, visible in common.items(): self.form.setRowVisible(widget, visible)
        while self.extra_form.rowCount(): self.extra_form.removeRow(0)
        self.parameters = {}
        for name, label, kind, default, *bounds in (PARAMETERS | LIST_PARAMETERS | SETTINGS_PARAMETERS | EXTRAS_PARAMETERS | MODE_PARAMETERS | BATTLE_PARAMETERS).get(key, ()):
            default = self.family_text.get(key + ':' + name, default)
            if kind == 'bool': control = QCheckBox(); control.setChecked(default); control.toggled.connect(self.changed)
            elif kind == 'text':
                control = QPlainTextEdit(); control.setMaximumHeight(130)
                control.setPlainText(self.family_text.get(key + ':' + name, default)); control.textChanged.connect(self.changed)
            elif kind == 'enum':
                control = QComboBox()
                for value, text in bounds[0]: control.addItem(text, value)
                control.setCurrentIndex(control.findData(default)); control.currentIndexChanged.connect(self.changed)
            else:
                control = QSpinBox(); control.setRange(*bounds); control.setValue(default); control.valueChanged.connect(self.changed)
            self.parameters[name] = control; self.extra_form.addRow(label, control)
        self.text.setToolTip('One entry per line' if key in ('choices', 'backlog') else 'Two caption lines' if key == 'calendar' else
                            'Chapter title then dialogue sample' if key == 'slots' else 'Preview text only')
        self.changed()

    def changed(self, *_):
        if self.catalog: self.timer.start()

    def show_recipe(self,recipe,text=None):
        """Open a source-bound text consumer using the existing composition UI."""
        self.family.setCurrentIndex(self.family.findData(recipe['family']));self.configure_family()
        common=dict(selected=self.selected,character=self.variant,chapter=self.chapter,text=self.text)
        for name,value in recipe.get('state',{}).items():
            control=self.parameters.get(name,common.get(name))
            if control is None:continue
            if isinstance(control,QComboBox):control.setCurrentIndex(control.findData(value))
            elif isinstance(control,QCheckBox):control.setChecked(value)
            elif isinstance(control,QPlainTextEdit):control.setPlainText(value)
            else:control.setValue(value)
        if recipe.get('text_parameter')=='text' and text is not None:self.text.setPlainText(text)
        self.timer.stop();self.rebuild();self.show();self.raise_();self.activateWindow()

    def refresh(self):
        if self.catalog:
            self.library = EnvironmentLibrary(self.catalog.root, catalog=self.catalog,ui_text_assets=getattr(self,'ui_text_assets',{}),ui_text_catalog=getattr(self,'ui_text_catalog',None)); self.rebuild()

    def rebuild(self):
        if not self.catalog: return
        self.timer.stop(); self.generation += 1; generation = self.generation
        key = self.family.currentData()
        self.canvas.clear(); self.layers.clear(); self.details.clear(); self.composition = None
        if self.job: self.job.requestInterruption()
        self.pending = None
        if key not in IMPLEMENTED_FAMILIES:
            self.status.setText('This UI family is pending; see UI families for the coverage checklist.')
            self.notes.setPlainText('No layout has been fabricated for this family. Its textures remain available in Images.'); return
        state = dict(selected=self.selected.value(), character=self.variant.value(), progress=self.progress.value(),
                     speaker=self.speaker.value(), opacity=self.opacity.value(), chapter=self.chapter.value(),
                     angle=self.angle.value(), press_start=self.press_start.isChecked(), skip=self.skip.isChecked(),
                     auto=self.auto.isChecked(), cursor=self.cursor.isChecked(), text=self.text.toPlainText())
        state.update({name: control.isChecked() if isinstance(control, QCheckBox) else control.currentData() if isinstance(control, QComboBox) else control.toPlainText() if isinstance(control, QPlainTextEdit) else control.value()
                      for name, control in self.parameters.items()})
        if any(len(value) > 4096 for value in state.values() if isinstance(value, str)):
            self.status.setText('Sample text is limited to4096 characters per field.'); return
        if len(state['text']) > 4096:
            self.status.setText('Sample text is limited to4096 characters.'); return
        try:
            if key == 'battle':
                for name, control in self.parameters.items(): self.extra_form.setRowVisible(control, battle_parameter_visible(name, state['view']))
                self.form.setRowVisible(self.opacity, state['view'] == 1); self.opacity.setEnabled(state['view'] == 1)
                env = cached(self.library, 'battle_ui', 'env/env_tukkomi.dat', battle_environment)
                limit = min(len(env[name]) for name in ('names', 'name_sizes', 'name_offsets', 'colors')) - 1
                for name in ('side_0', 'side_1'):
                    control = self.parameters[name]; control.blockSignals(True); control.setMaximum(limit); control.blockSignals(False); state[name] = control.value()
            if key == 'profile':
                for name, control in self.parameters.items(): self.extra_form.setRowVisible(control, mode_parameter_visible(name, state['view']))
                self.form.setRowVisible(self.selected, state['view'] == 4)
                self.form.setRowVisible(self.cursor, state['view'] in (1, 2, 5))
                for name, maximum in mode_limits(self.library, state).items():
                    control = self.selected if name == 'selected' else self.parameters[name]
                    control.blockSignals(True); control.setMaximum(maximum); control.blockSignals(False); state[name] = control.value()
            if key == 'extras':
                for name, control in self.parameters.items(): self.extra_form.setRowVisible(control, extras_parameter_visible(name, state['view']))
                for name, maximum in extras_limits(self.library, state).items():
                    control = self.selected if name == 'selected' else self.parameters[name]
                    control.blockSignals(True); control.setMaximum(maximum); control.blockSignals(False); state[name] = control.value()
            if key == 'settings':
                env = cached(self.library, 'settings', 'env/env_option.dat', settings_environment)
                page = state['page']
                if page == 3 and not state['alternate']:
                    control = self.parameters['alternate']; control.blockSignals(True); control.setChecked(True); control.blockSignals(False)
                    state['alternate'] = True
                self.selected.blockSignals(True); self.selected.setMaximum((6, 5, 1, 0)[page]); self.selected.blockSignals(False)
                state['selected'] = self.selected.value(); self.form.setRowVisible(self.selected, page < 3)
                for name, control in self.parameters.items():
                    self.extra_form.setRowVisible(control, parameter_visible(name, page))
                    if name in ('text_speed', 'auto_speed', 'window_opacity') or name.startswith('audio_') and name != 'audio_toggle':
                        maximum = env.signed(0x14 if name in ('text_speed', 'auto_speed') else 0x18) - 1
                        control.blockSignals(True); control.setMaximum(maximum); control.blockSignals(False); state[name] = control.value()
            if key == 'backlog':
                count = len(state['text'].splitlines())
                self.selected.blockSignals(True); self.selected.setMaximum(max(0, count - 1)); self.selected.blockSignals(False)
                state['selected'] = self.selected.value()
                env = cached(self.library, 'backlog', 'env/env_backlog.dat', backlog_environment)
                voice = self.parameters['voice_frame']; voice.blockSignals(True)
                voice.setMaximum(len(env.voices) - 1); voice.blockSignals(False); state['voice_frame'] = voice.value()
                first = self.parameters['first']; first.blockSignals(True)
                first.setMaximum(max(0, count - env.signed(0xc188))); first.blockSignals(False); state['first'] = first.value()
            if key == 'choices':
                count = len(state['text'].splitlines()) or 2
                self.selected.blockSignals(True); self.selected.setMaximum(max(0, count - 1)); self.selected.blockSignals(False)
                state['selected'] = self.selected.value()
            elif key == 'dialogs':
                env = cached(self.library, 'dialogs', 'env/env_dialog.dat', dialog_environment)
                group = self.parameters['group']; group.blockSignals(True); group.setMaximum(len(env['groups']) - 1); group.blockSignals(False)
                state['group'] = group.value()
                count = len(env['groups'][group.value()]) if group.value() >= 0 else 0
                self.selected.blockSignals(True); self.selected.setMaximum(count - 1); self.selected.blockSignals(False)
                state['selected'] = self.selected.value()
            elif key == 'calendar':
                env = cached(self.library, 'calendar', 'env/env_script.dat', calendar_environment)
                palette = self.parameters['palette']; palette.blockSignals(True)
                palette.setMaximum(min(len(env['labels']), len(env['colors'])) - 1); palette.blockSignals(False)
                state['palette'] = palette.value()
            if key in ('system', 'calendar'):
                count = len(self.library.get('system').colors[0x26c])
                self.chapter.blockSignals(True); self.chapter.setMaximum(count - 1); self.chapter.blockSignals(False)
                state['chapter'] = self.chapter.value()
            state['context_image'] = self.backdrop.currentData()
            self.catalog.verify(); composition = self.library.build(key, state, self.font)
            backdrop = self.backdrop.currentData()
            if backdrop and key != 'title':
                composition.layers.insert(0, Layer('Chosen context backdrop', asset=backdrop,
                    source=[0, 0, 960, 544], destination=[0, 0, 960, 544]))
            if key == 'title': composition.notes.append('Layout sample is shared channel progress, not a frame-accurate animation timeline.')
            composition.notes.append('Text uses the editor font consumer; Qt rasterization is not a native/Vita pixel-parity claim.')
        except (ValueError, KeyError, OSError) as error:
            self.status.setText(str(error)); return
        self.status.setText('Loading contributing assets…')
        self.pending = (composition, self.loader, generation)
        if self.job is None: self.start_pending()

    def start_pending(self):
        request, self.pending = self.pending, None
        if request is None: return
        composition, loader, generation = request
        self.job = ImageJob(lambda progress, cancel: loader.load(composition, progress, cancel), self)
        self.job.ready.connect(lambda result: self.ready(composition, generation, result))
        self.job.failed.connect(lambda message: self.status.setText(message) if generation == self.generation else None)
        self.job.finished.connect(self.job_finished); self.job.start()

    def ready(self, composition, generation, result):
        if generation != self.generation or not self.catalog: return
        try:
            self.catalog.verify(); self.library.verify()
            textures, errors = result
            image, issues = render_composition(composition, textures, self.font_consumer)
        except (ValueError, OSError) as error:
            self.status.setText(str(error)); return
        self.composition = composition; self.canvas.display(image)
        self.notes.setPlainText('\n'.join(composition.notes + errors + issues) + '\n\nLayout source hashes:\n' + json.dumps(composition.sources, indent=2))
        self.display_layers = list(walk_layers(composition.layers))
        for i, layer in enumerate(self.display_layers):
            item = QListWidgetItem(f'{i:02} · {layer.name} · {layer.asset or "text"}')
            item.setData(Qt.UserRole, i); self.layers.addItem(item)
        self.status.setText(f'{len(self.display_layers)} layers · {len(errors) + len(issues)} diagnostics. Preview state only; originals unchanged.')

    def job_finished(self):
        old, self.job = self.job, None
        if old: old.deleteLater()
        if self.pending: self.start_pending()

    def inspect_layer(self, item, *_):
        if not item or not self.composition: return
        layer = self.display_layers[item.data(Qt.UserRole)]
        self.details.setPlainText(json.dumps(asdict(layer), ensure_ascii=False, indent=2))
        self.canvas.region(layer.destination)
        if self.canvas.region_item and layer.rotation:
            degrees, x, y = layer.rotation
            self.canvas.region_item.setTransformOriginPoint(x, y); self.canvas.region_item.setRotation(degrees)

    def inspect_source(self, item):
        if self.composition:
            layer = self.display_layers[item.data(Qt.UserRole)]
            if layer.asset.startswith('@target:'):
                self.details.appendPlainText('\nGenerated render target; inspect its child layers for original source images.')
            elif layer.asset: self.assetPicked.emit(layer.asset)

    def cancel_work(self):
        self.timer.stop(); self.generation += 1; self.pending = None
        if self.job: self.job.requestInterruption()
        self.status.setText('Composition operation cancelled; original data unchanged.')

    def invalidate(self):
        self.cancel_work(); self.catalog = None; self.library = None; self.loader = None; self.font_consumer = None
        self.canvas.clear(); self.layers.clear(); self.details.clear(); self.composition = None
        self.status.setText('Open compositions again after the source folder is loaded.')

    def shutdown(self):
        self.cancel_work()
        return self.job is None or self.job.wait(1500)

    def closeEvent(self, event):
        self.cancel_work(); super().closeEvent(event)
