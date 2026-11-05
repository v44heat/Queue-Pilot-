"""Congestion levels from the number of customers waiting for a service.

Boundaries are INCLUSIVE lower bounds taken from system settings (defaults 5 / 11 / 21):
    LOW       fewer than moderate_min            (default 0-4)
    MODERATE  moderate_min .. high_min - 1       (default 5-10)
    HIGH      high_min .. critical_min - 1       (default 11-20)
    CRITICAL  critical_min or more               (default 21+, i.e. more than 20)
The level applies to ONE service's queue; the system-wide level is the worst of the services.
"""
from . import settings_service

LEVELS = ("LOW", "MODERATE", "HIGH", "CRITICAL")


def thresholds() -> dict:
    return {
        "moderate": settings_service.get("congestion.moderate_min"),
        "high": settings_service.get("congestion.high_min"),
        "critical": settings_service.get("congestion.critical_min"),
    }


def level_for(waiting: int, t: dict | None = None) -> str:
    t = t or thresholds()
    if waiting >= t["critical"]:
        return "CRITICAL"
    if waiting >= t["high"]:
        return "HIGH"
    if waiting >= t["moderate"]:
        return "MODERATE"
    return "LOW"


def worst(levels) -> str:
    return max(levels, key=LEVELS.index, default="LOW")
