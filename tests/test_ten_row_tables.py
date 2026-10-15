"""One table paging rule across read-only previews, results and reports."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'))
from localized_ui import table_page,TABLE_PAGE_SIZE
import app as dashboard


class PageSliceTests(unittest.TestCase):
    def test_page_api_uses_its_own_globals_when_another_session_replaces_registry(self):
        with patch.dict(sys.modules,{dashboard.__name__:SimpleNamespace()}):
            api=dashboard._page_api()
        self.assertEqual(api.SINGLE_ANALYSIS_MODE,dashboard.SINGLE_ANALYSIS_MODE)
        self.assertIs(api._render_inline_assistant,dashboard._render_inline_assistant)
        self.assertIs(api.run_dashboard_analysis,dashboard.run_dashboard_analysis)

    def test_every_record_is_reachable_once_without_mutating_complete_input(self):
        for count in (0,1,10,11,12,30,144):
            with self.subTest(count=count):
                frame=pd.DataFrame({'order':range(count)})
                original=frame.copy(deep=True)
                visible=[]
                pages=max(1,(count+9)//10)
                for i in range(pages):
                    part,page,total=table_page(frame,i)
                    self.assertLessEqual(len(part),TABLE_PAGE_SIZE)
                    self.assertEqual((page,total),(i,pages))
                    visible.extend(part['order'].tolist())
                self.assertEqual(visible,list(range(count)))
                pd.testing.assert_frame_equal(frame,original)

    def test_page_index_is_clamped_after_data_shrinks(self):
        frame=pd.DataFrame({'order':range(12)})
        self.assertEqual(table_page(frame,100)[0]['order'].tolist(),[10,11])
        self.assertEqual(table_page(frame,-1)[0]['order'].tolist(),list(range(10)))
        self.assertEqual(table_page(frame.iloc[:3],1)[1],0)


class PaginationFlowTests(unittest.TestCase):
    def app(self):return AppTest.from_file(ROOT/'app.py',default_timeout=30).run()

    def test_preview_paging_keeps_all_records_and_does_not_dirty_analysis_or_chat(self):
        a=self.app();a.get_by_key('analysis_mode').set_value('Excel / CSV 批量风险分析').run()
        a.get_by_key('start_batch_analysis').click().run()
        before=deepcopy(a.session_state['batch_draft_rows'])
        a.session_state['chat_messages']=[{'role':'user','content':'本次结果'}]
        a.get_by_key('table_next_batch_input_preview').click().run()
        self.assertEqual(a.session_state['batch_draft_rows'],before)
        self.assertEqual(a.session_state['batch_result']['success_count'],12)
        self.assertFalse(a.session_state['assistant_input_dirty'])
        self.assertEqual(a.session_state['chat_messages'],[{'role':'user','content':'本次结果'}])
        a.get_by_key('batch_overview_view').select('表格').run()
        first=next(m.value for m in a.markdown if 'data-table="batch_risk_table"' in m.value)
        self.assertEqual(first.count('<tr>'),11)
        a.get_by_key('table_next_batch_risk_table').click().run()
        second=next(m.value for m in a.markdown if 'data-table="batch_risk_table"' in m.value)
        self.assertEqual(second.count('<tr>'),3)
        self.assertEqual(list(a.exception),[])

    def test_complete_preview_option_cannot_bypass_ten_row_limit(self):
        a=self.app();a.get_by_key('analysis_mode').set_value('Excel / CSV 批量风险分析').run()
        a.get_by_key('batch_preview_all').set_value(True).run()
        markup=next(m.value for m in a.markdown if 'data-table="batch_input_preview"' in m.value)
        self.assertEqual(markup.count('<tr>'),11)
        self.assertIn('安全库存天数',markup)
        self.assertIn('供应商状态',markup)
        self.assertEqual(list(a.exception),[])


if __name__=='__main__':unittest.main()
