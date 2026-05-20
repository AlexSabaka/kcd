"""Git-backed snapshots for safe agentic editing.

We maintain a dedicated `.kcd/` git repo inside each KiCad project directory.
This is *separate* from any git the user already has on the project — we don't
want kcd's per-edit commits polluting their real history.

Layout::

    <project_root>/
        my_board.kicad_pro
        my_board.kicad_sch
        my_board.kicad_pcb
        .kcd/
            git-dir/           ← bare git dir, GIT_DIR points here
            work-tree -> ..    ← work tree is the project root

The trick: we use a separate `GIT_DIR` + `GIT_WORK_TREE` so kcd's git operations
don't see (or touch) any other `.git` directory in the project.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from kcd.core.project import Project


class SnapshotError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotInfo:
    """Metadata about a single snapshot commit."""

    ref: str          # full git SHA
    short: str        # short SHA
    message: str
    timestamp: str    # ISO 8601


class SnapshotStore:
    """Per-project snapshot store. Initialized lazily on first use."""

    def __init__(self, project: Project, dir_name: str = ".kcd") -> None:
        self.project = project
        self.dir_name = dir_name

    @property
    def git_dir(self) -> Path:
        return self.project.root / self.dir_name / "git-dir"

    @property
    def work_tree(self) -> Path:
        return self.project.root

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["GIT_DIR"] = str(self.git_dir)
        env["GIT_WORK_TREE"] = str(self.work_tree)
        # Quiet git's identity nag for snapshot commits
        env.setdefault("GIT_AUTHOR_NAME", "kcd")
        env.setdefault("GIT_AUTHOR_EMAIL", "kcd@localhost")
        env.setdefault("GIT_COMMITTER_NAME", "kcd")
        env.setdefault("GIT_COMMITTER_EMAIL", "kcd@localhost")
        return env

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = ["git", *args]
        return subprocess.run(
            cmd, env=self._env(), capture_output=True, text=True, check=check
        )

    def _ensure_init(self) -> None:
        if self.git_dir.exists() and (self.git_dir / "HEAD").exists():
            return
        self.git_dir.parent.mkdir(parents=True, exist_ok=True)
        # `git init --bare` must run without GIT_DIR/GIT_WORK_TREE set; otherwise
        # git rejects the work-tree override during init.
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ("GIT_DIR", "GIT_WORK_TREE")}
        subprocess.run(
            ["git", "init", "--bare", "--initial-branch=main", str(self.git_dir)],
            env=clean_env, capture_output=True, text=True, check=True,
        )
        # Write an exclude file so we don't snapshot ourselves
        info = self.git_dir / "info"
        info.mkdir(exist_ok=True)
        (info / "exclude").write_text(
            f"{self.dir_name}/\n"
            "*.bak\n"
            "*-cache/\n"
            "fp-info-cache\n"
            "_autosave-*\n"
        )
        # Create an empty initial commit so HEAD~1 makes sense later
        self._git("commit", "--allow-empty", "-m", "kcd: initial empty snapshot")

    def create(self, message: str) -> SnapshotInfo:
        """Stage all KiCad files and commit a snapshot. Returns the new commit info."""
        self._ensure_init()
        # Stage everything tracked + new files; .kcd/ is excluded above.
        self._git("add", "-A", check=True)
        # If nothing changed, allow-empty so the timeline still has the message.
        result = self._git("commit", "--allow-empty", "-m", message, check=True)
        sha = self._git("rev-parse", "HEAD").stdout.strip()
        return self._info_for(sha)

    def drop(self, ref: str) -> None:
        """Discard a snapshot created by `create()`, if it is still HEAD.

        Used to undo an auto-snapshot taken before a mutation that then
        failed: the pre-edit state was real, but a snapshot for an edit that
        never landed is just history noise. Moves the snapshot branch back
        one commit (`--soft`, so the working tree is untouched). A no-op
        when `ref` is no longer HEAD, so it can never clobber a newer
        snapshot.
        """
        if not (self.git_dir.exists() and (self.git_dir / "HEAD").exists()):
            return
        head = self._git("rev-parse", "HEAD").stdout.strip()
        if head != ref:
            return
        self._git("reset", "--soft", "HEAD~1")

    def restore(self, ref: str) -> SnapshotInfo:
        """Hard-reset the working tree to `ref`. Destructive within the project."""
        self._ensure_init()
        # Resolve the ref first (so bad refs fail before we wipe anything)
        resolved = self._git("rev-parse", "--verify", f"{ref}^{{commit}}").stdout.strip()
        self._git("reset", "--hard", resolved)
        return self._info_for(resolved)

    def list(self, limit: int = 20) -> list[SnapshotInfo]:
        """List the most recent snapshots, newest first."""
        if not self.git_dir.exists():
            return []
        out = self._git(
            "log",
            f"-n{limit}",
            "--pretty=format:%H%x09%h%x09%cI%x09%s",
        ).stdout
        infos: list[SnapshotInfo] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            sha, short, ts, msg = line.split("\t", 3)
            infos.append(SnapshotInfo(ref=sha, short=short, message=msg, timestamp=ts))
        return infos

    def diff(self, ref_a: str, ref_b: str | None = None) -> str:
        """Return a unified diff between two snapshots (or `ref_a` vs working tree)."""
        self._ensure_init()
        args = ["diff", ref_a]
        if ref_b:
            args.append(ref_b)
        return self._git(*args).stdout

    def _info_for(self, sha: str) -> SnapshotInfo:
        out = self._git(
            "show", "-s", f"--pretty=format:%H%x09%h%x09%cI%x09%s", sha
        ).stdout.strip()
        full, short, ts, msg = out.split("\t", 3)
        return SnapshotInfo(ref=full, short=short, message=msg, timestamp=ts)
