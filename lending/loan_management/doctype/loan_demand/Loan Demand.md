# Loan Demand Flow

This document outlines the purpose and process of the `Loan Demand` doctype, which is a crucial internal document for tracking amounts receivable from a borrower.

## 1. Core Purpose

A `Loan Demand` acts as an internal invoice or receivable record. Each time a borrower owes a specific amount on a specific date—be it for a scheduled EMI, a penalty, or a charge—a `Loan Demand` document is created to formally track that due amount.

It is the foundational record that the `Loan Repayment` process uses to determine what is owed by the borrower.

### Demand Types and Subtypes

Each demand is categorized by `Demand Type` and `Demand Subtype` to identify what the amount represents, for example:
*   **Type**: `EMI`, **Subtype**: `Principal`
*   **Type**: `EMI`, **Subtype**: `Interest`
*   **Type**: `Penalty`, **Subtype**: `Penalty`
*   **Type**: `Charges`, **Subtype**: `Processing Fee`

## 2. Demand Creation

Loan Demands are almost always created automatically by other processes in the system. Direct user creation is rare.

### Key Creation Processes

*   **Scheduled EMI Demands (`make_loan_demand_for_term_loans`)**:
    *   A daily background job (`Process Loan Demand`) runs this function.
    *   It scans all active term loans and checks their `Loan Repayment Schedule`.
    *   If an EMI's `payment_date` matches the current date, the system calls the `create_loan_demand` utility function.
    *   `create_loan_demand` then creates two separate `Loan Demand` documents: one for the `Principal` component and one for the `Interest` component of the EMI.

*   **Advance/Pre-payment Demands**:
    *   When a `Loan Repayment Schedule` is submitted as part of a `Loan Restructure` for a pre-payment, it immediately creates demands for the principal and interest being paid in advance.

*   **Charge Demands (`make_sales_invoice_for_charge`)**:
    *   When charges are applied (e.g., during disbursement or pre-payment), the system first creates a `Sales Invoice`.
    *   A `Loan Demand` is then created and linked to this `Sales Invoice` to track the receivable for that charge.

## 3. Detailed Actions on Submission (`on_submit`)

When a `Loan Demand` is submitted, it triggers a critical accounting event that moves the due amount from a temporary "accrued" state to a formal "receivable" state.

### General Ledger Entries (`make_gl_entries`)

*   **For Interest Demands**:
    *   **Debit**: `Interest Receivable Account` (An asset account, increasing what's owed to the company).
    *   **Credit**: `Interest Accrued Account` (Clears the temporary accrued account).
*   **For Penalty Demands**:
    *   **Debit**: `Penalty Receivable Account`.
    *   **Credit**: `Penalty Accrued Account`.
*   **For Principal Demands**: No GL entries are posted here. The principal liability is handled directly by the `Loan Disbursement` and `Loan Repayment` transactions.
*   **For Charge Demands**: No GL entries are posted here, as they are handled by the linked `Sales Invoice`.

This accounting entry is the formal recognition that a specific interest or penalty amount is now officially due from the borrower.

## 4. Detailed Actions on Cancellation (`on_cancel`)

Cancelling a `Loan Demand` fully reverses its impact.

*   **Reverse GL Entries**: It posts a reversing Journal Entry to move the amount from the "receivable" account back to the "accrued" account.
*   **Update Repayment Schedule**: If the demand was linked to a row in a `Loan Repayment Schedule` (for a scheduled EMI), it updates that row to mark the demand as not generated (`demand_generated = 0`).
*   **Create Credit Note**: If the demand was for a charge linked to a `Sales Invoice`, it creates a `Credit Note` to reverse the invoice.

## 5. Key Utility Functions

*   **`create_loan_demand(...)`**: This is the central, non-whitelisted function used by all other processes to create a new `Loan Demand` document. It's a standardized way to ensure all necessary details are included.
*   **`reverse_demands(...)`**: This function is used to find and cancel multiple demands related to a specific loan, often used during backdated reposting or loan cancellation.

---
## 6. Detailed Hooks Logic

The hooks in `Loan Demand` manage the accounting entries and the status of related documents.

### `validate()`
This hook performs basic calculations and data consistency checks before saving the document.
*   It calculates the `outstanding_amount` by subtracting the `paid_amount` from the `demand_amount`.
*   If the loan has a co-lender (`Loan Partner`), it fetches the partner's share of the principal or interest from the `Co-Lender Schedule` and populates the `partner_share` field.

### `on_submit()`
This hook formalizes the demand by creating the necessary accounting entries.
1.  **`make_gl_entries`**: This is the primary action. Based on the demand subtype, it posts a journal entry to move the amount from an "accrued" account to a "receivable" account. For example, for an interest demand, it will Debit `Interest Receivable Account` and Credit `Interest Accrued Account`.
2.  **`update_repayment_schedule`**: If the demand was generated from a `Loan Repayment Schedule` row, this function updates that row to set the `demand_generated` flag to 1. This prevents duplicate demands from being created for the same installment.
3.  **Trigger Interest Accrual**: If the demand was for interest and created by the `Process Loan Demand` job, it triggers the `process_loan_interest_accrual_for_loans` function. This ensures that the interest accrual process is run immediately after a demand is raised, keeping the books perfectly synchronized.

### `on_cancel()`
This hook reverses all the actions taken during submission.
1.  **`make_gl_entries(cancel=1)`**: It calls the same `make_gl_entries` function but with the `cancel` flag, which posts a perfect reversal of the original journal entry.
2.  **`update_repayment_schedule(cancel=1)`**: It sets the `demand_generated` flag on the corresponding `Loan Repayment Schedule` row back to 0.
3.  **`make_credit_note`**: If the demand was for a charge linked to a `Sales Invoice`, this function creates a `Credit Note` to cancel that invoice. 