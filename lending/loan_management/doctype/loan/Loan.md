# Loan Document Flow

This document outlines the complete flow for creating and managing a Loan in the system.

## 1. Loan Creation

A new loan can be created from a 'Loan Application' or directly as a new 'Loan' document. The process starts by creating a new loan record and filling in the necessary details.

### Key Fields:

*   **Applicant Type**: Specifies the type of applicant (e.g., Customer, Employee).
*   **Applicant**: The specific customer or employee applying for the loan.
*   **Company**: The company providing the loan.
*   **Loan Product**: A template that defines the terms and conditions of the loan, such as interest rates, charges, and accounting details.
*   **Loan Amount**: The principal amount of the loan.
*   **Interest Rate Type**: Can be 'Fixed' or 'Floating'.
*   **Rate of Interest**: The annual interest rate for the loan.
*   **Repayment Method**: Defines how the loan will be repaid (e.g., over a number of periods).
*   **Repayment Periods**: The total number of installments for repayment.
*   **Posting Date**: The date the loan is officially recorded.

Upon creation, the loan is in the **Draft** status.

## 2. Detailed Validations

This section explains each validation check performed when a loan is saved or submitted. These checks ensure the integrity and correctness of the loan data.

*   **Loan Amount (`validate_loan_amount`)**:
    *   For **Term Loans**, the `Loan Amount` must be greater than zero.
    *   For **Line of Credit** loans, the `Maximum Loan Amount` must be greater than zero.

*   **Accounting and Company (`validate_accounts`)**:
    *   Verifies that the `Payment Account`, `Loan Account`, `Interest Income Account`, and `Penalty Income Account` all belong to the same `Company` specified in the loan document. This prevents cross-company accounting errors.

*   **Cost Center (`validate_cost_center`)**:
    *   If a `Rate of Interest` is specified (i.e., it's not a zero-interest loan), a `Cost Center` is mandatory for accounting purposes.
    *   If no cost center is provided, the system attempts to use the default cost center from the `Company` master. If that is also not set, it will throw an error.

*   **Sanctioned Limit (`check_sanctioned_amount_limit`)**:
    *   The system checks the total of all active loans for the applicant against a sanctioned limit.
    *   This limit is fetched from either the `Loan Product` or the general `Lending Settings`.
    *   If the new loan amount causes the applicant to exceed this limit, the system will prevent the loan creation/submission.

*   **Repayment Terms (`validate_repayment_terms`)**:
    *   For term loans using the `Repay Over Number of Periods` method, the `Repayment Periods` field is mandatory.

*   **Special EMI (`validate_special_emi`)**:
    *   Validates the configuration for special EMI payments.
    *   If `Enable Special EMI` is checked, the `Special EMI Period` and `Special EMI Amount` fields become mandatory.
    *   It ensures that the `Special EMI Period` is not greater than or equal to the total `Repayment Periods`.

## 3. Loan Submission (Sanctioning)

Once all validations pass, the loan can be submitted. The submission triggers a series of automated actions.

### Detailed Actions on Submission (`on_submit`)

*   **1. Status Update**: The loan's `status` is officially changed from **Draft** to **Sanctioned**. This indicates that the loan is approved and ready for disbursement.

*   **2. Link Security Assignments (`link_loan_security_assignment`)**:
    *   If the loan is a **Secured Loan**, the system finds all securities that have been assigned to the applicant via the `Loan Security Assignment` doctype.
    *   It then links these assignments to the loan by updating their `loan` field and sets the status of these assignments to **Pledged**. This formally marks the securities as collateral against the loan.

*   **3. Create Loan Limit Change Log (`create_loan_limit_change_log`)**:
    *   A record is created in the `Loan Limit Change Log` to document the sanctioning of the loan amount.
    *   This log entry, with the event "Loan Booking", serves as an audit trail for changes in the applicant's utilized credit limit.

## 4. Loan Statuses

A loan progresses through several statuses during its lifecycle:

*   **Draft**: The initial state of a loan before submission.
*   **Sanctioned**: The loan has been approved but not yet disbursed.
*   **Partially Disbursed**: A portion of the loan amount has been disbursed.
*   **Disbursed**: The full loan amount has been disbursed to the applicant.
*   **Active**: The loan is active, and repayments are being made.
*   **Loan Closure Requested**: The applicant has requested to close the loan.
*   **Closed**: The loan is fully repaid and closed.
*   **Written Off**: The loan is deemed unrecoverable and written off.
*   **Settled**: The loan is settled for an amount different from the outstanding balance.

## 5. Detailed Actions on Cancellation (`on_cancel`)

If a **Sanctioned** loan is cancelled, the system performs the following actions to revert the changes:

*   **1. Cancel Repayment Schedules (`cancel_and_delete_repayment_schedule`)**:
    *   The system locates any `Loan Repayment Schedule` that was created for the loan.
    *   If a schedule exists, it is cancelled. If the schedule was still in a draft state, it is deleted entirely.

*   **2. Cancel Security Assignments (`cancel_loan_security_assignment`)**:
    *   The system finds all `Loan Security Assignment` documents linked to the loan.
    *   It unlinks the loan from these assignments and updates their status to **Cancelled**, effectively releasing the pledged securities.

*   **3. Update Loan Status**: The status of the loan is set to **Cancelled**.

This flow provides a comprehensive overview of the loan management process, from creation to closure, ensuring all necessary checks and balances are in place.

## 6. Detailed Hooks Logic

The `Loan` doctype has several key hooks that automate processes and ensure data integrity at different stages of the document lifecycle.

### `validate()`
This hook is triggered every time the loan document is saved. It acts as the primary gatekeeper for data quality by executing a series of checks in a specific order:
1.  **`set_status`**: Initializes the status to "Draft" if it's a new loan.
2.  **`set_loan_amount`**: Copies the `Maximum Loan Amount` to the `Loan Amount` field for Line of Credit loans.
3.  **`validate_loan_amount`**: Ensures loan amounts are greater than zero.
4.  **`set_missing_fields`**: Populates `Applicant Name` and other details from the selected applicant.
5.  **`validate_cost_center`**: Enforces that a cost center is linked if there's an interest rate.
6.  **`validate_accounts`**: Confirms all specified accounts belong to the loan's company.
7.  **`check_sanctioned_amount_limit`**: Verifies the loan does not exceed the applicant's credit limit.
8.  **`set_cyclic_date`**: Automatically calculates the repayment start date for certain monthly loans.
9.  **`set_default_charge_account`**: Fetches and sets the default income account for any added loan charges.
10. **`validate_repayment_terms`**: Makes repayment periods mandatory for certain term loans.
11. **`validate_special_emi`**: Checks that special EMI terms are logical and complete.
12. **`calculate_totals`**: If the loan is not new, it updates the total payment, principal, and interest fields.

### `on_submit()`
This hook executes when the user submits the loan, formally sanctioning it.
1.  **`link_loan_security_assignment`**: Finds and links any available security assignments for the applicant to the loan, changing their status to "Pledged".
2.  **`create_loan_limit_change_log`**: Creates a log entry to record that the sanctioned loan amount is now utilizing the applicant's credit limit.

### `on_cancel()`
This hook executes if a submitted loan is cancelled. It reverts the actions taken during `on_submit`.
1.  **`cancel_and_delete_repayment_schedule`**: Cancels any submitted repayment schedules or deletes any draft ones linked to the loan.
2.  **`cancel_loan_security_assignment`**: Finds all pledged security assignments linked to the loan, unlinks them, and sets their status to "Cancelled".
3.  The status of the loan itself is set to "Cancelled".

### `on_update_after_submit()`
This hook is triggered if a submitted loan is modified and saved (if allowed by permissions).
*   It primarily handles changes to the NPA (Non-performing Asset) status and the account freeze status.
*   If the `unmark_npa` checkbox is ticked, it calls `update_npa_check` to potentially upgrade the loan's NPA status.
*   If the `freeze_account` checkbox is changed, it creates a `Loan Freeze Log` to record the event.

---

## 7. Advanced Features and Automated Processes

Beyond the core lifecycle, the Loan doctype includes sophisticated features for handling risk and accounting for complex scenarios.

### NPA (Non-Performing Asset) Management

The system has a comprehensive, automated process for tracking and managing Non-Performing Assets (NPAs).

*   **Automatic NPA Marking**: A loan is automatically marked as an NPA based on the `Days Past Due` (DPD) exceeding a threshold defined in `Lending Settings`. This is handled by the `update_loan_and_customer_status` function, which runs periodically.
*   **Manual NPA Marking**: A loan can also be manually flagged as an NPA by a user.
*   **NPA Logging**: Every time a loan's NPA status changes, a record is created in the `Loan NPA Log` for audit purposes.
*   **Customer-Level NPA**: When a loan is marked as NPA, the system can be configured to mark all other active loans for that same applicant as NPA, ensuring a unified view of the applicant's credit risk. This is handled by `update_all_linked_loan_customer_npa_status`.
*   **Watch Period**: After an NPA loan is regularized (i.e., payments are made), it can be put into a "Watch Period" for a specified duration (configured in `Lending Settings`). This ensures the loan is monitored closely before being fully upgraded from NPA status.

### Days Past Due (DPD) Calculation (`update_days_past_due_in_loans`)

The DPD value is a critical metric for assessing loan health. It is calculated by a scheduled job that runs daily.

*   The function iterates through all active loans and compares the current date with the due dates on the `Loan Repayment Schedule`.
*   It calculates the number of days overdue for the oldest unpaid installment.
*   Based on the DPD, it updates the `Loan Classification` (e.g., Standard, Sub-Standard, Doubtful) according to the rules in `Loan Classification Range`.
*   A `Days Past Due Log` is created to maintain a historical record of the DPD for each loan.

### Interest in Suspense Accounting

When a loan becomes an NPA, standard accounting practices require that any further interest accrued should not be recognized as income immediately. Instead, it is moved to a suspense account.

*   **`move_unpaid_interest_to_suspense_ledger`**: This function is triggered when a loan is marked as NPA.
*   It calculates all the unpaid interest that has been accrued and recognized as income to date.
*   It then creates a reversing Journal Entry to move this amount from the `Interest Income Account` to an `Interest in Suspense` account. This ensures that the income statement is not overstated with income that is unlikely to be received.

## 8. Key API Functions

The Loan doctype provides several whitelisted (`@frappe.whitelist()`) functions that can be called from other parts of the system or via the API.

### `request_loan_closure(loan, posting_date)`
Initiates the loan closure process. It changes the loan status to "Loan Closure Requested" and can optionally trigger an automatic closure process if configured.

### `make_loan_disbursement(...)`
Creates a `Loan Disbursement` document for the loan. This is the function that facilitates the actual payout of money to the applicant. It takes the loan, disbursement amount, and other details as arguments and creates the corresponding accounting entries.

### `make_repayment_entry(...)`
This function is a utility to prepare a `Journal Entry` for a loan repayment. It's typically used to create a payment entry against an outstanding loan.

### `make_loan_write_off(...)`
Creates a `Loan Write Off` document. This is used when a loan is deemed unrecoverable. It creates the necessary Journal Entry to move the outstanding loan balance from the `Loan Account` to a `Write-Off Account`.

### `unpledge_security(...)`
This function is used to release securities that were pledged against the loan. It creates a `Loan Security Unpledge` document, which formally records the release of the collateral. It can be used for a full or partial release of securities.

## Glossary of Terms

*   **Cost Center**: An accounting dimension used to track costs and revenues for a specific department or business unit within a company.
*   **GL Entry (General Ledger Entry)**: A record of a financial transaction in the company's books. Every transaction creates at least two entries (a debit and a credit) in different accounts.
*   **NPA (Non-Performing Asset)**: A loan for which the borrower has stopped making payments for a specified period. It's an indicator of bad debt risk.
*   **Pledged**: A status indicating that an asset (like a security) has been formally committed as collateral for a loan.
*   **Sanctioned Limit**: The maximum amount of money a lender has agreed to lend to a borrower.
*   **Term Loan**: A loan that is repaid in regular, scheduled installments over a fixed period.
*   **Line of Credit**: A flexible loan from a financial institution that consists of a defined amount of money that you can access as needed and repay either immediately or over time. 