"""GUI-owned project/preview, served by optional localhost MCP transport."""
import asyncio
from concurrent.futures import Future
from copy import deepcopy
import hmac
import json
from pathlib import Path
import secrets
import socket
import threading
from typing import Any
from typing import Annotated
from pydantic import Field
import uuid
import uvicorn
from PySide6.QtCore import QObject,QThread,Signal,Slot
from PySide6.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,
    QPushButton,QPlainTextEdit,QFileDialog,QSpinBox)
from .translation import TranslationWorkspace,locked,digest
from .mcp_models import Id,Index
from .mcp_server import create_server,READ_TOOLS,VISUAL_TOOLS
from .engine import ROOT
from .routes import RouteBook

PREVIEW_WRITES={'preview_start','preview_step','preview_run','preview_rewind','preview_debug','focus_command'}


class OwnerDispatcher(QObject):
    requested=Signal(object)
    activity=Signal(str)

    def __init__(self,workspace,parent=None):
        super().__init__(parent);self.workspace=workspace;self.enabled=True;self.pending=set();self.guard=threading.Lock()
        self.requested.connect(self.execute)

    def call(self,fn,args,kwargs):
        with self.guard:
            if not self.enabled:raise ValueError('GUI MCP server is stopped')
        if QThread.currentThread()==self.thread():return self.workspace.invoke(fn,args,kwargs)
        future=Future()
        with self.guard:
            if not self.enabled:raise ValueError('GUI MCP server is stopped')
            self.pending.add(future)
        self.requested.emit((future,fn,args,kwargs))
        try:return future.result()
        finally:
            with self.guard:self.pending.discard(future)

    @Slot(object)
    def execute(self,request):
        future,fn,args,kwargs=request
        with self.guard:
            if future.done():return
            if not self.enabled:future.set_exception(ValueError('GUI MCP server stopped before request execution'));return
            future.set_running_or_notify_cancel()
        try:
            result=self.workspace.invoke(fn,args,kwargs)
            self.activity.emit(fn.__name__+': accepted');future.set_result(deepcopy(result))
        except Exception as error:
            self.activity.emit(fn.__name__+': rejected — '+str(error)[:400]);future.set_exception(error)

    def close(self):
        with self.guard:
            self.enabled=False
            for future in tuple(self.pending):
                if not future.running() and not future.done():future.set_exception(ValueError('GUI MCP server stopped'))


class GuiWorkspace(TranslationWorkspace):
    live=True

    def __init__(self,window,workspace):
        self.window=window
        self.initialize(window.project,window.session,workspace,load_saved=False)
        self._seen_project=None;self._seen_revision=None;self.export_status=None
        self.live_state_check=self.check_live_state
        self.sync()

    def remember_gui_file(self):
        path=self.window.project_path;stamp=self.window.project_disk_hash
        if not path or not stamp:return
        path=Path(path).resolve()
        if path.is_relative_to(self.workspace):
            self.project_file=path.relative_to(self.workspace).as_posix();self._disk_hashes[str(path)]=stamp

    def sync(self):
        w=self.window
        if w.project is None:raise ValueError('Live GUI project is not available')
        if self._seen_project is not w.project or self._seen_revision!=w.project.revision:
            self._cache={};self.project=w.project
            if self._seen_project is not w.project:
                self._baseline={c.uid:c for s in w.project.baseline.values() for c in s.commands}
                self.remember_gui_file()
            self._seen_project=w.project;self._seen_revision=w.project.revision
        self._runtime=w.session
        self._preview_revision=w.preview_revision if w.view and w.preview_available(False) else None

    def check_live_state(self,expected):
        if expected!=self.window.interaction_revision:raise ValueError('Stale or missing expected_state_revision; read get_status/preview_view and retry. Pause playback before controlling preview.')

    def gui_state(self):
        w=self.window;index=w.selected();uid=None
        if w.script_id in self.project.scripts and index is not None and index<len(self.project.scripts[w.script_id].commands):uid=self.project.scripts[w.script_id].commands[index].uid
        return dict(mode='live_gui',state_revision=w.interaction_revision,
            gui=dict(script_id=w.script_id,command_id=uid,playing=w.playing,modal=QApplication.activeModalWidget() is not None,
                     exporting=w.export_worker is not None),export=deepcopy(self.export_status))

    @locked
    def get_status(self)->dict[str,Any]:
        """Read live project revision, GUI selection/playback, state_revision, policy and export-job status."""
        result=super().get_status();result.update(self.gui_state());result['note']='Live GUI project/preview. Project edits use expected_revision; preview/navigation uses expected_state_revision.'
        return result

    def preview_packet(self):
        result=super().preview_packet();result['state_revision']=self.window.interaction_revision;return result

    @locked
    def pause_preview(self)->dict[str,Any]:
        """Pause the shared GUI playback and obtain a stable state_revision before preview/navigation requests."""
        self.window.pause();return self.get_status()

    @locked
    def focus_command(self,script_id:Index,command_id:Id,expected_state_revision:Id)->dict[str,Any]:
        """Focus a script/command in the actual GUI for inspection. Does not splice/reset scenario state."""
        self.check_live_state(expected_state_revision);index,_=self.command(script_id,command_id);w=self.window
        if w.script_id!=script_id:
            w.install_script(script_id);w.selector.blockSignals(True);w.selector.setCurrentIndex(w.selector.findData(script_id));w.selector.blockSignals(False)
        w.select_command(index);w.statusBar().showMessage(f'Agent inspection: file {script_id} / #{index}; scenario state unchanged.')
        return self.get_status()

    @locked
    def export_game_copy(self,folder:Annotated[str,Field(min_length=1,max_length=240)],expected_revision:Id)->dict[str,Any]:
        """Start a separate background game-copy export in the GUI; inspect get_status.export for completion/cancellation."""
        self.check_revision(expected_revision);path=self.path(folder)
        if path.exists() and (not path.is_dir() or any(path.iterdir())):raise ValueError('Export destination must be new or empty')
        if not path.parent.is_dir():raise ValueError('Export parent directory must exist')
        job=uuid.uuid4().hex;self.export_status=dict(job=job,state='running',path=str(path))
        try:self.window.start_export(str(path),remote=True)
        except Exception as error:
            self.export_status.update(state='failed',error=str(error));raise
        return dict(revision=self.project.revision,export=deepcopy(self.export_status))

    def invoke(self,fn,args,kwargs):
        """Only called on the Qt owner thread; the GUI and agent cannot interleave a commit."""
        self.sync();name=fn.__name__;w=self.window;write=name not in READ_TOOLS
        if name in VISUAL_TOOLS and not w.centralWidget().isEnabled():
            raise ValueError('GUI is loading/changing its game source; retry visual reads when loading finishes')
        if write and (QApplication.activeModalWidget() is not None or w.export_worker is not None or not w.centralWidget().isEnabled()):
            raise ValueError('GUI busy with a dialog/loading/export; request rejected without changes. Retry after it finishes.')
        if name in PREVIEW_WRITES and w.playing:raise ValueError('Shared preview is playing; call pause_preview, then use its state_revision')
        previous=self.project;revision=previous.revision;scenario=previous.scenario_key();sid=w.script_id
        result=fn(*args,**kwargs)
        if self.project is not previous or self.project.revision!=revision:
            w.project=self.project
            changed=result.get('applied') or result.get('changes') or []
            if changed:sid=changed[0]['script_id']
            uid=changed[0]['command_id'] if changed else None
            if sid not in self.project.scripts:sid=min(self.project.scripts)
            if self.project.scenario_key()==scenario:w.textures_edited(revision)
            else:w.edited(sid,uid,known_valid=name in {'apply_translations','apply_text_cleanup','edit_commands','load_project'})
            self._cache={}
            w.statusBar().showMessage('Agent '+name+' applied to the live project; shared Undo is available.')
        elif name.startswith('preview_') and name!='preview_view':
            if name=='preview_start':w.routes=RouteBook();w.rewind_points=[0]
            w.target=None;w.seek_origin=None;w.cancel_seek.hide();w.preview_revision=self.project.revision
            w.state_origin='Shared MCP scenario';w.update_view(w.session.call('view'))
            if w.follow.isChecked() and w.script_id==w.session.sid:w.select_command(w.session.pc)
        if name in {'save_project','load_project'}:
            path=self.path(self.project_file);w.project_path=str(path);w.project_disk_hash=self._disk_hashes.get(str(path))
            w.setWindowTitle('Saekano Script Studio — '+path.name)
        self.sync()
        if isinstance(result,dict):
            result['state_revision']=w.interaction_revision
        return result


class BearerApp:
    def __init__(self,app,token):self.app=app;self.token=token
    async def __call__(self,scope,receive,send):
        if scope['type']=='http':
            headers=dict(scope.get('headers',[]));auth=headers.get(b'authorization',b'')
            status=403 if b'origin' in headers else 401 if not hmac.compare_digest(auth,('Bearer '+self.token).encode()) else 0
            if status:
                await send(dict(type='http.response.start',status=status,headers=[(b'content-type',b'application/json'),(b'www-authenticate',b'Bearer')]))
                await send(dict(type='http.response.body',body=b'{"error":"Local MCP authorization required"}'));return
        await self.app(scope,receive,send)


class LiveServer(QThread):
    ready=Signal(str)
    failed=Signal(str)

    def __init__(self,workspace,dispatcher,port=0,parent=None):
        super().__init__(parent);self.workspace=workspace;self.dispatcher=dispatcher;self.token=secrets.token_urlsafe(32)
        self.socket=socket.socket();self.socket.bind(('127.0.0.1',port));self.socket.listen(128)
        self.url=f'http://127.0.0.1:{self.socket.getsockname()[1]}/mcp';self.server=None;self.stopping=False

    def run(self):
        try:
            mcp=create_server(self.workspace,self.dispatcher.call)
            app=BearerApp(mcp.streamable_http_app(json_response=True,host='127.0.0.1',max_sessions=16),self.token)
            self.server=uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False,timeout_graceful_shutdown=1))
            async def serve():
                task=asyncio.create_task(self.server.serve(sockets=[self.socket]))
                while not self.server.started and not task.done():
                    if self.stopping:self.server.should_exit=True
                    await asyncio.sleep(.01)
                if not self.stopping and self.server.started:self.ready.emit(self.url)
                await task
            if self.stopping:self.server.should_exit=True
            asyncio.run(serve())
        except Exception as error:self.failed.emit(str(error))
        finally:self.socket.close()

    def stop(self):
        self.stopping=True;self.dispatcher.close()
        if self.server:self.server.should_exit=True

    def client_config(self):return {'mcpServers':{'saekano-live':{'url':self.url,'headers':{'Authorization':'Bearer '+self.token}}}}


class McpPanel(QDialog):
    def __init__(self,window):
        super().__init__(window);self.owner=window;self.worker=None;self.dispatcher=None
        self.setWindowTitle('Live translation MCP');self.resize(650,450);layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Agents share this GUI project and preview. Connections are local to this computer.'))
        row=QHBoxLayout();self.folder=QLineEdit(str(ROOT/'.local/live-translation'));row.addWidget(self.folder)
        self.browse_button=QPushButton('Workspace…');self.browse_button.clicked.connect(self.browse);row.addWidget(self.browse_button);layout.addLayout(row)
        row=QHBoxLayout();row.addWidget(QLabel('Port (0 = automatic)'));self.port=QSpinBox();self.port.setRange(0,65535);row.addWidget(self.port)
        self.start_button=QPushButton('Start MCP');self.start_button.clicked.connect(self.start);row.addWidget(self.start_button)
        self.stop_button=QPushButton('Stop MCP');self.stop_button.clicked.connect(self.stop);self.stop_button.setEnabled(False);row.addWidget(self.stop_button);layout.addLayout(row)
        self.status=QLabel('Stopped');layout.addWidget(self.status)
        self.config=QPlainTextEdit();self.config.setReadOnly(True);self.config.setMaximumHeight(150);layout.addWidget(self.config)
        copy=QPushButton('Copy connection configuration');copy.clicked.connect(lambda:QApplication.clipboard().setText(self.config.toPlainText()));layout.addWidget(copy)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.document().setMaximumBlockCount(100);layout.addWidget(self.log)
        layout.addWidget(QLabel('Closing this panel leaves MCP running. Use Stop MCP or close the editor to stop it.'))

    def browse(self):
        path=QFileDialog.getExistingDirectory(self,'Choose separate agent workspace',self.folder.text())
        if path:self.folder.setText(path)

    def start(self):
        if self.worker:return
        if not self.owner.centralWidget().isEnabled():self.status.setText('Wait for loading/export to finish.');return
        if not self.owner.ensure_project():return
        if self.owner.export_worker is not None:self.status.setText('Wait for the active export.');return
        try:
            self.owner.pause();workspace=GuiWorkspace(self.owner,self.folder.text());self.dispatcher=OwnerDispatcher(workspace,self)
            self.dispatcher.activity.connect(self.log.appendPlainText)
            self.worker=LiveServer(workspace,self.dispatcher,self.port.value(),self)
            self.worker.ready.connect(self.serving);self.worker.failed.connect(self.failed);self.worker.finished.connect(self.server_finished)
            self.owner.mcp_workspace=workspace;self.start_button.setEnabled(False);self.stop_button.setEnabled(True)
            self.folder.setEnabled(False);self.browse_button.setEnabled(False);self.port.setEnabled(False);self.status.setText('Starting…');self.worker.start()
        except Exception as error:
            self.owner.mcp_workspace=None;self.status.setText('Could not start: '+str(error))
            if self.dispatcher:self.dispatcher.close()

    def serving(self,url):
        self.owner.mcp_button.setText('MCP: On');self.status.setText('Serving '+url);self.config.setPlainText(json.dumps(self.worker.client_config(),indent=2))

    def failed(self,message):self.status.setText('MCP error: '+message);self.log.appendPlainText(message)

    def stop(self):
        if self.worker:self.status.setText('Stopping…');self.stop_button.setEnabled(False);self.worker.stop()

    def server_finished(self):
        worker=self.worker;self.worker=None;self.owner.mcp_workspace=None
        if self.dispatcher:self.dispatcher.close();self.dispatcher.deleteLater()
        self.owner.mcp_button.setText('MCP…');self.start_button.setEnabled(True);self.stop_button.setEnabled(False);self.folder.setEnabled(True);self.browse_button.setEnabled(True);self.port.setEnabled(True)
        self.config.clear();self.status.setText('Stopped; previous connection token is no longer valid.')
        if worker:worker.deleteLater()

    def shutdown(self):
        if not self.worker:return True
        self.stop();return self.worker.wait(3000)
