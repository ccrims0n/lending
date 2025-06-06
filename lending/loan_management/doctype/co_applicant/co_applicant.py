# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class CoApplicant(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        address: DF.TextEditor | None
        city: DF.Data | None
        contact_number: DF.Data
        co_applicant_name: DF.Data
        country: DF.Link | None
        date_of_birth: DF.Date
        email: DF.Data
        pan_number: DF.Data
        pincode: DF.Data | None
        relationship_with_applicant: DF.Literal["", "Spouse", "Parent", "Sibling", "Other"]
        state: DF.Data | None
    # end: auto-generated types

    def validate(self):
        self.validate_pan_number()
        self.validate_email()
        self.validate_contact_number()
        self.validate_date_of_birth()

    def validate_pan_number(self):
        """Validate PAN number format"""
        if not self.pan_number:
            return

        # PAN format: ABCDE1234F (5 letters, 4 numbers, 1 letter)
        import re
        pan_pattern = r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$'
        if not re.match(pan_pattern, self.pan_number.upper()):
            frappe.throw("Invalid PAN Number format. It should be in the format: ABCDE1234F")

    def validate_email(self):
        """Validate email format"""
        if not self.email:
            return

        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, self.email):
            frappe.throw("Invalid email format")

    def validate_contact_number(self):
        """Validate contact number format"""
        if not self.contact_number:
            return

        # Remove any spaces or special characters
        contact = ''.join(filter(str.isdigit, self.contact_number))
        
        # Check if it's a valid Indian mobile number (10 digits starting with 6-9)
        if len(contact) != 10 or not contact[0] in ['6', '7', '8', '9']:
            frappe.throw("Invalid contact number. It should be a 10-digit Indian mobile number")

    def validate_date_of_birth(self):
        """Validate date of birth"""
        if not self.date_of_birth:
            return

        from frappe.utils import getdate
        today = getdate()
        dob = getdate(self.date_of_birth)

        # Check if DOB is not in future
        if dob > today:
            frappe.throw("Date of Birth cannot be in the future")

        # Check if age is at least 18 years
        from dateutil.relativedelta import relativedelta
        age = relativedelta(today, dob).years
        if age < 18:
            frappe.throw("Co-Applicant must be at least 18 years old") 