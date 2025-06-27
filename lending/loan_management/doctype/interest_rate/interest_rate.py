import frappe
from frappe.model.document import Document
from frappe import _
from datetime import datetime

class InterestRate(Document):
	def validate(self):
		self.validate_no_overlap()

	def validate_no_overlap(self):
		# Query for other Interest Rate records with the same type
		query = frappe.get_all(
			"Interest Rate",
			filters={
				"type": self.type,
				"name": ["!=", self.name],
				"docstatus": ["<", 2],
			},
			fields=["name", "valid_from", "valid_to"]
		)
		for row in query:
			# Check for overlap
			if self.datetimes_overlap(self.valid_from, self.valid_to, row["valid_from"], row["valid_to"]):
				frappe.throw(_(f"Overlapping validity period with Interest Rate: {row['name']}"))

	@staticmethod
	def datetimes_overlap(start1, end1, start2, end2):
		# Convert to datetime objects if they are strings
		def to_datetime(val):
			if not val:
				return None
			if isinstance(val, str):
				# Try parsing with and without time
				try:
					return datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
				except ValueError:
					return datetime.strptime(val, "%Y-%m-%d")
			return val
		start1 = to_datetime(start1)
		end1 = to_datetime(end1) or datetime(9999, 12, 31, 23, 59, 59)
		start2 = to_datetime(start2)
		end2 = to_datetime(end2) or datetime(9999, 12, 31, 23, 59, 59)
		return not (end1 < start2 or end2 < start1)
