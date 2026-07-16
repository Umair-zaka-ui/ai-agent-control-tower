"""Enterprise authorization administration portal (Phase 4.3.7).

The operational control plane for IAM: the ``/api/v1/admin`` API surface —
dashboard, delegated role/permission/organization/resource/policy management,
the policy simulator, the authorization decision explorer, access review
campaigns and security analytics. Every endpoint delegates to the existing
phase services (never raw SQL mutations) and is enforced through the 4.3.6
authorization gateway like any other route.
"""
