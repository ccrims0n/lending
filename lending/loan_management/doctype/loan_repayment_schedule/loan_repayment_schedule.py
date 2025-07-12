"""
Basic Loan Repayment Schedule Calculator
=======================================

A clean implementation for calculating loan repayment schedules with support for:
- Standard EMI calculations
- Special EMI overrides
- Edge case handling (special EMI < interest, etc.)
- Co-lender schedules
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Union

Number = Union[int, float]

# Frappe imports
try:
    import frappe
    from frappe.model.document import Document
except ImportError:
    # Fallback for standalone testing
    import frappe
    class Document:
        def __init__(self, *args, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        
        def set(self, key: str, value):
            setattr(self, key, value)


class LoanRepaymentSchedule(Document):
    """
    Frappe DocType for calculating loan repayment schedules with support for special EMI overrides.
    
    Attributes:
        principal: Loan principal amount
        annual_interest_rate: Annual interest rate (percentage)
        tenure_months: Loan tenure in months
        special_emi: Optional special EMI amount or dict of month-specific EMIs
        repayment_start_date: Date when repayments begin
        rounding: Decimal places for rounding calculations
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize calculation engine
        self._engine = None
        self._initialize_engine()
    
    def _initialize_engine(self):
        """Initialize the calculation engine with current document values."""
        try:
            # Get values with defaults, but don't validate yet
            # For multiple disbursements, use total disbursed amount
            principal = self._get_total_disbursed_amount()
            annual_interest_rate = getattr(self, "rate_of_interest", 0)
            tenure_months = getattr(self, "repayment_periods", 0)
            special_emi = getattr(self, "special_emi", None)
            repayment_start_date = getattr(self, "repayment_start_date", None)
            rounding = getattr(self, "rounding", 2)
            
            # Convert repayment_start_date to date object if it's a string
            if isinstance(repayment_start_date, str):
                try:
                    repayment_start_date = date.fromisoformat(repayment_start_date.split()[0])  # Take only date part
                except (ValueError, AttributeError):
                    repayment_start_date = date.today()
            elif repayment_start_date is None:
                repayment_start_date = date.today()
            
            # Only create engine if we have valid values
            if principal > 0 and tenure_months > 0:
                self._engine = _RepaymentEngine(
                    principal=principal,
                    annual_interest_rate=annual_interest_rate,
                    tenure_months=tenure_months,
                    special_emi=special_emi,
                    repayment_start_date=repayment_start_date,
                    rounding=rounding
                )
            else:
                # Create a minimal engine for empty documents
                self._engine = _RepaymentEngine(
                    principal=1,  # Dummy value
                    annual_interest_rate=0,
                    tenure_months=1
                )
        except Exception:
            # If initialization fails, create a minimal engine
            self._engine = _RepaymentEngine(
                principal=1,
                annual_interest_rate=0,
                tenure_months=1
            )
    
    def validate(self):
        """Frappe validation hook - calculates the schedule."""
        print("DEBUG: validate() called")  # Debug line
        
        if not self._engine:
            self._initialize_engine()
        
        # Get current values using correct field names
        # For multiple disbursements, use effective principal considering outstanding balance
        principal = self._get_effective_principal_for_new_disbursement()
        annual_interest_rate = getattr(self, "rate_of_interest", 0)
        tenure_months = getattr(self, "repayment_periods", 0)
        special_emi = getattr(self, "special_emi", None)
        
        # For multiple disbursements, use the first disbursement date as repayment start date
        if hasattr(self, 'loan_disbursement') and self.loan_disbursement:
            repayment_start_date = self._get_first_disbursement_date()
        else:
            repayment_start_date = getattr(self, "repayment_start_date", None)
            # Convert repayment_start_date to date object if it's a string
            if isinstance(repayment_start_date, str):
                try:
                    repayment_start_date = date.fromisoformat(repayment_start_date.split()[0])  # Take only date part
                except (ValueError, AttributeError):
                    repayment_start_date = date.today()
            elif repayment_start_date is None:
                repayment_start_date = date.today()
        
        print(f"DEBUG: Values - principal={principal}, tenure={tenure_months}, rate={annual_interest_rate}")  # Debug line
        print(f"DEBUG: Condition check - principal > 0: {principal > 0}, tenure_months > 0: {tenure_months > 0}")
        
        # Only calculate if we have valid values
        if principal > 0 and tenure_months > 0:
            try:
                print("DEBUG: Creating new engine")  # Debug line
                
                # Get special EMI configuration directly from loan document
                loan_doc = frappe.get_doc("Loan", self.loan)
                enable_special_emi = loan_doc.get("enable_special_emi", False)
                special_emi_amount = loan_doc.get("special_emi_amount", 0)
                special_emi_period = loan_doc.get("special_emi_period", 0)
                
                print(f"DEBUG: Loan special EMI config - enabled: {enable_special_emi}, amount: {special_emi_amount}, period: {special_emi_period}")
                
                # Apply special EMI if enabled and valid
                if enable_special_emi and special_emi_amount > 0 and special_emi_period > 0:
                    print("DEBUG: Applying special EMI from loan document")
                    print(f"DEBUG: Special EMI amount: {special_emi_amount}, period: {special_emi_period}")
                    
                    # Calculate standard EMI to compare
                    monthly_rate = annual_interest_rate / 1200  # Convert annual rate to monthly
                    if monthly_rate == 0:
                        standard_emi = principal / tenure_months
                    else:
                        factor = (1 + monthly_rate) ** tenure_months
                        standard_emi = principal * monthly_rate * factor / (factor - 1)
                    
                    print(f"DEBUG: Standard EMI: {standard_emi}, Special EMI: {special_emi_amount}")
                    
                    # Check if special EMI is significantly different from standard EMI
                    # If the difference is less than 10%, it might be a configuration error
                    if abs(special_emi_amount - standard_emi) / standard_emi < 0.1:
                        print("DEBUG: Special EMI too close to standard EMI, ignoring special EMI")
                        print(f"DEBUG: Special EMI ({special_emi_amount}) is only {abs(special_emi_amount - standard_emi) / standard_emi * 100:.1f}% different from standard EMI ({standard_emi})")
                        special_emi = None
                    else:
                        special_emi_dict = {}
                        for month in range(1, special_emi_period + 1):
                            special_emi_dict[month] = special_emi_amount
                        special_emi = special_emi_dict
                        print(f"DEBUG: Special EMI dict created: {special_emi}")
                        print(f"DEBUG: Special EMI ({special_emi_amount}) is {abs(special_emi_amount - standard_emi) / standard_emi * 100:.1f}% different from standard EMI ({standard_emi})")
                else:
                    print("DEBUG: Special EMI not enabled or invalid, using standard EMI")
                    print(f"DEBUG: enable_special_emi: {enable_special_emi}, special_emi_amount: {special_emi_amount}, special_emi_period: {special_emi_period}")
                    special_emi = None
                
                # Create a new engine with current values
                print(f"DEBUG: Creating engine with principal={principal}, tenure={tenure_months}, rate={annual_interest_rate}")
                self._engine = _RepaymentEngine(
                    principal=principal,
                    annual_interest_rate=annual_interest_rate,
                    tenure_months=tenure_months,
                    special_emi=special_emi,
                    repayment_start_date=repayment_start_date,
                    rounding=getattr(self, "rounding", 2)
                )
                # Pass parent document reference for disbursement tracking
                self._engine._parent_doc = self
                
                # Calculate schedule
                print("DEBUG: Calling engine.validate()")  # Debug line
                self._engine.validate()
                
                print(f"DEBUG: Schedule generated - {len(self._engine.customer_schedule)} rows")  # Debug line
                
                # Clear existing child tables
                self.repayment_schedule = []
                self.colender_schedule = []
                
                # Populate repayment schedule child table
                for i, row in enumerate(self._engine.customer_schedule, 1):
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
                
                # Populate co-lender schedule child table
                for i, row in enumerate(self._engine.co_lender_schedule, 1):
                    self.append("colender_schedule", {
                        "idx": i,
                        "payment_date": row["payment_date"],
                        "number_of_days": 30,  # Approximate days per month
                        "principal_amount": row["principal"],
                        "interest_amount": row["interest"],
                        "total_payment": row["emi"],
                        "balance_loan_amount": row["balance"]
                    })
                
                # Set other fields
                self.set("maturity_date", self._engine.maturity_date)
                self.set("number_of_rows", self._engine.number_of_rows)
                self.set("monthly_repayment_amount", self._engine.standard_emi)
                
                print("DEBUG: Fields set successfully")  # Debug line
            except ValueError as e:
                print(f"DEBUG: Validation error - {e}")  # Debug line
                # If validation fails, set empty schedules
                self.repayment_schedule = []
                self.colender_schedule = []
                self.set("maturity_date", None)
                self.set("number_of_rows", 0)
                self.set("monthly_repayment_amount", 0)
                # Re-raise the error for Frappe to handle
                raise e
        else:
            print("DEBUG: Invalid values, setting empty schedules")  # Debug line
            # Set empty schedules for invalid/empty documents
            self.repayment_schedule = []
            self.colender_schedule = []
            self.set("maturity_date", None)
            self.set("number_of_rows", 0)
            self.set("monthly_repayment_amount", 0)
    
    def calculate_schedule(self) -> Dict[str, any]:
        """
        Calculate the complete repayment schedule.
        
        Returns:
            Dictionary containing customer schedule, co-lender schedule, and metadata
        """
        if not self._engine:
            self._initialize_engine()
        
        self._engine.validate()
        
        return {
            "customer_schedule": self._engine.customer_schedule,
            "co_lender_schedule": self._engine.co_lender_schedule,
            "maturity_date": self._engine.maturity_date,
            "number_of_rows": self._engine.number_of_rows,
            "standard_emi": self._engine.standard_emi,
            "total_interest": sum(row["interest"] for row in self._engine.customer_schedule),
            "total_principal": sum(row["principal"] for row in self._engine.customer_schedule),
        }
    
    def generate_schedule(self):
        """Manual method to generate the repayment schedule."""
        print("DEBUG: generate_schedule() called")
        
        # Get current values using correct field names
        # For multiple disbursements, use effective principal considering outstanding balance
        principal = self._get_effective_principal_for_new_disbursement()
        annual_interest_rate = getattr(self, "rate_of_interest", 0)
        tenure_months = getattr(self, "repayment_periods", 0)
        special_emi = getattr(self, "special_emi", None)
        repayment_start_date = getattr(self, "repayment_start_date", None)
        
        # Convert repayment_start_date to date object if it's a string
        if isinstance(repayment_start_date, str):
            try:
                repayment_start_date = date.fromisoformat(repayment_start_date.split()[0])  # Take only date part
            except (ValueError, AttributeError):
                repayment_start_date = date.today()
        elif repayment_start_date is None:
            repayment_start_date = date.today()
        
        print(f"DEBUG: generate_schedule - principal={principal}, tenure={tenure_months}, rate={annual_interest_rate}")
        print(f"DEBUG: special_emi = {special_emi}")
        
        if principal > 0 and tenure_months > 0:
            try:
                # Create engine and calculate
                engine = _RepaymentEngine(
                    principal=principal,
                    annual_interest_rate=annual_interest_rate,
                    tenure_months=tenure_months,
                    special_emi=special_emi,
                    repayment_start_date=repayment_start_date,
                    rounding=getattr(self, "rounding", 2)
                )
                
                engine.validate()
                
                # Clear existing child tables
                self.repayment_schedule = []
                self.colender_schedule = []
                
                # Populate repayment schedule child table
                for i, row in enumerate(engine.customer_schedule, 1):
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
                
                # Populate co-lender schedule child table
                for i, row in enumerate(engine.co_lender_schedule, 1):
                    self.append("colender_schedule", {
                        "idx": i,
                        "payment_date": row["payment_date"],
                        "number_of_days": 30,  # Approximate days per month
                        "principal_amount": row["principal"],
                        "interest_amount": row["interest"],
                        "total_payment": row["emi"],
                        "balance_loan_amount": row["balance"]
                    })
                
                # Set other fields
                self.set("maturity_date", engine.maturity_date)
                self.set("number_of_rows", engine.number_of_rows)
                self.set("monthly_repayment_amount", engine.standard_emi)
                
                print(f"DEBUG: Schedule generated successfully - {len(engine.customer_schedule)} rows")
                return True
                
            except Exception as e:
                print(f"DEBUG: Error generating schedule - {e}")
                return False
        else:
            print("DEBUG: Invalid values for schedule generation")
            return False
    
    def set_special_emi_for_configurable_period(self, special_emi_amount=None, special_emi_period=None):
        """Set special EMI for a configurable period based on loan settings."""
        # Get values from loan document if not provided
        if special_emi_amount is None:
            special_emi_amount = getattr(self, "special_emi_amount", 0)
        if special_emi_period is None:
            special_emi_period = getattr(self, "special_emi_period", 0)
        
        print(f"DEBUG: Setting special EMI {special_emi_amount} for first {special_emi_period} months")
        
        if special_emi_period <= 0:
            print("DEBUG: Invalid special EMI period, clearing special EMI")
            self.set("special_emi", None)
            return self.generate_schedule()
        
        # Create a dictionary with special EMI for the specified period
        special_emi_dict = {}
        for month in range(1, special_emi_period + 1):  # Months 1 to special_emi_period
            special_emi_dict[month] = special_emi_amount
        
        # Set the special EMI field
        self.set("special_emi", special_emi_dict)
        
        # Regenerate the schedule
        return self.generate_schedule()
    

    
    def set_special_emi_for_specific_months(self, special_emi_dict):
        """Set special EMI for specific months.
        
        Args:
            special_emi_dict: Dictionary with month numbers as keys and EMI amounts as values
            Example: {1: 1000, 6: 1200, 12: 1500}
        """
        print(f"DEBUG: Setting special EMI for specific months: {special_emi_dict}")
        
        # Set the special EMI field
        self.set("special_emi", special_emi_dict)
        
        # Regenerate the schedule
        return self.generate_schedule()
    
    def set_constant_special_emi(self, special_emi_amount):
        """Set a constant special EMI for all months."""
        print(f"DEBUG: Setting constant special EMI: {special_emi_amount}")
        
        # Set the special EMI field
        self.set("special_emi", special_emi_amount)
        
        # Regenerate the schedule
        return self.generate_schedule()
    

    
    def test_calculation(self):
        """Test method to verify calculation works independently."""
        print("DEBUG: test_calculation() called")
        
        # Create a test engine
        test_engine = _RepaymentEngine(
            principal=100000,
            annual_interest_rate=12.0,
            tenure_months=12,
            repayment_start_date=date(2024, 1, 1)
        )
        
        # Calculate schedule
        test_engine.validate()
        
        print(f"DEBUG: Test schedule generated - {len(test_engine.customer_schedule)} rows")
        print(f"DEBUG: First row - {test_engine.customer_schedule[0] if test_engine.customer_schedule else 'No schedule'}")
        
        return test_engine.customer_schedule
    
    def _validate_positive(self, name: str, value: Number) -> float:
        """Validate that a value is positive."""
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number - got {value!r}")
        
        if value <= 0:
            raise ValueError(f"{name} must be > 0 - got {value}")
        
        return value
    
    def _validate_interest_rate(self, rate: Number) -> float:
        """Validate interest rate (can be 0 or positive)."""
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            raise ValueError(f"annual_interest_rate must be a number - got {rate!r}")
        
        if rate < 0:
            raise ValueError("annual_interest_rate cannot be negative")
        
        return rate

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
                    print(f"DEBUG: First disbursement - using only current amount: {current_disbursement.disbursed_amount}")
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
                print(f"DEBUG: No disbursements found for loan {self.loan}")
                return getattr(self, "loan_amount", 0)
            
            # Calculate total disbursed amount
            total_disbursed = sum(d["disbursed_amount"] for d in disbursements)
            
            print(f"DEBUG: Found {len(disbursements)} disbursements:")
            for d in disbursements:
                print(f"  - Name: {d['name']}, Amount: {d['disbursed_amount']}, Status: {d['status']}, DocStatus: {d['docstatus']}")
            print(f"DEBUG: Total disbursed amount: {total_disbursed}")
            
            return total_disbursed
            
        except Exception as e:
            print(f"DEBUG: Error getting disbursed amount: {e}")
            # Fallback to loan_amount
            return getattr(self, "loan_amount", 0)

    def _get_outstanding_balance_at_date(self, target_date):
        """Get the outstanding loan balance at a specific date considering all previous disbursements and repayments."""
        try:
            # Get all submitted disbursements up to the target date
            disbursements = frappe.get_all(
                "Loan Disbursement",
                filters={
                    "against_loan": self.loan,
                    "docstatus": 1,  # Only submitted disbursements
                    "disbursement_date": ["<=", target_date]
                },
                fields=["disbursed_amount", "disbursement_date"],
                order_by="disbursement_date"
            )
            
            # Calculate total disbursed up to target date
            total_disbursed = sum(d.disbursed_amount for d in disbursements)
            
            # Get all repayment schedules for this loan
            repayment_schedules = frappe.get_all(
                "Loan Repayment Schedule",
                filters={
                    "loan": self.loan,
                    "docstatus": 1  # Only submitted schedules
                },
                fields=["name"],
                order_by="creation"
            )
            
            # Calculate total repaid up to target date
            total_repaid = 0
            for schedule_name in [rs.name for rs in repayment_schedules]:
                schedule = frappe.get_doc("Loan Repayment Schedule", schedule_name)
                for payment in schedule.repayment_schedule:
                    if payment.payment_date <= target_date:
                        total_repaid += payment.principal_amount
            
            outstanding_balance = total_disbursed - total_repaid
            print(f"DEBUG: Outstanding balance at {target_date}: {outstanding_balance} (disbursed: {total_disbursed}, repaid: {total_repaid})")
            return max(0, outstanding_balance)
            
        except Exception as e:
            print(f"DEBUG: Error calculating outstanding balance: {e}")
            return 0

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
            
            # Convert to date object if it's a string
            if isinstance(current_disbursement_date, str):
                current_disbursement_date = date.fromisoformat(current_disbursement_date.split()[0])
            
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
                print(f"DEBUG: First disbursement - using only current amount: {effective_principal}")
            else:
                # This is a subsequent disbursement - we need to recalculate the entire schedule
                # based on the total outstanding amount and remaining tenure
                total_outstanding = previous_disbursements_total + current_disbursement_amount
                effective_principal = total_outstanding
                
                # Calculate remaining tenure from the disbursement date (for EMI calculation only)
                original_loan = frappe.get_doc("Loan", self.loan)
                original_start_date = original_loan.repayment_start_date
                original_tenure = original_loan.repayment_periods
                
                # Convert dates to date objects if they're strings
                if isinstance(original_start_date, str):
                    original_start_date = date.fromisoformat(original_start_date.split()[0])
                if isinstance(current_disbursement_date, str):
                    current_disbursement_date = date.fromisoformat(current_disbursement_date.split()[0])
                
                # Calculate how many months have passed since the original start date
                months_passed = (current_disbursement_date.year - original_start_date.year) * 12 + (current_disbursement_date.month - original_start_date.month)
                remaining_tenure = original_tenure - months_passed
                
                print(f"DEBUG: Subsequent disbursement - total outstanding: {effective_principal}")
                print(f"DEBUG: Original tenure: {original_tenure}, months passed: {months_passed}, remaining tenure: {remaining_tenure}")
                print(f"DEBUG: Keeping original tenure: {original_tenure} (not updating to remaining tenure)")
                
                # Store the remaining tenure for EMI calculation, but don't overwrite the original tenure
                self._remaining_tenure_for_emi = remaining_tenure
                
                # For subsequent disbursements, we need to adjust the repayment start date
                # to start from the current disbursement date, not the original loan start date
                if hasattr(self, 'repayment_start_date'):
                    self.repayment_start_date = current_disbursement_date
                    print(f"DEBUG: Adjusted repayment start date to disbursement date: {current_disbursement_date}")
            
            print(f"DEBUG: Current disbursement date: {current_disbursement_date}")
            print(f"DEBUG: Found {len(disbursements)} previous disbursements:")
            for d in disbursements:
                print(f"  - Date: {d['disbursement_date']}, Amount: {d['disbursed_amount']}")
            print(f"DEBUG: Previous disbursements total: {previous_disbursements_total}")
            print(f"DEBUG: Current disbursement amount: {current_disbursement_amount}")
            
            return effective_principal
            
        except Exception as e:
            print(f"DEBUG: Error calculating effective principal: {e}")
            return self._get_total_disbursed_amount()

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
                return date.today()
            
            # Get the earliest disbursement date
            first_disbursement_date = min(d["disbursement_date"] for d in disbursements)
            
            # Convert to date object if it's a string
            if isinstance(first_disbursement_date, str):
                first_disbursement_date = date.fromisoformat(first_disbursement_date.split()[0])
            
            print(f"DEBUG: First disbursement date: {first_disbursement_date}")
            return first_disbursement_date
            
        except Exception as e:
            print(f"DEBUG: Error getting first disbursement date: {e}")
            return date.today()
    
    def _get_disbursement_details(self):
        """Get detailed disbursement information for interest calculations."""
        try:
            # If we have a specific loan_disbursement, get disbursements up to that date
            if hasattr(self, 'loan_disbursement') and self.loan_disbursement:
                current_disbursement = frappe.get_doc("Loan Disbursement", self.loan_disbursement)
                current_disbursement_date = current_disbursement.disbursement_date
                
                # Convert to date object if it's a string
                if isinstance(current_disbursement_date, str):
                    current_disbursement_date = date.fromisoformat(current_disbursement_date.split()[0])
                
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
                
                print(f"DEBUG: Disbursement details - found {len(disbursements)} disbursements for interest calculation")
                
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
            print(f"DEBUG: Error getting disbursement details: {e}")
            return []

    def _calculate_interest_for_multiple_disbursements(self, payment_date):
        """Calculate interest for multiple disbursements up to a given payment date."""
        disbursements = self._get_disbursement_details()
        if not disbursements:
            return 0
        
        total_interest = 0
        monthly_rate = getattr(self, "rate_of_interest", 0) / 1200  # Convert to monthly decimal
        
        for disbursement in disbursements:
            disbursement_date = disbursement["disbursement_date"]
            disbursed_amount = disbursement["disbursed_amount"]
            
            # Convert dates to date objects if they're strings
            if isinstance(disbursement_date, str):
                disbursement_date = date.fromisoformat(disbursement_date.split()[0])
            if isinstance(payment_date, str):
                payment_date = date.fromisoformat(payment_date.split()[0])
            
            # Calculate days between disbursement and payment
            days = (payment_date - disbursement_date).days
            
            if days > 0:
                # Calculate interest for this disbursement
                daily_rate = monthly_rate / 30  # Approximate daily rate
                interest = disbursed_amount * daily_rate * days
                total_interest += interest
        
        return round(total_interest, getattr(self, "rounding", 2))

    def _get_outstanding_principal_at_payment_date(self, payment_date):
        """Get the outstanding principal amount at a specific payment date considering disbursement timing."""
        try:
            # Get all disbursements up to the payment date
            disbursements = frappe.get_all(
                "Loan Disbursement",
                filters={
                    "against_loan": self.loan,
                    "docstatus": 1,  # Only submitted disbursements
                    "disbursement_date": ["<=", payment_date]
                },
                fields=["disbursed_amount", "disbursement_date"],
                order_by="disbursement_date"
            )
            
            # If we have a specific loan_disbursement and it's not in the submitted list, add it
            if hasattr(self, 'loan_disbursement') and self.loan_disbursement:
                current_disbursement = frappe.get_doc("Loan Disbursement", self.loan_disbursement)
                if current_disbursement.docstatus == 0:  # If current disbursement is draft
                    # Only include if the disbursement date is on or before the payment date
                    if current_disbursement.disbursement_date <= payment_date:
                        disbursements.append({
                            "disbursed_amount": current_disbursement.disbursed_amount,
                            "disbursement_date": current_disbursement.disbursement_date
                        })
            
            # Calculate total disbursed up to this payment date
            total_disbursed = sum(d["disbursed_amount"] for d in disbursements)
            
            print(f"DEBUG: At payment date {payment_date}, total disbursed: {total_disbursed}")
            return total_disbursed
            
        except Exception as e:
            print(f"DEBUG: Error calculating outstanding principal at payment date: {e}")
            return 0


class _RepaymentEngine:
    """Internal engine for pure calculation logic - no Frappe dependencies."""
    
    def __init__(
        self,
        principal: Number,
        annual_interest_rate: Number,
        tenure_months: int,
        special_emi: Optional[Union[Number, Dict[int, Number]]] = None,
        repayment_start_date: Optional[date] = None,
        rounding: int = 2,
    ) -> None:
        # Set basic parameters without validation (validation happens later)
        self.principal = float(principal)
        self.annual_interest_rate = float(annual_interest_rate)
        self.tenure_months = int(tenure_months)
        self.special_emi = special_emi
        self.repayment_start_date = repayment_start_date or date.today()
        self.rounding = rounding
        
        # Calculate derived values
        self.monthly_rate = self.annual_interest_rate / 1200  # Convert annual % to monthly decimal
        self.standard_emi = self._calculate_standard_emi()
        
        # Initialize output schedules
        self.customer_schedule: List[Dict[str, float]] = []
        self.co_lender_schedule: List[Dict[str, float]] = []
        self.maturity_date: Optional[date] = None
        self.number_of_rows: int = 0
        
        # Only validate special EMI if we have valid base values
        if self.principal > 0 and self.tenure_months > 0:
            self._validate_special_emi()
    
    def validate(self) -> None:
        """Calculate the complete schedule."""
        # Validate basic parameters before calculation
        if self.principal <= 0:
            raise ValueError("principal must be > 0")
        if self.tenure_months <= 0:
            raise ValueError("tenure_months must be > 0")
        if self.annual_interest_rate < 0:
            raise ValueError("annual_interest_rate cannot be negative")
        
        # Recalculate derived values
        self.monthly_rate = self.annual_interest_rate / 1200
        self.standard_emi = self._calculate_standard_emi()
        
        # Calculate adjusted EMI for periods after special EMI
        self.adjusted_emi = self._calculate_adjusted_emi_for_special_periods()
        
        # Validate special EMI
        self._validate_special_emi()
        
        # Calculate schedules
        self.customer_schedule = self._generate_schedule()
        self.co_lender_schedule = self._generate_schedule()  # Same as customer for now
        self.number_of_rows = len(self.customer_schedule)
        self.maturity_date = self._calculate_maturity_date()
    
    def _calculate_standard_emi(self) -> float:
        """Calculate standard EMI using the formula: EMI = P * r * (1 + r)^n / ((1 + r)^n - 1)"""
        if self.monthly_rate == 0:
            # Zero interest rate - equal principal payments
            return round(self.principal / self.tenure_months, self.rounding)
        
        # Standard EMI formula for compound interest
        factor = (1 + self.monthly_rate) ** self.tenure_months
        emi = self.principal * self.monthly_rate * factor / (factor - 1)
        result = round(emi, self.rounding)
        print(f"DEBUG: _calculate_standard_emi - principal: {self.principal}, rate: {self.annual_interest_rate}%, tenure: {self.tenure_months}")
        print(f"DEBUG: _calculate_standard_emi - monthly_rate: {self.monthly_rate}, factor: {factor}")
        print(f"DEBUG: _calculate_standard_emi - calculated EMI: {result}")
        return result
    
    def _calculate_adjusted_emi_for_special_periods(self) -> float:
        """Calculate adjusted EMI for the period after special EMI ends."""
        if not self.special_emi or self.monthly_rate == 0:
            return self.standard_emi
        
        # Simulate the loan balance after special EMI period
        balance = self.principal
        special_emi_period = 0
        
        if isinstance(self.special_emi, dict):
            special_emi_period = max(self.special_emi.keys()) if self.special_emi else 0
        elif isinstance(self.special_emi, (int, float)):
            # For constant special EMI, we need to determine the period
            # This is a simplified approach - in practice, you'd need to specify the period
            special_emi_period = 24  # Default to 24 months for constant special EMI
        
        if special_emi_period == 0:
            return self.standard_emi
        
        # Calculate remaining months after special EMI period
        remaining_months = self.tenure_months - special_emi_period
        
        if remaining_months <= 0:
            return self.standard_emi
        
        # Simulate the balance after special EMI period
        for month in range(1, special_emi_period + 1):
            interest = balance * self.monthly_rate
            if isinstance(self.special_emi, dict):
                emi = self.special_emi.get(month, self.standard_emi)
            else:
                emi = self.special_emi
            
            if emi <= interest:
                # Negative amortization
                principal_paid = 0
                balance = balance + (interest - emi)
            else:
                principal_paid = min(emi - interest, balance)
                balance = balance - principal_paid
        
        # Calculate adjusted EMI for remaining months
        if balance <= 0:
            return 0
        
        if self.monthly_rate == 0:
            return round(balance / remaining_months, self.rounding)
        
        factor = (1 + self.monthly_rate) ** remaining_months
        adjusted_emi = balance * self.monthly_rate * factor / (factor - 1)
        return round(adjusted_emi, self.rounding)
    
    def _validate_special_emi(self) -> None:
        """Validate special EMI values and check for edge cases."""
        if self.special_emi is None:
            return
        
        # Calculate minimum EMI (interest component)
        min_emi = self.principal * self.monthly_rate
        
        def _check_emi(value: Number, label: str = "special_emi") -> None:
            """Check if EMI value is valid."""
            try:
                emi_val = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{label} must be a number - got {value!r}")
            
            if emi_val <= 0:
                raise ValueError(f"{label} must be > 0 - got {emi_val}")
            
            # Edge case: Special EMI less than interest component - allow with warning
            if self.monthly_rate > 0 and emi_val < min_emi:
                print(f"WARNING: {label} ({emi_val}) is less than minimum monthly interest ({min_emi:.2f}). "
                      f"This may result in increasing loan balance. Proceeding with calculation...")
                # Don't raise error, just warn and continue
            elif self.monthly_rate > 0 and emi_val == min_emi:
                print(f"INFO: {label} ({emi_val}) equals minimum monthly interest ({min_emi:.2f}). "
                      f"No principal reduction in this period.")
        
        if isinstance(self.special_emi, (int, float)):
            _check_emi(self.special_emi)
        elif isinstance(self.special_emi, dict):
            for month, emi_val in self.special_emi.items():
                if not isinstance(month, int) or month <= 0:
                    raise ValueError("special_emi month keys must be positive integers")
                if month > self.tenure_months:
                    raise ValueError(f"special_emi month {month} exceeds tenure {self.tenure_months}")
                _check_emi(emi_val, f"special_emi[{month}]")
        else:
            raise ValueError("special_emi must be None, a number, or a dict")
    
    def _generate_schedule(self) -> List[Dict[str, float]]:
        """Generate the repayment schedule with dynamic EMI recalculation on new disbursements, keeping tenure fixed."""
        schedule = []
        month = 1
        max_iterations = self.tenure_months * 3  # Safety limit

        # Get all disbursements (assume sorted by date)
        disbursements = []
        if hasattr(self, '_parent_doc') and hasattr(self._parent_doc, '_get_disbursement_details'):
            disbursements = self._parent_doc._get_disbursement_details()
        else:
            # Fallback: treat the whole principal as a single disbursement at start
            disbursements = [{"disbursed_amount": self.principal, "disbursement_date": self.repayment_start_date}]

        # Prepare a pointer for disbursement events
        disb_ptr = 0
        total_disbursed = 0.0
        emi = 0.0
        running_balance = 0.0
        total_principal_paid = 0.0
        current_emi_start_month = 1
        current_emi = self.standard_emi  # Initialize with standard EMI
        current_disbursement_month = 1
        disbursement_months = []
        
        print(f"DEBUG: Initial current_emi: {current_emi}")
        
        print(f"DEBUG: Initial values - principal: {self.principal}, tenure: {self.tenure_months}, rate: {self.annual_interest_rate}")
        print(f"DEBUG: Monthly rate: {self.monthly_rate}, Standard EMI: {self.standard_emi}")
        
        # Test EMI calculation
        test_principal = 10000
        test_rate = 12
        test_tenure = 60
        test_monthly_rate = test_rate / 1200
        test_factor = (1 + test_monthly_rate) ** test_tenure
        test_emi = test_principal * test_monthly_rate * test_factor / (test_factor - 1)
        print(f"DEBUG: Test calculation - Principal: {test_principal}, Rate: {test_rate}%, Tenure: {test_tenure}")
        print(f"DEBUG: Test calculation - Monthly rate: {test_monthly_rate}, Factor: {test_factor}")
        print(f"DEBUG: Test calculation - Expected EMI: {test_emi:.2f}")

        # Precompute payment dates for each month
        payment_dates = [self._calculate_payment_date(m) for m in range(1, self.tenure_months + 1)]

        # For each month, check if a new disbursement occurs and recalculate EMI if needed
        for month in range(1, self.tenure_months + 1):
            payment_date = payment_dates[month - 1]

            # Add any new disbursements that occur on or before this payment date
            new_disb = False
            while disb_ptr < len(disbursements) and disbursements[disb_ptr]["disbursement_date"] <= payment_date:
                amt = float(disbursements[disb_ptr]["disbursed_amount"])
                total_disbursed += amt
                running_balance += amt
                disbursement_months.append(month)
                print(f"DEBUG: New disbursement of {amt} on {disbursements[disb_ptr]['disbursement_date']} at month {month}, total_disbursed={total_disbursed}")
                new_disb = True
                disb_ptr += 1

            # If this is the first month or a new disbursement, recalculate EMI for remaining months
            # Use remaining tenure for EMI calculation if available (for subsequent disbursements)
            if hasattr(self, '_parent_doc') and hasattr(self._parent_doc, '_remaining_tenure_for_emi'):
                # For subsequent disbursements, use the remaining tenure for EMI calculation
                months_left_for_emi = self._parent_doc._remaining_tenure_for_emi - month + 1
                print(f"DEBUG: Using remaining tenure for EMI calculation: {self._parent_doc._remaining_tenure_for_emi}, months_left_for_emi: {months_left_for_emi}")
            else:
                # For first disbursement, use the original tenure
                months_left_for_emi = self.tenure_months - month + 1
            
            if new_disb or (month == 1):
                if running_balance > 0 and months_left_for_emi > 0:
                    # Check if special EMI applies for this month
                    special_emi_for_month = self._get_special_emi_for_month(month)
                    
                    if special_emi_for_month is not None:
                        # Use special EMI for this month
                        current_emi = special_emi_for_month
                        print(f"DEBUG: Using special EMI for month {month}: {special_emi_for_month}")
                    else:
                        # Use standard EMI calculation
                        if self.monthly_rate == 0:
                            emi = round(running_balance / months_left_for_emi, self.rounding)
                        else:
                            factor = (1 + self.monthly_rate) ** months_left_for_emi
                            emi = round(running_balance * self.monthly_rate * factor / (factor - 1), self.rounding)
                            print(f"DEBUG: EMI calculation - running_balance: {running_balance}, monthly_rate: {self.monthly_rate}, factor: {factor}")
                            print(f"DEBUG: EMI formula: {running_balance} * {self.monthly_rate} * {factor} / ({factor} - 1) = {emi}")
                        current_emi = emi
                        print(f"DEBUG: Recalculated standard EMI at month {month}: {emi} for balance {running_balance} and months_left_for_emi {months_left_for_emi}")
                        print(f"DEBUG: Monthly rate: {self.monthly_rate}, Factor: {factor}")
                        print(f"DEBUG: current_emi assigned: {current_emi}")
                        print(f"DEBUG: EMI calculation details - running_balance: {running_balance}, months_left_for_emi: {months_left_for_emi}")
                        print(f"DEBUG: Calculated emi: {emi}, Assigned current_emi: {current_emi}")
                    
                    current_emi_start_month = month
                else:
                    print(f"DEBUG: Skipping EMI calculation for month {month} - running_balance: {running_balance}, months_left_for_emi: {months_left_for_emi}")

            # Calculate interest and principal for this month
            interest = round(running_balance * self.monthly_rate, self.rounding)
            
            # Check if special EMI applies for this month
            special_emi_for_month = self._get_special_emi_for_month(month)
            if special_emi_for_month is not None:
                # Use special EMI for this month
                emi = special_emi_for_month
                print(f"DEBUG: Using special EMI for month {month}: {emi}")
            else:
                # Recalculate standard EMI for the remaining balance and tenure
                if self.monthly_rate == 0:
                    emi = round(running_balance / (self.tenure_months - month + 1), self.rounding)
                else:
                    remaining_months = self.tenure_months - month + 1
                    factor = (1 + self.monthly_rate) ** remaining_months
                    emi = round(running_balance * self.monthly_rate * factor / (factor - 1), self.rounding)
                
                print(f"DEBUG: Recalculated standard EMI for month {month}: {emi}")
                print(f"DEBUG: running_balance: {running_balance}, remaining_months: {self.tenure_months - month + 1}")
                print(f"DEBUG: self.standard_emi value: {self.standard_emi}")
                
                # Update current_emi for future months
                current_emi = emi
            
            # Ensure EMI doesn't exceed the remaining balance + interest
            max_payment = running_balance + interest
            if emi > max_payment:
                emi = max_payment
                print(f"DEBUG: EMI capped at max payment for month {month}: {emi}")
            
            # Check if this is the final payment for the current disbursement
            if running_balance <= 0:
                # No more balance to pay - EMI should be 0
                principal_component = 0.0
                emi = 0.0
                interest = 0.0  # No interest when no balance
                print(f"DEBUG: No balance remaining (month {month}) - emi: {emi}, balance: {running_balance}")
            elif month == self.tenure_months:
                # Final payment: clear the remaining balance
                principal_component = round(running_balance, self.rounding)
                emi = round(principal_component + interest, self.rounding)
                running_balance = 0.0
                print(f"DEBUG: Final payment (month {month}) - principal: {principal_component}, emi: {emi}, balance: {running_balance}")
            else:
                # Regular payment
                if emi <= interest:
                    principal_component = 0.0
                    running_balance = round(running_balance + (interest - emi), self.rounding)
                else:
                    principal_component = round(min(emi - interest, running_balance), self.rounding)
                    running_balance = round(running_balance - principal_component, self.rounding)

            total_principal_paid += principal_component

            schedule.append({
                "month": month,
                "payment_date": payment_date,
                "emi": round(emi, self.rounding),
                "interest": interest,
                "principal": principal_component,
                "balance": max(running_balance, 0.0),
            })

        # Edge case: If we hit max iterations, the loan might not be fully repaid
        if month > max_iterations and running_balance > 0:
            raise ValueError(
                f"Loan not fully repaid after {max_iterations} iterations. "
                f"Remaining balance: {running_balance:.2f}. Check EMI values."
            )

        return schedule
    
    def _calculate_payment_date(self, month: int) -> date:
        """Calculate the payment date for a given month."""
        # Ensure we're working with a date object
        if isinstance(self.repayment_start_date, str):
            try:
                start_date = date.fromisoformat(self.repayment_start_date.split()[0])
            except (ValueError, AttributeError):
                start_date = date.today()
        else:
            start_date = self.repayment_start_date
        
        # Calculate payment date by adding actual months
        # This handles different month lengths and year boundaries properly
        year = start_date.year
        month_num = start_date.month + (month - 1)  # month - 1 because first payment is on start date
        
        # Handle year rollover
        while month_num > 12:
            year += 1
            month_num -= 12
        
        # Get the day of the month, handling month length differences
        day = start_date.day
        try:
            payment_date = date(year, month_num, day)
        except ValueError:
            # Handle cases where the day doesn't exist in the target month (e.g., Jan 31 -> Feb 31)
            # Use the last day of the target month
            if month_num == 12:
                next_month = date(year + 1, 1, 1)
            else:
                next_month = date(year, month_num + 1, 1)
            payment_date = next_month - timedelta(days=1)
        
        return payment_date
    
    def _get_special_emi_for_month(self, month: int) -> Optional[float]:
        """Get special EMI amount for a specific month if configured."""
        print(f"DEBUG: _get_special_emi_for_month called for month {month}")
        print(f"DEBUG: self.special_emi value: {self.special_emi}")
        print(f"DEBUG: self.special_emi type: {type(self.special_emi)}")
        
        if self.special_emi is None:
            print(f"DEBUG: No special EMI configured for month {month}")
            return None
        
        if isinstance(self.special_emi, (int, float)):
            # Constant special EMI - return the same value for all months
            result = float(self.special_emi)
            print(f"DEBUG: Using constant special EMI for month {month}: {result}")
            return result
        elif isinstance(self.special_emi, dict):
            # Month-specific special EMI
            result = self.special_emi.get(month)
            print(f"DEBUG: Using month-specific special EMI for month {month}: {result}")
            return result
        
        print(f"DEBUG: No special EMI found for month {month}")
        return None

    def _calculate_maturity_date(self) -> date:
        """Calculate the maturity date based on the last payment."""
        if not self.customer_schedule:
            return self.repayment_start_date
        
        # Use the last payment date as maturity date
        last_payment = self.customer_schedule[-1]
        return last_payment["payment_date"]


# Example usage and testing
if __name__ == "__main__":
    # Example 1: Standard loan
    loan1 = LoanRepaymentSchedule(
        principal=100000,
        annual_interest_rate=12.0,
        tenure_months=12,
        repayment_start_date=date(2024, 1, 1)
    )
    result1 = loan1.calculate_schedule()
    print("Standard Loan Schedule:")
    print(f"Standard EMI: {result1['standard_emi']}")
    print(f"Total Interest: {result1['total_interest']:.2f}")
    print(f"Maturity Date: {result1['maturity_date']}")
    
    # Example 2: Loan with special EMI
    loan2 = LoanRepaymentSchedule(
        principal=100000,
        annual_interest_rate=12.0,
        tenure_months=12,
        special_emi=10000,  # Higher EMI
        repayment_start_date=date(2024, 1, 1)
    )
    result2 = loan2.calculate_schedule()
    print("\nSpecial EMI Loan Schedule:")
    print(f"Special EMI: {result2['standard_emi']}")
    print(f"Total Interest: {result2['total_interest']:.2f}")
    print(f"Number of payments: {result2['number_of_rows']}")
    
    # Example 3: Loan with month-specific EMIs
    loan3 = LoanRepaymentSchedule(
        principal=100000,
        annual_interest_rate=12.0,
        tenure_months=12,
        special_emi={1: 15000, 6: 12000},  # Higher EMI in first and 6th month
        repayment_start_date=date(2024, 1, 1)
    )
    result3 = loan3.calculate_schedule()
    print("\nMonth-specific EMI Loan Schedule:")
    print(f"Standard EMI: {result3['standard_emi']}")
    print(f"Total Interest: {result3['total_interest']:.2f}")
    print(f"Number of payments: {result3['number_of_rows']}")
    
    # Example 4: Loan with configurable special EMI period
    loan4 = LoanRepaymentSchedule(
        principal=100000,
        annual_interest_rate=12.0,
        tenure_months=60,
        enable_special_emi=True,
        special_emi_amount=1500,
        special_emi_period=18,  # Special EMI for first 18 months
        repayment_start_date=date(2024, 1, 1)
    )
    result4 = loan4.calculate_schedule()
    print("\nConfigurable Special EMI Loan Schedule:")
    print(f"Standard EMI: {result4['standard_emi']}")
    print(f"Special EMI Amount: {loan4.special_emi_amount}")
    print(f"Special EMI Period: {loan4.special_emi_period} months")
    print(f"Total Interest: {result4['total_interest']:.2f}")
    print(f"Number of payments: {result4['number_of_rows']}")
