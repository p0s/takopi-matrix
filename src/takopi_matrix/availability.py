"""
Centralized Matrix dependency availability checks.

This module provides a single source of truth for nio and E2EE availability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class NioAvailability:
    """
    Cached nio availability state.

    Attributes:
        basic: Whether matrix-nio is installed (required)
        e2ee: Whether E2EE support is available (optional)
        e2ee_check_mode: How E2EE was validated
    """

    basic: bool
    e2ee: bool
    e2ee_check_mode: Literal["hasattr", "olm_import", "unchecked"]


def check_basic_nio() -> bool:
    """
    Check if basic matrix-nio is available.

    Returns True if matrix-nio can be imported.
    This is a REQUIRED dependency for Matrix transport.
    """
    try:
        import nio  # noqa: F401

        return True
    except ImportError:
        return False


def check_e2ee_available(*, strict: bool = False) -> bool:
    """
    Check if E2EE support is available.

    Args:
        strict: If True, validates Olm can be imported (crypto.py pattern).
                If False, only checks hasattr(nio, "crypto") (client.py pattern).

    Returns True if matrix-nio[e2e] dependencies are available.
    This is an OPTIONAL feature.
    """
    try:
        import nio

        if not hasattr(nio, "crypto"):
            return False

        if strict:
            # Validate Olm is actually importable (crypto.py's stricter check)
            from nio.crypto import Olm  # noqa: F401

        return True
    except ImportError:
        return False
    except Exception:
        # Catch any other exceptions (like missing libolm)
        return False


def check_nio_availability(*, strict_e2ee: bool = False) -> NioAvailability:
    """
    Check all nio dependencies and return cached state.

    Args:
        strict_e2ee: Use strict E2EE validation (imports Olm)

    Returns:
        NioAvailability with basic and E2EE status
    """
    basic = check_basic_nio()

    if not basic:
        return NioAvailability(
            basic=False, e2ee=False, e2ee_check_mode="unchecked"
        )

    e2ee = check_e2ee_available(strict=strict_e2ee)
    mode: Literal["hasattr", "olm_import", "unchecked"] = (
        "olm_import" if strict_e2ee else "hasattr"
    )

    return NioAvailability(basic=basic, e2ee=e2ee, e2ee_check_mode=mode)
