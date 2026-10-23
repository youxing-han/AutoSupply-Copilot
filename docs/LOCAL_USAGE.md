# User Guide

The application UI is in Chinese. This English guide describes the workflow; screenshot captions do not change the UI language.

## Choose an Analysis Mode

- **Single SKU:** Edit inventory, average daily demand, procurement lead time, safety days, supplier status and material criticality, then run analysis. Outputs include coverage, the lead-time coverage gap and a reference replenishment quantity. This static model excludes purchase orders.
- **Batch screening:** Use the built-in data, enter your own fictional rows or import Excel/CSV. Run analysis to obtain risk priorities and component details. Up to 50 SKUs are supported.
- **Dynamic planning:** Use the 12-component planning dataset or the five-component formula-verification fixture. Choose a scenario, start date and horizon, load inputs, inspect inventory, demand and orders, then run analysis.

## Load, Edit, Run

Loading a demonstration or importing a file prepares inputs; it does not automatically analyze them. After changing dates or a scenario, reload the demonstration before running. Manual inputs use the corresponding plan-rebuild control to apply a new horizon.

Edits within one source preserve drafts and the previous successful result, marked as outdated. Switching sources hides the previous source's results, exports and AI context. Each source retains its own draft. Results reflect the last explicit analysis, not unsubmitted edits.

## Demand and Purchase Orders

Dynamic planning accepts 1-90 days. Calendar editing uses Monday-Sunday weeks; dates outside the horizon are placeholders excluded from calculations. Missing in-horizon values are rejected rather than silently treated as zero. Week and day totals include all filtered items, not just the visible page. Excel demand data use `part_code,date,quantity` rows.

Average daily demand is calculated from the complete plan. Standard lead time is not needed for daily inventory projections. Only confirmed orders contribute receipts; pending and cancelled orders remain separate. Confirmed open quantity is not evidence of shipment, and receipts outside the horizon do not become in-period supply.

## Review Results

Cards show six items per page, with an option to display all. Filter by risk or search for an item or supplier; switch to a table if preferred. All data tables paginate at ten rows without reducing calculations. Select a component for daily inventory curves and purchase-order details.

The risk-priority chart ranks cumulative unmet demand. Medium risk can reflect a safety-stock or supplier warning without a quantity shortage. Aggregated units across different components are not lost vehicle output.

Expand scenario comparison to overlay an original-date receipt reference, which restores original dates for non-cancelled orders and assumes confirmation. This is a comparison assumption, not a promise of arrival. Enable mitigation assessment to compare fixed-lot expediting, backup supply and transfers. Inspect eligibility, dates, remaining shortages and incremental costs before interpreting a recommendation.

## Import and Export

Download a populated template, edit simulated values in Excel, upload and preview, then run. A downloaded example represents the selected demonstration dataset, not the current edited draft. Preserve the workbook sheets and compatible column fields. Dynamic workbooks contain settings, parts, suppliers, demands and orders.

Downloads include CSV risk results, mitigation comparisons and PDF reports. Uploads are limited to 5 MB and held in session memory. Save necessary inputs and outputs before closing the session or restarting the service.

## Local AI

Run the analysis first, then ask a question about the current snapshot. Changing mode, source, item, scenario or inputs clears stale conversation context. The interface keeps the latest question-and-answer pair; ordinary viewing does not repeatedly call the model.

The local model only explains facts. Numeric and action-claim checks reject certain responses, with a constrained JSON explanation-key retry. Dynamic explanations also use constrained selection. Model failure leaves the deterministic results and exports available. Public mode blocks model access and displays an availability notice.

## Reproducible Calculation Fixture

The five-component fixture uses SEN-001 with 800 opening units, demand of 80 per day and a receipt of 500 on day eight. Over 14 days it leaves 180 units and no unmet demand. Delaying receipt to day twelve produces 80 unmet units. A 30-day horizon changes the result; do not mix this fixture with the 12-component dataset.

## Desktop Launchers

Optional Windows shortcuts can start or stop the application. The launcher prefers installed Chrome and otherwise uses the system browser without changing its default. Cloud execution does not depend on these shortcuts. Installation commands are in the repository README.
