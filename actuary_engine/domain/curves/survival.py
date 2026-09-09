"""
Survival curve computation.

Provides the ``SurvivalCurve`` class which constructs vectorized arrays
of survival probabilities (ₜpₓ), mortality probabilities (ₜqₓ), and
deferred mortality (ₜ|₁qₓ) for a given entry age x. Also computes
curtate and complete life expectancies.

Designed as a data object suitable for direct plotting (e.g., Plotly
line charts, survival function visualizations).
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from actuary_engine.domain.tables.mortality_table import MortalityTable


class SurvivalCurve:
    """Vectorized survival curve for a given entry age.

    Computes survival function S(t) = ₜpₓ and related quantities over
    the entire remaining lifetime, stored as NumPy arrays for efficient
    access and visualization.

    Attributes:
        table: Source mortality table.
        entry_age: Age x at which the curve starts.
        max_duration: Maximum projection duration (ω - x).
        durations: Array [0, 1, ..., max_duration].
        tpx: Survival probabilities ₜpₓ for each duration.
        tqx: Mortality probabilities ₜqₓ = 1 - ₜpₓ.
        deferred_qx: Deferred mortality ₜ|₁qₓ = ₜpₓ · qₓ₊ₜ.
    """

    __slots__ = (
        "table",
        "entry_age",
        "max_duration",
        "durations",
        "tpx",
        "tqx",
        "deferred_qx",
    )

    def __init__(
        self,
        table: MortalityTable,
        entry_age: int,
        max_duration: Optional[int] = None,
    ) -> None:
        """Initialize a survival curve for a given entry age.

        Args:
            table: A parsed MortalityTable.
            entry_age: Age x at which the survival curve begins.
            max_duration: Maximum duration to compute. Defaults to ω - x.

        Raises:
            ValueError: If entry_age is out of the table range.
        """
        if entry_age < table.min_age or entry_age > table.max_age:
            raise ValueError(
                f"Entry age {entry_age} is out of range "
                f"[{table.min_age}, {table.max_age}]."
            )

        self.table = table
        self.entry_age = entry_age

        if max_duration is None:
            max_duration = table.max_age - entry_age
        elif max_duration < 0:
            raise ValueError(f"max_duration must be non-negative. Got {max_duration}.")
        elif entry_age + max_duration > table.max_age:
            raise ValueError(
                f"Requested duration ({max_duration} years) from entry age {entry_age} "
                f"(attained age {entry_age + max_duration}) exceeds available mortality table data. "
                f"Maximum available duration is {table.max_age - entry_age} years "
                f"(reaching limiting age {table.max_age} of {table.name})."
            )

        self.max_duration = max_duration

        # Duration array [0, 1, ..., max_duration]
        self.durations = np.arange(max_duration + 1, dtype=np.int64)

        # ₜpₓ = l_{x+t} / l_x — vectorized via MortalityTable
        self.tpx = table.tpx_vector(entry_age, max_duration)

        # ₜqₓ = 1 - ₜpₓ
        self.tqx = 1.0 - self.tpx

        # ₜ|₁qₓ = ₜpₓ · q_{x+t} (deferred 1-year mortality)
        # For t = 0, 1, ..., max_duration - 1
        x_idx = entry_age - table.min_age
        qx_slice = table.qx[x_idx : x_idx + max_duration]
        self.deferred_qx = np.empty(max_duration + 1, dtype=np.float64)
        self.deferred_qx[:max_duration] = self.tpx[:max_duration] * qx_slice
        self.deferred_qx[max_duration] = self.tpx[max_duration]  # All remaining die

    def curtate_expectation(self) -> float:
        """Curtate expectation of life eₓ.

        eₓ = Σₜ₌₁^{ω-x} ₜpₓ

        The expected number of complete future years lived.

        Returns:
            Curtate expectation of life.
        """
        # Sum tpx for t = 1, 2, ..., max_duration
        return float(np.sum(self.tpx[1:]))

    def complete_expectation(self) -> float:
        """Complete expectation of life e̊ₓ.

        Under the Uniform Distribution of Deaths (UDD) assumption:
        e̊ₓ ≈ eₓ + 0.5

        Returns:
            Complete (continuous) expectation of life.
        """
        return self.curtate_expectation() + 0.5

    def median_future_lifetime(self) -> float:
        """Median future lifetime — the duration t where ₜpₓ first drops below 0.5.

        Uses linear interpolation between the last t where ₜpₓ ≥ 0.5
        and the first t where ₜpₓ < 0.5.

        Returns:
            Estimated median future lifetime in years.
        """
        below_half = np.where(self.tpx < 0.5)[0]
        if len(below_half) == 0:
            return float(self.max_duration)

        t_cross = below_half[0]
        if t_cross == 0:
            return 0.0

        # Linear interpolation
        p_before = self.tpx[t_cross - 1]
        p_after = self.tpx[t_cross]
        fraction = (p_before - 0.5) / (p_before - p_after)
        return float(t_cross - 1 + fraction)

    def survival_at(self, t: int) -> float:
        """Get ₜpₓ at a specific duration.

        Args:
            t: Duration in years.

        Returns:
            Survival probability at duration t.

        Raises:
            ValueError: If t is out of range.
        """
        if t < 0 or t > self.max_duration:
            raise ValueError(
                f"Duration {t} is out of range [0, {self.max_duration}]."
            )
        return float(self.tpx[t])

    def mortality_at(self, t: int) -> float:
        """Get ₜqₓ at a specific duration.

        Args:
            t: Duration in years.

        Returns:
            Mortality probability at duration t.
        """
        return 1.0 - self.survival_at(t)

    def to_dict(self) -> dict[str, list[float]]:
        """Export curve data as a dictionary suitable for DataFrame or JSON.

        Returns:
            Dictionary with keys 'duration', 'tpx', 'tqx', 'deferred_qx'.
        """
        return {
            "duration": self.durations.tolist(),
            "tpx": self.tpx.tolist(),
            "tqx": self.tqx.tolist(),
            "deferred_qx": self.deferred_qx.tolist(),
        }

    def __repr__(self) -> str:
        ex = self.curtate_expectation()
        return (
            f"SurvivalCurve(table='{self.table.name}', x={self.entry_age}, "
            f"eₓ={ex:.2f}, max_t={self.max_duration})"
        )
