# Focused synthetic checks

These checks exercise editor reference repair, transactions, archive export,
translator context and command help using synthetic fixtures. No original game
assets or captured native evidence are distributed. Some optional checks skip
when the locally supplied game data or MCP dependencies are unavailable.

After setup, create the ignored scratch directory once:

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
```

Run the affected module, for example:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_document.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_game_export.py -v
```

Translator/MCP checks require `requirements-mcp.txt`. Run a focused check when
changing its boundary; do not replay a game or run unrelated suites for every edit.
