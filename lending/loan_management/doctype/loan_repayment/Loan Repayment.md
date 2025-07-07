# Loan Repayment Flow

This document outlines the complete process of handling a loan repayment, which is the core transaction for recording payments received from a borrower.

## 1. Overview and Purpose

The `Loan Repayment` doctype is used to record any funds received from a borrower against their loan. It is a versatile document that handles numerous repayment scenarios, controlled by the `Repayment Type` field.

### Key Repayment Types

The behavior of the Loan Repayment document changes significantly based on the selected `Repayment Type`:

*   **Normal Repayment**: The standard repayment of an EMI or other due amount.
*   **Pre-payment / Advance Payment**: Paying an amount before it is due. This typically triggers a `Loan Restructure` to recalculate the remaining EMIs.
*   **Waiver (Interest, Penalty, Charges)**: Forgiving a certain part of the due amount. This does not involve a real money transaction but creates accounting entries to write off the waived amount.
*   **Settlement (Partial, Full, Write-off)**: Used to close a loan by accepting an amount different from the total outstanding balance.
*   **Charge Payment**: A payment made specifically to settle outstanding charges.

## 2. Core Logic: Calculation and Allocation

The central logic of a Loan Repayment involves two steps: calculating the total amount due and allocating the paid amount against it.

### Step 1: Calculating Due Amounts (`calculate_amounts`)

*   When a `Loan` is selected, the system calls the `calculate_amounts` function.
*   This function queries the `Loan Demand` doctype to find all unpaid or partially paid demands for the loan up to the repayment's `Posting Date`.
*   Demands exist for each component: `Principal`, `Interest`, `Penalty`, and `Charges`.
*   The function sums up all outstanding demands to calculate the `Payable Amount`.

### Step 2: Allocating the Paid Amount (`allocate_amount_against_demands`)

This is the most critical function in the doctype. When a user enters the `Amount Paid`, this function distributes it among the various outstanding components.

*   **Allocation Order**: The allocation does not happen randomly. It follows a strict priority order defined in the `Loan Demand Offset Order` master. The default order is typically:
    1.  Penalty
    2.  Charges
    3.  Interest
    4.  Principal
*   **Process**: The function takes the `Amount Paid` and settles the demands in the defined priority order. For example, it will pay off all outstanding penalty demands first before moving to charges, and so on.
*   **Tracking**: The allocation details are stored in the `Repayment Details` child table, showing exactly how much of the paid amount was applied to each specific `Loan Demand`.

## 3. Detailed Validations (`validate`)

Several checks are performed to ensure the integrity of the repayment:

*   **Future Entry Check (`check_future_entries`)**: Prevents a backdated repayment from being entered if there are already other repayments recorded after that date. This forces users to process repayments chronologically.
*   **Amount Validation (`validate_amount`)**: Ensures that for a `Normal Repayment`, the `Amount Paid` does not exceed the total `Payable Amount`.
*   **Moratorium Check (`no_repayments_during_moratorium`)**: Prevents repayments during a moratorium period unless they are for settling moratorium interest.

## 4. Detailed Actions on Submission (`on_submit`)

Submitting a Loan Repayment triggers a complex chain of events:

*   **1. General Ledger Entries (`make_gl_entries`)**:
    *   This function posts the core accounting transaction. A standard entry involves:
        *   **Debit**: `Payment Account` (The bank/cash account where money was received).
        *   **Credit**: `Loan Account` (The borrower's liability account, reducing their outstanding balance).
    *   If interest or penalty is paid, corresponding credits are also made to the `Interest Income Account` and `Penalty Income Account`.

*   **2. Update Loan Demands (`update_demands`)**:
    *   The status of the `Loan Demand` documents that were settled by this repayment is updated to **Paid** or **Partially Paid**. This ensures they are not picked up in future repayment calculations.

*   **3. Update Loan Status (`auto_close_loan`)**:
    *   After the payment is applied, the system checks if the total outstanding balance of the loan is zero.
    *   If it is, the status of the parent `Loan` is automatically updated to **Closed**.

*   **4. Pre-payment and Restructuring**:
    *   If the `Repayment Type` was **Pre-payment** or **Advance Payment**, the submission triggers the creation of a `Loan Restructure` document.
    *   This `Loan Restructure` then automatically creates a new, recalculated `Loan Repayment Schedule` for the remaining loan tenure.

*   **5. Backdated Reposting (`create_repost`)**:
    *   If the `is_backdated` checkbox is checked, the system does not submit the repayment directly.
    *   Instead, it enqueues a background job (`create_repost`) that cancels and re-submits all loan transactions (repayments, accruals, etc.) that occurred after the posting date of this backdated repayment. This ensures all subsequent calculations are corrected based on the backdated entry.

## 5. Detailed Actions on Cancellation (`on_cancel`)

Cancelling a submitted repayment meticulously reverses all the actions taken during submission:

*   **1. Reverse GL Entries**: A reversing Journal Entry is posted to negate the accounting impact.
*   **2. Revert Demand Status**: The `Loan Demand` statuses are changed back from "Paid" to "Unpaid".
*   **3. Cancel Loan Restructure**: If a `Loan Restructure` was created, it is also cancelled.
*   **4. Re-open Loan**: If the repayment had closed the loan, the `Loan` status is reverted to **Active**.

## 6. Key API Functions

*   **`calculate_amounts(...)`**: A whitelisted function that can be called to get the total amount due for a loan on a given date.
*   **`post_bulk_payments(...)`**: A powerful whitelisted function that accepts a list of payments and processes them in bulk. This is essential for operational efficiency, as it allows for the import and processing of many repayments at once. It intelligently groups the payments by loan and processes them in chronological order.

## 7. Detailed Hooks Logic

The `Loan Repayment` doctype has a complex set of hooks to manage the validation, allocation, and submission process.

### `before_validate()`
*   **`set_repayment_account`**: This simple hook ensures that a default `Payment Account` is fetched from the selected `Mode of Payment`.

### `validate()`
This is the main validation hook and runs in a specific order to ensure data integrity before saving.
1.  **`calculate_amounts`**: Fetches all due demands to calculate total payable amounts.
2.  **`set_missing_values`**: Populates fields like `Applicant`, `Loan Product`, etc., from the parent `Loan`.
3.  **Validation Checks**: Runs a series of validation functions:
    *   `validate_repayment_type()`: Ensures the repayment type is valid.
    *   `validate_disbursement_link()`: Checks for valid disbursement links.
    *   `no_repayments_during_moratorium()`: Prevents entries during a moratorium.
    *   `check_future_entries()`: Prevents backdated entries if future entries exist.
    *   `validate_amount()`: Checks if the paid amount is valid for the repayment type.
4.  **`allocate_amount_against_demands`**: This is the core logic engine. It takes the `Amount Paid` and allocates it against outstanding demands (penalty, charges, interest, principal) based on the `Loan Demand Offset Order`. It populates the `Repayment Details` child table with the allocation results.

### `on_update()`
This hook is primarily for handling pre-payments.
*   If the repayment is a **Pre-payment** or **Advance Payment**, and the amount paid is less than the total outstanding principal, this hook triggers the creation or update of a **Draft** `Loan Restructure` document. This allows the user to see the effect of the pre-payment on the loan schedule before the repayment is formally submitted.

### `on_submit()`
The submission hook orchestrates the entire transaction and its downstream effects.
1.  **Backdated Reposting (`create_repost`)**: If `is_backdated` is checked, the hook stops here and queues a background job. The job will cancel and resubmit all subsequent transactions for the loan to ensure calculations are correct.
2.  **Pre-payment Charges**: Creates a `Sales Invoice` for any applicable pre-payment charges.
3.  **Reverse Future Accruals**: For pre-payments, it reverses any interest accruals that were booked for future dates, as the principal is now changing.
4.  **Final Allocation**: Re-runs `allocate_amount_against_demands` to ensure the final allocation is correct before creating GL entries.
5.  **Create Loan Restructure**: If it's a pre-payment, it submits the `Loan Restructure` document, which in turn generates the new repayment schedule.
6.  **Book Unbooked Interest**: Creates an on-the-fly `Loan Interest Accrual` for any interest that was earned but not yet formally accrued by the background job.
7.  **Make GL Entries**: Posts the final, audited General Ledger entries for the transaction.
8.  **Update Demands**: Updates the status of all settled `Loan Demand` documents.
9.  **Update Paid Amounts on Loan**: Updates the summary fields (`total_principal_paid`, `total_interest_paid`, etc.) on the parent `Loan` document.
10. **Auto Close Loan**: Checks if the loan balance is zero and, if so, sets the `Loan` status to "Closed".

### `on_cancel()`
This hook meticulously reverses every action taken during `on_submit`.
1.  **Cancel Loan Restructure**: Finds and cancels any `Loan Restructure` created by this repayment.
2.  **Make Reversing GL Entries**: Posts a reverse journal entry.
3.  **Revert Demands**: Updates the status of the `Loan Demand` documents back to "Unpaid".
4.  **Update Paid Amounts on Loan**: Reverts the summary fields on the parent `Loan` document.
5.  **Re-open Loan**: If the loan was closed by this repayment, it sets the status back to "Active".
6.  **Cancel Auto-generated Waivers**: If the repayment automatically triggered a waiver, that waiver document is also cancelled. 