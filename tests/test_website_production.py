"""Business and UI acceptance for the actual three-mode Chinese website."""
import base64
from copy import deepcopy
from datetime import timedelta
import sys
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch
import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'))
from demo_data import RICH_SCENARIOS,build_rich_planning,build_rich_batch,blank_part,custom_plan
from planning_data import validate_planning_bundle,analyze_planning_bundle,planning_xlsx_bytes,read_planning_xlsx
from localized_ui import upload_value,zh_text,user_error
from inventory_planning import day
import assistant
from agents import create_initial_state,build_supply_chain_graph
from supply_data import get_scenario_part


class RichBusinessDataTests(unittest.TestCase):
    def test_chinese_excel_status_values_normalize_to_existing_contract(self):
        b=build_rich_planning(horizon_days=14)
        for p in b['parts']:p.update(supplier_status='正常交付',criticality='高')
        for s in b['suppliers']:s.update(status='正常交付',qualified='是')
        for o in b['orders']:o['status']='已确认'
        normalized=validate_planning_bundle(b)
        self.assertTrue(all(p['criticality']=='HIGH' for p in normalized['parts']))
        self.assertTrue(all(o['status']=='CONFIRMED' for o in normalized['orders']))

    def test_chinese_messages_keep_identifiers_intact(self):
        self.assertIn('有效年月日',user_error('arrival_date: expected YYYY-MM-DD date'))
        self.assertEqual(zh_text('USR-HIGH-001 为 HIGH'),'USR-HIGH-001 为 高')

    def test_all_scenes_12_skus_complete_days_and_unique_pos(self):
        for scene in RICH_SCENARIOS:
            for horizon in (1,14,30,90):
                with self.subTest(scene=scene,horizon=horizon):
                    b=validate_planning_bundle(build_rich_planning('2026-10-14',horizon,scene))
                    self.assertEqual(len(b['parts']),12)
                    self.assertEqual(len(b['demands']),12*horizon)
                    self.assertEqual(len({o['po_id'] for o in b['orders']}),len(b['orders']))

    def test_scenario_changes_are_attributable_and_horizon_does_not_add_orders(self):
        base=build_rich_planning('2026-10-14',30)
        for scene in RICH_SCENARIOS:
            b=build_rich_planning('2026-10-14',30,scene)
            self.assertEqual([p['current_stock'] for p in b['parts']],[p['current_stock'] for p in base['parts']])
            self.assertEqual([o['open_quantity'] for o in b['orders']],[o['open_quantity'] for o in base['orders']])
            if scene not in ('生产需求激增','周末检修'):self.assertEqual(b['demands'],base['demands'])
            self.assertEqual(b['orders'],build_rich_planning('2026-10-14',14,scene)['orders'])

    def test_reference_excel_round_trip_preserves_all_computed_results(self):
        for scene in RICH_SCENARIOS:
            b=build_rich_planning('2026-10-14',30,scene)
            restored=read_planning_xlsx(planning_xlsx_bytes(b,named_sheets=True))
            a,c=analyze_planning_bundle(b),analyze_planning_bundle(restored)
            self.assertEqual(a['summary'].to_dict('records'),c['summary'].to_dict('records'))
            for sku in a['details']:self.assertEqual(a['details'][sku]['inventory_projection'],c['details'][sku]['inventory_projection'])

    def test_curves_have_receipt_driven_rises_and_demand_driven_falls(self):
        a=analyze_planning_bundle(build_rich_planning('2026-10-14',30))
        for result in a['details'].values():
            daily=result['inventory_projection']['daily']
            self.assertTrue(any(b['closing_available']>a['closing_available'] for a,b in zip(daily,daily[1:])))
            self.assertTrue(any(b['closing_available']<a['closing_available'] for a,b in zip(daily,daily[1:])))
            for d in daily:
                self.assertEqual(d['opening_available']+d['confirmed_receipts'],d['satisfied_demand']+d['closing_available'])

    def test_upload_decodes_actual_workbook_and_rejects_oversize(self):
        content=planning_xlsx_bytes(build_rich_planning(horizon_days=14),named_sheets=True)
        uploaded=upload_value({'name':'demo.xlsx','data':base64.b64encode(content).decode()})
        self.assertEqual(len(read_planning_xlsx(uploaded.getvalue())['parts']),12)
        with self.assertRaises(ValueError):upload_value({'name':'large.xlsx','data':base64.b64encode(b'x'*(10*1024*1024+1)).decode()})


class ProductionWorkflowTests(unittest.TestCase):
    def test_warm_server_adopts_new_ui_even_when_graph_schema_is_unchanged(self):
        script="""
import sys, types
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'agent'))
import workflow_runtime
workflow_runtime.WORKFLOW_RUNTIME_VERSION=4
workflow_runtime.current_planning_ui=lambda:types.SimpleNamespace(render_planning_mode=lambda *a:None)
from streamlit.testing.v1 import AppTest
a=AppTest.from_file(Path.cwd()/'app.py',default_timeout=30).run()
a.get_by_key('analysis_mode').set_value('动态物料计划').run()
assert not list(a.exception)
assert a.get_by_key('planning_source').value=='演示数据'
assert len(a.session_state['planning_draft']['parts'])==12
assert workflow_runtime.WORKFLOW_RUNTIME_VERSION==6
"""
        completed=subprocess.run([sys.executable,'-c',script],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=45)
        self.assertEqual(completed.returncode,0,completed.stderr)

    def app(self):return AppTest.from_file(ROOT/'app.py',default_timeout=30).run()
    def assert_clean(self,a):self.assertEqual([e.value for e in a.exception],[])

    def test_single_custom_input_is_independent_and_needs_explicit_run(self):
        a=self.app();before=deepcopy(a.session_state['last_result'])
        a.get_by_key('single_source').set_value('业务数据录入').run()
        self.assertEqual(a.get_by_key('current_inventory').value,0)
        a.get_by_key('single_custom_code').set_value('USR-900').run()
        a.get_by_key('single_custom_name').set_value('自定义连接件').run()
        a.get_by_key('supplier').set_value('用户填写的模拟供应商').run()
        a.get_by_key('current_inventory').set_value(600.).run()
        a.get_by_key('daily_usage').set_value(100.).run()
        a.get_by_key('lead_time_days').set_value(8.).run()
        self.assertEqual(a.session_state['last_result'],before)
        a.get_by_key('run_single_analysis').click().run()
        result=a.session_state['last_result']
        self.assertEqual(result['selected_part']['part_code'],'USR-900')
        self.assertEqual(result['inventory_metrics']['stockout_gap'],2)
        self.assertEqual(result['scenario'],'自行填写业务数据')
        snapshot=deepcopy(a.session_state['last_analyzed_input'])
        a.get_by_key('single_custom_code').set_value('USR-OTHER').run()
        import app as dashboard
        with patch.object(dashboard.st,'session_state',{}):
            original=dashboard._build_selected_part(snapshot)
        self.assertEqual(original['part_code'],'USR-900')
        self.assert_clean(a)

    def test_dynamic_custom_source_generates_real_daily_demand_and_retains_draft(self):
        a=self.app();a.get_by_key('analysis_mode').set_value('动态物料计划').run()
        self.assertEqual(len(a.session_state['planning_draft']['parts']),12)
        a.get_by_key('planning_source').set_value('业务数据录入').run()
        self.assertEqual(a.session_state['planning_draft']['parts'],[])
        a.get_by_key('planning_horizon').set_value(14).run()
        p=blank_part();p.update(part_code='USR-900',part_name='自定义连接件',supplier='模拟来源',current_stock=800,daily_usage=80,lead_time_days=7)
        revision=a.session_state['planning_workspace']['revision']
        a.session_state[f'planning_editor_parts_{revision}']={'rows':[p]};a.run()
        a.get_by_key('generate_custom_demands').click().run()
        self.assertEqual(len(a.session_state['planning_draft']['demands']),14)
        self.assertTrue(all(r['quantity']==0 for r in a.session_state['planning_draft']['demands']))
        revision=a.session_state['planning_workspace']['revision']
        rows=deepcopy(a.session_state['planning_draft']['demands'])
        for row in rows:row['quantity']=80
        a.session_state[f'planning_editor_demands_{revision}']={'rows':rows,'edit_id':1};a.run()
        a.get_by_key('custom_suppliers_qualified').check().run()
        a.get_by_key('run_planning_analysis').click().run()
        result=a.session_state['planning_analysis']['details']['USR-900']['inventory_projection']
        self.assertEqual(result['total_unmet_demand'],320)
        a.get_by_key('planning_source').set_value('演示数据').run()
        a.get_by_key('planning_source').set_value('业务数据录入').run()
        self.assertEqual(a.session_state['planning_draft']['parts'][0]['part_code'],'USR-900')
        self.assertTrue(a.get_by_key('custom_suppliers_qualified').value)
        self.assert_clean(a)

    def test_imported_batch_selection_survives_switching_modes(self):
        a=self.app()
        a.get_by_key('analysis_mode').set_value('Excel / CSV 批量风险分析').run()
        payload=build_rich_batch().to_csv(index=False).encode('utf-8-sig')
        a.session_state['batch_upload']={'name':'reference.csv','data':base64.b64encode(payload).decode()}
        a.get_by_key('batch_source').set_value('文件导入').run()
        a.get_by_key('start_batch_analysis').click().run()
        a.get_by_key('batch_selected_sku').select('BRG-002').run()
        a.get_by_key('analysis_mode').set_value('单零部件情景分析').run()
        a.get_by_key('analysis_mode').set_value('Excel / CSV 批量风险分析').run()
        self.assertEqual(a.get_by_key('batch_selected_sku').value,'BRG-002')
        self.assert_clean(a)

    def test_batch_custom_rows_are_validated_and_computed(self):
        a=self.app();a.get_by_key('analysis_mode').set_value('Excel / CSV 批量风险分析').run()
        a.get_by_key('batch_source').set_value('业务数据录入').run()
        p=blank_part();p.update(part_code='USR-901',part_name='定制轴承',supplier='模拟轴承供应商',current_stock=100,daily_usage=20,lead_time_days=8)
        revision=a.session_state['batch_revision'];a.session_state[f'batch_editor_{revision}']={'rows':[p]};a.run()
        a.get_by_key('start_batch_analysis').click().run()
        result=a.session_state['batch_result']['details']['USR-901']
        self.assertEqual(result['inventory_metrics']['stockout_gap'],3)
        self.assertEqual(result['replenishment_decision']['recommended_order_qty'],120)
        self.assert_clean(a)


class AssistantRecoveryTests(unittest.TestCase):
    def test_rejected_numeric_prose_recovers_only_with_verified_json_keys(self):
        result=build_supply_chain_graph().invoke(create_initial_state('Supplier Delay',get_scenario_part('Supplier Delay','SEN-001')))
        context=assistant.build_assistant_context('single',single_result=result)
        class Fake:
            def __init__(self):self.calls=0
            def invoke(self,prompt):
                self.calls+=1
                return '采购99999件。' if self.calls==1 else '{"explanation_keys":["risk","quantity"]}'
        fake=Fake()
        with patch.object(assistant,'_create_ollama_llm',return_value=fake):answer=assistant.answer_supply_chain_question('为什么缺料？',context)
        self.assertEqual(fake.calls,2)
        self.assertNotIn('99999',answer)
        self.assertIn('560',answer)
        self.assertNotIn('HIGH',zh_text(answer))

    def test_unknown_retry_key_still_rejects_unverified_output(self):
        result=build_supply_chain_graph().invoke(create_initial_state('Supplier Delay',get_scenario_part('Supplier Delay','SEN-001')))
        context=assistant.build_assistant_context('single',single_result=result)
        class Fake:
            def invoke(self,prompt):return '已下单100件'
        with patch.object(assistant,'_create_ollama_llm',return_value=Fake()):
            with self.assertRaises(assistant.AssistantUnavailableError):assistant.answer_supply_chain_question('怎么办',context)


if __name__=='__main__':unittest.main()
