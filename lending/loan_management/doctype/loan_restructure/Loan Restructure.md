# Loan Restructure Flow

This document describes the detailed process of restructuring an existing loan, including validations, automated actions, and accounting entries.

## 1. Initiating a Loan Restructure

A `Loan Restructure` can be initiated for an active `Loan`. This is typically done when a borrower is unable to adhere to the original repayment schedule or wishes to make a pre-payment.

### Restructure Types:
*   **Normal Restructure**: This is used when the borrower faces difficulty in repayment. Terms like interest rate or tenure can be modified to make repayments more manageable.
*   **Pre Payment**: The borrower pays off a significant portion of the loan principal before the due date.
*   **Advance Payment**: The borrower pays a few installments in advance.

A new `Loan Restructure` document is created, linking to the original `Loan`. Upon creation, its status is **Draft**.

## 2. Detailed Validations (`validate`)
Before submission, a series of validation checks are performed:

*   **No Other Initiated Restructures**: Checks if another restructure for the same loan is already in the "Initiated" state (`validate_against_initiated_restructure`).
*   **Restructure Date**: For a "Normal Restructure", ensures the `Restructure Date` is not before the last interest accrual date (`validate_restructure_date`).
*   **Waiver Amounts**: Ensures that waiver amounts for interest or charges do not exceed the respective overdue amounts (`validate_waiver_amount`).
*   **Repayment Start Date**: Ensures the `New Repayment Start Date` is not before the `Restructure Date` (`validate_repayment_start_date`).

## 3. Pre-submission Logic: Calculating the New Loan State
As the user fills in the details, the system dynamically calculates the outcome:

*   **Calculate Overdues (`update_overdue_amounts`)**: Fetches all unpaid `Loan Demand` records to calculate the precise `Principal Overdue`, `Interest Overdue`, `Penalty Overdue`, and `Charges Overdue`.
*   **Allocate Security Deposit (`allocate_security_deposit`)**: If `Available Security Deposit` exists, it's automatically allocated towards outstanding dues, prioritizing principal, then interest, then penalty.
*   **Calculate Balances (`calculate_balance_amounts`)**: After applying adjustments and waivers, it calculates the final balance for each component (principal, interest, etc.).
*   **Calculate New Loan Amount (`calculate_new_loan_amount`)**: This is the critical calculation for the new schedule.
    *   `New Loan Amount` starts with the `Pending Principal Amount` minus any principal paid from the security deposit.
    *   If interest/charges are marked for **Capitalization**, their balance amounts are added to the `New Loan Amount`.
*   **Generate Draft Schedule (`make_update_draft_loan_repayment_schedule`)**: Based on the `New Loan Amount` and new terms, a new **Draft** `Loan Repayment Schedule` is generated in the background to provide a preview.

## 4. Submission and Approval Workflow

*   Once the restructure terms are finalized, the document is **Submitted**. Its status changes to **Initiated**.
*   The document then goes through an approval workflow. An approver can either **Approve** or **Reject** the restructure request.

### Detailed Actions on Approval (`restructure_loan`)

*   **1. Mark Old Schedule as Outdated (`update_repayment_schedule_status`)**: The previously **Active** `Loan Repayment Schedule` is marked as **Outdated**.
*   **2. Create Accounting Entries for Adjustments and Waivers**:
    *   The system creates other documents (`Loan Repayment` and `Loan Adjustment`) to handle the accounting for waivers and capitalization.
    *   **Waivers (`make_loan_repayment_for_waiver`)**: A `Loan Repayment` document is created to book the waivers.
        *   **Debit**: `Write Off` Account (Expense account for the waived amount).
        *   **Credit**: `Loan Account` (Reduces the applicant's liability).
    *   **Capitalization (`make_loan_adjustment_for_capitalization`)**: A `Loan Adjustment` document is created to capitalize dues.
        *   **Debit**: `Loan Account` (Increases applicant's liability by the capitalized amount).
        *   **Credit**: `Interest Income Account` (or other relevant income accounts).
*   **3. Submit the New Repayment Schedule**: The new **Draft** `Loan Repayment Schedule` linked to the restructure is submitted and becomes **Active**.
*   **4. Update Loan Document (`update_restructured_loan_details`)**: The parent `Loan` is updated with the new interest rate, repayment terms, and its `loan_restructure_count` is incremented.
*   **5. Update NPA Status**: If the restructure qualifies the loan to be upgraded from NPA (Non-Performing Asset), the `update_all_linked_loan_customer_npa_status` function is called to update the status and set the `watch_period_end_date`.
*   **6. Set Final Status**: The `Loan Restructure` status is set to **Approved**.

## 5. Detailed Actions on Cancellation (`on_cancel`)

If an approved restructure is cancelled:
*   **1. Cancel New Schedule (`cancel_repayment_schedule`)**: The newly **Active** `Loan Repayment Schedule` is cancelled.
*   **2. Reactivate Old Schedule (`update_repayment_schedule_status`)**: The **Outdated** schedule is set back to **Active**.
*   **3. Cancel Adjustments (`cancel_loan_adjustments`)**: All `Loan Repayment` and `Loan Adjustment` documents created for waivers and capitalization are cancelled, which reverses their GL entries.
*   **4. Revert Loan Document**: The `loan_restructure_count` on the parent `Loan` is decremented.
*   **5. Set Final Status**: The `Loan Restructure` status is set to **Cancelled**.

This comprehensive workflow allows for flexible and controlled restructuring of loans, ensuring all financial implications are accurately recorded and new repayment terms are systematically implemented.

## 6. Detailed Hooks Logic

The `Loan Restructure` doctype is highly automated, with its hooks managing calculations, generating schedules, and posting complex accounting entries.

### `validate()`
This hook runs on every save and is responsible for the real-time calculation of the restructured loan state.
1.  **Initial Validations**: Checks for other initiated restructures and validates the restructure date.
2.  **`set_completed_tenure`**: Counts how many installments have already been paid on the active schedule.
3.  **`update_overdue_amounts`**: Fetches all unpaid demands to get the current overdue principal, interest, and penalty.
4.  **`allocate_security_deposit`**: If available, applies security deposit amounts to the overdue figures.
5.  **`validate_waiver_amount`**: Ensures waiver amounts are not more than the amounts overdue.
6.  **`calculate_balance_amounts`**: Subtracts waivers and adjustments from overdues to get the final balances.
7.  **`set_missing_values`**: Populates default values for new loan terms if they are not filled.
8.  **`calculate_new_loan_amount`**: Calculates the principal for the new loan by taking the pending principal and adding any capitalized interest or charges.
9.  **`make_update_draft_loan_repayment_schedule`**: Based on the newly calculated principal and terms, it creates or updates a draft `Loan Repayment Schedule` to act as a preview.

### `after_insert()`
This hook runs once after the document is created for the first time. It calls `make_update_draft_loan_repayment_schedule` to ensure a draft schedule is created as soon as the restructure document is created.

### `on_submit()`
This hook simply sets the document status to "Initiated", which formally puts it into the approval workflow.

### `on_update_after_submit()`
This hook is triggered when the document's workflow state is changed (e.g., from "Initiated" to "Approved").
*   It calls the `apply_workflow` method, which contains the main logic for when a restructure is **Approved**. `apply_workflow` in turn calls `restructure_loan` to execute the series of actions detailed in section 4.

### `on_cancel()`
This hook orchestrates the complete reversal of the restructure process.
1.  **`update_totals`**: Reverts the totals on the parent `Loan` document.
2.  **`cancel_repayment_schedule`**: Cancels the new `Loan Repayment Schedule` that was created.
3.  **`update_repayment_schedule_status`**: Finds the old schedule that was marked "Outdated" and sets its status back to "Active".
4.  **`update_restructure_count`**: Decrements the restructure count on the parent `Loan`.
5.  **`cancel_loan_adjustments`**: Finds and cancels all the `Loan Adjustment` and `Loan Repayment` documents that were created for capitalization and waivers, which reverses their GL entries.

---
## Glossary of Terms
*   **Capitalization**: The process of adding unpaid interest or charges to the principal balance of a loan. The new, larger principal balance is then used to calculate future interest payments.
*   **Loan Adjustment**: An internal document used to make debit/credit adjustments to a loan account without an actual cash transaction, such as for capitalizing interest.
*   **NPA (Non-Performing Asset)**: A loan that is in default or close to being in default. Restructuring a loan can sometimes help in upgrading its status from NPA.
*   **Restructure**: The process of modifying the terms of an existing loan, such as the interest rate, tenure, or installments, to help a borrower who is facing financial difficulty or to handle a pre-payment.
*   **Waiver**: The act of forgiving a portion of the debt owed, such as overdue interest or penalty charges. This is usually an expense for the lender.
*   **Write Off**: An accounting action that removes a bad debt from the books by recognizing it as an expense. Waivers are a form of write-off. 