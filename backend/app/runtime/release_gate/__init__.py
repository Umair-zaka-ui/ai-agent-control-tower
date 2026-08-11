"""ACT-SRS-M3 §Phase-3.3 -- the deployment preflight / release gate engine.

Deliberately no eager re-exports here (mirrors ``app.runtime.environment``'s
own empty ``__init__.py``): ``app.runtime.deployment.service`` imports
``app.runtime.release_gate.service`` to wire the gate into
``start_deploying()``, and this package's own ``checks.py`` needs a local
(function-body) import of ``DeploymentLifecycleService`` from that same
``deployment.service`` module to reuse its approval-funnel logic -- an
eager import here would make that circular.
"""
