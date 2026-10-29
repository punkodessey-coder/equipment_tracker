#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m venv .buildenv
source .buildenv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -c "import flask, flask_sqlalchemy, flask_login, werkzeug, docx, reportlab, segno, openpyxl"
rm -rf build dist
pyinstaller --noconfirm --clean --windowed --name Tracker --collect-all flask --collect-all flask_sqlalchemy --collect-all flask_login --collect-all segno --collect-all reportlab --collect-all openpyxl launcher.py
printf '\nREADY: dist/Tracker/Tracker\n'
