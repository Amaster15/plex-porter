$ErrorActionPreference = 'Stop'
python -m pip install . pyinstaller
if ($LASTEXITCODE) { exit $LASTEXITCODE }
python scripts/collect_licenses.py
if ($LASTEXITCODE) { exit $LASTEXITCODE }
$licensePath = Join-Path $PWD "build/licenses"
python -m PyInstaller --noconfirm --clean --onefile --windowed --add-data "$licensePath;licenses" --name PlexPorter --distpath dist --workpath build/windows-freeze --specpath build run.py
if ($LASTEXITCODE) { exit $LASTEXITCODE }
