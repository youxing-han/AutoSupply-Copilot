import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from planning_data import analyze_planning_bundle, build_planning_demo
from workflow_runtime import current_workflow_module, WorkflowContractError


class WorkflowRuntimeTests(unittest.TestCase):
    def test_warm_legacy_schema_is_refreshed_and_real_inventory_is_produced(self):
        # Isolated process models the actual long-running pre-upgrade server.
        script = """
import sys, types
sys.path.insert(0, 'agent')
from pathlib import Path
# Recreate the obsolete contract from source, without requiring local Git history.
source = Path('agent/agents.py').read_text(encoding='utf-8')
legacy = types.ModuleType('agents')
legacy.__file__ = str(__import__('pathlib').Path('agent/agents.py').resolve())
sys.modules['agents'] = legacy
exec(compile(source, legacy.__file__, 'exec'), legacy.__dict__)
for name in ('planning_input', 'inventory_projection', 'mitigation_candidates', 'mitigation_comparison'):
    legacy.SupplyChainState.__annotations__.pop(name, None)
legacy.DYNAMIC_INPUT_VERSION = 1
assert 'planning_input' not in legacy.SupplyChainState.__annotations__
from planning_data import analyze_planning_bundle, build_planning_demo
r = analyze_planning_bundle(build_planning_demo())
p = r['details']['SEN-001']['inventory_projection']
assert len(p['daily']) == 30
assert p['total_unmet_demand'] == 80
assert p['final_available'] == 480
assert [x['execution_status'] for x in r['details']['SEN-001']['execution_trace']] == ['SUCCESS'] * 4
print('real projection recovered')
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("real projection recovered", result.stdout)

    def test_missing_projection_is_internal_error_not_input_failure(self):
        module = current_workflow_module()
        with patch.object(module, "build_supply_chain_graph") as builder:
            builder.return_value.channels = {"planning_input", "inventory_projection", "mitigation_candidates", "mitigation_comparison"}
            builder.return_value.invoke.return_value = {"workflow_error": ""}
            with self.assertRaisesRegex(WorkflowContractError, "inventory_projection"):
                analyze_planning_bundle(build_planning_demo())

    def test_current_schema_is_not_reloaded_on_normal_rerun(self):
        with patch("workflow_runtime.importlib.reload", side_effect=AssertionError("must not reload current modules")):
            self.assertIn("inventory_projection", current_workflow_module().SupplyChainState.__annotations__)
