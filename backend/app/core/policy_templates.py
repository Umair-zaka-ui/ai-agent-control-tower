"""Built-in policy templates surfaced in the dashboard's template gallery."""

from __future__ import annotations

from app.schemas.policy import PolicyTemplate

POLICY_TEMPLATES: list[PolicyTemplate] = [
    PolicyTemplate(
        key="large_claim_approval",
        name="Large Claim Approval",
        description="Require human approval when a submitted claim exceeds $10,000.",
        resource="CLAIM",
        action="SUBMIT_CLAIM",
        conditions={"amount_gt": 10000},
        decision="PENDING_APPROVAL",
        severity="HIGH",
    ),
    PolicyTemplate(
        key="phi_access_restriction",
        name="PHI Access Restriction",
        description="Block agents from reading patient records flagged as PHI.",
        resource="PATIENT_RECORD",
        action="READ",
        conditions={"contains_phi_eq": True},
        decision="BLOCK",
        severity="CRITICAL",
    ),
    PolicyTemplate(
        key="medication_recommendation_block",
        name="Medication Recommendation Block",
        description="Block agents from recommending medication.",
        resource="MEDICATION",
        action="RECOMMEND_MEDICATION",
        conditions={},
        decision="BLOCK",
        severity="CRITICAL",
    ),
    PolicyTemplate(
        key="delete_record_protection",
        name="Delete Record Protection",
        description="Require approval before any record deletion.",
        resource="PATIENT_RECORD",
        action="DELETE",
        conditions={},
        decision="PENDING_APPROVAL",
        severity="HIGH",
    ),
    PolicyTemplate(
        key="external_email_review",
        name="External Email Review",
        description="Route outbound emails to external domains for human review.",
        resource="USER",
        action="SEND_EMAIL",
        conditions={"external_eq": True},
        decision="PENDING_APPROVAL",
        severity="MEDIUM",
    ),
    PolicyTemplate(
        key="payment_transfer_block",
        name="Payment Transfer Block",
        description="Block money transfers above $50,000.",
        resource="PAYMENT",
        action="TRANSFER_MONEY",
        conditions={"amount_gt": 50000},
        decision="BLOCK",
        severity="CRITICAL",
    ),
    PolicyTemplate(
        key="after_hours_high_risk_review",
        name="After-Hours High-Risk Action Review",
        description="Require approval for high-risk actions attempted outside business hours.",
        resource="CUSTOM",
        action="UPDATE",
        conditions={"risk_score_gt": 70, "business_hours_eq": False},
        decision="PENDING_APPROVAL",
        severity="HIGH",
    ),
]
