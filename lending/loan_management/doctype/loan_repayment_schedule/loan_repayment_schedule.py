# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
	add_days,
	add_months,
	cint,
	date_diff,
	flt,
	get_first_day,
	get_last_day,
	getdate,
	nowdate,
)

from lending.loan_management.doctype.loan.loan import get_cyclic_date
from lending.loan_management.doctype.loan_demand.loan_demand import create_loan_demand
from lending.loan_management.doctype.loan_repayment_schedule.utils import (
	add_single_month,
	get_amounts,
	get_loan_partner_details,
	get_monthly_repayment_amount,
	set_demand,
)
from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import get_effective_interest_rate


# nosemgrep
class LoanRepaymentSchedule(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.co_lender_schedule.co_lender_schedule import (
			CoLenderSchedule,
		)
		from lending.loan_management.doctype.repayment_schedule.repayment_schedule import (
			RepaymentSchedule,
		)

		adjusted_interest: DF.Currency
		amended_from: DF.Link | None
		broken_period_interest: DF.Currency
		broken_period_interest_days: DF.Int
		colender_schedule: DF.Table[CoLenderSchedule]
		company: DF.Link | None
		current_principal_amount: DF.Currency
		disbursed_amount: DF.Currency
		loan: DF.Link
		loan_amount: DF.Currency
		loan_disbursement: DF.Link | None
		loan_partner: DF.Link | None
		loan_partner_rate_of_interest: DF.Float
		loan_product: DF.Link | None
		loan_restructure: DF.Link | None
		maturity_date: DF.Date | None
		monthly_repayment_amount: DF.Currency
		moratorium_end_date: DF.Date | None
		moratorium_tenure: DF.Int
		moratorium_type: DF.Data | None
		partner_base_interest_rate: DF.Percent
		partner_loan_share_percentage: DF.Percent
		partner_monthly_repayment_amount: DF.Currency
		partner_repayment_schedule_type: DF.Data | None
		posting_date: DF.Datetime | None
		rate_of_interest: DF.Float
		repayment_date_on: DF.Literal["Start of the next month", "End of the current month"]
		repayment_frequency: DF.Literal[
			"Monthly", "Daily", "Weekly", "Bi-Weekly", "Quarterly", "One Time"
		]
		repayment_method: DF.Literal["", "Repay Fixed Amount per Period", "Repay Over Number of Periods"]
		repayment_periods: DF.Int
		repayment_schedule: DF.Table[RepaymentSchedule]
		repayment_schedule_type: DF.Data | None
		repayment_start_date: DF.Date | None
		restructure_type: DF.Literal["", "Normal Restructure", "Advance Payment", "Pre Payment"]
		status: DF.Literal[
			"Initiated",
			"Rejected",
			"Active",
			"Restructured",
			"Rescheduled",
			"Outdated",
			"Draft",
			"Cancelled",
			"Closed",
		]
		total_installments_overdue: DF.Int
		total_installments_paid: DF.Int
		total_installments_raised: DF.Int
		treatment_of_interest: DF.Literal["Capitalize", "Add to first repayment"]
	# end: auto-generated types

	def validate(self):
		self.number_of_rows = 0
		# Set the effective rate of interest for this schedule
		loan_doc = frappe.get_doc("Loan", self.loan)
		self.rate_of_interest = get_effective_interest_rate(loan_doc, self.posting_date or nowdate())
		self.set_repayment_period()
		self.set_repayment_start_date()
		self.validate_repayment_method()
		self.make_customer_repayment_schedule()
		self.make_co_lender_schedule()
		self.reset_index()
		self.set_maturity_date()

	def reset_index(self):
		for idx, row in enumerate(self.get("repayment_schedule"), start=1):
			row.idx = idx

	def set_maturity_date(self):
		if self.get("repayment_schedule"):
			self.maturity_date = self.get("repayment_schedule")[-1].payment_date

	# nosemgrep
	def on_submit(self):
		self.number_of_rows = 0
		self.make_demand_for_advance_payment()

	def make_demand_for_advance_payment(self):
		from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
			get_interest_for_term,
			get_last_accrual_date,
			make_loan_interest_accrual_entry,
		)

		advance_payment = ""
		if not self.restructure_type in ("Advance Payment", "Pre Payment"):
			return
		for row in self.repayment_schedule:
			if not row.demand_generated:
				advance_payment = row
				break

		precision = cint(frappe.db.get_default("currency_precision")) or 2
		principal_balance = 0

		if self.restructure_type == "Advance Payment":
			set_demand(advance_payment.name)

		prepayment_details = frappe.db.get_value(
			"Loan Restructure",
			{"loan": self.loan, "name": self.loan_restructure},
			["unaccrued_interest", "principal_adjusted", "balance_principal"],
			as_dict=1,
		)

		interest_amount = prepayment_details.unaccrued_interest
		principal_amount = abs(prepayment_details.balance_principal)
		principal_balance = prepayment_details.balance_principal
		paid_interest_amount = interest_amount
		paid_principal_amount = principal_amount

		if flt(interest_amount) > 0:
			create_loan_demand(
				self.loan,
				self.posting_date,
				"EMI",
				"Interest",
				interest_amount,
				loan_repayment_schedule=self.name,
				loan_disbursement=self.loan_disbursement,
				repayment_schedule_detail=advance_payment.name
				if self.restructure_type == "Advance Payment"
				else None,
				paid_amount=paid_interest_amount,
			)

		create_loan_demand(
			self.loan,
			self.posting_date,
			"EMI",
			"Principal",
			principal_amount,
			loan_repayment_schedule=self.name,
			loan_disbursement=self.loan_disbursement,
			repayment_schedule_detail=advance_payment.name
			if self.restructure_type == "Advance Payment"
			else None,
			paid_amount=paid_principal_amount,
		)

		last_accrual_date = get_last_accrual_date(self.loan, self.posting_date, "Normal Interest")

		payable_interest = get_interest_for_term(
			self.company,
			self.rate_of_interest,
			self.current_principal_amount - principal_balance,
			add_days(last_accrual_date, 1),
			add_days(self.posting_date, -1),
		)

		if payable_interest > 0:
			make_loan_interest_accrual_entry(
				self.loan,
				self.current_principal_amount - principal_balance,
				flt(payable_interest, precision),
				"",
				last_accrual_date,
				add_days(self.posting_date, -1),
				"Regular",
				"Normal Interest",
				self.rate_of_interest,
				loan_repayment_schedule=self.name,
			)
		self.repayment_periods = self.number_of_rows - self.moratorium_tenure

	def on_cancel(self):
		from lending.loan_management.doctype.loan_demand.loan_demand import reverse_demands
		from lending.loan_management.doctype.loan_interest_accrual.loan_interest_accrual import (
			reverse_loan_interest_accruals,
		)

		precision = cint(frappe.db.get_default("currency_precision")) or 2

		bpi_accrual = frappe.db.get_value(
			"Loan Interest Accrual",
			{
				"loan_repayment_schedule": self.name,
				"docstatus": 1,
				"interest_amount": flt(self.broken_period_interest, precision),
			},
		)

		if bpi_accrual:
			bpi_accrual_doc = frappe.get_doc("Loan Interest Accrual", bpi_accrual)
			bpi_accrual_doc.cancel()

		if cint(self.get("reverse_interest_accruals")):
			if not frappe.flags.in_test:
				frappe.enqueue(
					reverse_loan_interest_accruals,
					loan=self.loan,
					posting_date=self.posting_date,
					loan_repayment_schedule=self.name,
					queue="long",
					enqueue_after_commit=True,
				)

				frappe.enqueue(
					reverse_demands,
					loan=self.loan,
					posting_date=self.posting_date,
					loan_repayment_schedule=self.name,
					queue="long",
					enqueue_after_commit=True,
				)
			else:
				reverse_loan_interest_accruals(
					loan=self.loan,
					posting_date=self.posting_date,
					loan_repayment_schedule=self.name,
				)

				reverse_demands(
					loan=self.loan,
					posting_date=self.posting_date,
					loan_repayment_schedule=self.name,
				)

		self.ignore_linked_doctypes = ["Loan Interest Accrual", "Loan Demand"]

		self.db_set("status", "Cancelled")

	def set_repayment_period(self):
		if self.repayment_frequency == "One Time":
			self.repayment_method = "Repay Over Number of Periods"
			self.repayment_periods = 1

		if self.restructure_type and self.repayment_periods == 1:
			self.repayment_frequency = "One Time"

	def make_customer_repayment_schedule(self):
		"""Generate customer repayment schedule with support for multiple disbursements and special EMI."""
		print("=== Starting make_customer_repayment_schedule ===")
		self.set("repayment_schedule", [])
		self.broken_period_interest = 0

		# Check if this is a subsequent disbursement
		is_subsequent = self._is_subsequent_disbursement()
		print(f"Determined is_subsequent_disbursement: {is_subsequent}")
		
		if is_subsequent:
			print("Handling as subsequent disbursement")
			self._handle_subsequent_disbursement()
		else:
			print("Handling as first disbursement")
			# First disbursement - use the original logic
			self._handle_first_disbursement()
		
		print("=== Finished make_customer_repayment_schedule ===")

	def _is_subsequent_disbursement(self):
		"""Check if this is a subsequent disbursement (not the first one)."""
		if not hasattr(self, 'loan_disbursement') or not self.loan_disbursement:
			print("No loan_disbursement found, treating as first disbursement")
			return False
		
		# Get the current disbursement details
		current_disbursement = frappe.get_doc("Loan Disbursement", self.loan_disbursement)
		current_disbursement_date = current_disbursement.disbursement_date
		current_disbursement_amount = current_disbursement.disbursed_amount
		
		print(f"Current disbursement: {self.loan_disbursement}, date: {current_disbursement_date}, amount: {current_disbursement_amount}")
		
		# Check if there are any previous disbursements
		previous_disbursements = frappe.get_all(
			"Loan Disbursement",
			filters={
				"against_loan": self.loan,
				"docstatus": 1,  # Only submitted disbursements
				"disbursement_date": ["<", current_disbursement_date]
			},
			fields=["name", "disbursed_amount", "disbursement_date"],
			order_by="disbursement_date"
		)
		
		print(f"Found {len(previous_disbursements)} previous disbursements:")
		for d in previous_disbursements:
			print(f"  - {d['name']}: {d['disbursed_amount']} on {d['disbursement_date']}")
		
		is_subsequent = len(previous_disbursements) > 0
		print(f"Is subsequent disbursement: {is_subsequent}")
		
		return is_subsequent

	def _handle_first_disbursement(self):
		"""Handle the first disbursement using the original logic."""
		# Get effective principal for new disbursement (handles multiple disbursements)
		principal = self._get_effective_principal_for_new_disbursement()
		annual_interest_rate = getattr(self, "rate_of_interest", 0)
		tenure_months = getattr(self, "repayment_periods", 0)
		
		# Get repayment start date
		if hasattr(self, 'loan_disbursement') and self.loan_disbursement:
			repayment_start_date = self._get_first_disbursement_date()
			print(f"Repayment start date from loan_disbursement: {repayment_start_date}")
		else:
			repayment_start_date = getattr(self, "repayment_start_date", None)
			print(f"Repayment start date from self: {repayment_start_date}")
			if isinstance(repayment_start_date, str):
				try:
					repayment_start_date = frappe.utils.getdate(repayment_start_date)
				except (ValueError, AttributeError):
					print("Error getting date from string")
					repayment_start_date = frappe.utils.nowdate()
			elif repayment_start_date is None:
				repayment_start_date = frappe.utils.nowdate()
				

		# Only calculate if we have valid values
		if principal > 0 and tenure_months > 0:
			try:
				# Get special EMI configuration from loan document
				loan_doc = frappe.get_doc("Loan", self.loan)
				enable_special_emi = loan_doc.get("enable_special_emi", False)
				special_emi_amount = loan_doc.get("special_emi_amount", 0)
				special_emi_period = loan_doc.get("special_emi_period", 0)
				
				# Apply special EMI if enabled and valid
				special_emi = None
				if enable_special_emi and special_emi_amount > 0 and special_emi_period > 0:
					# Create special EMI dictionary for the specified period
					special_emi_dict = {}
					for month in range(1, special_emi_period + 1):
						special_emi_dict[month] = special_emi_amount
					special_emi = special_emi_dict

				# Generate schedule using the new engine
				schedule_data = self._generate_repayment_schedule_engine(
					principal=principal,
					annual_interest_rate=annual_interest_rate,
					tenure_months=tenure_months,
					special_emi=special_emi,
					repayment_start_date=repayment_start_date,
					special_emi_period=special_emi_period
				)

				# Populate repayment schedule child table
				for i, row in enumerate(schedule_data["customer_schedule"], 1):
					self.append("repayment_schedule", {
						"idx": i,
						"payment_date": row["payment_date"],
						"number_of_days": 30,  # Approximate days per month
						"principal_amount": row["principal"],
						"interest_amount": row["interest"],
						"total_payment": row["emi"],
						"balance_loan_amount": row["balance"],
						"demand_generated": 0
					})

				# Set other fields
				self.maturity_date = schedule_data["maturity_date"]
				self.number_of_rows = schedule_data["number_of_rows"]
				self.monthly_repayment_amount = schedule_data["standard_emi"]

			except Exception as e:
				frappe.log_error(f"Error generating repayment schedule: {str(e)}", "Loan Repayment Schedule Error")
				# Set empty schedules on error
				self.repayment_schedule = []
				self.maturity_date = None
				self.number_of_rows = 0
				self.monthly_repayment_amount = 0
		else:
			# Set empty schedules for invalid values
			self.repayment_schedule = []
			self.maturity_date = None
			self.number_of_rows = 0
			self.monthly_repayment_amount = 0

	def _handle_subsequent_disbursement(self):
		"""Handle subsequent disbursements by copying past schedules and recalculating from new disbursement date."""
		try:
			# Get current disbursement details
			current_disbursement = frappe.get_doc("Loan Disbursement", self.loan_disbursement)
			current_disbursement_date = current_disbursement.disbursement_date
			current_disbursement_amount = current_disbursement.disbursed_amount
			
			# Get the most recent active repayment schedule
			prev_schedule = self._get_most_recent_active_schedule()
			if not prev_schedule:
				# Fallback to first disbursement logic if no previous schedule found
				self._handle_first_disbursement()
				return
			
			# Copy past schedule rows up to the new disbursement date
			self._copy_past_schedule_rows(prev_schedule, current_disbursement_date)
			
			# Calculate remaining tenure and outstanding balance
			remaining_tenure, outstanding_balance = self._calculate_remaining_tenure_and_balance(
				prev_schedule, current_disbursement_date, current_disbursement_amount
			)
			
			# Generate new schedule for remaining period
			if remaining_tenure > 0 and outstanding_balance > 0:
				self._generate_remaining_schedule(
					outstanding_balance, remaining_tenure, current_disbursement_date
				)
			
			# Update maturity date and other fields
			if self.repayment_schedule:
				self.maturity_date = self.repayment_schedule[-1].payment_date
				self.number_of_rows = len(self.repayment_schedule)
			
		except Exception as e:
			frappe.log_error(f"Error handling subsequent disbursement: {str(e)}", "Loan Repayment Schedule Error")
			# Fallback to first disbursement logic
			self._handle_first_disbursement()

	def _get_most_recent_active_schedule(self):
		"""Get the most recent active repayment schedule for this loan."""
		try:
			print(f"Looking for most recent active schedule for loan: {self.loan}")
			
			# Get the most recent active schedule
			prev_schedule_name = frappe.db.get_value(
				"Loan Repayment Schedule",
				{
					"loan": self.loan,
					"docstatus": 1,  # Only submitted schedules
					"status": "Active"
				},
				"name",
				order_by="creation desc"
			)
			
			print(f"Found previous schedule name: {prev_schedule_name}")
			
			if prev_schedule_name:
				prev_schedule = frappe.get_doc("Loan Repayment Schedule", prev_schedule_name)
				print(f"Previous schedule has {len(prev_schedule.repayment_schedule)} rows")
				return prev_schedule
			else:
				print("No previous active schedule found")
				return None
			
		except Exception as e:
			print(f"Error getting most recent schedule: {str(e)}")
			return None

	def _copy_past_schedule_rows(self, prev_schedule, new_disbursement_date):
		"""Copy past schedule rows up to the new disbursement date."""
		try:
			copied_rows = 0
			print(f"Copying rows from previous schedule. New disbursement date: {new_disbursement_date}")
			print(f"Previous schedule has {len(prev_schedule.repayment_schedule)} rows")
			
			for row in prev_schedule.repayment_schedule:
				print(f"Checking row {row.idx}: payment_date={row.payment_date}, balance={row.balance_loan_amount}")
				
				# Copy rows that have payment dates before or equal to the new disbursement date
				if getdate(row.payment_date) <= getdate(new_disbursement_date):
					self.append("repayment_schedule", {
						"idx": row.idx,
						"payment_date": row.payment_date,
						"number_of_days": row.number_of_days,
						"principal_amount": row.principal_amount,
						"interest_amount": row.interest_amount,
						"total_payment": row.total_payment,
						"balance_loan_amount": row.balance_loan_amount,
						"demand_generated": row.demand_generated
					})
					copied_rows += 1
					print(f"Copied row {row.idx}: balance={row.balance_loan_amount}")
				else:
					# Stop copying once we reach a payment date after the new disbursement
					print(f"Stopping at row {row.idx}: payment_date={row.payment_date} is after disbursement date")
					break
			
			print(f"Copied {copied_rows} rows from previous schedule up to {new_disbursement_date}")
			
		except Exception as e:
			print(f"Error copying past schedule rows: {str(e)}")

	def _calculate_remaining_tenure_and_balance(self, prev_schedule, new_disbursement_date, new_disbursement_amount):
		"""Calculate remaining tenure and outstanding balance after copying past rows."""
		try:
			# Get the original loan details
			loan_doc = frappe.get_doc("Loan", self.loan)
			original_tenure = loan_doc.repayment_periods
			original_start_date = loan_doc.repayment_start_date
			
			# Calculate how many months have passed since the original start date
			# More accurate calculation considering the actual payment dates
			months_passed = 0
			if self.repayment_schedule:
				# Count the number of rows we copied (these represent months that have passed)
				months_passed = len(self.repayment_schedule)
				print(f"Calculated months_passed from copied rows: {months_passed}")
			else:
				# Fallback calculation
				months_passed = (new_disbursement_date.year - original_start_date.year) * 12 + \
							   (new_disbursement_date.month - original_start_date.month)
				print(f"Fallback months_passed calculation: {months_passed}")
			
			# Calculate remaining tenure - this should be the full remaining months from original tenure
			remaining_tenure = original_tenure - months_passed
			remaining_tenure = max(0, remaining_tenure)  # Ensure non-negative
			
			# Calculate outstanding balance from the last copied row
			outstanding_balance = 0
			if self.repayment_schedule:
				# Use the balance from the last copied row (this is the remaining balance from previous disbursements)
				last_copied_row = self.repayment_schedule[-1]
				outstanding_balance = last_copied_row.balance_loan_amount
				print(f"Using balance from last copied row: {outstanding_balance}")
			else:
				# Fallback: calculate from previous disbursements
				outstanding_balance = self._get_total_disbursed_amount_before_date(new_disbursement_date)
				print(f"Using fallback balance calculation: {outstanding_balance}")
			
			# Add the new disbursement amount
			outstanding_balance += new_disbursement_amount
			
			print(f"Original tenure: {original_tenure}, months passed: {months_passed}, remaining tenure: {remaining_tenure}, outstanding balance: {outstanding_balance}")
			
			return remaining_tenure, outstanding_balance
			
		except Exception as e:
			print(f"Error calculating remaining tenure and balance: {str(e)}")
			return 0, 0

	def _get_total_disbursed_amount_before_date(self, target_date):
		"""Get total disbursed amount before a specific date."""
		try:
			disbursements = frappe.get_all(
				"Loan Disbursement",
				filters={
					"against_loan": self.loan,
					"docstatus": 1,  # Only submitted disbursements
					"disbursement_date": ["<", target_date]
				},
				fields=["disbursed_amount"]
			)
			
			total_disbursed = sum(d["disbursed_amount"] for d in disbursements)
			return total_disbursed
			
		except Exception as e:
			print(f"Error getting total disbursed amount: {str(e)}")
			return 0

	def _generate_remaining_schedule(self, outstanding_balance, remaining_tenure, start_date):
		"""Generate repayment schedule for the remaining period after new disbursement."""
		try:
			annual_interest_rate = getattr(self, "rate_of_interest", 0)
			monthly_rate = annual_interest_rate / 1200  # Convert to monthly decimal
			
			# Get special EMI configuration from loan document
			loan_doc = frappe.get_doc("Loan", self.loan)
			enable_special_emi = loan_doc.get("enable_special_emi", False)
			special_emi_amount = loan_doc.get("special_emi_amount", 0)
			special_emi_period = loan_doc.get("special_emi_period", 0)
			
			# Calculate how many months have already passed (including special EMI period)
			original_start_date = loan_doc.repayment_start_date
			# Use the same logic as tenure calculation - count copied rows
			months_passed = len(self.repayment_schedule)
			
			print(f"Original start date: {original_start_date}, new disbursement date: {start_date}, months_passed: {months_passed}")
			
			# Determine if we're still in special EMI period
			in_special_emi_period = False
			if enable_special_emi and special_emi_period > 0:
				# Check if the current month is within the special EMI period
				if months_passed < special_emi_period:
					in_special_emi_period = True
					# Calculate how many special EMI months are remaining
					special_emi_months_remaining = special_emi_period - months_passed
				else:
					special_emi_months_remaining = 0
			else:
				special_emi_months_remaining = 0
			
			print(f"Months passed: {months_passed}, special_emi_period: {special_emi_period}, special_emi_months_remaining: {special_emi_months_remaining}")
			
			# Calculate EMI for the remaining tenure
			if in_special_emi_period and special_emi_months_remaining > 0:
				# Use special EMI for the remaining special EMI months
				special_emi = special_emi_amount
				# After special EMI period, calculate EMI for the remaining months
				regular_tenure_after_special = remaining_tenure - special_emi_months_remaining
				if regular_tenure_after_special > 0:
					# Calculate the balance that will remain after special EMI period
					balance_after_special_emi = outstanding_balance
					for month in range(1, special_emi_months_remaining + 1):
						interest = balance_after_special_emi * monthly_rate
						if special_emi > interest:
							principal = special_emi - interest
							balance_after_special_emi = balance_after_special_emi - principal
						else:
							balance_after_special_emi = balance_after_special_emi + (interest - special_emi)
					
					# Calculate EMI for the period after special EMI
					if monthly_rate == 0:
						regular_emi = round(balance_after_special_emi / regular_tenure_after_special, 2)
					else:
						factor = (1 + monthly_rate) ** regular_tenure_after_special
						regular_emi = round(balance_after_special_emi * monthly_rate * factor / (factor - 1), 2)
				else:
					regular_emi = special_emi
			else:
				# No special EMI period remaining, use standard calculation for full remaining tenure
				if monthly_rate == 0:
					regular_emi = round(outstanding_balance / remaining_tenure, 2)
				else:
					factor = (1 + monthly_rate) ** remaining_tenure
					regular_emi = round(outstanding_balance * monthly_rate * factor / (factor - 1), 2)
				special_emi = regular_emi
				special_emi_months_remaining = 0
			
			print(f"EMI calculation - outstanding_balance: {outstanding_balance}, remaining_tenure: {remaining_tenure}, monthly_rate: {monthly_rate}, special_emi: {special_emi}, regular_emi: {regular_emi}, special_emi_months_remaining: {special_emi_months_remaining}")
			
			# Generate schedule for the full remaining tenure
			running_balance = outstanding_balance
			start_idx = len(self.repayment_schedule) + 1
			
			print(f"Starting to generate {remaining_tenure} rows with running_balance: {running_balance}")
			
			for month in range(1, remaining_tenure+1):
				# Calculate payment date based on original loan start date and the month number from original schedule
				# The month number should be months_passed + month (to continue from where we left off)
				original_month_number = months_passed + month
				payment_date = self._calculate_payment_date_with_offset(original_start_date, original_month_number)
				print(f"Payment date calculation: original_month_number={original_month_number}, payment_date={payment_date}")
				
				# Calculate interest and principal
				interest = round(running_balance * monthly_rate, 2)
				
				# Determine EMI for this month
				if month <= special_emi_months_remaining:
					# Use special EMI for this month
					emi = special_emi
				else:
					# Use regular EMI for this month
					emi = regular_emi
				
				if month == remaining_tenure:
					# Final payment: clear the remaining balance
					principal = round(running_balance, 2)
					emi = round(principal + interest, 2)
					running_balance = 0.0
				else:
					# Regular payment
					if emi <= interest:
						principal = 0.0
						running_balance = round(running_balance + (interest - emi), 2)
					else:
						principal = round(min(emi - interest, running_balance), 2)
						running_balance = round(running_balance - principal, 2)
						emi = round(principal + interest, 2)
				
				print(f"Month {month}: payment_date={payment_date}, emi={emi}, principal={principal}, interest={interest}, running_balance={running_balance}")
				
				# Add the row
				self.append("repayment_schedule", {
					"idx": start_idx + month - 1,
					"payment_date": payment_date,
					"number_of_days": 30,  # Approximate days per month
					"principal_amount": principal,
					"interest_amount": interest,
					"total_payment": emi,
					"balance_loan_amount": max(running_balance, 0.0),
					"demand_generated": 0
				})
			
			print(f"Generated {remaining_tenure} new rows for remaining schedule (special EMI months: {special_emi_months_remaining})")
			print(f"Final running_balance: {running_balance}")
			
		except Exception as e:
			print(f"Error generating remaining schedule: {str(e)}")

	def _generate_repayment_schedule_engine(self, principal, annual_interest_rate, tenure_months, special_emi, repayment_start_date, special_emi_period):
		"""Internal engine for generating repayment schedule with support for multiple disbursements."""
		from datetime import date, timedelta
		
		# Initialize variables
		monthly_rate = annual_interest_rate / 1200  # Convert annual rate to monthly
		standard_emi = self._calculate_standard_emi(principal, monthly_rate, tenure_months)
		schedule = []
		running_balance = 0.0
		
		# Get disbursement details for multiple disbursements
		disbursements = self._get_disbursement_details()
		if not disbursements:
			# Fallback: treat the whole principal as a single disbursement
			disbursements = [{"disbursed_amount": principal, "disbursement_date": repayment_start_date}]

		# Prepare disbursement tracking
		disb_ptr = 0
		total_disbursed = 0.0
		current_emi = standard_emi

		# Precompute payment dates
		payment_dates = [self._calculate_payment_date_with_offset(repayment_start_date, m) for m in range(1, tenure_months + 1)]

		# Generate schedule for each month
		for month in range(1, tenure_months + 1):
			payment_date = payment_dates[month - 1]

			# Add any new disbursements that occur on or before this payment date
			new_disb = False
			while disb_ptr < len(disbursements) and disbursements[disb_ptr]["disbursement_date"] <= payment_date:
				amt = float(disbursements[disb_ptr]["disbursed_amount"])
				total_disbursed += amt
				running_balance += amt
				new_disb = True
				disb_ptr += 1

			# Calculate remaining months for EMI calculation
			if hasattr(self, '_remaining_tenure_for_emi'):
				months_left_for_emi = self._remaining_tenure_for_emi - month + 1
			else:
				months_left_for_emi = tenure_months - month + 1

			# Recalculate EMI if this is the first month or there's a new disbursement
			if new_disb or (month == 1):
				if running_balance > 0 and months_left_for_emi > 0:
					# Check if special EMI applies for this month
					special_emi_for_month = self._get_special_emi_for_month(month, special_emi)
					
					if special_emi_for_month is not None:
						current_emi = special_emi_for_month
					else:
						# Use standard EMI calculation
						if monthly_rate == 0:
							current_emi = round(running_balance / months_left_for_emi, 2)
						else:
							factor = (1 + monthly_rate) ** months_left_for_emi
							current_emi = round(running_balance * monthly_rate * factor / (factor - 1), 2)

			# Calculate interest and principal for this month
			interest = round(running_balance * monthly_rate, 2)
			
			# Check if special EMI applies for this month
			special_emi_for_month = self._get_special_emi_for_month(month, special_emi)
			if special_emi_for_month is not None:
				emi = special_emi_for_month
			else:
				# Use current EMI or recalculate if needed
				should_recalculate = (new_disb or (month == 1) or 
									(special_emi and isinstance(special_emi, dict) and 
									 month > max(special_emi.keys()) if special_emi else 0))
				
				if should_recalculate:
					if monthly_rate == 0:
						emi = round(running_balance / (tenure_months - month + 1), 2)
					else:
						remaining_months = tenure_months - month + 1
						factor = (1 + monthly_rate) ** remaining_months
						emi = round(running_balance * monthly_rate * factor / (factor - 1), 2)
					current_emi = emi
				else:
					emi = current_emi

			# Ensure EMI doesn't exceed the remaining balance + interest
			max_payment = running_balance + interest
			if emi > max_payment:
				emi = max_payment

			# Calculate principal component
			if running_balance <= 0:
				principal_component = 0.0
				emi = 0.0
				interest = 0.0
			elif month == tenure_months:
				# Final payment: clear the remaining balance
				principal_component = round(running_balance, 2)
				emi = round(principal_component + interest, 2)
				running_balance = 0.0
			else:
				# Regular payment
				if emi <= interest:
					principal_component = 0.0
					running_balance = round(running_balance + (interest - emi), 2)
				else:
					principal_component = round(min(emi - interest, running_balance), 2)
					running_balance = round(running_balance - principal_component, 2)

			schedule.append({
				"month": month,
				"payment_date": payment_date,
				"emi": round(emi, 2),
				"interest": interest,
				"principal": principal_component,
				"balance": max(running_balance, 0.0),
			})

		# Calculate maturity date
		maturity_date = schedule[-1]["payment_date"] if schedule else repayment_start_date

		return {
			"customer_schedule": schedule,
			"co_lender_schedule": schedule,  # Same as customer for now
			"maturity_date": maturity_date,
			"number_of_rows": len(schedule),
			"standard_emi": standard_emi,
		}

	def _calculate_standard_emi(self, principal, monthly_rate, tenure_months):
		"""Calculate standard EMI using the formula: EMI = P * r * (1 + r)^n / ((1 + r)^n - 1)"""
		if monthly_rate == 0:
			# Zero interest rate - equal principal payments
			return round(principal / tenure_months, 2)
		
		# Standard EMI formula for compound interest
		factor = (1 + monthly_rate) ** tenure_months
		emi = principal * monthly_rate * factor / (factor - 1)
		return round(emi, 2)

	def _calculate_payment_date_with_offset(self, start_date, month):
		"""Calculate the payment date for a given month."""
		from frappe.utils import add_months
		
		# Calculate payment date by adding months
		payment_date = add_months(start_date, month - 1)  # month - 1 because first payment is on start date
		return payment_date
	
	def _calculate_payment_date(self, start_date, month): #without offset
		"""Calculate the payment date for a given month."""
		from frappe.utils import add_months
		
		# Calculate payment date by adding months
		payment_date = add_months(start_date, month)  # month - 1 because first payment is on start date
		return payment_date

	def _get_special_emi_for_month(self, month, special_emi):
		"""Get special EMI amount for a specific month if configured."""
		if special_emi is None:
			return None
		
		if isinstance(special_emi, (int, float)):
			# Constant special EMI - return the same value for all months
			return float(special_emi)
		elif isinstance(special_emi, dict):
			# Month-specific special EMI - only return if month exists in dict
			return special_emi.get(month)
		
		return None

	def _get_effective_principal_for_new_disbursement(self):
		"""Get the effective principal amount for a new disbursement considering outstanding balance."""
		try:
			# If this is the first disbursement, use the disbursed amount
			if not hasattr(self, 'loan_disbursement') or not self.loan_disbursement:
				return self._get_total_disbursed_amount()
			
			# Get the current disbursement details
			current_disbursement = frappe.get_doc("Loan Disbursement", self.loan_disbursement)
			current_disbursement_date = current_disbursement.disbursement_date
			current_disbursement_amount = current_disbursement.disbursed_amount
			
			# Get all disbursements up to the current disbursement date (EXCLUDING the current one)
			disbursements = frappe.get_all(
				"Loan Disbursement",
				filters={
					"against_loan": self.loan,
					"docstatus": 1,  # Only submitted disbursements
					"disbursement_date": ["<", current_disbursement_date]  # Strictly less than, not <=
				},
				fields=["disbursed_amount", "disbursement_date"],
				order_by="disbursement_date"
			)
			
			# Calculate total disbursed amount from previous disbursements
			previous_disbursements_total = sum(d["disbursed_amount"] for d in disbursements)
			
			if previous_disbursements_total == 0:
				# This is the first disbursement - use only the current disbursement amount
				effective_principal = current_disbursement_amount
			else:
				# This is a subsequent disbursement - we need to recalculate the entire schedule
				# based on the total outstanding amount and remaining tenure
				total_outstanding = previous_disbursements_total + current_disbursement_amount
				effective_principal = total_outstanding
				
				# Calculate remaining tenure from the disbursement date (for EMI calculation only)
				original_loan = frappe.get_doc("Loan", self.loan)
				original_start_date = original_loan.repayment_start_date
				original_tenure = original_loan.repayment_periods
				
				# Calculate how many months have passed since the original start date
				months_passed = (current_disbursement_date.year - original_start_date.year) * 12 + (current_disbursement_date.month - original_start_date.month)
				remaining_tenure = original_tenure - months_passed
				
				# Store the remaining tenure for EMI calculation, but don't overwrite the original tenure
				self._remaining_tenure_for_emi = remaining_tenure
				
				# For subsequent disbursements, we need to adjust the repayment start date
				# to start from the current disbursement date, not the original loan start date
				if hasattr(self, 'repayment_start_date'):
					self.repayment_start_date = current_disbursement_date
			
			return effective_principal
			
		except Exception as e:
			frappe.log_error(f"Error calculating effective principal: {str(e)}", "Loan Repayment Schedule Error")
			return self._get_total_disbursed_amount()

	def _get_total_disbursed_amount(self):
		"""Get the total disbursed amount for the loan (cumulative for multiple disbursements)."""
		try:
			# If we have a specific loan_disbursement, use that amount for the first disbursement
			if hasattr(self, 'loan_disbursement') and self.loan_disbursement:
				current_disbursement = frappe.get_doc("Loan Disbursement", self.loan_disbursement)
				
				# Check if this is the first disbursement
				previous_disbursements = frappe.get_all(
					"Loan Disbursement",
					filters={
						"against_loan": self.loan,
						"docstatus": 1,  # Only submitted disbursements
						"disbursement_date": ["<", current_disbursement.disbursement_date]
					},
					fields=["name"],
					limit=1
				)
				
				if not previous_disbursements:
					# This is the first disbursement - use only the current disbursement amount
					return current_disbursement.disbursed_amount
			
			# Get disbursements for this loan - only submitted ones, plus the current disbursement if it's draft
			disbursements = frappe.get_all(
				"Loan Disbursement",
				filters={
					"against_loan": self.loan,
					"docstatus": 1,  # Only submitted disbursements
				},
				fields=["disbursed_amount", "disbursement_date", "status", "docstatus", "name"],
				order_by="disbursement_date"
			)
			
			# If we have a specific loan_disbursement and it's not in the submitted list, add it
			if hasattr(self, 'loan_disbursement') and self.loan_disbursement:
				current_disbursement = frappe.get_doc("Loan Disbursement", self.loan_disbursement)
				if current_disbursement.docstatus == 0:  # If current disbursement is draft
					disbursements.append({
						"disbursed_amount": current_disbursement.disbursed_amount,
						"disbursement_date": current_disbursement.disbursement_date,
						"status": current_disbursement.status,
						"docstatus": current_disbursement.docstatus,
						"name": current_disbursement.name
					})
			
			if not disbursements:
				# Fallback to loan_amount if no disbursements found
				return getattr(self, "loan_amount", 0)
			
			# Calculate total disbursed amount
			total_disbursed = sum(d["disbursed_amount"] for d in disbursements)
			return total_disbursed
			
		except Exception as e:
			frappe.log_error(f"Error getting disbursed amount: {str(e)}", "Loan Repayment Schedule Error")
			# Fallback to loan_amount
			return getattr(self, "loan_amount", 0)

	def _get_first_disbursement_date(self):
		"""Get the date of the first disbursement for this loan."""
		try:
			# Get all disbursements for this loan (submitted and current draft)
			disbursements = frappe.get_all(
				"Loan Disbursement",
				filters={
					"against_loan": self.loan,
					"docstatus": 1,  # Only submitted disbursements
				},
				fields=["disbursed_amount", "disbursement_date"],
				order_by="disbursement_date"
			)
			
			# If we have a specific loan_disbursement and it's not in the submitted list, add it
			if hasattr(self, 'loan_disbursement') and self.loan_disbursement:
				current_disbursement = frappe.get_doc("Loan Disbursement", self.loan_disbursement)
				if current_disbursement.docstatus == 0:  # If current disbursement is draft
					disbursements.append({
						"disbursed_amount": current_disbursement.disbursed_amount,
						"disbursement_date": current_disbursement.disbursement_date
					})
			
			if not disbursements:
				# Fallback to current date if no disbursements found
				return frappe.utils.nowdate()
			
			# Get the earliest disbursement date
			first_disbursement_date = min(d["disbursement_date"] for d in disbursements)
			return first_disbursement_date
			
		except Exception as e:
			frappe.log_error(f"Error getting first disbursement date: {str(e)}", "Loan Repayment Schedule Error")
			return frappe.utils.nowdate()

	def _get_disbursement_details(self):
		"""Get detailed disbursement information for interest calculations."""
		try:
			# If we have a specific loan_disbursement, get disbursements up to that date
			if hasattr(self, 'loan_disbursement') and self.loan_disbursement:
				current_disbursement = frappe.get_doc("Loan Disbursement", self.loan_disbursement)
				current_disbursement_date = current_disbursement.disbursement_date
				
				# Get all disbursements up to the current disbursement date (EXCLUDING the current one)
				disbursements = frappe.get_all(
					"Loan Disbursement",
					filters={
						"against_loan": self.loan,
						"docstatus": 1,  # Only submitted disbursements
						"disbursement_date": ["<", current_disbursement_date]  # Strictly less than, not <=
					},
					fields=["disbursed_amount", "disbursement_date"],
					order_by="disbursement_date"
				)
				
				# Add the current disbursement to the list for interest calculations
				disbursements.append({
					"disbursed_amount": current_disbursement.disbursed_amount,
					"disbursement_date": current_disbursement_date
				})
				
				return disbursements
			else:
				# Fallback: Get all disbursements for this loan
				disbursements = frappe.get_all(
					"Loan Disbursement",
					filters={
						"against_loan": self.loan,
						"docstatus": 1,  # Only submitted disbursements
					},
					fields=["disbursed_amount", "disbursement_date"],
					order_by="disbursement_date"
				)
				return disbursements
			
		except Exception as e:
			frappe.log_error(f"Error getting disbursement details: {str(e)}", "Loan Repayment Schedule Error")
			return []

	def make_co_lender_schedule(self):
		if not self.loan_partner:
			return

		self.set("colender_schedule", [])

		loan_partner_details = get_loan_partner_details(self.loan_partner)

		if loan_partner_details.repayment_schedule_type == "EMI (PMT) based":
			partner_loan_amount = (
				self.current_principal_amount * flt(loan_partner_details.partner_loan_share_percentage) / 100
			)
			principal_share_percentage = 100
			interest_share_percentage = 100
			rate_of_interest = self.loan_partner_rate_of_interest
		elif loan_partner_details.repayment_schedule_type == "Collection at partner's percentage":
			partner_loan_amount = self.current_principal_amount
			rate_of_interest = self.rate_of_interest
			principal_share_percentage = flt(loan_partner_details.partner_loan_share_percentage)
			interest_share_percentage = flt(loan_partner_details.partner_loan_share_percentage)
		else:
			partner_loan_amount = (
				self.current_principal_amount * flt(loan_partner_details.partner_loan_share_percentage) / 100
			)
			rate_of_interest = self.loan_partner_rate_of_interest
			principal_share_percentage = flt(loan_partner_details.partner_loan_share_percentage)
			interest_share_percentage = 100

		self.make_repayment_schedule(
			"colender_schedule",
			0,
			partner_loan_amount,
			0,
			0,
			rate_of_interest,
			principal_share_percentage,
			interest_share_percentage,
			loan_partner_details.repayment_schedule_type,
		)

	def make_repayment_schedule(
		self,
		schedule_field,
		previous_interest_amount,
		balance_amount,
		additional_principal_amount,
		pending_prev_days,
		rate_of_interest,
		completed_tenure,
		principal_share_percentage,
		interest_share_percentage,
		partner_schedule_type=None,
	):
		payment_date = self.repayment_start_date
		carry_forward_interest = self.adjusted_interest
		moratorium_interest = 0
		row = 0
		remaining_repayment_period = self.repayment_periods - completed_tenure
		if not self.restructure_type and self.repayment_method != "Repay Fixed Amount per Period":
			monthly_repayment_amount = get_monthly_repayment_amount(
				balance_amount, rate_of_interest, remaining_repayment_period, self.repayment_frequency
			)
		else:
			monthly_repayment_amount = self.monthly_repayment_amount

		# Move this to disbursement and repayment schedule
		loan_doc = frappe.get_doc("Loan", self.loan)
		special_emi_enabled = loan_doc.get("enable_special_emi")
		special_emi_period = loan_doc.get("special_emi_period")
		special_emi_amount = loan_doc.get("special_emi_amount")
		special_emi_end_date = None

		if not self.restructure_type:
			if (
				self.moratorium_tenure
				and self.repayment_frequency == "Monthly"
				and self.repayment_schedule_type == "Monthly as per cycle date"
			):
				payment_date = self.repayment_start_date
				self.repayment_start_date = add_months(payment_date, self.moratorium_tenure)
				self.moratorium_end_date = add_months(self.repayment_start_date, -1)
			elif self.moratorium_tenure and self.repayment_frequency == "Monthly":
				self.moratorium_end_date = add_months(self.repayment_start_date, self.moratorium_tenure)
				if self.repayment_schedule_type == "Pro-rated calendar months":
					self.moratorium_end_date = add_days(self.moratorium_end_date, -1)

		if special_emi_period and self.repayment_frequency == "Monthly":
			special_emi_end_date = add_months(loan_doc.get("repayment_start_date"), (special_emi_period - 1))
			remaining_repayment_period = self.repayment_periods - special_emi_period

		tenure = self.get_applicable_tenure(payment_date)

		additional_days = cint(self.broken_period_interest_days)

		if len(self.get(schedule_field)) > 0:
			self.broken_period_interest_days = 0

		if additional_days < 0:
			self.broken_period_interest_days = 0

		remaining_amount = None

		if special_emi_enabled and self.repayment_frequency == "Monthly":
			monthly_repayment_amount = special_emi_amount

		while balance_amount > 0:
			if self.moratorium_tenure and self.repayment_frequency == "Monthly":
				if getdate(payment_date) > getdate(self.moratorium_end_date):
					if (
						self.moratorium_type == "EMI"
						and self.treatment_of_interest == "Capitalize"
						and moratorium_interest
					):
						balance_amount = self.loan_amount + moratorium_interest
						monthly_repayment_amount = get_monthly_repayment_amount(
							balance_amount, rate_of_interest, remaining_repayment_period, self.repayment_frequency
						)
						moratorium_interest = 0

			if special_emi_enabled and self.repayment_frequency == "Monthly":
				if getdate(payment_date) > getdate(special_emi_end_date) and not remaining_amount:
					remaining_amount = balance_amount
					print(f"special_emi. remaining amount: {remaining_amount}")
					monthly_repayment_amount = get_monthly_repayment_amount(
						remaining_amount, rate_of_interest, remaining_repayment_period, self.repayment_frequency
					)

				# print(f"rrp: {remaining_repayment_period}, monthly emi: {monthly_repayment_amount}")

			# print(f"tenure: {tenure}, rrp: {remaining_repayment_period}, nor: {self.number_of_rows}, rp: {self.repayment_periods}")
			prev_balance_amount = balance_amount

			payment_days, months = self.get_days_and_months(
				payment_date,
				additional_days,
				balance_amount,
				rate_of_interest,
				schedule_field,
				principal_share_percentage,
				interest_share_percentage,
			)

			(
				interest_amount,
				principal_amount,
				balance_amount,
				total_payment,
				days,
				previous_interest_amount,
			) = get_amounts(
				balance_amount,
				rate_of_interest,
				payment_days,
				months,
				monthly_repayment_amount,
				carry_forward_interest,
				previous_interest_amount,
				additional_principal_amount,
				pending_prev_days,
			)

			if (
				schedule_field == "colender_schedule"
				and partner_schedule_type == "POS reduction plus interest at partner ROI"
				and row <= len(self.get("repayment_schedule")) - 1
			):
				principal_amount = self.get("repayment_schedule")[row].principal_amount
				balance_amount = prev_balance_amount - (principal_amount * principal_share_percentage / 100)
				row = row + 1

			if (
				self.moratorium_end_date and self.moratorium_tenure and self.repayment_frequency == "Monthly"
			):
				if getdate(payment_date) <= getdate(self.moratorium_end_date):
					principal_amount = 0
					balance_amount = self.current_principal_amount
					moratorium_interest += interest_amount

					if self.moratorium_type == "EMI":
						total_payment = 0
						interest_amount = 0
					else:
						total_payment = interest_amount

				elif (
					self.moratorium_type == "EMI"
					and self.treatment_of_interest == "Add to first repayment"
					and moratorium_interest
				):
					interest_amount += moratorium_interest
					total_payment = principal_amount + interest_amount
					moratorium_interest = 0

			self.add_repayment_schedule_row(
				payment_date,
				principal_amount,
				interest_amount,
				total_payment,
				balance_amount,
				days,
				repayment_schedule_field=schedule_field,
				principal_share_percentage=principal_share_percentage,
				interest_share_percentage=interest_share_percentage,
			)

			# All the residue amount is added to the last row for "Repay Over Number of Periods"
			#
			# Also, when such a Repayment Schedule is rescheduled, its repayment_method changes to Repay Fixed Amount per Period
			# Here, the tenure shouldn't change. Thus, if this is a restructed repayment schedule, the last row is all the residue amount left.
			# This is a special case.

			if (
				self.repayment_method == "Repay Over Number of Periods"
				or (self.restructure_type and self.repayment_method == "Repay Fixed Amount per Period")
			) and len(self.get(schedule_field)) >= tenure:
				self.get(schedule_field)[-1].principal_amount += balance_amount
				self.get(schedule_field)[-1].balance_loan_amount = 0
				self.get(schedule_field)[-1].total_payment = (
					self.get(schedule_field)[-1].interest_amount + self.get(schedule_field)[-1].principal_amount
				)
				balance_amount = 0

			payment_date = self.get_next_payment_date(payment_date)
			carry_forward_interest = 0
			additional_days = 0
			additional_principal_amount = 0
			pending_prev_days = 0
			completed_tenure = completed_tenure + 1

		if schedule_field == "repayment_schedule" and not self.restructure_type:
			if self.repayment_frequency == "One Time":
				self.monthly_repayment_amount = self.get(schedule_field)[0].total_payment
			else:
				self.monthly_repayment_amount = monthly_repayment_amount
		else:
			self.repayment_periods = self.number_of_rows

	def get_next_payment_date(self, payment_date):
		if (
			self.repayment_schedule_type
			in [
				"Monthly as per repayment start date",
				"Monthly as per cycle date",
				"Line of Credit",
				"Pro-rated calendar months",
			]
		) and self.repayment_frequency == "Monthly":
			next_payment_date = add_single_month(payment_date)
			payment_date = next_payment_date
		elif self.repayment_frequency == "Bi-Weekly":
			payment_date = add_days(payment_date, 14)
		elif self.repayment_frequency == "Weekly":
			payment_date = add_days(payment_date, 7)
		elif self.repayment_frequency == "Daily":
			payment_date = add_days(payment_date, 1)
		elif self.repayment_frequency == "Quarterly":
			payment_date = add_months(payment_date, 3)

		return payment_date

	def get_applicable_tenure(self, payment_date):
		loan_status = frappe.db.get_value("Loan", self.loan, "status") or "Sanctioned"

		if self.repayment_frequency == "Monthly" and (
			loan_status == "Sanctioned" or self.repayment_schedule_type == "Line of Credit"
		):
			tenure = self.repayment_periods
			if self.repayment_frequency == "Monthly" and self.moratorium_tenure:
				tenure += cint(self.moratorium_tenure)
		elif self.restructure_type in ("Advance Payment", "Pre Payment") and self.moratorium_tenure:
			tenure = self.repayment_periods + self.moratorium_tenure
		elif loan_status == "Partially Disbursed":
			prev_schedule = frappe.db.get_value(
				"Loan Repayment Schedule", {"loan": self.loan, "docstatus": 1, "status": "Active"}
			)
			tenure = frappe.db.count("Repayment Schedule", {"parent": prev_schedule})
		else:
			tenure = self.repayment_periods

		if (
			self.restructure_type != "Normal Restructure"
			and self.repayment_frequency == "Monthly"
			or (self.restructure_type == "Pre Payment" and self.repayment_frequency != "One Time")
		):
			self.broken_period_interest_days = date_diff(add_months(payment_date, -1), self.posting_date)
			if (
				self.broken_period_interest_days > 0
				and not self.moratorium_tenure
				and loan_status != "Partially Disbursed"
			):
				tenure += 1

		return tenure

	def add_rows_from_prev_disbursement(
		self, schedule_field, principal_share_percentage, interest_share_percentage=100
	):
		previous_interest_amount = 0
		completed_tenure = 0
		balance_principal_amount = self.current_principal_amount
		additional_principal_amount = 0
		pending_prev_days = 0

		loan_status = frappe.db.get_value("Loan", self.loan, "status")
		if (
			(loan_status == "Partially Disbursed" and self.repayment_schedule_type != "Line of Credit")
			or self.restructure_type in ("Advance Payment", "Pre Payment")
			and self.repayment_frequency != "One Time"
		):
			filters = {"loan": self.loan, "docstatus": 1, "status": "Active"}

			if self.loan_disbursement and self.repayment_schedule_type == "Line of Credit":
				filters["loan_disbursement"] = self.loan_disbursement

			prev_schedule = frappe.get_doc("Loan Repayment Schedule", filters)

			self.total_installments_raised = prev_schedule.total_installments_raised
			self.total_installments_paid = prev_schedule.total_installments_paid
			self.total_installments_overdue = prev_schedule.total_installments_overdue

			if prev_schedule:
				if self.restructure_type:
					self.loan_disbursement = prev_schedule.loan_disbursement

				after_bpi = 0
				prev_repayment_date = prev_schedule.posting_date
				prev_balance_amount = prev_schedule.current_principal_amount
				self.monthly_repayment_amount = prev_schedule.monthly_repayment_amount
				first_date = prev_schedule.get(schedule_field)[0].payment_date

				if getdate(first_date) < prev_schedule.repayment_start_date:
					after_bpi = 1

				if (
					getdate(self.repayment_start_date) > getdate(prev_schedule.repayment_start_date) or after_bpi
				):
					for row in prev_schedule.get(schedule_field):
						if getdate(row.payment_date) < getdate(self.posting_date) or (
							getdate(row.payment_date) == getdate(self.posting_date)
							and self.restructure_type in ("Pre Payment", "Advance Payment")
						):

							if getdate(row.payment_date) == getdate(self.posting_date) and self.restructure_type in (
								"Pre Payment",
								"Advance Payment",
							):
								row.balance_loan_amount = self.current_principal_amount

							self.add_repayment_schedule_row(
								row.payment_date,
								row.principal_amount,
								row.interest_amount,
								row.total_payment,
								row.balance_loan_amount,
								row.number_of_days,
								demand_generated=row.demand_generated,
								repayment_schedule_field=schedule_field,
							)
							prev_repayment_date = row.payment_date
							prev_balance_amount = row.balance_loan_amount
							if row.principal_amount:
								completed_tenure += 1
						elif not after_bpi and getdate(self.posting_date) > row.payment_date:
							self.repayment_start_date = row.payment_date
							prev_repayment_date = row.payment_date
							break

					balance_principal_amount = prev_balance_amount

					if (
						self.moratorium_end_date
						and getdate(self.posting_date) <= getdate(self.moratorium_end_date)
						and self.restructure_type
					):
						self.monthly_repayment_amount = get_monthly_repayment_amount(
							self.current_principal_amount,
							self.rate_of_interest,
							self.repayment_periods,
							self.repayment_frequency,
						)
						return (
							previous_interest_amount,
							self.current_principal_amount,
							additional_principal_amount,
							pending_prev_days,
							completed_tenure,
						)

					if self.restructure_type in ("Pre Payment", "Advance Payment") and completed_tenure >= 1:
						self.get("repayment_schedule")[
							completed_tenure - 1
						].balance_loan_amount = self.current_principal_amount

					if after_bpi and not self.restructure_type:
						self.broken_period_interest = prev_schedule.broken_period_interest

					pending_prev_days = date_diff(self.posting_date, prev_repayment_date)

					if pending_prev_days > 0:
						previous_interest_amount += flt(
							prev_balance_amount * flt(self.rate_of_interest) * pending_prev_days / (36500)
						)
				elif date_diff(add_months(self.repayment_start_date, -1), self.posting_date) > 0:
					self.repayment_start_date = prev_schedule.repayment_start_date
					prev_days = date_diff(self.posting_date, prev_schedule.posting_date)
					interest_amount = flt(prev_balance_amount * flt(self.rate_of_interest) * prev_days / (36500))

					if self.repayment_frequency != "One Time":
						self.broken_period_interest += interest_amount
				else:
					prev_balance_amount = prev_schedule.current_principal_amount
					previous_interest_amount = prev_schedule.get(schedule_field)[0].interest_amount
					additional_principal_amount = self.disbursed_amount

				if self.restructure_type == "Advance Payment":
					unaccrued_interest = frappe.db.get_value(
						"Loan Restructure", self.loan_restructure, "unaccrued_interest"
					)

					interest_amount = unaccrued_interest

					paid_principal_amount = self.monthly_repayment_amount - interest_amount
					total_payment = paid_principal_amount + interest_amount
					balance_principal_amount = self.current_principal_amount
					previous_interest_amount = 0

					if self.repayment_schedule_type == "Monthly as per cycle date":
						next_emi_date = get_cyclic_date(self.loan_product, prev_repayment_date, ignore_bpi=False)
					else:
						next_emi_date = self.get_next_payment_date(prev_repayment_date)

					self.repayment_start_date = frappe.db.get_value(
						"Loan Restructure", self.loan_restructure, "repayment_start_date"
					)
					self.add_repayment_schedule_row(
						next_emi_date,
						paid_principal_amount,
						interest_amount,
						total_payment,
						balance_principal_amount,
						pending_prev_days,
						0,
						repayment_schedule_field=schedule_field,
						principal_share_percentage=principal_share_percentage,
						interest_share_percentage=interest_share_percentage,
					)

					pending_prev_days = date_diff(next_emi_date, self.posting_date)

					if pending_prev_days > 0:
						previous_interest_amount += flt(
							balance_principal_amount * flt(self.rate_of_interest) * pending_prev_days / (36500)
						)

					self.repayment_start_date = self.get_next_payment_date(next_emi_date)

					completed_tenure += 1
				elif not self.restructure_type:
					self.current_principal_amount = self.disbursed_amount + prev_balance_amount
					balance_principal_amount = self.current_principal_amount

				if self.repayment_method == "Repay Over Number of Periods" and not self.restructure_type:
					self.monthly_repayment_amount = get_monthly_repayment_amount(
						balance_principal_amount,
						self.rate_of_interest,
						self.repayment_periods - completed_tenure,
						self.repayment_frequency,
					)

				if self.restructure_type == "Pre Payment" and self.repayment_frequency != "One Time":
					interest_amount = 0
					principal_amount = 0

					# Pre payment made even before the first EMI
					if getdate(self.posting_date) < getdate(first_date):
						next_emi_date = get_cyclic_date(self.loan_product, self.posting_date, ignore_bpi=True)
					else:
						next_emi_date = self.get_next_payment_date(prev_repayment_date)

					pending_prev_days = date_diff(next_emi_date, self.posting_date)

					if pending_prev_days > 0:
						interest_amount = flt(
							self.current_principal_amount * flt(self.rate_of_interest) * pending_prev_days / (36500)
						)

						if self.current_principal_amount > self.monthly_repayment_amount:
							principal_amount = self.monthly_repayment_amount - interest_amount
						else:
							principal_amount = self.current_principal_amount

					total_payment = principal_amount + interest_amount

					balance_principal_amount = self.current_principal_amount - principal_amount
					self.add_repayment_schedule_row(
						next_emi_date,
						principal_amount,
						interest_amount,
						total_payment,
						balance_principal_amount,
						pending_prev_days,
						0,
						repayment_schedule_field=schedule_field,
						principal_share_percentage=principal_share_percentage,
						interest_share_percentage=interest_share_percentage,
					)

					pending_prev_days = 0
					previous_interest_amount = 0
					additional_principal_amount = 0
					self.repayment_start_date = self.get_next_payment_date(next_emi_date)

		return (
			previous_interest_amount,
			balance_principal_amount,
			additional_principal_amount,
			pending_prev_days,
			completed_tenure,
		)

	def set_repayment_start_date(self):
		if self.repayment_schedule_type == "Pro-rated calendar months" and not self.restructure_type:
			repayment_start_date = get_last_day(self.posting_date)
			if self.repayment_date_on == "Start of the next month":
				repayment_start_date = add_days(repayment_start_date, 1)

			self.repayment_start_date = repayment_start_date

	def validate_repayment_method(self):
		if not self.repayment_start_date:
			frappe.throw(_("Repayment Start Date is mandatory for term loans"))

		if self.repayment_method == "Repay Over Number of Periods" and not self.repayment_periods:
			frappe.throw(_("Please enter Repayment Periods"))

		if self.repayment_method == "Repay Fixed Amount per Period" and not self.restructure_type:
			self.monthly_repayment_amount = frappe.db.get_value(
				"Loan", self.loan, "monthly_repayment_amount"
			)
			if not self.monthly_repayment_amount:
				frappe.throw(_("Please enter monthly repayment amount"))
			if self.monthly_repayment_amount > self.loan_amount:
				frappe.throw(_("Monthly Repayment Amount cannot be greater than Loan Amount"))

	def get_days_and_months(
		self,
		payment_date,
		additional_days,
		balance_amount,
		rate_of_interest,
		schedule_field,
		principal_share_percentage,
		interest_share_percentage,
	):
		months = 365
		if self.repayment_frequency == "Monthly":
			expected_payment_date = get_last_day(payment_date)
			if self.repayment_date_on == "Start of the next month":
				expected_payment_date = add_days(expected_payment_date, 1)

			if self.repayment_schedule_type in (
				"Monthly as per cycle date",
				"Line of Credit",
				"Monthly as per repayment start date",
				"Pro-rated calendar months",
			):
				days = date_diff(payment_date, add_months(payment_date, -1))
				if (
					additional_days < 0
					or (additional_days > 0 and self.moratorium_tenure and not self.restructure_type)
					or (additional_days > 0 and self.restructure_type == "Normal Restructure")
				):
					days = date_diff(payment_date, self.posting_date)
					additional_days = 0

				if additional_days and not self.moratorium_tenure and not self.restructure_type:
					self.add_broken_period_interest(
						balance_amount,
						rate_of_interest,
						additional_days,
						payment_date,
						schedule_field,
						principal_share_percentage=principal_share_percentage,
						interest_share_percentage=interest_share_percentage,
					)
					additional_days = 0

			elif expected_payment_date == payment_date:
				if self.repayment_schedule_type == "Pro-rated calendar months":
					if payment_date == self.repayment_start_date:
						days = date_diff(payment_date, self.posting_date)
					elif self.repayment_date_on == "End of the current month":
						days = date_diff(payment_date, get_first_day(payment_date)) + 1
					else:
						days = date_diff(get_last_day(payment_date), payment_date) + 1
				else:
					# using 30 days for calculating interest for all full months
					days = 30
			else:
				if payment_date == self.repayment_start_date:
					days = date_diff(payment_date, self.posting_date)
				else:
					days = date_diff(get_last_day(payment_date), payment_date)
		else:
			if payment_date == self.repayment_start_date:
				days = date_diff(payment_date, self.posting_date)
			elif self.repayment_frequency == "Bi-Weekly":
				days = 14
			elif self.repayment_frequency == "Weekly":
				days = 7
			elif self.repayment_frequency == "Daily":
				days = 1
			elif self.repayment_frequency == "Quarterly":
				days = 3
			elif self.repayment_frequency == "One Time":
				days = date_diff(self.repayment_start_date, self.posting_date)

		return days, months

	def add_broken_period_interest(
		self,
		balance_amount,
		rate_of_interest,
		additional_days,
		payment_date,
		schedule_field,
		principal_share_percentage,
		interest_share_percentage,
	):
		interest_amount = flt(balance_amount * flt(rate_of_interest) * additional_days / (365 * 100))

		if schedule_field == "repayment_schedule":
			self.broken_period_interest += interest_amount

		payment_date = add_months(payment_date, -1)
		self.add_repayment_schedule_row(
			payment_date,
			0,
			interest_amount,
			interest_amount,
			balance_amount,
			additional_days,
			repayment_schedule_field=schedule_field,
			principal_share_percentage=principal_share_percentage,
			interest_share_percentage=interest_share_percentage,
		)

	def add_repayment_schedule_row(
		self,
		payment_date,
		principal_amount,
		interest_amount,
		total_payment,
		balance_loan_amount,
		days,
		demand_generated=0,
		repayment_schedule_field=None,
		principal_share_percentage=100,
		interest_share_percentage=100,
	):
		if (
			self.moratorium_type == "EMI"
			and self.moratorium_end_date
			and getdate(payment_date) <= getdate(self.moratorium_end_date)
		):
			demand_generated = 1

		if not repayment_schedule_field:
			repayment_schedule_field = "repayment_schedule"

		interest_amount = interest_amount * interest_share_percentage / 100
		principal_amount = principal_amount * principal_share_percentage / 100
		total_payment = principal_amount + interest_amount

		if repayment_schedule_field == "colender_schedule" and not self.partner_monthly_repayment_amount:
			self.partner_monthly_repayment_amount = total_payment

		self.append(
			repayment_schedule_field,
			{
				"number_of_days": days,
				"payment_date": payment_date,
				"principal_amount": principal_amount,
				"interest_amount": interest_amount,
				"total_payment": total_payment,
				"balance_loan_amount": balance_loan_amount,
				"demand_generated": demand_generated,
			},
		)
		self.increment_number_of_rows(payment_date)

	def increment_number_of_rows(self, payment_date):
		self.number_of_rows += 1
