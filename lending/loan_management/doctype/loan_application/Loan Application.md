# Loan Application Flow

This document outlines the process of creating and managing a Loan Application, which is the initial step in the loan lifecycle.

## 1. Purpose and Lifecycle

A `Loan Application` is a preliminary, non-binding document used to capture a request for a loan from an applicant. It allows the lender to perform initial checks and due diligence before sanctioning a formal loan.

The lifecycle is simple:
*   **Open**: The initial status of a new application.
*   **Approved**: The application has been reviewed and approved. An approved application can be converted into a `Loan`.
*   **Rejected**: The application has been rejected.

## 2. Key Information and Calculations

The application captures the desired loan terms and, for secured loans, the collateral being offered. The system performs several preliminary calculations to aid in the decision-making process.

### Repayment Details (`get_repayment_details`)
Based on the selected `Repayment Method`, the system provides an **estimated** repayment plan:
*   **If "Repay Over Number of Periods" is chosen**: It calculates the estimated `Repayment Amount` (EMI).
*   **If "Repay Fixed Amount per Period" is chosen**: It calculates the estimated `Repayment Periods` (tenure).
*   It also calculates the `Total Payable Interest` over the life of the loan. These are for informational purposes at the application stage and are finalized in the `Loan Repayment Schedule` later.

### Proposed Pledges for Secured Loans
If the `is_secured_loan` flag is checked, the applicant must provide details of the securities they intend to pledge in the `Proposed Pledges` table.
*   **Price Fetching**: The system automatically fetches the latest market price for each security from the `Loan Security Price` doctype.
*   **Haircut Calculation**: A "haircut" (a percentage reduction in value to mitigate risk) is applied to the market value of the securities.
*   **Maximum Loan Amount**: The final, post-haircut value of all proposed securities determines the `Maximum Loan Amount` the applicant is eligible for under this application.

## 3. Detailed Validations (`validate`)

Before an application can be approved, the system performs several critical checks:

*   **Loan Product Company**: Ensures the selected `Loan Product` belongs to the same `Company` as the application.
*   **Loan Amount Limits**:
    *   The requested `Loan Amount` cannot exceed the `maximum_loan_amount` defined in the `Loan Product`.
    *   For secured loans, the `Loan Amount` also cannot exceed the calculated `Maximum Loan Amount` based on the post-haircut value of the proposed pledges.
*   **Applicant Sanctioned Limit (`check_sanctioned_amount_limit`)**: This is a crucial check. The system calculates the applicant's total outstanding loan balance across all their existing active loans and adds the amount of the current application. This total is checked against a global `Sanctioned Amount Limit` (set in `Lending Settings` or on the `Loan Product`) to ensure the applicant does not become over-leveraged.

## 4. Creating a Loan (`create_loan`)

This is the primary action taken on an **Approved** Loan Application.

*   A custom button on the form calls the whitelisted `create_loan` function.
*   This function uses the `get_mapped_doc` utility to create a new `Loan` document.
*   It maps all the relevant fields from the `Loan Application` to the new `Loan` (e.g., `applicant`, `loan_product`, `loan_amount`, `rate_of_interest`).
*   **Crucially**, it also fetches and sets the required accounting details (`payment_account`, `loan_account`, `interest_income_account`, etc.) from the `Loan Product` onto the new `Loan`.
*   The new `Loan` is created in **Draft** status, ready to be submitted for sanctioning.

## 5. Creating Security Assignments (`create_loan_security_assignment`)

After a `Loan` has been created from the application, this function can be triggered to formalize the pledging of the securities.
*   It creates a `Loan Security Assignment` document.
*   It links the `applicant`, the `loan_application`, and the newly created `loan`.
*   It copies the securities from the `proposed_pledges` table of the application into the `Loan Security Assignment`, preparing them to be officially pledged when the loan is sanctioned.

## 6. Detailed Hooks Logic

The logic of the `Loan Application` is primarily contained within the `validate` hook, which triggers a series of functions to calculate and verify the application details.

### `validate()`
This hook runs every time the document is saved. It orchestrates the following sequence of actions:
1.  **`set_pledge_amount`**: If the loan is secured, this function iterates through the `Proposed Pledges` table. It fetches the latest price for each security, calculates the total `amount`, and then applies the specified `haircut` to determine the final `post_haircut_amount`.
2.  **`set_loan_amount`**: For a secured loan, it sums up the `post_haircut_amount` of all pledges to set the `Maximum Loan Amount`. If no `Loan Amount` was manually entered, it defaults the `Loan Amount` to this maximum value.
3.  **`validate_loan_amount`**: Ensures the requested `Loan Amount` is not zero and does not exceed the limits set on the `Loan Product` or the calculated maximum based on pledges.
4.  **`validate_repayment_method`**: Ensures that the `Repayment Periods` or `Repayment Amount` are provided, depending on the chosen `Repayment Method`.
5.  **`validate_loan_product`**: Confirms that the `Loan Product` selected is valid for the `Company` specified in the application.
6.  **`get_repayment_details`**: This function calculates the estimated EMI or tenure based on the chosen repayment method and also computes the total interest payable over the loan's lifetime for informational purposes.
7.  **`check_sanctioned_amount_limit`**: Performs the critical check against the applicant's total credit exposure to ensure they do not breach their overall sanctioned limit. 