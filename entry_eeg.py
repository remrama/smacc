# PyInstaller bootstrap for the optional EEG review component (#136):
#   > pyinstaller entry_eeg.py --name SMACC-EEG --onefile --noconsole
# Same absolute-import requirement as entry.py: PyInstaller runs its target as
# the top-level __main__, where smacc/eeg/__main__.py's relative imports would
# fail. For normal runs use `python -m smacc.eeg`.
from smacc.eeg.__main__ import main

if __name__ == "__main__":
    main()
