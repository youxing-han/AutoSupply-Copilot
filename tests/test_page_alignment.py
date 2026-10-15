"""Screenshot regressions: visible controls and understandable compact results."""
from pathlib import Path
import sys
import unittest
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'))
from planning_data import build_interview_demo,analyze_planning_bundle
from planning_workspace import risk_overview_rows,analysis_totals


class RiskOverviewTests(unittest.TestCase):
    def test_zero_shortage_and_buffer_warning_are_not_conflated(self):
        analysis=analyze_planning_bundle(build_interview_demo(horizon_days=14))
        rows=risk_overview_rows(analysis)
        sen=next(r for r in rows if r['SKU']=='SEN-001')
        self.assertEqual(sen['累计未满足需求'],0)
        self.assertGreater(sen['安全库存预警天数'],0)
        self.assertEqual(sen['风险'],'MEDIUM')
        self.assertEqual(sum(r['累计未满足需求'] for r in rows),analysis_totals(analysis)['total_unmet_demand'])

    def test_positive_shortage_priority_uses_real_projection_and_names(self):
        analysis=analyze_planning_bundle(build_interview_demo(horizon_days=14,scenario='供应商交付延迟'))
        rows=risk_overview_rows(analysis)
        self.assertEqual(rows[0]['SKU'],'SEN-001')
        self.assertEqual(rows[0]['累计未满足需求'],80)
        for row in rows:
            result=analysis['details'][row['SKU']]
            self.assertEqual(row['名称'],result['selected_part']['part_name'])
            self.assertEqual(row['安全库存预警天数'],len(result['inventory_projection']['safety_warning_dates']))


class PageAlignmentTests(unittest.TestCase):
    def app(self):return AppTest.from_file(ROOT/'app.py',default_timeout=30).run()

    def test_zero_shortage_has_clear_message_instead_of_empty_plot(self):
        a=self.app();a.get_by_key('analysis_mode').set_value('动态物料计划').run()
        a.get_by_key('planning_data_pack').select('公式核验 · 5种物料').run()
        a.get_by_key('planning_horizon').set_value(14).run()
        a.get_by_key('load_planning_demo').click().run()
        a.get_by_key('run_planning_analysis').click().run()
        self.assertTrue(any('均未出现数量短缺' in m.value for m in a.success))
        self.assertTrue(any('安全库存预警' in m.value for m in a.markdown))
        with self.assertRaises(KeyError):a.get_by_key('planning_priority_chart')
        a.get_by_key('planning_scenario').select('供应商交付延迟').run()
        a.get_by_key('load_planning_demo').click().run()
        a.get_by_key('run_planning_analysis').click().run()
        self.assertIsNotNone(a.get_by_key('planning_priority_chart'))
        self.assertFalse(any('均未出现数量短缺' in m.value for m in a.success))
        self.assertEqual(list(a.exception),[])

    def test_all_input_preview_has_real_last_row_and_page_controls(self):
        a=self.app();a.get_by_key('analysis_mode').set_value('Excel / CSV 批量风险分析').run()
        first=next(m.value for m in a.markdown if 'batch_input_preview' in m.value)
        self.assertEqual(first.count('<tr>'),11)
        self.assertTrue(any('显示第1—10行，共12行' in m.value for m in a.caption))
        a.get_by_key('batch_preview_all').set_value(True).run()
        whole=next(m.value for m in a.markdown if 'batch_input_preview' in m.value)
        self.assertEqual(whole.count('<tr>'),11)
        self.assertIn('关键程度',whole)
        a.get_by_key('table_next_batch_input_preview').click().run()
        last=next(m.value for m in a.markdown if 'batch_input_preview' in m.value)
        self.assertEqual(last.count('<tr>'),3)
        self.assertIn(a.session_state['batch_draft_rows'][-1]['part_code'],last)
        self.assertTrue(a.get_by_key('table_next_batch_input_preview').disabled)
        self.assertEqual(list(a.exception),[])


if __name__=='__main__':unittest.main()
