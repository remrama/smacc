# PyInstaller bootstrap. The frozen build targets this file:
#   > pyinstaller entry.py --name SMACC --onefile --noconsole
# It must use an absolute import: PyInstaller runs its target as the top-level
# __main__, where smacc/__main__.py's relative imports would fail. For normal runs
# use `python -m smacc` or the `smacc` GUI script (see pyproject.toml).
from smacc.__main__ import main

if __name__ == "__main__":
    main()
