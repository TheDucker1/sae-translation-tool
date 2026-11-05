import argparse
import sys
from PySide6.QtWidgets import QApplication
from editor.ui import Window


def main():
    parser=argparse.ArgumentParser(description='Saekano translation editor, scenario preview and patched game-data export')
    parser.add_argument('--usrdir',help='Original USRDIR folder, opened read-only')
    parser.add_argument('--script',type=int,default=0,help='Initial script ID')
    args=parser.parse_args()
    app=QApplication(sys.argv[:1]);app.setStyle('Fusion')
    try:window=Window(args.usrdir,args.script)
    except Exception as e:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None,'Script Studio setup',str(e));return 1
    window.show();return app.exec()


if __name__=='__main__':raise SystemExit(main())
