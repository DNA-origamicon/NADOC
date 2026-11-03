"""Exercise process-wide GC policy in a child, never freeze the pytest worker."""
import subprocess
import sys


def test_bootstrap_excludes_startup_graph_but_keeps_later_cycles_collectible():
    result = subprocess.run([sys.executable, '-c', '''
import gc, sys, types, weakref
class Node: pass
startup = Node()
startup.cycle = startup
module = types.ModuleType('backend.api.main')
module.app = startup
sys.modules['backend.api.main'] = module
thresholds, enabled = gc.get_threshold(), gc.isenabled()
frozen = gc.get_freeze_count()
import server_bootstrap
assert gc.get_freeze_count() == frozen  # importing is inert
assert server_bootstrap.create_app() is startup
assert gc.get_freeze_count() > frozen
later = Node()
later.cycle = later
ref = weakref.ref(later)
assert server_bootstrap.create_app() is startup  # must not freeze again
del later
gc.collect()
assert ref() is None
assert gc.get_threshold() == thresholds
assert gc.isenabled() == enabled
'''], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
