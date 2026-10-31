"""Regression analysis and bisection across prompt/configuration history.

Planned capabilities (``docs/architecture/relia.md``, roadmap):

* Evaluation comparison across prompt/configuration versions, with
  bootstrap confidence intervals where statistics justify them.
* Regression bisection over recorded cassettes to locate the change that
  introduced a performance regression.
* Failure categorization and reproducible regression reports.

Not implemented yet — interfaces will be added when the applications
define their first real regression-detection needs (per ADR-0005's
staged-dependency principle applied to RELIA's own scope).
"""
