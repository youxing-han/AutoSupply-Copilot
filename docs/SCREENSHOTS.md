# Screenshot Provenance

## Capture Session

- Date: 2026-10-23, Asia/Shanghai.
- Application: a fresh local `public_app.py` process, Python 3.11 environment.
- Interface: the real Chinese-language application, operated through its browser controls.
- Data: built-in 12-component production-planning dataset; supplier-delay scenario; start 2026-10-12; horizon 30 days.
- No local model, paid API, enterprise system or real purchasing operation was used.
- Images are direct JPEG browser captures, with no added data, translated labels or generated UI.

## Selected Views

| File | View | Observed result |
|---|---|---|
| `demo-risk-dashboard.jpg` | Six component cards, from the same 12-item analysis | Three high-risk shortage items: HRN-006 613 unmet units, CTL-003 112, SEN-001 106; total 831 |
| `demo-inventory-projection.jpg` | HRN-006 daily stock, demand, receipts and safety threshold | Opening stock 1,500; in-period confirmed receipts 4,014; first shortage 2026-10-21; unmet 613; closing stock 1,492 |
| `demo-delivery-scenario.jpg` | Same component and quantities, original-date receipt reference | Delayed: unmet 613, closing 1,492; reference: unmet zero, closing 879 |
| `demo-mitigation-tradeoffs.jpg` | Candidate scenario table, first 10 of 16 rows | Existing-order expedite: unmet zero at CNY 6,000; late low-price option: unmet 375 at CNY 613 |

## Reproduce

1. Launch the public entrypoint and select dynamic planning.
2. Select the 12-component dataset, supplier delay, 2026-10-12 and 30 days.
3. Load the demonstration, then run dynamic analysis.
4. Inspect the cards and select HRN-006 for detail.
5. Expand scenario comparison and enable the normal-arrival reference.
6. Enable supply mitigation comparison. Leave the default fictional candidate parameters unchanged.

The reference restores original dates and assumes confirmation for non-cancelled orders; it is a conditional comparison. Missed demand is not backordered, so the delayed plan can have higher closing stock despite shortages. A confirmed order is not proof of shipment.

## Scope

The new gallery replaces older screenshots in the README. Older captures remain as historical evidence, not as current gallery images. This capture session verifies the illustrated local workflow, not a new end-to-end cloud release, a real-model acceptance run, or fresh download verification. Historical online tests are dated separately in `RELEASE_AUDIT.md`.
