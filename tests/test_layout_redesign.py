"""Regression for editor event acknowledgement and the approved page workflow."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'))
import localized_ui
from demo_data import blank_part
from streamlit.testing.v1 import AppTest


class EditorSynchronizationTests(unittest.TestCase):
    def test_newest_component_event_is_echoed_before_callers_previous_draft(self):
        stale=[{'part_code':'OLD'}]
        newest={'rows':[{'part_code':'EDITED'},{'part_code':'NEW'}],'edit_id':3}
        with patch.object(localized_ui.st,'session_state',{'editor':newest}),patch.object(localized_ui,'_widget',return_value=newest) as widget:
            rows=localized_ui.editor(stale,[],key='editor')
        self.assertEqual(widget.call_args.kwargs['rows'],newest['rows'])
        self.assertEqual(widget.call_args.kwargs['editRevision'],3)
        self.assertEqual(rows,newest['rows'])
        self.assertEqual(stale,[{'part_code':'OLD'}])

    def test_empty_snapshot_is_a_real_delete_and_not_replaced_with_fallback(self):
        self.assertEqual(localized_ui.editor_rows({'rows':[]},[{'part_code':'OLD'}]),[])

    def test_retained_native_edits_do_not_mutate_workspace(self):
        rows=[{'quantity':80}]
        self.assertEqual(localized_ui.editor_rows({'edited_rows':{0:{'quantity':120}}},rows),[{'quantity':120}])
        self.assertEqual(rows,[{'quantity':80}])

    def test_risk_labels_have_distinct_classes_and_unknown_values_are_escaped(self):
        for key,level in [('HIGH','high'),('中','medium'),('低风险','low')]:
            self.assertIn('risk-'+level,localized_ui.risk_badge(key))
        self.assertEqual(localized_ui.risk_badge('<script>bad</script>'),'&lt;script&gt;bad&lt;/script&gt;')

    def test_table_only_marks_risk_columns_and_escapes_user_supplied_names(self):
        with patch.object(localized_ui.st,'markdown') as output:
            localized_ui.table([{'part_name':'<img onerror=bad>','risk_level':'HIGH','supplier':'HIGH'}])
        rendered=output.call_args.args[0]
        self.assertIn('&lt;img onerror=bad&gt;',rendered)
        self.assertEqual(rendered.count('risk-badge'),1)
        self.assertIn('高风险',rendered)


class ApprovedLayoutFlowTests(unittest.TestCase):
    def app(self):return AppTest.from_file(ROOT/'app.py',default_timeout=30).run()

    def test_demo_data_is_visible_and_runs_without_loading_or_uploading(self):
        a=self.app();a.get_by_key('analysis_mode').set_value('Excel / CSV 批量风险分析').run()
        self.assertEqual(len(a.session_state['batch_draft_rows']),12)
        self.assertTrue(any('batch_input_preview' in m.value for m in a.markdown))
        a.get_by_key('start_batch_analysis').click().run()
        self.assertEqual(a.session_state['batch_result']['success_count'],12)
        self.assertEqual(list(a.exception),[])

    def test_incomplete_new_rows_are_not_immediate_errors_and_cannot_replace_results(self):
        a=self.app();a.get_by_key('analysis_mode').set_value('Excel / CSV 批量风险分析').run()
        a.get_by_key('start_batch_analysis').click().run()
        before=deepcopy(a.session_state['batch_result']['summary'].to_dict('records'))
        a.get_by_key('batch_source').set_value('业务数据录入').run()
        key=f"batch_editor_{a.session_state['batch_revision']}"
        a.session_state[key]={'rows':[blank_part(),blank_part()],'edit_id':2};a.run()
        self.assertFalse(list(a.error))
        self.assertEqual(len(a.session_state['batch_draft_rows']),2)
        a.get_by_key('start_batch_analysis').click().run()
        self.assertTrue(list(a.error))
        self.assertEqual(a.session_state['batch_result']['summary'].to_dict('records'),before)
        self.assertEqual(list(a.exception),[])

    def test_dynamic_data_precedes_results_and_has_no_hidden_outer_data_tab(self):
        a=self.app();a.get_by_key('analysis_mode').set_value('动态物料计划').run()
        self.assertIn('物料与库存',[t.label for t in a.tabs])
        self.assertNotIn('数据准备',[t.label for t in a.tabs])
        self.assertTrue(any('planning_editor_parts_' in str(c.key) for c in a.get('component_instance')))
        a.get_by_key('run_planning_analysis').click().run()
        self.assertEqual(len(a.session_state['planning_analysis']['details']),12)
        self.assertIsNotNone(a.get_by_key('quick_planning_0'))
        self.assertEqual(list(a.exception),[])


if __name__=='__main__':unittest.main()
