#!/usr/bin/env python3
"""Integrations package: status report + Google/Outlook OAuth integrations.

Re-exports `report` from .status for backward compatibility:
    from jev.integrations import report
"""
from .status import report

__all__ = ["report"]
