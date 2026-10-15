"""Acceptance of the agreed calendar, import, portfolio and chat semantics."""
import base64
from copy import deepcopy
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'))
from planning_calendar import natural_weeks,demand_grid,apply_demand_patches,WEEKDAYS
from planning_data import build_interview_demo,analyze_planning_bundle,validate_planning_bundle,planning_xlsx_bytes,read_planning_xlsx,PlanningInputError
from portfolio_ui import filtered_codes,order_totals
from report_pdf import build_pdf_report
import app as dashboard


class NaturalWeekTests(unittest.TestCase):
    def test_wednesday_start_is_padded_from_monday_without_extending_forecast(self):
        b=build_interview_demo('2026-10-14',14)
        grid=demand_grid(b['parts'],b['demands'],'2026-10-14',14,sku='SEN-001')
        self.assertEqual([d['weekday'] for d in grid['dates']],list(WEEKDAYS))
        self.assertEqual(grid['dates'][0]['date'],'2026-10-12')
        self.assertEqual(grid['rows'][0]['values'],[0,0,80,80,80,80,80])
        self.assertEqual(grid['rows'][0]['total'],400)
        self.assertEqual(grid['week_count'],3)
        last=demand_grid(b['parts'],b['demands'],'2026-10-14',14,2,'SEN-001')
        self.assertEqual(last['rows'][0]['values'],[80,80,0,0,0,0,0])
        self.assertEqual(sum(d['in_period'] for w in natural_weeks('2026-10-14',14) for d in w),14)
        self.assertEqual(len(b['demands']),70)

    def test_natural_week_handles_sunday_leap_day_and_year_boundary(self):
        for start,horizon,first,last in [('2026-10-18',1,'2026-10-12','2026-10-18'),('2028-02-29',7,'2028-02-28','2028-03-12'),('2026-12-31',3,'2026-12-28','2027-01-03')]:
            with self.subTest(start=start):
                weeks=natural_weeks(start,horizon)
                self.assertEqual(weeks[0][0]['date'],first)
                self.assertEqual(weeks[-1][-1]['date'],last)
                self.assertEqual(sum(d['in_period'] for w in weeks for d in w),horizon)

    def test_missing_inside_period_is_not_converted_to_zero(self):
        b=build_interview_demo('2026-10-14',14);b['demands'].pop(0)
        grid=demand_grid(b['parts'],b['demands'],'2026-10-14',14,sku='SEN-001')
        self.assertIsNone(grid['rows'][0]['values'][2])
        self.assertIsNone(grid['rows'][0]['total'])
        with self.assertRaises(PlanningInputError):validate_planning_bundle(b)

    def test_invalid_editor_values_remain_invalid_in_calendar_and_analysis(self):
        for value in ('',-1,1.5):
            b=build_interview_demo('2026-10-14',14);b['demands'][0]['quantity']=value
            grid=demand_grid(b['parts'],b['demands'],'2026-10-14',14,sku='SEN-001')
            self.assertIsNone(grid['rows'][0]['total'])
            with self.assertRaises(PlanningInputError):analyze_planning_bundle(b)

    def test_edit_changes_actual_forecast_and_padding_cannot_be_edited(self):
        b=build_interview_demo('2026-10-14',14)
        old=deepcopy(b['demands'])
        b['demands']=apply_demand_patches(old,b['parts'],'2026-10-14',14,[dict(part_code='SEN-001',date='2026-10-14',quantity=120)])
        result=analyze_planning_bundle(b)['details']['SEN-001']['inventory_projection']
        self.assertEqual(result['final_available'],140)
        self.assertEqual(old[0]['quantity'],80)
        for code,date,q in [('SEN-001','2026-10-12',0),('UNKNOWN','2026-10-14',1),('SEN-001','2026-10-14',-1),('SEN-001','2026-10-14',1.5)]:
            with self.subTest(code=code,date=date,q=q),self.assertRaises(ValueError):
                apply_demand_patches(old,b['parts'],'2026-10-14',14,[dict(part_code=code,date=date,quantity=q)])

    def test_weekly_totals_include_all_materials_and_filter_is_independent(self):
        b=build_interview_demo('2026-10-14',14)
        grid=demand_grid(b['parts'],b['demands'],'2026-10-14',14)
        daily=sum(p['daily_usage'] for p in b['parts'])
        self.assertEqual(grid['totals'],[0,0]+[daily]*5)
        self.assertEqual(demand_grid(b['parts'],b['demands'],'2026-10-14',14,sku='SEN-001')['totals'],[0,0]+[80]*5)


class DynamicInputTests(unittest.TestCase):
    def minimal(self,horizon=14):
        b=build_interview_demo(horizon_days=horizon)
        for p in b['parts']:
            for k in ('daily_usage','lead_time_days'):p.pop(k)
        for s in b['suppliers']:s.pop('lead_time_days')
        return b

    def test_dynamic_without_average_or_lead_runs_four_nodes_real_formula_pdf(self):
        b=self.minimal();r=analyze_planning_bundle(b)['details']['SEN-001']
        self.assertEqual(r['inventory_projection']['final_available'],180)
        self.assertEqual(r['inventory_projection']['total_unmet_demand'],0)
        self.assertEqual(r['selected_part']['daily_usage'],80)
        self.assertIsNone(r['selected_part']['lead_time_days'])
        self.assertIsNone(r['inventory_metrics']['stockout_gap'])
        self.assertEqual([t['execution_status'] for t in r['execution_trace']],['SUCCESS']*4)
        self.assertTrue(build_pdf_report(r).startswith(b'%PDF'))

    def test_14_vs_30_and_delayed_order_are_not_conflated(self):
        b=self.minimal();b['orders'][0]['arrival_date']='2026-10-23'
        r=analyze_planning_bundle(b)['details']['SEN-001']['inventory_projection']
        self.assertEqual((r['first_shortage_date'],r['total_unmet_demand']),('2026-10-22',80))
        p=analyze_planning_bundle(self.minimal(30))['details']['SEN-001']['inventory_projection']
        self.assertEqual(len(p['daily']),30)
        self.assertEqual(p['total_unmet_demand'],1100)

    def test_excel_has_no_required_average_or_lead_and_round_trips(self):
        payload=planning_xlsx_bytes(self.minimal(),named_sheets=True)
        frame=pd.read_excel(io.BytesIO(payload),sheet_name='SKU_Master')
        self.assertNotIn('daily_usage',frame.columns)
        self.assertNotIn('lead_time_days',frame.columns)
        b=read_planning_xlsx(payload)
        self.assertEqual(analyze_planning_bundle(b)['details']['SEN-001']['inventory_projection']['final_available'],180)

    def test_mean_is_derived_and_optional_lead_does_not_change_dynamic_risk(self):
        b=self.minimal();b['parts'][0]['daily_usage']=99999
        b['demands'][0]['quantity']=120
        a=analyze_planning_bundle(b)['details']['SEN-001']
        self.assertAlmostEqual(a['selected_part']['daily_usage'],1160/14)
        b['parts'][0]['lead_time_days']=300
        c=analyze_planning_bundle(b)['details']['SEN-001']
        self.assertEqual(a['inventory_projection'],c['inventory_projection'])
        self.assertEqual(a['supplier_risk'],c['supplier_risk'])

    def test_optional_fields_still_reject_invalid_values(self):
        for field,value in [('lead_time_days',-1),('lead_time_days','unknown'),('safety_days',float('inf')),('criticality','INVALID'),('current_stock',-1)]:
            b=self.minimal();b['parts'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(PlanningInputError):validate_planning_bundle(b)

    def test_portfolio_filters_and_pending_are_actual_result_values(self):
        b=self.minimal();b['orders'][0]['status']='PENDING'
        details=analyze_planning_bundle(b)['details']
        self.assertEqual(filtered_codes(details,'高风险','SEN'),['SEN-001'])
        self.assertEqual(filtered_codes(details,'低风险','SEN'),[])
        totals=order_totals(details['SEN-001']['inventory_projection'])
        self.assertEqual(totals,dict(confirmed=0,in_period=0,pending=500))


class NewWorkbenchFlowTests(unittest.TestCase):
    def app(self):return AppTest.from_file(ROOT/'app.py',default_timeout=30).run()

    def test_single_is_one_material_with_two_sources_and_no_import(self):
        a=self.app()
        self.assertEqual(a.get_by_key('single_source').options,['演示数据','业务数据录入'])
        self.assertFalse(any('single_upload'==c.key for c in a.get('component_instance')))
        self.assertEqual(len(a.metric),3)
        self.assertEqual(list(a.exception),[])

    def test_draft_change_clears_ai_and_blocks_questions_until_reanalysis(self):
        a=self.app();a.session_state['chat_messages']=[dict(role='user',content='旧问题'),dict(role='assistant',content='旧答案')]
        a.get_by_key('current_inventory').set_value(100.).run()
        self.assertEqual(a.session_state['chat_messages'],[])
        self.assertTrue(a.session_state['assistant_input_dirty'])
        with self.assertRaises(KeyError):a.get_by_key('quick_single_0')
        a.get_by_key('run_single_analysis').click().run()
        self.assertIsNotNone(a.get_by_key('quick_single_0'))
        self.assertEqual(list(a.exception),[])

    def test_import_entry_loads_real_batch_csv_and_filter_keeps_independent_details(self):
        from demo_data import build_rich_batch
        a=self.app();a.get_by_key('analysis_mode').set_value('Excel / CSV 批量风险分析').run()
        a.get_by_key('batch_import_entry').click().run()
        self.assertEqual(a.get_by_key('batch_source').value,'文件导入')
        a.session_state['batch_upload']={'name':'demo.csv','data':base64.b64encode(build_rich_batch().to_csv(index=False).encode('utf-8-sig')).decode()};a.run()
        a.get_by_key('start_batch_analysis').click().run()
        a.get_by_key('batch_risk_filter').set_value('低风险').run()
        for code in a.get_by_key('batch_selected_sku').options:
            self.assertIn(code.split(' · ')[0],filtered_codes(a.session_state['batch_result']['details'],'低风险'))
        a.session_state['chat_messages']=[dict(role='user',content='旧问题')]
        a.get_by_key('analysis_mode').set_value('动态物料计划').run()
        self.assertEqual(a.session_state['chat_messages'],[])
        self.assertEqual(list(a.exception),[])

    def test_detail_open_and_selected_material_survive_reanalysis(self):
        a=self.app();a.get_by_key('analysis_mode').set_value('动态物料计划').run()
        a.get_by_key('run_planning_analysis').click().run()
        a.get_by_key('planning_open_SEN-001').click().run()
        self.assertTrue(a.session_state['planning_detail_open'])
        a.get_by_key('planning_sku').select('BRG-002').run()
        a.get_by_key('run_planning_analysis').click().run()
        self.assertTrue(a.session_state['planning_detail_open'])
        self.assertEqual(a.session_state['planning_selected_result']['selected_part']['part_code'],'BRG-002')
        self.assertEqual(list(a.exception),[])

    def test_list_edits_survive_return_to_week_matrix(self):
        a=self.app();a.get_by_key('analysis_mode').set_value('动态物料计划').run()
        a.get_by_key('demand_calendar_editing').set_value(True).run()
        a.get_by_key('demand_calendar_view').set_value('明细列表').run()
        key=f"planning_editor_demands_{a.session_state['planning_workspace']['revision']}_list"
        rows=deepcopy(a.session_state['planning_draft']['demands'])
        rows[0]['quantity']=123
        a.session_state[key]={'rows':rows,'edit_id':1};a.run()
        a.get_by_key('demand_calendar_view').set_value('周计划矩阵').run()
        self.assertEqual(a.session_state['planning_draft']['demands'][0]['quantity'],123)
        a.get_by_key('run_planning_analysis').click().run()
        self.assertEqual(a.session_state['planning_analysis']['details']['SEN-001']['inventory_projection']['daily'][0]['planned_demand'],123)
        self.assertEqual(list(a.exception),[])


@unittest.skipUnless(sys.platform == "win32", "Windows launcher is Windows-only")
class ChromeLauncherTests(unittest.TestCase):
    def test_resolver_uses_installed_chrome_without_changing_system_default(self):
        run=subprocess.run(['powershell','-NoProfile','-File',str(ROOT/'scripts/open_dashboard.ps1'),'-Url','http://127.0.0.1:8501','-ResolveOnly'],capture_output=True,text=True,timeout=15)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertTrue(run.stdout.strip()=='SYSTEM_DEFAULT' or Path(run.stdout.strip()).name=='chrome.exe')

    def test_browser_launch_and_missing_chrome_fallback_without_opening_windows(self):
        for present in (True,False):
            ps="""
function Test-Path { param($LiteralPath,$PathType) return PRESENT -and $LiteralPath.EndsWith('Google\\Chrome\\Application\\chrome.exe') }
function Start-Process { param($FilePath,$ArgumentList) Write-Output $FilePath; Write-Output $ArgumentList }
& 'HELPER' -Url 'http://127.0.0.1:8501'
""".replace('PRESENT','$true' if present else '$false').replace('HELPER',str(ROOT/'scripts/open_dashboard.ps1'))
            run=subprocess.run(['powershell','-NoProfile','-Command',ps],capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)
            if present:
                self.assertIn('chrome.exe',run.stdout)
                self.assertIn('--new-tab',run.stdout)
            else:self.assertEqual(run.stdout.strip(),'http://127.0.0.1:8501')


if __name__=='__main__':unittest.main()
