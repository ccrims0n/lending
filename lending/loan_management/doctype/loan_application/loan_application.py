# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import json
import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import cint, flt, rounded

from lending.loan_management.doctype.loan.loan import (
	get_sanctioned_amount_limit,
	get_total_loan_amount,
)
from lending.loan_management.doctype.loan_repayment_schedule.loan_repayment_schedule import (
	get_monthly_repayment_amount,
)
from lending.loan_management.doctype.loan_security_price.loan_security_price import (
	get_loan_security_price,
)


class LoanApplication(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from lending.loan_management.doctype.co_applicant.co_applicant import CoApplicant
		from lending.loan_management.doctype.proposed_pledge.proposed_pledge import ProposedPledge

		amended_from: DF.Link | None
		applicant: DF.DynamicLink
		applicant_name: DF.Data | None
		applicant_type: DF.Literal["Employee", "Member", "Customer"]
		backlogs: DF.Int
		co_applicants: DF.Table[CoApplicant]
		company: DF.Link
		course: DF.Data
		course_type: DF.Literal["", "Full Time", "Part Time", "Online"]
		currently_employed: DF.Check
		description: DF.SmallText | None
		gmat_score: DF.Float
		gpa: DF.Float
		gpa_base: DF.Float
		graduation_year: DF.Int
		gre_score: DF.Float
		ielts_score: DF.Float
		is_secured_loan: DF.Check
		is_term_loan: DF.Check
		loan_amount: DF.Currency
		loan_product: DF.Link
		maximum_loan_amount: DF.Currency
		program: DF.Data
		pte_score: DF.Float
		proposed_pledges: DF.Table[ProposedPledge]
		rate_of_interest: DF.Percent
		repayment_amount: DF.Currency
		repayment_method: DF.Literal["", "Repay Fixed Amount per Period", "Repay Over Number of Periods"]
		repayment_periods: DF.Int
		status: DF.Literal["Open", "Approved", "Rejected"]
		tenth_score: DF.Float
		toefl_score: DF.Float
		total_payable_amount: DF.Currency
		total_payable_interest: DF.Currency
		twelveth_score: DF.Float
		ug_college: DF.Data
		university_name: DF.Data
		university_country: DF.Data
	# end: auto-generated types

	def validate(self):
		self.set_pledge_amount()
		self.set_loan_amount()
		self.validate_loan_amount()
		self.validate_scores()
		self.validate_co_applicants()

		if self.is_term_loan:
			self.validate_repayment_method()

		self.validate_loan_product()

		self.get_repayment_details()
		self.check_sanctioned_amount_limit()

	def validate_co_applicants(self):
		"""Validate co-applicants to ensure they are unique to this loan application"""
		if not self.co_applicants:
			return

		# Check for duplicate PAN numbers within the same loan application
		pan_numbers = [co_app.pan_number for co_app in self.co_applicants]
		if len(pan_numbers) != len(set(pan_numbers)):
			frappe.throw(_("Duplicate PAN numbers found in co-applicants"))

		# Check if any co-applicant's PAN is already used in another loan application
		for co_app in self.co_applicants:
			existing_loan = frappe.db.sql("""
				SELECT parent 
				FROM `tabCo Applicant` 
				WHERE pan_number = %s 
				AND parent != %s 
				AND parenttype = 'Loan Application'
			""", (co_app.pan_number, self.name))
			
			if existing_loan:
				frappe.throw(_("Co-Applicant with PAN {0} is already associated with another loan application").format(co_app.pan_number))

	def validate_scores(self):
		"""Validate all test scores and academic scores"""
		# Test Scores Validation
		if self.gre_score:
			if not (0 <= self.gre_score <= 340):
				frappe.throw(_("GRE Score must be between 0 and 340"))

		if self.toefl_score:
			if not (0 <= self.toefl_score <= 120):
				frappe.throw(_("TOEFL Score must be between 0 and 120"))

		if self.ielts_score:
			if not (0 <= self.ielts_score <= 9):
				frappe.throw(_("IELTS Score must be between 0 and 9"))

		if self.gmat_score:
			if not (0 <= self.gmat_score <= 800):
				frappe.throw(_("GMAT Score must be between 0 and 800"))

		if self.pte_score:
			if not (0 <= self.pte_score <= 90):
				frappe.throw(_("PTE Score must be between 0 and 90"))

		# Academic Scores Validation
		if self.tenth_score:
			if not (0 <= self.tenth_score <= 100):
				frappe.throw(_("10th Score must be between 0 and 100"))

		if self.twelveth_score:
			if not (0 <= self.twelveth_score <= 100):
				frappe.throw(_("12th Score must be between 0 and 100"))

		# GPA Validation
		if self.gpa:
			if not self.gpa_base:
				frappe.throw(_("Please specify GPA Base"))
			if not (0 <= self.gpa <= self.gpa_base):
				frappe.throw(_("GPA must be between 0 and {0}").format(self.gpa_base))

		# Graduation Year Validation
		if self.graduation_year:
			current_year = frappe.utils.getdate().year
			if not (1900 <= self.graduation_year <= current_year + 5):
				frappe.throw(_("Graduation Year must be between 1900 and {0}").format(current_year + 5))

		# Backlogs Validation
		if self.backlogs is not None and self.backlogs < 0:
			frappe.throw(_("Number of Backlogs cannot be negative"))

	def validate_repayment_method(self):
		if self.repayment_method == "Repay Over Number of Periods" and not self.repayment_periods:
			frappe.throw(_("Please enter Repayment Periods"))

		if self.repayment_method == "Repay Fixed Amount per Period":
			if not self.repayment_amount:
				frappe.throw(_("Please enter repayment Amount"))
			if self.repayment_amount > self.loan_amount:
				frappe.throw(_("Monthly Repayment Amount cannot be greater than Loan Amount"))

	def validate_loan_product(self):
		company = frappe.get_value("Loan Product", self.loan_product, "company")
		if company != self.company:
			frappe.throw(_("Please select Loan Product for company {0}").format(frappe.bold(self.company)))

	def validate_loan_amount(self):
		if not self.loan_amount:
			frappe.throw(_("Loan Amount is mandatory"))

		maximum_loan_limit = frappe.db.get_value(
			"Loan Product", self.loan_product, "maximum_loan_amount"
		)
		if maximum_loan_limit and self.loan_amount > maximum_loan_limit:
			frappe.throw(
				_("Loan Amount cannot exceed Maximum Loan Amount of {0}").format(maximum_loan_limit)
			)

		if self.maximum_loan_amount and self.loan_amount > self.maximum_loan_amount:
			frappe.throw(
				_("Loan Amount exceeds maximum loan amount of {0} as per proposed securities").format(
					self.maximum_loan_amount
				)
			)

	def check_sanctioned_amount_limit(self):
		sanctioned_amount_limit = get_sanctioned_amount_limit(
			self.applicant_type, self.applicant, self.company
		)

		if sanctioned_amount_limit:
			total_loan_amount = get_total_loan_amount(self.applicant_type, self.applicant, self.company)

		if sanctioned_amount_limit and flt(self.loan_amount) + flt(total_loan_amount) > flt(
			sanctioned_amount_limit
		):
			frappe.throw(
				_("Sanctioned Amount limit crossed for {0} {1}").format(
					self.applicant_type, frappe.bold(self.applicant)
				)
			)

	def set_pledge_amount(self):
		for proposed_pledge in self.proposed_pledges:

			if not proposed_pledge.qty:
				frappe.throw(_("Qty is mandatory for loan security!"))

			if not proposed_pledge.loan_security_price:
				loan_security_price = get_loan_security_price(proposed_pledge.loan_security)

				if loan_security_price:
					proposed_pledge.loan_security_price = loan_security_price
				else:
					frappe.throw(
						_("No valid Loan Security Price found for {0}").format(
							frappe.bold(proposed_pledge.loan_security)
						)
					)

			proposed_pledge.amount = proposed_pledge.qty * proposed_pledge.loan_security_price
			proposed_pledge.post_haircut_amount = cint(
				proposed_pledge.amount - (proposed_pledge.amount * proposed_pledge.haircut / 100)
			)

	def get_repayment_details(self):

		if self.is_term_loan:
			if self.repayment_method == "Repay Over Number of Periods":
				self.repayment_amount = get_monthly_repayment_amount(
					self.loan_amount, self.rate_of_interest, self.repayment_periods, "Monthly"
				)

			if self.repayment_method == "Repay Fixed Amount per Period":
				monthly_interest_rate = flt(self.rate_of_interest) / (12 * 100)
				if monthly_interest_rate:
					min_repayment_amount = self.loan_amount * monthly_interest_rate
					if self.repayment_amount - min_repayment_amount <= 0:
						frappe.throw(_("Repayment Amount must be greater than " + str(flt(min_repayment_amount, 2))))
					self.repayment_periods = math.ceil(
						(math.log(self.repayment_amount) - math.log(self.repayment_amount - min_repayment_amount))
						/ (math.log(1 + monthly_interest_rate))
					)
				else:
					self.repayment_periods = self.loan_amount / self.repayment_amount

			self.calculate_payable_amount()
		else:
			self.total_payable_amount = self.loan_amount

	def calculate_payable_amount(self):
		balance_amount = self.loan_amount
		self.total_payable_amount = 0
		self.total_payable_interest = 0

		while balance_amount > 0:
			interest_amount = rounded(balance_amount * flt(self.rate_of_interest) / (12 * 100))
			balance_amount = rounded(balance_amount + interest_amount - self.repayment_amount)

			self.total_payable_interest += interest_amount

		self.total_payable_amount = self.loan_amount + self.total_payable_interest

	def set_loan_amount(self):
		if self.is_secured_loan and not self.proposed_pledges:
			frappe.throw(_("Proposed Pledges are mandatory for secured Loans"))

		if self.is_secured_loan and self.proposed_pledges:
			self.maximum_loan_amount = 0
			for security in self.proposed_pledges:
				self.maximum_loan_amount += flt(security.post_haircut_amount)

		if not self.loan_amount and self.is_secured_loan and self.proposed_pledges:
			self.loan_amount = self.maximum_loan_amount


@frappe.whitelist()
def create_loan(source_name, target_doc=None, submit=0):
	def update_accounts(source_doc, target_doc, source_parent):
		account_details = frappe.get_all(
			"Loan Product",
			fields=[
				"payment_account",
				"loan_account",
				"interest_income_account",
				"penalty_income_account",
			],
			filters={"name": source_doc.loan_product},
		)[0]

		if source_doc.is_secured_loan:
			target_doc.maximum_loan_amount = 0

		target_doc.payment_account = account_details.payment_account
		target_doc.loan_account = account_details.loan_account
		target_doc.interest_income_account = account_details.interest_income_account
		target_doc.penalty_income_account = account_details.penalty_income_account
		target_doc.loan_application = source_name

	doclist = get_mapped_doc(
		"Loan Application",
		source_name,
		{
			"Loan Application": {
				"doctype": "Loan",
				"validation": {"docstatus": ["=", 1]},
				"postprocess": update_accounts,
			}
		},
		target_doc,
	)

	if submit:
		doclist.submit()

	return doclist


@frappe.whitelist()
def create_loan_security_assignment(loan_application, loan=None):
	loan_application_doc = frappe.get_doc("Loan Application", loan_application)

	lsa = frappe.new_doc("Loan Security Assignment")
	lsa.applicant_type = loan_application_doc.applicant_type
	lsa.applicant = loan_application_doc.applicant
	lsa.company = loan_application_doc.company
	lsa.loan_application = loan_application
	lsa.loan = loan

	for pledge in loan_application_doc.proposed_pledges:
		lsa.append(
			"securities",
			{
				"loan_security": pledge.loan_security,
				"qty": pledge.qty,
				"loan_security_price": pledge.loan_security_price,
				"haircut": pledge.haircut,
			},
		)

	lsa.save()
	lsa.submit()

	message = _("Loan Security Assignment Created : {0}").format(lsa.name)
	frappe.msgprint(message)

	return lsa.name


# This is a sandbox method to get the proposed pledges
@frappe.whitelist()
def get_proposed_pledge(securities):
	if isinstance(securities, str):
		securities = json.loads(securities)

	proposed_pledges = {"securities": []}
	maximum_loan_amount = 0

	for security in securities:
		security = frappe._dict(security)
		if not security.qty and not security.amount:
			frappe.throw(_("Qty or Amount is mandatroy for loan security"))

		security.loan_security_price = get_loan_security_price(security.loan_security)

		if not security.qty:
			security.qty = cint(security.amount / security.loan_security_price)

		security.amount = security.qty * security.loan_security_price
		security.post_haircut_amount = cint(security.amount - (security.amount * security.haircut / 100))

		maximum_loan_amount += security.post_haircut_amount

		proposed_pledges["securities"].append(security)

	proposed_pledges["maximum_loan_amount"] = maximum_loan_amount

	return proposed_pledges
