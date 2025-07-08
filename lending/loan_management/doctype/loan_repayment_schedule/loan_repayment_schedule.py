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
            principal = getattr(self, "loan_amount", 0)
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
        principal = getattr(self, "loan_amount", 0)
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
        
        print(f"DEBUG: Values - principal={principal}, tenure={tenure_months}, rate={annual_interest_rate}")  # Debug line
        
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
                    special_emi_dict = {}
                    for month in range(1, special_emi_period + 1):
                        special_emi_dict[month] = special_emi_amount
                    special_emi = special_emi_dict
                else:
                    print("DEBUG: Special EMI not enabled or invalid, using standard EMI")
                    special_emi = None
                
                # Create a new engine with current values
                self._engine = _RepaymentEngine(
                    principal=principal,
                    annual_interest_rate=annual_interest_rate,
                    tenure_months=tenure_months,
                    special_emi=special_emi,
                    repayment_start_date=repayment_start_date,
                    rounding=getattr(self, "rounding", 2)
                )
                
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
        principal = getattr(self, "loan_amount", 0)
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
        return round(emi, self.rounding)
    
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
        """Generate the repayment schedule."""
        schedule = []
        balance = self.principal
        month = 1
        max_iterations = self.tenure_months * 3  # Safety limit
        
        # Prepare special EMI overrides
        constant_emi: Optional[float] = None
        month_overrides: Dict[int, float] = {}

        if self.special_emi is not None:
            if isinstance(self.special_emi, (int, float)):
                constant_emi = float(self.special_emi)
            else:
                month_overrides = {int(k): float(v) for k, v in self.special_emi.items()}

        while balance > 10 ** (-self.rounding) and month <= max_iterations:
            # Determine EMI for this month
            if month in month_overrides:
                emi = month_overrides[month]
            elif constant_emi is not None:
                emi = constant_emi
            else:
                # Use adjusted EMI for months after special EMI period
                if hasattr(self, 'adjusted_emi') and self.adjusted_emi > 0:
                    emi = self.adjusted_emi
                else:
                    emi = self.standard_emi
            
            # Calculate interest and principal components
            interest = round(balance * self.monthly_rate, self.rounding)
            
            # Check if this is the final payment (last month)
            if month == self.tenure_months:
                # Final payment - clear the entire remaining balance
                principal_component = round(balance, self.rounding)
                emi = round(principal_component + interest, self.rounding)
                balance = 0
            else:
                # Handle case where EMI is less than interest
                if emi <= interest:
                    # EMI covers only part or none of the interest
                    principal_component = 0
                    # The remaining interest gets added to the balance (negative amortization)
                    balance = round(balance + (interest - emi), self.rounding)
                else:
                    # Normal case: EMI exceeds interest
                    principal_component = round(min(emi - interest, balance), self.rounding)
                    balance = round(balance - principal_component, self.rounding)
            
            # Calculate payment date
            payment_date = self._calculate_payment_date(month)
            
            # Add to schedule
            schedule.append({
                "month": month,
                "payment_date": payment_date,
                "emi": round(emi, self.rounding),
                "interest": interest,
                "principal": principal_component,
                "balance": max(balance, 0.0),
            })
            
            # Check if loan is fully repaid
            if balance <= 0:
                break
            
            month += 1

        # Edge case: If we hit max iterations, the loan might not be fully repaid
        if month > max_iterations and balance > 0:
            raise ValueError(
                f"Loan not fully repaid after {max_iterations} iterations. "
                f"Remaining balance: {balance:.2f}. Check EMI values."
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
