"""Generate a PyInstaller version-info file for a frozen SMACC exe (#116).

Writes the ``VSVersionInfo`` resource PyInstaller embeds via ``--version-file``,
so the exe's Properties dialog (and tools IT departments use to vet binaries)
show the product name, version, and publisher instead of nothing. The version is
read from ``smacc.__version__`` — the single source of truth — so the resource
can never drift from the release tag (the release workflow checks the tag against
the same attribute). Run by the release workflow before PyInstaller, once per
exe (the optional EEG component, #136, is a second frozen exe)::

    uv run python tools/make_versionfile.py version_info.txt
    uv run python tools/make_versionfile.py version_info_eeg.txt \\
        --product SMACC-EEG --description "SMACC EEG Annotator"
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
                        StringStruct("FileDescription", "{description}"),
                        StringStruct("FileVersion", "{version}"),
                        StringStruct("ProductName", "{product}"),
                        StringStruct("ProductVersion", "{version}"),
                        StringStruct("OriginalFilename", "{product}.exe"),
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

_DEFAULT_DESCRIPTION = "Sleep Manipulation and Communication Clickything"


def version_tuple(version: str) -> tuple[int, int, int, int]:
    """``"0.1.0"`` → ``(0, 1, 0, 0)`` — the four-part numeric form VS_FIXEDFILEINFO needs.

    A pre-release suffix is dropped first (``"1.0.0-rc.1"`` → ``(1, 0, 0, 0)``):
    VS_FIXEDFILEINFO is numeric-only. The suffix is preserved in the string
    ``FileVersion``/``ProductVersion`` fields, which take arbitrary text.
    """
    core = version.split("-", 1)[0]
    parts = [int(part) for part in core.split(".")]
    return tuple(parts + [0] * (4 - len(parts)))[:4]  # type: ignore[return-value]


def render(
    version: str,
    product: str = "SMACC",
    description: str = _DEFAULT_DESCRIPTION,
) -> str:
    """The version-file text for one exe (pure, for tests)."""
    return _TEMPLATE.format(
        version=version,
        vers_tuple=version_tuple(version),
        product=product,
        description=description,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", type=Path, help="path to write (e.g. version_info.txt)"
    )
    parser.add_argument(
        "--product",
        default="SMACC",
        help="ProductName / OriginalFilename stem (e.g. SMACC-EEG)",
    )
    parser.add_argument(
        "--description",
        default=_DEFAULT_DESCRIPTION,
        help="FileDescription shown in the exe's Properties dialog",
    )
    args = parser.parse_args()
    args.output.write_text(
        render(__version__, args.product, args.description), encoding="utf-8"
    )
    print(f"Wrote VSVersionInfo for {args.product} {__version__} to {args.output}")


if __name__ == "__main__":
    main()
