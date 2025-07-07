# Loan Interest Accrual Flow

This document describes the `Loan Interest Accrual` doctype, which handles the time-based recognition of interest income from loans.

## 1. Core Purpose

The purpose of `Loan Interest Accrual` is to recognize interest income as it is *earned*, not just when it is *paid*. This adheres to the accrual basis of accounting. It creates a journal entry to record the interest that has accumulated on a loan over a specific period (typically daily), even before a payment or a demand is made.

This process ensures that the company's financial statements accurately reflect the interest revenue earned during each accounting period.

## 2. Automatic Creation Process

Loan Interest Accrual records are almost always created by an automated background process.

*   **`Process Loan Interest Accrual`**: This is a scheduled background job that typically runs daily.
*   **Scanning Loans**: The job scans for all active loans.
*   **Calculating Interest**: For each loan, it calculates the interest earned since the last accrual date. The core calculation is handled by the `get_interest_for_term` function, which is essentially: `(Outstanding Principal * Annual Rate of Interest * Days) / (Days in Year * 100)`.
*   **Creating the Record**: The system then calls the `make_loan_interest_accrual_entry` function, which creates the `Loan Interest Accrual` document for the calculated amount.

## 3. Detailed Actions on Submission (`on_submit`)

The submission of a `Loan Interest Accrual` document triggers the core accounting event.

### General Ledger Entries (`make_gl_entries`)

The system posts a Journal Entry with the following debits and credits:
*   **Debit**: `Interest Accrued Account` (This is an asset account on the Balance Sheet, representing money that is earned but not yet received).
*   **Credit**: `Interest Income Account` (This is a revenue account on the Profit and Loss Statement, recognizing the income).

This entry formally records the earned interest in the company's books.

### Handling for Non-Performing Assets (NPA)

The behavior changes if the parent `Loan` is marked as an NPA.
*   When an accrual happens for an NPA loan, an additional Journal Entry is created via the `make_suspense_journal_entry` function.
*   This entry moves the recognized interest from the regular `Interest Income Account` to an `Interest in Suspense Account`.
*   This ensures that the company's profit is not overstated with income that has a high probability of not being collected.

## 4. Detailed Actions on Cancellation (`on_cancel`)

Cancelling a `Loan Interest Accrual` record reverses all its actions:
*   **Reverse GL Entries**: It calls `make_gl_entries` with the `cancel=1` flag, which posts a reversing Journal Entry to negate the original accounting transaction.
*   **Reverse Suspense Entry**: If an interest-in-suspense entry was created, it is also found and cancelled.

## 5. Key Utility Functions

*   **`make_loan_interest_accrual_entry(...)`**: The central, non-whitelisted function used by the background job to create the accrual record and its associated data.
*   **`get_effective_interest_rate(...)`**: A utility to find the correct interest rate to be applied on a given date, which is especially important for floating-rate loans.
*   **`reverse_loan_interest_accruals(...)`**: A function to find and cancel all accruals for a loan, often used during backdated reposting or loan cancellation to clean up old entries.

## 6. Detailed Hooks Logic

The hooks for `Loan Interest Accrual` are focused on data validation and posting the correct accounting entries for both standard and NPA loans.

### `validate()`
This hook ensures that the accrual entry is valid and chronologically correct.
*   It checks that the `interest_amount` is not zero.
*   It fetches the `last_accrual_date` for the loan to ensure there are no gaps in the accrual timeline.
*   **`validate_last_accrual_date_before_current_posting_date`**: This crucial validation prevents the creation of an accrual if another accrual for a later date already exists. This enforces strict chronological ordering of interest calculations.

### `on_submit()`
This hook posts the accounting entries to recognize the earned interest.
1.  **`make_gl_entries`**: This is the primary function. It creates a journal entry to Debit the `Interest Accrued Account` and Credit the `Interest Income Account` (or the corresponding penalty accounts if it's a penal interest accrual).
2.  **NPA Handling**: If the loan is marked as NPA (`is_npa` is checked), it then calls `make_suspense_journal_entry`. This function creates a second journal entry to move the amount from the income account to the `Interest in Suspense` account, ensuring that un-collectible income does not appear on the Profit and Loss statement.

### `on_cancel()`
This hook reverses the accounting entries created during submission.
1.  **`make_gl_entries(cancel=1)`**: This posts a reversing journal entry for the main accrual transaction.
2.  **Cancel Suspense Entry**: If a suspense journal entry was created (`normal_interest_journal_entry` field is set), it fetches that journal entry and cancels it as well. 