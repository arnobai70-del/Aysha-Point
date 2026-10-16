"""The research workspace: `%AYESHA_HOME%/research/` with its registry, artifact store and folders.

    research/
      config.yaml   research settings (research only)
      research.db   research registry (never the live ayesha.db)
      raw/ normalized/ quality/ runs/ candidates/ exports/   content-addressed artifacts
      manifests/    one write-once manifest per frozen dataset
      backups/      rotating verified registry backups (+ pre-restore copies)
      logs/         sanitised worker logs
      jobs/         worker job and result files
"""

from __future__ import annotations

from functools import cached_property
from pathlib import Path

from ayesha.research.config import ResearchConfig, load, research_home
from ayesha.research.datasets.store import ArtifactStore
from ayesha.research.storage.db import ResearchDB


class Workspace:
    def __init__(self, cfg: ResearchConfig | None = None, root: Path | None = None) -> None:
        self.root = Path(root) if root else research_home()
        self.cfg = cfg or load(self.root / "config.yaml")

    @cached_property
    def db(self) -> ResearchDB:
        self.root.mkdir(parents=True, exist_ok=True)
        return ResearchDB(self.root / "research.db")

    @cached_property
    def store(self) -> ArtifactStore:
        return ArtifactStore(self.root)

    def dir(self, name: str) -> Path:
        d = self.root / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def manifests(self) -> Path:
        return self.dir("manifests")

    @property
    def backups(self) -> Path:
        return self.dir("backups")

    @property
    def logs(self) -> Path:
        return self.dir("logs")

    @property
    def jobs(self) -> Path:
        return self.dir("jobs")

    def close(self) -> None:
        if "db" in self.__dict__:
            self.db.close()
            del self.__dict__["db"]
