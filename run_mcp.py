"""Stdio MCP entry. This starts no GUI and calls no model service."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description='Saekano translation editor MCP server (stdio)')
    parser.add_argument('--usrdir',default=str(root.parent/'GAMEFILE/USRDIR'),help='Original read-only USRDIR')
    parser.add_argument('--workspace',required=True,help='Separate writable project/context/export folder')
    parser.add_argument('--project',default='translation.saekano.json',help='Workspace-relative project to reopen if present')
    parser.add_argument('--print-config',action='store_true',help='Print generic stdio MCP client configuration, then exit')
    parser.add_argument('--check',action='store_true',help='Load/check workspace and tool schemas, print status, then exit')
    args=parser.parse_args()
    if args.print_config:
        config=dict(command=sys.executable,args=[str(Path(__file__).resolve()),'--usrdir',str(Path(args.usrdir).expanduser().resolve()),
                                                '--workspace',str(Path(args.workspace).expanduser().resolve()),'--project',args.project],env={'PYTHONUTF8':'1'})
        print(json.dumps({'mcpServers':{'saekano-translator':config}},indent=2));return 0
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    try:
        from PySide6.QtGui import QGuiApplication
        font_app=QGuiApplication.instance() or QGuiApplication([])
        from editor.translation import TranslationWorkspace
        from editor.mcp_server import create_server,READ_TOOLS,WRITE_TOOLS
        workspace=TranslationWorkspace(args.usrdir,args.workspace,args.project);server=create_server(workspace)
        if args.check:
            print(json.dumps(dict(status=workspace.get_status(),tools=list(READ_TOOLS+WRITE_TOOLS)),ensure_ascii=False,indent=2));return 0
        server.run(transport='stdio');return 0
    except ImportError as error:
        print('MCP setup missing: run setup-mcp.ps1. '+str(error),file=sys.stderr);return 2
    except (ValueError,OSError,RuntimeError) as error:
        print('Saekano MCP: '+str(error),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
