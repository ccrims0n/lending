# Loan Repayment Schedule Flow

This document explains the creation, management, and logic behind the Loan Repayment Schedule.

## 1. Schedule Creation

A `Loan Repayment Schedule` is automatically created in **Draft** status when a `Loan Disbursement` for a term loan is saved. It acts as a detailed amortization plan.

*   It is linked to the parent `Loan` and the specific `Loan Disbursement`.
*   The `validate` method orchestrates the creation by calling a series of helper functions to build the schedule table row by row.

## 2. Detailed Calculation Logic

The core of this doctype is the `repayment_schedule` table. The system calculates this schedule within the `make_customer_repayment_schedule` function, which loops until the loan balance becomes zero.

### Repayment Method Logic (`validate_repayment_method`):
*   **Repay Over Number of Periods**: The EMI is calculated using a standard formula via `get_monthly_repayment_amount`. This EMI remains constant.
*   **Repay Fixed Amount per Period**: The `Monthly Repayment Amount` is a fixed value specified in the `Loan`, and the number of periods will vary.

### Core Calculation Loop (`make_repayment_schedule`):
For each installment, the loop does the following:
1.  **Determines Payment Date**: Calculates the next payment date based on the `repayment_frequency`.
2.  **Calculates Days**: Computes the number of days between the last payment date and the current one for accurate interest calculation.
3.  **Calculates Amounts (`get_amounts` function)**: This is the heart of the EMI calculation.
    *   **Interest Component**: `(Outstanding Principal * Annual Rate of Interest * Days in Period) / (Days in Year * 100)`.
    *   **Principal Component**: `EMI Amount - Interest Component`.
    *   **Balance Principal**: `Outstanding Principal - Principal Component`.
    *   **Edge Case Handling**: If the calculated interest is higher than the EMI, the entire EMI is treated as interest, and the unpaid interest is carried forward to the next period. If the final balance is less than the EMI, the principal is adjusted to make the final balance exactly zero.
4.  **Adds Row to Table**: Appends a new row to the `repayment_schedule` table with the calculated principal, interest, and balance amounts for that period.

### Broken Period Interest (`add_broken_period_interest`):
*   **Condition**: This is triggered if the period between the `Disbursement Date` and the `Repayment Start Date` is not a standard full period.
*   **Logic**: It calculates interest just for this initial "broken" period. This interest is not part of the regular EMI.
*   **Accounting**: A separate `Loan Interest Accrual` entry is created for this amount, and it is typically added to the first EMI, making the first payment higher than the rest.

## 3. Detailed Actions on Submission (`on_submit`)

When a `Loan Repayment Schedule` is submitted (usually triggered by submitting the `Loan Disbursement`), the following occurs:

*   **Status Change**: The schedule's status becomes **Active**.
*   **Advance/Pre-payment Demand (`make_demand_for_advance_payment`)**:
    *   **Condition**: This logic runs only if the schedule is created as part of a `Loan Restructure` of type "Advance Payment" or "Pre Payment".
    *   **Action**: It immediately creates `Loan Demand` records for the principal and interest components of the advance payment. This makes the advance amount officially due and payable.
    It also creates a `Loan Interest Accrual` entry for any unaccrued interest between the last accrual date and the pre-payment date.

## 4. Moratorium Handling

*   **Logic**: During the schedule generation loop, if the current payment date falls within the `moratorium_end_date`, the logic changes.
*   **Principal Moratorium**: The `Principal Amount` for the row is set to 0, and the `Interest Amount` is calculated as usual. The entire EMI for that period is just the interest.
*   **EMI Moratorium**: Both `Principal Amount` and `Interest Amount` are set to 0.
*   **Treatment of Interest**: The interest accrued during the moratorium is handled based on the `treatment_of_interest` flag:
    *   **Capitalize**: The accrued interest is added back to the outstanding principal amount after the moratorium ends.
    *   **Add to first repayment**: The total accrued interest is added to the interest component of the first EMI after the moratorium.

## 5. Detailed Actions on Cancellation (`on_cancel`)

When a schedule is cancelled:
*   **Reverse BPI Accrual**: It finds the specific `Loan Interest Accrual` for the broken period interest and cancels it.
*   **Reverse Interest Accruals (`reverse_loan_interest_accruals`)**: If the `reverse_interest_accruals` flag is set, the system finds and cancels all `Loan Interest Accrual` entries that were generated based on this schedule. This is run as a background job.
*   **Reverse Demands (`reverse_demands`)**: It cancels all `Loan Demand` records linked to this schedule, also as a background job.

This detailed flow ensures accurate and automated management of loan repayments, accommodating various scenarios like moratoriums and restructuring while maintaining financial integrity.

## 6. Detailed Hooks Logic

The primary logic of the `Loan Repayment Schedule` is housed in the `validate` hook, which is responsible for generating the entire amortization table.

### `validate()`
This hook is the engine of the doctype, triggered every time the document is saved. It builds the repayment schedule from scratch.
1.  **`get_effective_interest_rate`**: It first determines the correct interest rate to use based on the posting date, especially for floating rate loans.
2.  **`set_repayment_period`**: Determines the total number of installments.
3.  **`set_repayment_start_date`**: Calculates the start date, factoring in moratoriums if any.
4.  **`validate_repayment_method`**: Calculates the EMI amount if the method is "Repay Over Number of Periods".
5.  **`make_customer_repayment_schedule`**: This function orchestrates the creation of the customer's repayment schedule. It doesn't perform the calculations itself but calls a series of helper methods in a specific order to build the full amortization table.

    The process is as follows:

    1.  **Initialization**:
        *   `set_repayment_start_date()`: Determines the date of the first installment.
        *   `validate_repayment_method()`: Ensures the repayment method is valid and calculates the EMI if the method is "Repay Over Number of Periods".
        *   `set_repayment_period()`: Calculates the total number of periods if not already specified.
        *   The existing `repayment_schedule` table is cleared.

    2.  **Handling Existing Schedules**:
        *   If the loan is not a "Line of Credit" and is not a new loan (i.e., it's a subsequent disbursement or a restructure), the process is more complex.
        *   `add_rows_from_prev_disbursement()`: This crucial function is called to handle existing active schedules. It copies the already-paid installments from the previous schedule to the new one. This ensures continuity and that the new schedule only calculates the remaining payments. It also calculates any interest accrued between the last due date and the current disbursement/restructure date.

    3.  **Generating the Schedule**:
        *   `make_repayment_schedule()`: This is the core function that generates the actual repayment rows. It takes the outstanding balance, interest rate, and remaining periods as inputs and builds the amortization table line by line until the loan balance is zero. It calculates the principal and interest components for each installment.

    This function acts as a controller, preparing the data and then delegating the heavy lifting of schedule generation to `make_repayment_schedule`.
    
6.  **`make_repayment_schedule`**: This is the core function where the amortization schedule is actually built. It operates as a loop that continues until the `balance_amount` of the loan becomes zero.

    **Key Inputs**:
    *   `schedule_field`: The name of the table to populate (e.g., `repayment_schedule`).
    *   `balance_amount`: The outstanding principal to be repaid.
    *   `rate_of_interest`: The applicable interest rate.
    *   `completed_tenure`: The number of installments already paid or carried over.
    *   `monthly_repayment_amount`: The EMI amount.

    **Core Loop Logic**:
    1.  **Date Calculation**: It determines the `payment_date` for the current installment using `get_next_payment_date`. This helper function simply adds the appropriate interval (e.g., 1 month, 14 days) based on the `repayment_frequency`.
    2.  **Days Calculation**: It calls `get_days_and_months` to determine the exact number of days in the current repayment period. This is crucial for accurate interest calculation, especially for non-monthly frequencies or pro-rated months.
    3.  **Amount Calculation**: It calls the `get_amounts` utility function, which performs the core financial calculations for the installment:
        *   Calculates the `interest_amount` for the period.
        *   Calculates the `principal_amount` (EMI - Interest).
        *   Calculates the new `balance_amount`.
    4.  **Moratorium Handling**: If the current `payment_date` falls within a moratorium period, it adjusts the installment. For a principal moratorium, it sets `principal_amount` to 0. For an EMI moratorium, both principal and interest are zeroed out.
    5.  **Add Row**: It calls `add_repayment_schedule_row` to append a new row to the schedule table with all the calculated values (`principal_amount`, `interest_amount`, `balance_loan_amount`, etc.).
    6.  **Final Installment Adjustment**: For the last installment, it adjusts the `principal_amount` to ensure the final `balance_loan_amount` is exactly zero, clearing out any residue from floating-point calculations.
    7.  The loop repeats until the entire loan principal is amortized.

7.  **`add_rows_from_prev_disbursement`**: This function is critical for handling scenarios beyond the first disbursement, such as loan restructures (Pre-Payment, Advance Payment) or subsequent disbursements in a partially disbursed loan. Its primary job is to ensure continuity from a previous, active repayment schedule.

    **Workflow**:
    1.  **Fetch Previous Schedule**: It finds the currently "Active" `Loan Repayment Schedule` for the same loan.
    2.  **Copy Paid Installments**: It iterates through the rows of the old schedule. Any row with a `payment_date` before the current transaction's `posting_date` is considered settled or already in progress. These rows are copied directly into the new schedule using `add_repayment_schedule_row`. This preserves the history of payments.
    3.  **Calculate Intermediate Interest**: It calculates the interest accrued between the last payment date on the old schedule and the posting date of the new transaction. This "pending" interest is passed to the `make_repayment_schedule` function, which will typically add it to the next installment's interest.
    4.  **Handle Restructures**:
        *   **Advance Payment**: It specifically creates a new row in the schedule for the advance payment itself, calculating how much of it goes towards principal and how much towards unaccrued interest.
        *   **Pre-Payment**: It recalculates the EMI based on the new, lower principal balance after the pre-payment.
    5.  **Update Principal**: It sets the `current_principal_amount` for the new schedule, factoring in any additional disbursement or principal reduction.

    This function ensures that a new schedule is not created in isolation but is a continuation of the loan's history, accurately reflecting past payments and correctly calculating future ones based on the new balance.

8.  **`make_co_lender_schedule`**: This function checks if the loan has a `Loan Partner` (co-lender) with a defined `Partner Loan Share Percentage`. If so, it creates a parallel amortization schedule in the `colender_schedule` child table. This co-lender schedule mirrors the main schedule but calculates the principal and interest amounts for each installment that are specific to the co-lender's share, providing a clear record for profit-sharing and accounting.

9.  **`set_maturity_date`**: Sets the final payment date based on the last row of the generated schedule.

### `on_submit()`
This hook is primarily designed to handle schedules created during a "Pre Payment" or "Advance Payment" restructure.
*   **`make_demand_for_advance_payment`**:
    *   It immediately creates `Loan Demand` records for the principal and interest that are being paid in advance.
    *   It also creates `Loan Interest Accrual` entries to correctly account for the interest being paid off. This ensures that the pre-payment is formally recorded and becomes due.

### `on_cancel()`
This hook meticulously reverses the financial impact of the schedule.
1.  **Cancel BPI Accrual**: It finds and cancels the specific `Loan Interest Accrual` that was created for the Broken Period Interest.
2.  **`reverse_loan_interest_accruals`**: If the `reverse_interest_accruals` flag is set (passed from the `Loan Disbursement` cancellation), it finds all interest accruals linked to this schedule and cancels them. This is run as a background job (`enqueue`) because it can be a long process.
3.  **`reverse_demands`**: Similarly, it finds and cancels all payment demands linked to this schedule, also as a background job.

---
## Glossary of Terms

*   **Amortization**: The process of spreading out a loan into a series of fixed payments over time. The repayment schedule is an amortization schedule.
*   **Broken Period Interest (BPI)**: Interest calculated for a period shorter or longer than a standard repayment period (e.g., the time between the disbursement date and the first EMI date).
*   **Capitalize**: The action of adding an unpaid amount (like interest accrued during a moratorium) to the outstanding principal of the loan. This increases the base on which future interest is calculated.
*   **EMI (Equated Monthly Installment)**: A fixed payment amount made by a borrower to a lender at a specified date each calendar month. EMIs are used to pay off both interest and principal each month.
*   **Loan Demand**: An internal document that represents an amount that has become due from the borrower (like an EMI). It serves as a basis for tracking payments and overdue status.
*   **Maturity Date**: The date on which the final payment of a loan is due, and the loan should be fully paid off.
*   **Moratorium**: A specified period during which the borrower is allowed to temporarily stop making payments (either principal only or the full EMI). 