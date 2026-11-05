"""Qt canvas for script/file flow; selecting never changes execution state."""
import html
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QPainterPath, QPolygonF, QTextLayout, QTextOption
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLineEdit,
    QLabel,QGraphicsView,QGraphicsScene,QGraphicsItem,QGraphicsTextItem,QCheckBox)
from .flowmodel import layered_positions

PALETTE={'text':('#203e40','#77d5bd'),'choice':('#443b26','#f2c77c'),
         'branch':('#362d40','#c4a1e4'),'quiet':('#202c39','#8194a8'),
         'file':('#253a53','#91b9ec')}


class CardItem(QGraphicsItem):
    WIDTH=350

    def __init__(self, card, canvas):
        super().__init__();self.card=card;self.canvas=canvas;self.running=False;self.match=False
        self.height=176 if card.kind in {'text','choice'} else 110
        self.setFlags(QGraphicsItem.ItemIsSelectable|QGraphicsItem.ItemIsFocusable)
        self.setZValue(2);self.setToolTip(card.tooltip or card.body)
        self.title_font=QFont('Segoe UI',10);self.title_font.setBold(True)
        self.body_font=QFont('Segoe UI',10 if card.kind!='quiet' else 9)
        self.layout=QTextLayout(card.body,self.body_font)
        option=self.layout.textOption();option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere);self.layout.setTextOption(option)
        self.layout.beginLayout();y=0
        while y<self.height-61:
            line=self.layout.createLine()
            if not line.isValid():break
            line.setLineWidth(self.WIDTH-28);line.setPosition(QPointF(0,y));y+=line.height()+2
        self.layout.endLayout()

    def boundingRect(self):return QRectF(0,0,self.WIDTH,self.height)

    def paint(self,painter,option,widget=None):
        fill,stroke=PALETTE[self.card.kind]
        painter.setRenderHint(QPainter.Antialiasing)
        pen=QPen(QColor('#f6d58a' if self.running else '#86e6df' if self.isSelected() else stroke),3 if self.isSelected() or self.running else 1.3)
        if self.card.detached:pen.setStyle(Qt.DashLine)
        painter.setPen(pen);painter.setBrush(QColor('#3b5358' if self.match else fill));painter.drawRoundedRect(self.boundingRect(),9,9)
        painter.setPen(QColor(stroke));painter.setFont(self.title_font)
        painter.drawText(QRectF(14,10,self.WIDTH-28,24),Qt.AlignVCenter,self.card.title)
        painter.setPen(QColor('#e7edf1' if self.card.kind!='quiet' else '#abb9c6'))
        painter.save();painter.setClipRect(QRectF(14,40,self.WIDTH-28,self.height-53));self.layout.draw(painter,QPointF(14,40));painter.restore()
        if self.running:
            painter.setPen(QColor('#ffe0a4'));painter.setFont(QFont('Segoe UI',8));painter.drawText(self.WIDTH-47,16,'RUN')

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:self.canvas.picked.emit(self.card)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self,event):
        self.canvas.activated.emit(self.card);event.accept()


class Canvas(QGraphicsView):
    picked=Signal(object)
    activated=Signal(object)

    def __init__(self):
        super().__init__();self.setScene(QGraphicsScene(self));self.setBackgroundBrush(QColor('#101923'))
        self.setDragMode(QGraphicsView.ScrollHandDrag);self.setRenderHints(QPainter.Antialiasing|QPainter.TextAntialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse);self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

    def zoom(self,factor):
        current=self.transform().m11()
        if current>0:
            target=max(.005,min(3,current*factor));self.scale(target/current,target/current)

    def wheelEvent(self,event):
        if event.modifiers() & Qt.ControlModifier:self.zoom(1.18 if event.angleDelta().y()>0 else 1/1.18);event.accept()
        else:super().wheelEvent(event)


class FlowPanel(QWidget):
    picked=Signal(object)
    activated=Signal(object)
    rebuild=Signal()

    def __init__(self, files=False):
        super().__init__();self.diagram=None;self.nodes={};self.selected_key=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        tools=QHBoxLayout()
        self.search=QLineEdit();self.search.setPlaceholderText('Find text / command… Enter for next match');self.search.textChanged.connect(self.search_cards);self.search.returnPressed.connect(self.next_match);tools.addWidget(self.search,2)
        for label,fn in [('−',lambda:self.canvas.zoom(1/1.2)),('+',lambda:self.canvas.zoom(1.2)),('Fit',self.fit),('Focus',self.focus_selected)]:
            button=QPushButton(label);button.clicked.connect(fn);tools.addWidget(button)
        self.detail=QCheckBox('Neighbors only' if files else 'Show setup details');self.detail.setChecked(files);self.detail.toggled.connect(lambda:self.rebuild.emit());tools.addWidget(self.detail)
        layout.addLayout(tools);self.canvas=Canvas();self.canvas.picked.connect(self.picked);self.canvas.activated.connect(self.activated);layout.addWidget(self.canvas,1)
        self.note=QLabel('Explicit file links · double-click a file to open its graph · drag to pan · Ctrl+wheel to zoom' if files else 'Potential flow · click to inspect · double-click text to preview via replay · drag background to pan · Ctrl+wheel to zoom')
        self.note.setWordWrap(True);layout.addWidget(self.note);self.matches=[];self.match_cursor=-1

    def set_diagram(self,diagram):
        self.diagram=diagram;self.nodes={};self.canvas.scene().clear();self.selected_key=None
        positions=layered_positions(diagram)
        for key,card in diagram.cards.items():
            item=CardItem(card,self.canvas);item.setPos(*positions[key]);self.nodes[key]=item;self.canvas.scene().addItem(item)
        for ordinal,edge in enumerate(diagram.links):
            a,b=self.nodes[edge.source],self.nodes[edge.target]
            ar=a.sceneBoundingRect();br=b.sceneBoundingRect();path=QPainterPath()
            if br.top()>ar.bottom():
                start=QPointF(ar.center().x(),ar.bottom());end=QPointF(br.center().x(),br.top());middle=(start.y()+end.y())/2
                path.moveTo(start);path.cubicTo(QPointF(start.x(),middle),QPointF(end.x(),middle),end)
            else:
                start=QPointF(ar.right(),ar.center().y());end=QPointF(br.right(),br.center().y());gutter=max(ar.right(),br.right())+55+(ordinal%5)*18
                path.moveTo(start);path.cubicTo(QPointF(gutter,start.y()),QPointF(gutter,end.y()-50),end)
            color=QColor('#77bd9c' if edge.label.startswith('true:') else '#d894ad' if edge.label.startswith('false:') else '#8da8c0')
            line=self.canvas.scene().addPath(path,QPen(color,1.7));line.setToolTip(edge.label)
            tip=path.pointAtPercent(1);previous=path.pointAtPercent(.96);delta=tip-previous;length=max(1,(delta.x()**2+delta.y()**2)**.5)
            direction=delta/length;normal=QPointF(-direction.y(),direction.x())
            self.canvas.scene().addPolygon(QPolygonF([tip,tip-direction*10+normal*4,tip-direction*10-normal*4]),QPen(color),color)
            if edge.label not in {'next','fallthrough'}:
                text=QGraphicsTextItem();text.setHtml('<span style="color:'+color.name()+';background-color:#101923">'+html.escape(edge.label[:80])+('…' if len(edge.label)>80 else '')+'</span>');text.setTextWidth(180);text.setFont(QFont('Segoe UI',8));text.setToolTip(edge.label);text.setZValue(1)
                point=path.pointAtPercent(.5);text.setPos(point.x()+6,point.y()-12);self.canvas.scene().addItem(text)
        self.canvas.scene().setSceneRect(self.canvas.scene().itemsBoundingRect().adjusted(-70,-60,80,60))
        self.search_cards(self.search.text())
        self.canvas.resetTransform()
        if self.nodes:self.select(next(iter(self.nodes)),True)

    def select(self,key,focus=False):
        if key not in self.nodes:return
        if self.selected_key in self.nodes:self.nodes[self.selected_key].setSelected(False)
        self.selected_key=key;self.nodes[key].setSelected(True)
        if focus:self.canvas.centerOn(self.nodes[key])

    def mark_command(self,command):
        for item in self.nodes.values():
            running=command in item.card.commands
            if running!=item.running:item.running=running;item.update()

    def fit(self):
        if self.nodes:self.canvas.fitInView(self.canvas.scene().sceneRect(),Qt.KeepAspectRatio)

    def focus_selected(self):
        if self.selected_key in self.nodes:
            self.canvas.resetTransform();self.canvas.centerOn(self.nodes[self.selected_key])

    def search_cards(self,text):
        query=text.casefold();self.matches=[];self.match_cursor=-1
        for key,item in self.nodes.items():
            item.match=bool(query) and query in (item.card.title+' '+item.card.body+' '+item.card.tooltip).casefold()
            if item.match:self.matches.append(key)
            item.update()

    def next_match(self):
        if self.matches:
            self.match_cursor=(self.match_cursor+1)%len(self.matches);key=self.matches[self.match_cursor];self.select(key,True);self.picked.emit(self.nodes[key].card)
