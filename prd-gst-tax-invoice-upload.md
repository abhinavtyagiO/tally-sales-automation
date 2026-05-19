## Problem Statement

AccountPilot currently supports a simple retail sales upload flow where each Excel row becomes a sales voucher and `payment_mode` is used as the party/payment ledger. This works for normal walk-in, cash, UPI, and card customers, but it does not support buyers who need a GST tax invoice under their firm name and GSTIN for GST return filing.

GST buyers require a proper Tally Sales invoice voucher with invoice view, buyer GST details, supplier GST details, item HSN/GST details, tax ledger entries, and a buyer party ledger. The current flow creates an accounting-style Sales voucher with `ISINVOICE=No`, no buyer GSTIN, no buyer firm ledger, and no CGST/SGST/IGST tax allocation. Users need a clear way to bulk create both simple retail sales entries and GST tax invoices without confusing the two accounting behaviors.

## Solution

AccountPilot will add a second upload type alongside the existing retail sales upload:

- Retail Sales: the existing lightweight flow for normal customers where buyer GST details are not required.
- GST Tax Invoices: a new bulk upload flow for registered buyers who need GST-compliant Tally sales invoices.

Both upload types will use the same high-level import lifecycle: upload, parse, validate, preview, commit, and result summary. They will differ in Excel templates, validation rules, voucher builder, and Tally XML payload. The GST Tax Invoice flow will create Tally Sales vouchers using `Invoice Voucher View` and `ISINVOICE=Yes`, with buyer GSTIN, buyer party ledger, item HSN/GST details, and appropriate CGST/SGST or IGST ledger entries.

From the user perspective, the upload page will present two clear choices: Retail Sales and GST Tax Invoices. Each choice will provide the right template and validation expectations. The existing retail workflow will remain unchanged for current users.

## User Stories

1. As a business owner, I want to choose between Retail Sales and GST Tax Invoices, so that I can upload the correct type of sales data.
2. As an accountant, I want the Retail Sales flow to keep working as-is, so that existing simple sales uploads are not disrupted.
3. As an accountant, I want a GST Tax Invoice upload flow, so that registered buyers can receive invoices under their GSTIN.
4. As a GST-registered buyer, I want my firm name and GSTIN on the invoice, so that I can claim input tax credit where applicable.
5. As a business owner, I want separate Excel templates for Retail Sales and GST Tax Invoices, so that my team does not mix up required columns.
6. As a non-technical user, I want the app to explain which upload type to choose in simple terms, so that I do not need to understand accounting internals.
7. As an accountant, I want GST invoice rows to require buyer name, buyer GSTIN, buyer state, product, quantity, rate, and voucher date, so that the generated invoice has enough compliance data.
8. As an accountant, I want payment mode captured for GST invoices without using it as the buyer ledger, so that payment tracking and party accounting are not mixed up.
9. As an accountant, I want GST invoice party ledger to be the buyer firm name, so that Tally records receivables against the correct customer.
10. As an accountant, I want AccountPilot to create or reuse the buyer ledger in Tally, so that GST invoices can be committed without manual ledger setup.
11. As an accountant, I want buyer ledgers to be grouped under Sundry Debtors by default, so that Tally accounting remains conventional.
12. As a business owner, I want the GST invoice preview to show buyer name and GSTIN, so that I can catch mistakes before committing.
13. As an accountant, I want the GST invoice preview to show taxable amount, GST amount, and invoice total, so that I can verify the final invoice value.
14. As an accountant, I want AccountPilot to derive HSN and GST rate from synced Tally stock items, so that the Excel file does not duplicate master data.
15. As an accountant, I want validation to fail when a product is missing from synced Tally stock items, so that invoices do not reference invalid stock masters.
16. As an accountant, I want validation to fail when a GST invoice row is missing buyer GSTIN, so that incomplete tax invoices are not created.
17. As an accountant, I want validation to fail when a GSTIN looks malformed, so that obvious data-entry mistakes are caught early.
18. As an accountant, I want validation to fail when required GST tax ledgers are missing, so that voucher commits do not fail halfway.
19. As an accountant, I want AccountPilot to create configured missing ledgers when safe, so that setup remains simple.
20. As a business owner, I want same-state GST invoices to split tax into CGST and SGST, so that Tally records the correct tax liability.
21. As a business owner, I want interstate GST invoices to use IGST, so that Tally records the correct tax liability.
22. As an accountant, I want company GSTIN and company state stored in AccountPilot, so that GST tax split and Tally XML can be generated reliably.
23. As an accountant, I want AccountPilot to use the active Tally company GST configuration, so that invoice data matches the selected company.
24. As a business owner, I want GST invoice rows to support quantity and rate, so that taxable value can be calculated clearly.
25. As a business owner, I want the app to treat GST invoice rate as pre-tax taxable rate, so that GST is added transparently.
26. As an accountant, I want the final party ledger amount to include taxable value plus GST, so that the invoice total balances.
27. As an accountant, I want the Tally voucher XML to follow the Sales Create GST contract, so that Tally accepts the import reliably.
28. As an accountant, I want the commit result screen to show which GST invoices succeeded and failed, so that I can reconcile the batch.
29. As a user, I want failed GST invoice rows to show short user-readable errors, so that I am not exposed to raw Tally XML or nested exception dumps.
30. As a user, I want successful GST invoice rows to show the voucher identifier when available, so that I can cross-check in Tally.
31. As a business owner, I want GST invoice upload history to appear in the same history area as retail uploads, so that all batches are traceable.
32. As an accountant, I want history to distinguish Retail Sales from GST Tax Invoices, so that I know what kind of vouchers were created.
33. As a user, I want templates to include sample rows, so that I can format my upload correctly.
34. As a user, I want the app to block commit when Tally is disconnected, so that I do not lose work or create partial batches.
35. As a business owner, I want existing retail uploads to remain compatible with old sample sheets, so that adoption does not require immediate process changes.
36. As an accountant, I want GST invoice validation to run before Tally commit, so that invalid rows are skipped before creating vouchers.
37. As an accountant, I want valid GST rows to be committable even when some rows are invalid, so that one bad invoice does not block the whole batch.
38. As a product owner, I want this implemented as a second import type in the same import engine, so that the system remains maintainable.
39. As a developer, I want separate voucher builders for retail sales and GST tax invoices, so that the Tally XML contracts do not become tangled.
40. As a developer, I want GST calculation isolated in a testable module, so that same-state and interstate tax behavior can be verified without Tally.

## Implementation Decisions

- AccountPilot will support two upload types: Retail Sales and GST Tax Invoices.
- The current retail sales behavior remains the default/simple path and must remain backward compatible.
- GST Tax Invoices will be implemented as a new import type in the existing upload/import lifecycle rather than as a completely separate subsystem.
- Imports will store an import type so history, preview, validation, and commit can distinguish retail uploads from GST invoice uploads.
- The upload UI will show two clear upload cards: Retail Sales and GST Tax Invoices.
- Each upload type will have its own Excel column contract and template.
- Retail Sales will keep the existing required columns: `product_name`, `price`, `payment_mode`, and `voucher_date`.
- GST Tax Invoices will use a richer contract including `voucher_date`, `buyer_name`, `buyer_gstin`, `buyer_state`, `product_name`, `quantity`, `rate`, and `payment_mode`.
- GST invoice `payment_mode` will not become the party ledger. It will be captured as payment metadata for future use.
- GST invoice `PartyLedgerName` will be the buyer firm/customer ledger.
- Buyer ledgers will be created or reused in Tally before GST invoice commit.
- Buyer ledgers should default to a Sundry Debtors-style group unless company configuration says otherwise.
- Company GST configuration will be added for supplier GSTIN, supplier state, GST registration name, GST registration type, GST sales ledger, CGST ledger, SGST ledger, and IGST ledger.
- The GST invoice builder will use the Tally Sales Create GST XML structure provided from Tally API Explorer.
- GST invoice vouchers will use Invoice Voucher View and `ISINVOICE=Yes`.
- Retail sales vouchers will continue to use the current simple sales voucher path unless explicitly changed in a future PRD.
- GST invoice item HSN, GST type, taxability, and GST rate will be derived from synced stock item cache when available.
- Stock item cache must remain the source of truth for product names and GST master data.
- GST calculation will treat Excel `rate` as pre-tax taxable rate for GST rows.
- Taxable value will be calculated as quantity multiplied by rate.
- Same-state sales will split GST into CGST and SGST ledger entries.
- Interstate sales will create IGST ledger entries.
- Party ledger total will include taxable value plus GST amount.
- The preview screen will show GST-specific fields including buyer name, GSTIN, taxable value, tax amount, and invoice total.
- Commit result will remain a separate screen after commit and will show success and failed counts.
- Error formatting must remain user-friendly and must not expose raw Tally XML or nested response dumps.
- The Tally connector remains the execution boundary for creating ledgers and vouchers in local Tally.
- The implementation should extract deep modules for GST import parsing, GST validation, GST tax calculation, and GST voucher XML construction.

## Testing Decisions

- Tests should cover external behavior and generated contracts, not private implementation details.
- Existing retail sales tests must continue passing without requiring new GST columns.
- Add parser tests for Retail Sales and GST Tax Invoice templates.
- Add validation tests for missing GSTIN, malformed GSTIN, missing buyer name, missing buyer state, missing product, missing synced stock item, and missing GST stock metadata.
- Add GST calculation tests for same-state CGST/SGST split and interstate IGST calculation.
- Add voucher builder tests that assert the generated GST invoice payload includes invoice view, `ISINVOICE=Yes`, buyer GSTIN, company GSTIN, inventory entries, rate details, bill allocation, and tax ledger entries.
- Add route-level tests using the existing import flow style to verify GST upload, process, preview, and commit behavior.
- Add tests to ensure invalid GST rows do not block committing valid GST rows.
- Add tests to ensure history/import records include import type.
- Use existing multi-company/import flow tests as prior art for route-level behavior.
- Use existing derivation tests as prior art for frontend display logic where GST preview totals are derived.
- Avoid tests that require a live Tally server; use mocked connector dispatch responses for commit paths.
- Add at least one fixture based on the Tally Sales Create GST XML sample from the API Explorer payload.

## Out of Scope

- Full GST return filing is out of scope.
- E-invoicing and IRN generation are out of scope.
- E-way bill generation is out of scope.
- Editing or cancelling GST invoices after creation is out of scope.
- Bulk updating buyer ledgers outside the invoice upload flow is out of scope.
- Payment receipt reconciliation is out of scope.
- Advanced discounts, shipping charges, cess, state cess, round-off, and multi-tax overrides are out of scope for the first version.
- Multi-line invoices with multiple products under one invoice number are out of scope for the first version unless the implementation can support it without delaying the MVP slice.
- Live Tally contract discovery is out of scope when Tally is unavailable; implementation should use the provided API Explorer XML and existing Tally dump references.

## Further Notes

- The provided Tally API Explorer payload uses `Invoice Voucher View`, `ISINVOICE=Yes`, buyer GSTIN fields, company GST fields, inventory entries, `RATEDETAILS.LIST`, buyer bill allocation, and CGST/SGST tax ledger entries.
- The current simple sales voucher uses `Accounting Voucher View` and `ISINVOICE=No`, so GST support should be a separate builder rather than a conditional patch inside the existing XML.
- The product terminology should stay simple for users: Retail Sales and GST Tax Invoices.
- The current inventory work that stores HSN/GST-related stock item fields is a useful prerequisite for GST invoice generation.

## Implementation Status

Completed the GST Tax Invoice MVP slice:

- Added import type storage and branching for Retail Sales vs GST Tax Invoices.
- Added company GST configuration fields in the backend schema/API and first-run setup form.
- Added GST Excel parsing, GSTIN validation, stock master validation, GST tax calculation, and preview persistence.
- Added GST Sales invoice XML generation for Tally `Invoice Voucher View` with buyer/company GST fields, inventory entries, rate details, buyer bill allocation, and tax ledger entries.
- Added GST commit through the local connector with safe creation/reuse of GST sales, buyer, CGST, SGST, and IGST ledgers.
- Updated frontend upload, preview, history, row tables, summary totals, and downloadable templates to distinguish the two upload types.
- Added backend regression coverage for GST preview totals and GST commit dispatch.

Verification completed:

- `.venv/bin/python -m unittest discover -s tests` - 37 tests passed.
- `cd frontend && pnpm run test:derivations` - 6 tests passed.
- `cd frontend && pnpm run build` - production build passed.
