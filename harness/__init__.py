"""BlackStar vs Baseline audit harness.

Note on naming: 'BlackStar' is a label for the experimental environment.
This repository does not ship a blackstarctl binary or a blackstar package.
The --env flag on audit_run.py sets a label; it does not enable a real
BlackStar orchestration. When such a component exists, orchestration.py
becomes its adapter.
"""
