"""A source switch requires a new analysis without discarding independent drafts."""
from copy import deepcopy
from pathlib import Path
import base64
import sys
import unittest
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'))
from demo_data import build_rich_batch,build_rich_planning
from planning_data import planning_xlsx_bytes


class ResultSourceTests(unittest.TestCase):
    def app(self):return AppTest.from_file(ROOT/'app.py',default_timeout=30).run()

    def assert_waiting(self,a):
        self.assertEqual(list(a.exception),[])
        self.assertEqual(len(a.metric),0)
        self.assertFalse(any('以下保留上次' in x.value for x in a.warning))
        self.assertTrue(any('等待输入并运行分析' in x.value for x in [*a.info,*a.markdown]))
        self.assertFalse(any('quick_' in str(b.key) for b in a.button))
        self.assertEqual(a.session_state['chat_messages'],[])
        self.assertFalse(any('PDF' in b.label for b in a.get('download_button')))

    def test_single_source_switch_hides_reports_keeps_draft_and_needs_new_run(self):
        a=self.app();old=deepcopy(a.session_state['last_result'])
        a.session_state['chat_messages']=[dict(role='user',content='旧问题')]
        a.get_by_key('single_source').set_value('业务数据录入').run();self.assert_waiting(a)
        self.assertEqual(a.session_state['last_result'],old)
        for key,value in [('single_custom_code','USR-901'),('single_custom_name','模拟传感器'),('supplier','模拟供应商'),('current_inventory',100.),('daily_usage',20.),('lead_time_days',8.)]:
            a.get_by_key(key).set_value(value)
        a.run();self.assert_waiting(a)
        a.get_by_key('run_single_analysis').click().run()
        self.assertEqual(a.session_state['single_result_source'],'业务数据录入')
        self.assertEqual(a.session_state['last_result']['inventory_metrics']['stockout_gap'],3)
        self.assertEqual(len(a.metric),3)
        a.get_by_key('current_inventory').set_value(120.).run()
        self.assertTrue(any('以下保留上次' in w.value for w in a.warning))
        a.get_by_key('single_source').set_value('演示数据').run();self.assert_waiting(a)
        a.get_by_key('single_source').set_value('业务数据录入').run();self.assert_waiting(a)
        self.assertEqual(a.get_by_key('current_inventory').value,120.)
        a.get_by_key('run_single_analysis').click().run();self.assertEqual(len(a.metric),3)

    def test_batch_empty_invalid_and_imported_sources_cannot_show_old_report(self):
        a=self.app();a.get_by_key('analysis_mode').set_value('Excel / CSV 批量风险分析').run()
        a.get_by_key('start_batch_analysis').click().run();old=deepcopy(a.session_state['batch_result']['summary'])
        a.get_by_key('batch_search').set_value('BRG').run()
        a.get_by_key('batch_risk_filter').set_value('低风险').run()
        a.session_state['chat_messages']=[dict(role='user',content='旧问题')]
        a.get_by_key('batch_source').set_value('业务数据录入').run();self.assert_waiting(a)
        a.get_by_key('start_batch_analysis').click().run();self.assert_waiting(a)
        self.assertTrue(a.session_state['batch_result']['summary'].equals(old))
        a.get_by_key('batch_source').set_value('文件导入').run();self.assert_waiting(a)
        payload=build_rich_batch().iloc[:1].copy();payload.loc[0,'current_stock']=100;payload.loc[0,'daily_usage']=20;payload.loc[0,'lead_time_days']=8
        a.session_state['batch_upload']={'name':'reference.csv','data':base64.b64encode(payload.to_csv(index=False).encode('utf-8-sig')).decode()}
        a.run();self.assert_waiting(a)
        a.get_by_key('start_batch_analysis').click().run()
        self.assertEqual(a.session_state['batch_result_source'],'文件导入')
        self.assertEqual(a.session_state['batch_result']['total_count'],1)
        self.assertEqual(a.session_state['batch_result']['details']['SEN-001']['inventory_metrics']['stockout_gap'],3)
        self.assertEqual(a.get_by_key('batch_search').value,'')
        self.assertEqual(a.get_by_key('batch_risk_filter').value,'全部')
        self.assertEqual(a.get_by_key('batch_selected_sku').value,'SEN-001')
        self.assertTrue(len(a.metric)>0)
        a.get_by_key('batch_source').set_value('演示数据').run();self.assert_waiting(a)
        self.assertEqual(len(a.session_state['batch_draft_rows']),12)

    def test_dynamic_empty_invalid_and_imported_sources_require_new_analysis(self):
        a=self.app();a.get_by_key('analysis_mode').set_value('动态物料计划').run()
        a.get_by_key('run_planning_analysis').click().run();old=deepcopy(a.session_state['planning_analysis']['summary'])
        a.get_by_key('planning_search').set_value('BRG').run()
        a.session_state['chat_messages']=[dict(role='user',content='旧问题')]
        a.get_by_key('planning_source').set_value('业务数据录入').run();self.assert_waiting(a)
        a.get_by_key('run_planning_analysis').click().run();self.assert_waiting(a)
        self.assertTrue(a.session_state['planning_analysis']['summary'].equals(old))
        a.get_by_key('planning_source').set_value('文件导入').run();self.assert_waiting(a)
        data=planning_xlsx_bytes(build_rich_planning('2026-10-14',14),named_sheets=True)
        a.session_state['planning_upload']={'name':'plan.xlsx','data':base64.b64encode(data).decode()};a.run();self.assert_waiting(a)
        a.get_by_key('run_planning_analysis').click().run()
        self.assertEqual(a.session_state['planning_result_source'],'文件导入')
        self.assertEqual(a.session_state['planning_analysis']['bundle']['settings'][0]['horizon_days'],14)
        self.assertEqual(a.get_by_key('planning_search').value,'')
        self.assertTrue(len(a.metric)>0)
        a.get_by_key('planning_source').set_value('演示数据').run();self.assert_waiting(a)
        self.assertEqual(len(a.session_state['planning_draft']['parts']),12)

    def test_source_result_survives_mode_navigation_without_source_change(self):
        a=self.app()
        for mode,source_key,run_key,owner in [('Excel / CSV 批量风险分析','batch_source','start_batch_analysis','batch_result_source'),('动态物料计划','planning_source','run_planning_analysis','planning_result_source')]:
            a.get_by_key('analysis_mode').set_value(mode).run()
            a.get_by_key(run_key).click().run()
            a.get_by_key('analysis_mode').set_value('单零部件情景分析').run()
            a.get_by_key('analysis_mode').set_value(mode).run()
            self.assertEqual(a.session_state[owner],'演示数据')
            self.assertTrue(len(a.metric)>0)
            self.assertEqual(list(a.exception),[])


if __name__=='__main__':unittest.main()
