# Loan Disbursement Charge

This document explains the purpose and function of the `Loan Disbursement Charge` child doctype.

## 1. Purpose

`Loan Disbursement Charge` is not a standalone doctype but a **child table** within the `Loan Disbursement` document. Its purpose is to record any charges that are levied at the time of disbursement, such as:

*   Processing Fees
*   Documentation Charges
*   Legal Fees

## 2. Process Flow

The logic for handling these charges resides entirely within the parent `Loan Disbursement` doctype.

1.  **Adding Charges**: A user adds one or more charge items to the `Loan Disbursement Charges` table in the `Loan Disbursement` form.
2.  **Submission Trigger**: When the parent `Loan Disbursement` is submitted, it triggers the `make_sales_invoice_for_charge` utility function.
3.  **Sales Invoice Creation**: This function creates a new `Sales Invoice` document.
    *   The `Customer` on the invoice is the loan's applicant.
    *   The `Items` on the invoice correspond to the charges listed in the `Loan Disbursement Charges` table.
4.  **Accounting Impact**: The `Sales Invoice` itself handles all the necessary accounting entries for the charge, typically:
    *   **Debit**: The applicant's accounts receivable account.
    *   **Credit**: The respective income account for the charge.
5.  **Demand Creation**: A `Loan Demand` is then automatically created, linked to this `Sales Invoice`, to formally track the amount due for the charge.

In essence, the `Loan Disbursement Charge` table acts as a data entry point that initiates a standard sales and invoicing process to apply charges to a loan account. Reversing these charges is handled by creating a `Credit Note` against the generated `Sales Invoice`, which is triggered when the parent `Loan Disbursement` is cancelled.

---
## 3. Hooks Logic

As a child doctype, `Loan Disbursement Charge` does not have its own independent hooks (like `on_submit` or `validate`). All logic and actions related to these charges are managed by the hooks within the parent `Loan Disbursement` document. The process described above is initiated from the `on_submit` hook of the parent document. 