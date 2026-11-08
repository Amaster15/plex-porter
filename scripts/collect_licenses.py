"""Collect redistributable runtime notices into a build artifact directory."""
from importlib import metadata
from pathlib import Path
import shutil
import sys

output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build/licenses")
output.mkdir(parents=True, exist_ok=True)
shutil.copy2("LICENSE", output / "Plex-Porter-MIT.txt")
for name in ("psutil", "certifi", "pyinstaller", "pyinstaller-hooks-contrib"):
    distribution = metadata.distribution(name)
    for relative in distribution.files or []:
        if any(word in relative.name.lower() for word in ("license", "copying")):
            source = Path(distribution.locate_file(relative))
            if source.is_file():
                shutil.copy2(source, output / (name + "-" + relative.name))
if sys.platform == "win32":
    base = Path(sys.base_prefix)
    for source in [base / "LICENSE.txt", *base.glob("tcl/*/license.terms")]:
        if source.is_file():
            shutil.copy2(source, output / (source.parent.name + "-" + source.name))
else:
    # Ubuntu build root: notices for the bundled Python/Tk and shared libraries.
    for source in Path("/usr/share/doc").glob("*/copyright"):
        if source.is_file():
            shutil.copy2(source, output / (source.parent.name + "-copyright.txt"))
print(f"Collected runtime notices in {output}")
