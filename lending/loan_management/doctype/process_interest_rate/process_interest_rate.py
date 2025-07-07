import frappe
from frappe.model.document import Document
from frappe.utils import nowdate, get_datetime
from lending.loan_management.doctype.loan_restructure.loan_restructure import (
	get_pending_tenure_and_start_date,
)


class ProcessInterestRate(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.
	from typing import TYPE_CHECKING
	if TYPE_CHECKING:
		from frappe.types import DF
		interest_rate_type: DF.Link
		valid_from: DF.Date
		status: DF.Data
		log: DF.Text
	# end: auto-generated types

	def on_submit(self):
		self.status = "In Progress"
		self.save()
		try:
			process_interest_rate_for_loans(self.interest_rate_type, self.valid_from, self)
			self.status = "Completed"
		except Exception:
			self.status = "Failed"
			self.log = frappe.get_traceback()
		self.save()

def process_interest_rate_for_loans(interest_rate_type, valid_from, process_doc=None):
	loans = frappe.get_all(
		"Loan",
		filters={"interest_rate_type": "Floating", "interest_rate_type_link": interest_rate_type, "docstatus": 1},
		pluck="name"
	)
	for loan_name in loans:
		create_and_submit_loan_restructure(loan_name, valid_from, process_doc)

def create_and_submit_loan_restructure(loan_name, restructure_date, process_doc=None):
	loan = frappe.get_doc("Loan", loan_name)
	# Fetch the new applicable rate for the restructure date
	rate = get_applicable_interest_rate(loan, restructure_date)
	if not rate:
		if process_doc:
			process_doc.log = (process_doc.log or "") + f"\nNo rate found for {loan_name} on {restructure_date}" + f"\nInterest Rate: {loan.interest_rate_type_link}"
			process_doc.save()
		return

	# Fetch completed_tenure from previous active Loan Repayment Schedule
	schedule_name = frappe.db.get_value(
		"Loan Repayment Schedule",
		{"loan": loan_name, "docstatus": 1, "status": "Active"},
		"name"
	)

	posting_date = nowdate()
	(
		pending_tenure,
		monthly_repayment_amount,
		repayment_start_date,
		moratorium_end_date,
	) = get_pending_tenure_and_start_date(
		loan_name, posting_date, "Normal Restructure"
	)

	# Create the Loan Restructure doc
	restructure_doc = frappe.new_doc("Loan Restructure")
	restructure_doc.loan = loan_name
	restructure_doc.restructure_type = "Normal Restructure"
	restructure_doc.restructure_date = restructure_date
	restructure_doc.new_rate_of_interest = rate
	restructure_doc.repayment_start_date = restructure_date
	restructure_doc.reason_for_restructure = "Interest rate updated via ProcessInterestRate"
	restructure_doc.new_repayment_period_in_months = pending_tenure
	# Let the DocType logic fill in other fields (validate, etc.)

	try:
		restructure_doc.save()
		restructure_doc.submit()
		if process_doc:
			process_doc.log = (process_doc.log or "") + f"\nRestructured {loan_name} at rate {rate})"
			process_doc.save()
	except Exception as e:
		if process_doc:
			process_doc.log = (process_doc.log or "") + f"\nFailed to restructure {loan_name}: {frappe.get_traceback()} \n Doc: {restructure_doc.as_dict()}"
			process_doc.save()

def get_applicable_interest_rate(loan, posting_date=None):
	current_datetime = get_datetime()
	if not posting_date:
		posting_date = get_datetime(nowdate())

	if getattr(loan, 'interest_rate_type', None) == 'Floating':
		# Get the Interest Rate Type link
		interest_rate_type = getattr(loan, 'interest_rate_type_link', None)
		additional_interest_rate = getattr(loan, 'additional_interest_rate', 0) or 0
		if not interest_rate_type:
			frappe.throw('Interest Rate Type is required for floating rate loans.')

		rate_doc = frappe.db.get_value(
				'Interest Rate',
				{
					'type': interest_rate_type,
					'valid_from': ('<=', posting_date),
					'valid_to': ('>=', posting_date)
				},
				'rate'
			)
		if not rate_doc:
			# If no valid_to, check for open-ended
			rate_doc = frappe.db.get_value(
				'Interest Rate',
				{
					'type': interest_rate_type,
					'valid_from': ('<=', posting_date),
					'valid_to': ['is', None]
				},
				'rate'
			)

		benchmark_rate = rate_doc if rate_doc else None

		if not benchmark_rate:
			#raise error
			return

		rate = benchmark_rate + loan.additional_interest_rate

		return rate
	else:
		return getattr(loan, 'rate_of_interest', 0)
