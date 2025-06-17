import math

import frappe
from frappe.utils import add_months, cint, flt, get_last_day, getdate

frappe.utils.logger.set_log_level("INFO")
logger = frappe.logger("loan_repayment", allow_site=True, file_count=10, max_size=10485760)

def add_single_month(date):
	if getdate(date) == get_last_day(date):
		return get_last_day(add_months(date, 1))
	else:
		return add_months(date, 1)


def get_monthly_repayment_amount(loan_amount, rate_of_interest, repayment_periods, frequency):
	if frequency == "One Time":
		repayment_periods = 1

	if rate_of_interest:
		monthly_interest_rate = flt(rate_of_interest) / (get_frequency(frequency) * 100)
		monthly_repayment_amount = math.ceil(
			(loan_amount * monthly_interest_rate * (1 + monthly_interest_rate) ** repayment_periods)
			/ ((1 + monthly_interest_rate) ** repayment_periods - 1)
		)
	else:
		monthly_repayment_amount = math.ceil(flt(loan_amount) / repayment_periods)
	return monthly_repayment_amount


def get_frequency(frequency):
	return {
		"Monthly": 12,
		"Bi-Weekly": 26,
		"Weekly": 52,
		"Daily": 365,
		"Quarterly": 4,
		"One Time": 1,
	}.get(frequency)


def set_demand(row_name):
	frappe.db.set_value("Repayment Schedule", row_name, "demand_generated", 1)


def get_amounts(
    balance_amount,
    rate_of_interest,
    days,
    months,
    monthly_repayment_amount,
    carry_forward_interest=0,
    previous_interest_amount=0,
    additional_principal_amount=0,
    pending_prev_days=0,
):
    user = frappe.session.user if hasattr(frappe.session, "user") else "system"
    logger.info(f"{user} called get_amounts with params: balance_amount={balance_amount}, "
                f"rate_of_interest={rate_of_interest}, days={days}, months={months}, "
                f"monthly_repayment_amount={monthly_repayment_amount}, "
                f"carry_forward_interest={carry_forward_interest}, "
                f"previous_interest_amount={previous_interest_amount}, "
                f"additional_principal_amount={additional_principal_amount}, "
                f"pending_prev_days={pending_prev_days}")

    precision = cint(frappe.db.get_default("currency_precision")) or 2

    if additional_principal_amount:
        current_balance_amount = additional_principal_amount
        additional_principal_amount = 0
        logger.info(f"Using additional_principal_amount: {current_balance_amount}")
    else:
        current_balance_amount = balance_amount

    interest_amount = flt(
        current_balance_amount * flt(rate_of_interest) * days / (months * 100), precision
    )
    logger.info(f"Calculated interest_amount: {interest_amount}")

    principal_amount = monthly_repayment_amount - flt(interest_amount)
    logger.info(f"Calculated principal_amount: {principal_amount}")

    if carry_forward_interest:
        interest_amount += carry_forward_interest
        logger.info(f"Added carry_forward_interest: {carry_forward_interest}, updated interest_amount: {interest_amount}")

    if previous_interest_amount > 0:
        interest_amount += previous_interest_amount
        principal_amount -= previous_interest_amount
        logger.info(f"Added previous_interest_amount: {previous_interest_amount}, updated interest_amount: {interest_amount}, updated principal_amount: {principal_amount}")
        previous_interest_amount = 0

    if interest_amount > monthly_repayment_amount:
        previous_interest_amount = interest_amount - monthly_repayment_amount
        interest_amount = monthly_repayment_amount
        principal_amount = 0
        logger.info(f"Interest amount exceeds monthly_repayment_amount. Setting previous_interest_amount: {previous_interest_amount}, "
                    f"interest_amount: {interest_amount}, principal_amount: {principal_amount}")

    balance_amount = flt(balance_amount + interest_amount - monthly_repayment_amount, 2)
    logger.info(f"Updated balance_amount: {balance_amount}")

    if balance_amount < 0:
        principal_amount += balance_amount
        balance_amount = 0.0
        logger.info(f"Balance less than 0. Adjusted principal_amount: {principal_amount}, balance_amount set to 0.")

    total_payment = principal_amount + interest_amount

    if pending_prev_days > 0:
        days += pending_prev_days
        pending_prev_days = 0
        logger.info(f"Added pending_prev_days to days: {days}")

    logger.info(
        f"Returning: interest_amount={interest_amount}, principal_amount={principal_amount}, "
        f"balance_amount={balance_amount}, total_payment={total_payment}, days={days}, previous_interest_amount={previous_interest_amount}"
    )

    return (
        interest_amount,
        principal_amount,
        balance_amount,
        total_payment,
        days,
        previous_interest_amount,
    )


def get_loan_partner_details(loan_partner):
	loan_partner_details = frappe.db.get_value(
		"Loan Partner",
		loan_partner,
		[
			"partner_loan_share_percentage",
			"repayment_schedule_type",
			"receivable_account",
			"credit_account",
			"enable_partner_accounting",
		],
		as_dict=True,
	)

	return loan_partner_details
