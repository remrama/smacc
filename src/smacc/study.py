"""A study workspace: a folder that owns its config, cues, and session runs.

A *study* is the unit a lab configures once and reuses. Each study is a folder
holding its portable ``study.smacc`` config, its own ``cues/`` sounds, and the
``sessions/`` runs recorded under it::

    <study-root>/
      study.smacc        # the config (smacc.settings); cue paths relative to here
      cues/              # this study's sound files (demo cues seeded on create)
      sessions/
        smacc-<ts>/      # one per run (smacc.session.make_session_dir)

Multiple studies live side by side under ``$SMACC_DIRECTORY/studies/`` so a lab
running several protocols keeps each one's cues and runs separate. Because the
``.smacc`` stores cue paths relative to itself when they sit alongside it (see
:func:`smacc.settings.relativize_paths`), a whole study folder is portable as-is.
"""

from __future__ import annotations

from pathlib import Path

from . import utils
from .paths import BUNDLED_CUES_DIR

# The fixed config filename at a study's root, so a study folder auto-loads.
CONFIG_NAME = "study.smacc"
# The auto-managed study used when no specific one is chosen, giving a zero-config
# user a working setup out of the box (seeded with demo cues on first run).
DEFAULT_STUDY_NAME = "default"


class Study:
    """A study workspace rooted at a folder (config + cues + sessions)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def name(self) -> str:
        """The study's display name (its folder name)."""
        return self.root.name

    @property
    def config_path(self) -> Path:
        """The study's ``study.smacc`` config file (may not exist yet)."""
        return self.root / CONFIG_NAME

    @property
    def cues_dir(self) -> Path:
        """The study's own cues folder."""
        return self.root / "cues"

    @property
    def sessions_dir(self) -> Path:
        """The folder holding this study's session runs."""
        return self.root / "sessions"

    def has_config(self) -> bool:
        """True when a ``study.smacc`` config exists at the study root."""
        return self.config_path.is_file()

    def ensure_dirs(self) -> None:
        """Create the study's cues/ and sessions/ subfolders if absent (idempotent)."""
        self.cues_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def open(cls, root: str | Path) -> Study:
        """Open an existing study folder, creating its subfolders if needed.

        Lenient: a folder without a ``study.smacc`` is still a valid (unconfigured)
        study — the config is written when the user saves one.
        """
        study = cls(root)
        study.ensure_dirs()
        return study

    @classmethod
    def create(cls, parent: str | Path, name: str) -> Study:
        """Scaffold a new study folder under ``parent`` and seed its demo cues.

        Builds ``<parent>/<name>/`` with ``cues/`` (seeded with the demo cues so
        there is always something to test with) and ``sessions/``. Does not write a
        ``study.smacc`` — the study designer saves the config.

        Raises:
            FileExistsError: if the study folder already exists.
        """
        root = Path(parent) / name
        if root.exists():
            raise FileExistsError(f"A study folder already exists: {root}")
        study = cls(root)
        study.ensure_dirs()
        utils.seed_demo_cues(study.cues_dir, BUNDLED_CUES_DIR)
        return study


def default_study(studies_dir: str | Path) -> Study:
    """Return the auto-managed ``default`` study, scaffolding it on first use.

    Gives a zero-config user a working study out of the box (demo cues seeded), so
    SMACC behaves as before but inside the study-folder layout. Opens the existing
    folder on later launches rather than re-seeding.
    """
    root = Path(studies_dir) / DEFAULT_STUDY_NAME
    if root.exists():
        return Study.open(root)
    return Study.create(studies_dir, DEFAULT_STUDY_NAME)
