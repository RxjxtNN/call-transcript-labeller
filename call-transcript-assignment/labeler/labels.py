"""Fixed label sets and orderings from the workbook's Label Rules sheet."""

from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# PAIR rows: each disposition and its allowed sub-dispositions.
LABELS = {
    "Appointment Scheduled": ("Clinic Visit", "Online Consultation", "Rescheduled"),
    "Follow-up Required": (
        "Specific Callback", "Vague Deferral", "Family Discussion", "Cost Concern",
        "Travel Constraint", "Current Treatment", "Treatment Concern",
        "Information Requested", "Further Discussion",
    ),
    "Not Interested": ("Explicit Refusal", "Do Not Contact"),
    "Invalid Lead": ("Wrong Contact", "No Pain Need", "Outside Service Area", "Policy Exclusion", "Test Enquiry"),
    "Unable to Assess": ("Incomplete Conversation",),
}

# SUB tie-breaking order for Follow-up blockers, then the non-blocker children.
PRIMARY_BLOCKERS = ("Family Discussion", "Cost Concern", "Travel Constraint", "Current Treatment", "Treatment Concern")
FINAL_REASONS = (*PRIMARY_BLOCKERS, "Information Requested", "Vague Deferral", "Further Discussion")
# SUB tie-breaking order for multiple invalid reasons.
INVALID_REASONS = ("Test Enquiry", "Wrong Contact", "No Pain Need", "Policy Exclusion", "Outside Service Area")
REFUSALS = ("Do Not Contact", "Explicit Refusal")  # Do Not Contact takes precedence.

VAGUE_CALLBACK_DAYS = 3  # F7
ORDINARY_CALLBACK_DAYS = 1  # F8
