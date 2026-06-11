"""Generate the PyInstaller version-info file for the frozen SMACC.exe (#116).

Writes the ``VSVersionInfo`` resource PyInstaller embeds via ``--version-file``,
so the exe's Properties dialog (and tools IT departments use to vet binaries)
show the product name, version, and publisher instead of nothing. The version is
read from ``smacc.__version__`` — the single source of truth — so the resource
can never drift from the release tag (the release workflow checks the tag against
the same attribute). Run by the release workflow before PyInstaller::

    uv run python tools/make_versionfile.py version_info.txt
"""

from __future__ import annotations

import argparse
from pathlib import Path

from smacc import __version__

_TEMPLATE = """\
VSVersionInfo(
    ffi=FixedFileInfo(
        filevers={vers_tuple},
        prodvers={vers_tuple},
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "Remington Mallett"),
                        StringStruct(
                            "FileDescription",
                            "Sleep Manipulation and Communication Clickything",
                        ),
                        StringStruct("FileVersion", "{version}"),
                        StringStruct("ProductName", "SMACC"),
                        StringStruct("ProductVersion", "{version}"),
                        StringStruct("OriginalFilename", "SMACC.exe"),
                        StringStruct(
                            "LegalCopyright", "Remington Mallett, GPL-3.0-or-later"
                        ),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)
"""


def version_tuple(version: str) -> tuple[int, int, int, int]:
    """``"0.1.0"`` → ``(0, 1, 0, 0)`` — the four-part numeric form VS_FIXEDFILEINFO needs."""
    parts = [int(part) for part in version.split(".")]
    return tuple(parts + [0] * (4 - len(parts)))[:4]  # type: ignore[return-value]


def render(version: str) -> str:
    """The version-file text for ``version`` (pure, for tests)."""
    return _TEMPLATE.format(version=version, vers_tuple=version_tuple(version))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", type=Path, help="path to write (e.g. version_info.txt)"
    )
    args = parser.parse_args()
    args.output.write_text(render(__version__), encoding="utf-8")
    print(f"Wrote VSVersionInfo for SMACC {__version__} to {args.output}")


if __name__ == "__main__":
    main()
