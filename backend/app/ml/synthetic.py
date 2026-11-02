"""Reproducible SYNTHETIC training data.

This data exists only for development and demonstration. It is generated from assumed
relationships (below) and does NOT represent any real organisation; model scores on it say
nothing about real-world accuracy.

Assumed relationships (each is also checked by tests):
* more people ahead -> longer wait
* more free counters (active - busy) -> shorter wait
* longer average service duration -> longer wait (services differ: TEC > GEN > DOC ...)
* peak hours -> longer queues and slightly slower service
* realistic noise: multiplicative (grows with the number of people ahead) plus additive.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .features import DATASET_COLUMNS, PEAK_HOURS

# service prefix -> (typical minutes per customer, share of arrivals). Matches the demo seed services.
SERVICE_PROFILES = {"GEN": (10, 0.30), "PAY": (6, 0.25), "REG": (12, 0.15), "TEC": (15, 0.15), "DOC": (5, 0.15)}
HOURS = np.arange(8, 17)
HOUR_WEIGHTS = np.array([0.08, 0.15, 0.17, 0.13, 0.06, 0.06, 0.13, 0.14, 0.08])
DEFAULT_START = date(2025, 1, 6)


def generate_dataset(n_rows: int = 6000, seed: int = 42, start: date = DEFAULT_START) -> pd.DataFrame:
    if n_rows < 1:
        raise ValueError("n_rows must be at least 1.")
    rng = np.random.default_rng(seed)
    n_days = max(int(np.ceil(n_rows / 40)), 30)

    days = np.array([start + timedelta(days=i) for i in range(n_days)])
    weekday = np.array([d.weekday() for d in days])
    day_weight = np.select([weekday == 5, weekday == 6, np.isin(weekday, (0, 4))], [0.5, 0.3, 1.15], default=1.0)
    day_idx = rng.choice(n_days, size=n_rows, p=day_weight / day_weight.sum())
    dates, dow = days[day_idx], weekday[day_idx]

    hour = rng.choice(HOURS, size=n_rows, p=HOUR_WEIGHTS)
    peak = np.isin(hour, list(PEAK_HOURS)).astype(int)

    codes = list(SERVICE_PROFILES)
    service = rng.choice(codes, size=n_rows, p=[SERVICE_PROFILES[c][1] for c in codes])
    base = np.array([SERVICE_PROFILES[c][0] for c in service], dtype=float)

    active = np.minimum(1 + rng.binomial(3, 0.5, n_rows) + (peak & (rng.random(n_rows) < 0.5)), 5)
    busy = rng.binomial(active, 0.55 + 0.30 * peak)
    staff = active + (rng.random(n_rows) < 0.15).astype(int)

    waiting_now = rng.poisson(4 + 6 * peak + 1.5 * np.isin(dow, (0, 4)))  # customers already waiting
    ahead = np.where(rng.random(n_rows) < 0.7, waiting_now, rng.integers(0, waiting_now + 1))
    queue_length = waiting_now + 1  # includes the customer being predicted

    avg_duration = np.round(np.maximum(base * rng.normal(1.0, 0.10, n_rows), 0.5 * base), 2)
    d_eff = avg_duration * np.where(staff > active, 0.95, 1.0) * np.where(peak == 1, 1.05, 1.0)

    free = active - busy
    completions_needed = np.maximum(ahead - free + 1, 0)  # services that must finish before this customer starts
    mean_wait = completions_needed / active * d_eff * (1 + 0.01 * queue_length)
    multiplicative = rng.lognormal(0.0, 0.12 + 0.02 * np.sqrt(ahead))
    additive = rng.normal(0.5, 0.8, n_rows)
    waiting = np.round(np.maximum(mean_wait * multiplicative + additive, 0.0), 2)

    service_duration = np.round(base * rng.lognormal(0.0, 0.30, n_rows), 2)  # only known after service

    df = pd.DataFrame({
        "date": [d.isoformat() for d in dates],
        "day_of_week": dow, "hour": hour, "service_type": service,
        "queue_length": queue_length, "people_ahead": ahead,
        "active_counters": active, "busy_counters": busy,
        "average_service_duration": avg_duration, "staff_count": staff, "peak_hour": peak,
        "waiting_time": waiting, "service_duration": service_duration,
    })
    df = df.sort_values(["date", "hour"], kind="stable").reset_index(drop=True)
    return df[DATASET_COLUMNS]
