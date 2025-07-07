# Loan Disbursement Flow

This document outlines the process of disbursing a loan to an applicant, including detailed validations, actions, and accounting entries.

## 1. Creating a Loan Disbursement

A Loan Disbursement can be created from a **Sanctioned** or **Partially Disbursed** Loan.

### Key Fields:
*   **Against Loan**: A mandatory link to the `Loan` document.
*   **Disbursement Date**: The date funds are disbursed. It defaults to the current date and is crucial for interest calculations.
*   **Disbursed Amount**: The amount being disbursed.
*   **Disbursement Account**: The company's bank or cash account from which the money is paid.
*   **Loan Account**: The applicant's liability account (fetched from the Loan).

A Loan Disbursement document is in **Draft** status upon creation.

## 2. Detailed Validations (`validate`)

Before submission, the following checks are performed:

*   **Disbursal Amount (`validate_disbursal_amount`)**:
    *   It checks that the `Disbursed Amount` is greater than zero.
    *   It calculates the total amount already disbursed for the `Against Loan`.
    *   It ensures the sum of the current `Disbursed Amount` and the previously disbursed amount does not exceed the `Sanctioned Loan Amount` from the parent loan.

*   **Repayment Start Date (`validate_repayment_start_date`)**:
    *   Ensures the `Repayment Start Date` is not before the `Disbursement Date`.

*   **Set Cyclic Date (`set_cyclic_date`)**:
    *   For **Line of Credit** loans with a monthly repayment frequency, if a `Repayment Start Date` is not specified, this function automatically calculates it based on the `Loan Product` settings (`repayment_date_on` field) and the `Disbursement Date`.

## 3. Detailed Actions on Submit (`on_submit`)

Upon submission, a series of critical actions are triggered:

*   **1. Interest Accrual for Top-up (`on_submit`)**:
    *   If the parent `Loan` was already `Partially Disbursed` (i.e., this is a top-up), the system runs an interest accrual process (`process_loan_interest_accrual_for_loans`) up to the new disbursement date to ensure interest calculations are current before the new disbursement is factored in.

*   **2. Repayment Schedule Submission (`submit_repayment_schedule`)**:
    *   Finds the corresponding **Draft** `Loan Repayment Schedule` that was created along with this disbursement.
    *   It submits this schedule, changing its status to **Active**.

*   **3. Update Existing Schedules (`update_current_repayment_schedule` & `update_repayment_schedule_status`)**:
    *   If this disbursement is a top-up, the previously **Active** repayment schedule is marked as **Outdated** because it no longer reflects the correct loan balance.

*   **4. Update Loan Status & Amounts (`set_status_and_amounts`)**:
    *   The `Disbursed Amount` on the parent `Loan` is increased by the amount of the current disbursement.
    *   The status of the parent `Loan` is re-evaluated:
        *   If `Total Disbursed Amount` equals `Loan Amount`, status becomes **Disbursed**.
        *   If `Total Disbursed Amount` is less than `Loan Amount`, status becomes **Partially Disbursed**.

*   **5. Security Value Update (`update_loan_securities_values`)**:
    *   If the loan is secured, the current market value of the pledged securities is updated to reflect the new outstanding loan amount.

*   **6. Loan Limit Log (`create_loan_limit_change_log`)**:
    *   A log is created in `Loan Limit Change Log` with the event "Disbursement" to track the change in the applicant's utilized credit limit.

*   **7. Withhold Security Deposit (`withheld_security_deposit`)**:
    *   If the `Withhold Security Deposit` flag is checked, the system creates a `Loan Security Deposit` document to record the withheld amount.

*   **8. General Ledger Entries (`make_gl_entries`)**:
    *   This is the core accounting transaction. It creates a Journal Entry with the following postings:
        *   **Debit**: `Loan Account` (Applicant's liability account). This increases the loan balance owed by the applicant.
        *   **Credit**: `Disbursement Account` (Company's bank/cash account). This reflects the outflow of cash from the company.
        *   The entry is made against the applicant (Party).
    *   If there is a **Broken Period Interest (BPI)** difference amount, an additional GL entry is posted to the `Broken Period Interest Recovery Account` defined in the `Loan Product`.

## 4. Detailed Actions on Cancel (`on_cancel`)

If a submitted disbursement is cancelled:

*   **1. Reverse GL Entries (`make_gl_entries` with `cancel=1`)**:
    *   An exact reversal of the original Journal Entry is posted:
        *   **Debit**: `Disbursement Account` (Cash comes back into the company's account).
        *   **Credit**: `Loan Account` (Applicant's liability is reduced).

*   **2. Cancel Repayment Schedule (`cancel_and_delete_repayment_schedule`)**:
    *   The **Active** `Loan Repayment Schedule` linked to this disbursement is cancelled.

*   **3. Reverse Loan Status & Amounts (`set_status_and_amounts` with `cancel=1`)**:
    *   The `Disbursed Amount` on the parent `Loan` is reduced.
    *   The status of the parent `Loan` and any previously **Outdated** repayment schedules are reverted to their prior states.

*   **4. Reverse Security Deposit (`delete_security_deposit`)**:
    *   If a security deposit was withheld, the corresponding `Loan Security Deposit` entry is cancelled.

*   **5. Reverse Charges (`make_credit_note`)**:
    *   If any charges (like processing fees) were levied during disbursement via a `Sales Invoice`, a `Credit Note` is created to reverse them. The original charges are typically created via the `make_sales_invoice_for_charge` utility function, which generates a Sales Invoice linked to the disbursement.

This flow ensures that all financial and logistical aspects of loan disbursement are handled systematically, maintaining data integrity across the lending module.

## 5. Detailed Hooks Logic

The `Loan Disbursement` doctype automates the creation of repayment schedules and accounting entries through its hooks.

### `validate()`
This hook runs every time the document is saved, ensuring all data is logical before it's stored.
1.  **`set_status`**: Sets the status to "Draft" on creation.
2.  **`set_missing_values`**: Fetches and sets details like `Loan Product`, `Repayment Method`, `Tenure`, etc., from the parent `Loan`.
3.  **`validate_disbursal_amount`**: Confirms the disbursed amount is valid and does not exceed the sanctioned loan amount.
4.  **`set_cyclic_date`**: For Line of Credit loans, it calculates the repayment start date if not manually set.
5.  **`validate_repayment_start_date`**: Ensures the repayment start date is not before the disbursement date.

### `on_update()`
This hook is triggered when a **Draft** disbursement document is saved (updated).
*   **`make_update_draft_schedule`**: This is a critical function.
    *   It checks if a draft `Loan Repayment Schedule` already exists for this disbursement.
    *   If it does, it updates the schedule with the latest details from the disbursement (e.g., if the disbursed amount was changed).
    *   If it doesn't, it creates a new draft `Loan Repayment Schedule`.
    *   This provides a real-time preview of the repayment plan as the disbursement is being prepared.

### `on_submit()`
This hook orchestrates the entire disbursement process when the user submits the document.
1.  **Interest Accrual**: If the loan was already partially disbursed, it first runs an interest accrual process to bring all calculations up to date before this new disbursement.
2.  **`submit_repayment_schedule`**: Submits the linked draft repayment schedule, making it active.
3.  **Update Schedules**: Marks any previous active schedules for the same loan as "Outdated".
4.  **`set_status_and_amounts`**: Updates the `Disbursed Amount` and `Status` on the parent loan.
5.  **`update_loan_securities_values`**: Updates the value of pledged securities.
6.  **`create_loan_limit_change_log`**: Logs the disbursement against the applicant's credit limit.
7.  **`withheld_security_deposit`**: Creates a security deposit record if applicable.
8.  **`make_gl_entries`**: Posts the core accounting entry for the disbursement.

### `on_cancel()`
This hook reverses all the actions taken by `on_submit`.
1.  **`make_gl_entries` (with `cancel=1`)**: Posts a reversing Journal Entry to cancel the accounting impact.
2.  **`set_status_and_amounts` (with `cancel=1`)**: Reverts the status and disbursed amount on the parent loan.
3.  **`cancel_and_delete_repayment_schedule`**: Cancels the active repayment schedule linked to this disbursement.
4.  **`update_repayment_schedule_status`**: Re-activates the previously outdated repayment schedule.
5.  **`delete_security_deposit`**: Deletes the security deposit record.
6.  **`make_credit_note`**: Creates a credit note to reverse any sales invoices for charges.

### `on_trash()`
This is a cleanup hook. If a user deletes a **Draft** disbursement document, this hook also deletes the corresponding draft `Loan Repayment Schedule` that was created with it.

---
## 6. Key API Functions

The `Loan Disbursement` doctype also provides API functions for integration and utility purposes.

### `get_disbursal_amount(loan, on_current_security_price)`
This whitelisted (`@frappe.whitelist()`) function calculates the maximum amount that can be disbursed for a given loan.
*   It takes the `loan` as a parameter.
*   It considers the value of the securities pledged against the loan to determine the maximum permissible disbursement amount based on the Loan-to-Value (LTV) ratio defined in the `Loan Product`.
*   The `on_current_security_price` flag, if set, forces a recalculation using the latest security prices.

---
## Glossary of Terms

*   **Broken Period Interest (BPI)**: Interest calculated for a period shorter than the normal interest period. This often occurs on the first installment if the disbursement date is not aligned with the start of a standard repayment cycle.
*   **Credit Note**: A document sent from a seller to a buyer, reducing the amount the buyer owes. It's used to reverse a `Sales Invoice`.
*   **GL Entries (General Ledger Entries)**: The fundamental records of financial transactions. Each disbursement and cancellation creates a set of these entries to ensure the books are balanced.
*   **Journal Entry**: The formal document that contains the GL Entries for a specific transaction.
*   **Sales Invoice**: A document used to bill for goods or services. In this context, it's used to levy charges (like processing fees) during disbursement.
*   **Top-up**: An additional disbursement on a loan that has already been partially disbursed, increasing the outstanding principal. 