"""Analyze/review existing translation cleanup before one atomic Apply."""
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QCheckBox,
    QSpinBox,QPushButton,QTableWidget,QTableWidgetItem,QHeaderView,QPlainTextEdit,QSplitter)
from .textcleanup import analyze_cleanup


class AutoFitDialog(QDialog):
    def __init__(self,window):
        super().__init__(window);self.owner=window;self.project=window.project;self.plan=None;self.resize(1050,780)
        self.setWindowTitle('Auto-fit existing translations');layout=QVBoxLayout(self)
        note=QLabel('Analyze current text, repair native line breaks, hyphenate long words and split overflowing dialogue. Review checked changes; Apply is one Undo operation.');note.setWordWrap(True);layout.addWidget(note)
        row=QHBoxLayout();self.scope=QComboBox();self.scope.addItems(['Current file','Selected command','Whole project']);row.addWidget(self.scope)
        self.skip_japanese=QCheckBox('Skip Japanese text');self.skip_japanese.setChecked(True);self.skip_japanese.setToolTip('Kana/Han character check; speaker names and control tags are excluded. Includes other scripts. Uncheck for mixed/Japanese/Chinese text.');row.addWidget(self.skip_japanese)
        self.hyphen=QCheckBox('Hyphenate long words');self.hyphen.setChecked(True);row.addWidget(self.hyphen)
        self.split=QCheckBox('Split overflowing dialogue');self.split.setChecked(True);row.addWidget(self.split);layout.addLayout(row)
        self.full_width=QCheckBox('Full-width Latin for readability (convert, then fit)')
        self.full_width.setToolTip('Optional for the current PVF player: wider supported Latin glyphs. Controls, spaces and reserved breaks are preserved; extra pages may be needed.')
        layout.addWidget(self.full_width)
        self.proportional=QCheckBox('Proportional dialogue font asset (Vita + PC; no executable changes)')
        self.proportional.setChecked(bool(self.project.font_asset));self.proportional.setToolTip('Generate and save/export a Font.gsf bitmap override. Refit selected dialogue using those widths; speaker/UI DrawString spacing remains fixed. Undo restores font plus text.')
        layout.addWidget(self.proportional)
        row=QHBoxLayout();self.mode=QComboBox()
        for label,value in [('Auto dialogue layout','auto'),('Message window','ordinary'),('Battle dialogue','battle')]:self.mode.addItem(label,value)
        row.addWidget(self.mode)
        self.width=self.spin(row,'Multiline width',4096,'Authored');self.lines=self.spin(row,'Lines/page',20,'Fit frame')
        self.label_width=self.spin(row,'Single-line width',4096,'Auto screen fit');layout.addLayout(row)
        actions=QHBoxLayout();analyze=QPushButton('Analyze again');analyze.clicked.connect(self.analyze);actions.addWidget(analyze)
        self.apply_button=QPushButton('Apply checked changes');self.apply_button.setEnabled(False);self.apply_button.clicked.connect(self.accept);actions.addWidget(self.apply_button)
        cancel=QPushButton('Cancel');cancel.clicked.connect(self.reject);actions.addWidget(cancel);layout.addLayout(actions)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        splitter=QSplitter(Qt.Vertical);self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Apply','File / command','Result','Details'])
        self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch);self.table.setColumnWidth(1,180);self.table.setColumnWidth(2,170)
        self.table.setSelectionBehavior(QTableWidget.SelectRows);self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.inspect);splitter.addWidget(self.table)
        self.review=QPlainTextEdit();self.review.setReadOnly(True);splitter.addWidget(self.review);splitter.setSizes([360,260]);layout.addWidget(splitter,1)
        for widget in (self.scope,self.mode):widget.currentIndexChanged.connect(self.invalidate)
        for widget in (self.skip_japanese,self.hyphen,self.split,self.full_width,self.proportional):widget.toggled.connect(self.invalidate)
        for widget in (self.width,self.lines,self.label_width):widget.valueChanged.connect(self.invalidate)
        QTimer.singleShot(0,self.analyze)

    def spin(self,row,label,maximum,zero):
        row.addWidget(QLabel(label));widget=QSpinBox();widget.setRange(0,maximum);widget.setSpecialValueText(zero);row.addWidget(widget);return widget

    def invalidate(self,*_):
        self.plan=None;self.apply_button.setEnabled(False);self.status.setText('Options changed; Analyze again to refresh the proposals.')

    def analyze(self):
        self.apply_button.setEnabled(False);self.status.setText('Analyzing current text and native box geometry…');self.status.repaint()
        try:
            self.owner.guard_edit_snapshot(self.project,self.project.revision)
            scope=self.scope.currentIndex();uid=None
            if scope==1:
                index=self.owner.selected()
                if index is None:raise ValueError('Select a command first')
                uid=[self.project.scripts[self.owner.script_id].commands[index].uid]
            self.plan=analyze_cleanup(self.project,self.owner.session.text,self.owner.session.settings,
                script_ids=None if scope==2 else [self.owner.script_id],command_ids=uid,skip_japanese=self.skip_japanese.isChecked(),
                hyphenate=self.hyphen.isChecked(),paginate=self.split.isChecked(),width=self.width.value() or None,
                max_lines=self.lines.value() or None,label_width=self.label_width.value() or None,dialogue_mode=self.mode.currentData(),full_width_latin=self.full_width.isChecked(),proportional_latin=self.proportional.isChecked())
            self.table.setRowCount(0);self.review.clear();self.font_note=''
            if self.plan.get('font_changed'):
                before=self.project.font_asset['manifest'].get('generator_revision',1) if self.project.font_asset else 'Original'
                after=self.plan['font_asset']['manifest'].get('generator_revision',1)
                self.font_note=f'Font asset update: {before} -> revision {after}. Saved/exported Font.gsf and preview metrics update with Apply; script text may stay unchanged. Undo restores both.'
            for change in self.plan['changes']:
                details=change['details'];description='Convert only' if details[0].get('wrapping_skipped') else f"{change['page_count']} page(s)" if change['page_count']>1 else 'Wrap / normalize'
                capacity=f"; box fits {change['capacity']} lines" if change['capacity'] else ''
                self.add_row(change['script_id'],change['command_id'],description,f"{max(d['line_count'] for d in details)} line(s)/page{capacity}",change,True)
            for issue in self.plan['issues']:
                m=issue.get('measurement');status='Reported / skipped'
                if m:status='Context needed' if m['context_required'] else 'Fits / read-only' if m['fits'] else 'Overflow / read-only'
                if m and m['auto_edit']:status=status.replace('read-only','conversion only')
                self.add_row(issue['script_id'],issue['command_id'],status,issue['reason'],issue,False)
            s=self.plan['summary'];self.status.setText(f"{s['scanned']} text commands scanned; {s['eligible']} eligible; {s['changed_commands']} changes; +{s['inserted_commands']} commands; {s['reported']} reported/skipped. Mechanical hyphens are not language-specific syllabification.")
            self.status.setText(self.status.text()+(' Font asset update pending.' if self.plan.get('font_changed') else ''))
            self.apply_button.setText('Apply font update + checked text' if self.plan.get('font_changed') else 'Apply checked changes')
            self.apply_button.setEnabled(bool(self.plan['changes']) or self.plan.get('font_changed',False))
            if self.font_note:self.review.setPlainText(self.font_note)
            if self.table.rowCount():self.table.selectRow(0)
        except (ValueError,RuntimeError,KeyError) as error:self.plan=None;self.status.setText(str(error))

    def add_row(self,sid,uid,status,note,data,checked):
        row=self.table.rowCount();self.table.insertRow(row);check=QTableWidgetItem()
        check.setData(Qt.UserRole,data)
        if checked:
            check.setFlags(Qt.ItemIsEnabled|Qt.ItemIsSelectable|Qt.ItemIsUserCheckable)
            check.setCheckState(Qt.Checked)
        else:check.setFlags(Qt.ItemIsEnabled|Qt.ItemIsSelectable)
        self.table.setItem(row,0,check)
        for column,text in enumerate((f'{sid:03} / {uid}',status,note),1):self.table.setItem(row,column,QTableWidgetItem(text))

    def selected_commands(self):
        return [self.table.item(i,0).data(Qt.UserRole)['command_id'] for i in range(self.table.rowCount()) if self.table.item(i,0).checkState()==Qt.Checked]

    def inspect(self):
        row=self.table.currentRow()
        if row<0 or self.table.item(row,0) is None:return
        data=self.table.item(row,0).data(Qt.UserRole)
        if 'reason' in data:
            m=data.get('measurement');lines=[self.font_note,data['reason']]
            if m:
                verdict='Fits in isolation' if m['standalone_fits'] else 'Overflows in isolation'
                lines.extend([f"\n{verdict}: {m['line_count']} line(s), capacity {m['capacity']}, widest {max(m['line_widths'],default=0)}/{m['width']}px",'\nMEASURED TEXT',*m['lines']])
            self.review.setPlainText('\n'.join(lines));return
        f=self.owner.session.text.format;lines=[self.font_note,'BEFORE']
        for key,text in data['before_texts'].items():lines.extend([key,text.replace(f.break_char,'\n')])
        for page,fields in enumerate(data['after_texts'],1):
            lines.append(f'\nAFTER — page {page}')
            for key,text in fields.items():lines.extend([key,text.replace(f.break_char,'\n')])
        lines.extend(['\n'+warning for warning in data['warnings']]);self.review.setPlainText('\n'.join(lines))
