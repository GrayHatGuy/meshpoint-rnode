"""Detects stale compiled core modules left behind by older Meshpoint installs.

Versions before 0.7.0 shipped 11 compiled `.cpython-*.so` extension modules
alongside `.py` source in `src/{capture,decode,hal,transmit}/`. Python's
import machinery prefers `.so` over `.py` for the same module name, which
means a leftover binary from a prior install will silently shadow the
current source and freeze that module at the older behavior.

`scripts/install.sh` removes any stale binaries on every run. This module
is the runtime safety net for users who update with `git pull` outside the
installer, or who copy files in place during development.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CORE_MODULE_DIRS = ("capture", "decode", "hal", "transmit")
_SO_GLOB = "*.cpython-*.so"


class StaleSoChecker:
    """Scans the source tree for compiled extension modules and reports them."""

    def __init__(self, src_root: Path | None = None) -> None:
        self._root = src_root or Path(__file__).resolve().parent

    def find_stale(self) -> list[Path]:
        """Return all stale compiled extension files under known core dirs."""
        stale: list[Path] = []
        for sub in _CORE_MODULE_DIRS:
            target = self._root / sub
            if target.is_dir():
                stale.extend(target.glob(_SO_GLOB))
        return sorted(stale)

    def warn_if_stale(self) -> list[Path]:
        """Log a startup WARN if any stale binaries exist. Returns the list."""
        stale = self.find_stale()
        if not stale:
            return stale

        names = ", ".join(p.relative_to(self._root.parent).as_posix() for p in stale)
        logger.warning(
            "Stale compiled core modules detected (%d files): %s. These shadow "
            "the v0.7.0 Python source and freeze behavior at the prior version. "
            "Re-run sudo /opt/meshpoint/scripts/install.sh to remove them, or "
            "delete manually: find /opt/meshpoint/src -name '*.cpython-*.so' "
            "-delete",
            len(stale),
            names,
        )
        return stale


def warn_if_stale_so_files() -> list[Path]:
    """Convenience wrapper for callers that don't need the class instance."""
    return StaleSoChecker().warn_if_stale()
