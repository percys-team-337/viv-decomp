"""Vivisect workspace (.viv) cache — generate once, reuse forever.

A ``.viv`` is a fully-analyzed Vivisect workspace saved to disk. Generating it
(via ``vivbin -B`` bulk mode, or ``vw.analyze()+saveWorkspace``) is the slow
part (seconds to minutes for large binaries); loading it is near-instant
(``loadWorkspace`` ~70ms).

This module caches the generated workspace so the decompiler/benchmark avoids
re-analyzing a binary on every run — the workflow Vivisect's ``-B`` bulk mode
provides: generate the workspace once, reuse it.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_WS_DIR = os.path.expanduser("~/.viv")


def default_ws_dir() -> str:
    return _DEFAULT_WS_DIR


def workspace_name_for(binary_path: str, ws_dir: Optional[str] = None) -> str:
    """Derive the ``.viv`` filename for a binary under ``ws_dir``."""
    ws_dir = ws_dir or default_ws_dir()
    os.makedirs(ws_dir, exist_ok=True)
    base = os.path.basename(binary_path)
    if base.endswith(".viv"):
        base = base[:-4]
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in base)
    return os.path.join(ws_dir, safe + ".viv")


def _run_vivbin(binary_path: str, viv_path: str,
                timeout: Optional[int] = None) -> str:
    """Generate a .viv with vivbin -B (bulk: load + analyze + save)."""
    cmd = [sys.executable, "-m", "vivisect.vivbin", "-B", "-o", viv_path,
           binary_path]
    logger.info("Generating .viv: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout or 600)
    if proc.returncode != 0:
        raise RuntimeError(
            f"vivbin -B failed ({proc.returncode}): {proc.stderr[-500:]}"
        )
    if not os.path.exists(viv_path):
        raise RuntimeError(f".viv was not created at {viv_path}")
    return viv_path


def get_workspace(binary_path: str, ws_dir: Optional[str] = None,
                  regenerate: bool = False, timeout: Optional[int] = None):
    """Return a loaded Vivisect workspace for ``binary_path``.

    Uses the .viv cache; generates one (via vivbin -B) on miss. Returns the
    loaded workspace object.
    """
    import vivisect

    viv_path = workspace_name_for(binary_path, ws_dir)
    if regenerate or not os.path.exists(viv_path):
        _run_vivbin(binary_path, viv_path, timeout=timeout)

    vw = vivisect.VivWorkspace()
    vw.loadWorkspace(viv_path)
    return vw
