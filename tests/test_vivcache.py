"""Tests for the .viv workspace cache (generate-once, reuse)."""
import os, sys, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from viv_decomp import vivcache


class TestWorkspaceNaming:
    def test_name_under_ws_dir(self):
        p = vivcache.workspace_name_for("/usr/bin/true")
        assert p.startswith(vivcache.default_ws_dir())
        assert p.endswith(".viv")
        assert os.path.basename(p).startswith("true")

    def test_custom_ws_dir(self):
        p = vivcache.workspace_name_for("/usr/bin/true", ws_dir="/tmp/ws")
        assert p.startswith("/tmp/ws")

    def test_safe_basename(self):
        p = vivcache.workspace_name_for("/usr/bin/printf")
        assert os.path.basename(p).startswith("printf")


@pytest.mark.skipif(not os.path.exists("/usr/bin/true"),
                    reason="no real ELF")
def test_get_workspace_roundtrip():
    import vivisect
    vw = vivcache.get_workspace("/usr/bin/true",
                                ws_dir="/tmp/vivcache_test")
    assert vw is not None
    assert len(list(vw.getFunctions())) >= 1
    # second load uses cache (also proves file exists)
    assert os.path.exists(vivcache.workspace_name_for(
        "/usr/bin/true", ws_dir="/tmp/vivcache_test"))
