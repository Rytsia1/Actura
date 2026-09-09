"""
Mortality table parsing and life table computation.

Provides the ``MortalityTable`` class which parses raw mortality rates (qx)
from CSV files and computes the full life table columns (lx, dx, px) using
vectorized NumPy operations. Supports loading the bundled SOA Illustrative
Life Table or any custom table in ``age,qx`` CSV format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union
import os

import numpy as np
import pandas as pd


# Default radix (initial cohort size) — SOA convention
_DEFAULT_RADIX: int = 10_000_000

# Path to the bundled SOA Illustrative Life Table
_env_path = os.getenv("MORTALITY_TABLE_PATH")
_SOA_ILT_PATH: Path = Path(_env_path) if _env_path else Path(__file__).parent.parent.parent / "data" / "soa_ilt.csv"


class MortalityTable:
    """Parsed mortality table with vectorized life table columns.

    Constructs the complete life table from an array of age-specific
    mortality rates (qx). All derived columns — survivorship (lx),
    deaths (dx), and survival probabilities (px) — are computed
    on initialization using fully vectorized NumPy operations.

    Attributes:
        name: Human-readable table name.
        min_age: Minimum age in the table.
        max_age: Maximum age (ω) — the age where qx = 1.
        radix: Initial cohort size (l₀).
        qx: Mortality rate array, shape (num_ages,).
        lx: Survivorship array, shape (num_ages,).
        dx: Deaths array, shape (num_ages,).
        px: Survival probability array, shape (num_ages,).
    """

    __slots__ = ("name", "min_age", "max_age", "radix", "qx", "lx", "dx", "px", "_ages")

    def __init__(
        self,
        ages: np.ndarray,
        qx: np.ndarray,
        name: str = "custom",
        radix: int = _DEFAULT_RADIX,
    ) -> None:
        """Initialize MortalityTable from age and qx arrays.

        Args:
            ages: 1-D integer array of ages. Must be contiguous (e.g., 0–110).
            qx: 1-D float array of mortality rates. Must satisfy 0 ≤ qx ≤ 1
                for all ages, with qx[ω] = 1 at the limiting age.
            name: Human-readable name for this table.
            radix: Initial cohort size for the lx column (default 10,000,000).

        Raises:
            ValueError: If input arrays are inconsistent or contain invalid values.
        """
        self._validate_inputs(ages, qx, radix)

        self.name = name
        self._ages = ages.astype(np.int64)
        self.min_age = int(self._ages[0])
        self.max_age = int(self._ages[-1])
        self.radix = radix

        # Store qx as float64 for precision
        self.qx = qx.astype(np.float64)
        self.px = 1.0 - self.qx

        # Compute lx via cumulative product of survival probabilities
        # lx[0] = radix, lx[k] = radix * prod(px[0:k])
        self.lx = np.empty(len(self.qx) + 1, dtype=np.float64)
        self.lx[0] = float(radix)
        self.lx[1:] = radix * np.cumprod(self.px)

        # dx = lx[x] - lx[x+1] = lx[x] * qx[x]
        self.dx = self.lx[:-1] * self.qx

    @staticmethod
    def _validate_inputs(ages: np.ndarray, qx: np.ndarray, radix: int = _DEFAULT_RADIX) -> None:
        """Validate input arrays and fundamental mortality table invariants.

        Invariants enforced at table creation:
        1. Dimensionality: `ages` and `qx` must be 1-dimensional arrays.
        2. Equal Length: `len(ages) == len(qx)`.
        3. Minimum Size: `len(ages) >= 2`.
        4. Contiguity & Bounds: `ages` must be contiguous integers with min_age >= 0.
        5. Probability Bounds: All `qx` values must satisfy 0 <= qx <= 1 with no NaN or Inf.
        6. Limiting Age Closure (Omega): `qx[-1] == 1.0` at the terminal age (omega).
        7. Pre-Omega Survivorship: `qx[x] < 1.0` for all ages prior to omega.
        8. Radix: `radix > 0`.

        Args:
            ages: Array of ages.
            qx: Array of mortality rates.
            radix: Initial cohort size.

        Raises:
            ValueError: On invalid inputs or invariant violations.
        """
        if ages.ndim != 1 or qx.ndim != 1:
            raise ValueError("ages and qx must be 1-dimensional arrays.")
        if len(ages) != len(qx):
            raise ValueError(
                f"ages and qx must have the same length. "
                f"Got {len(ages)} ages and {len(qx)} qx values."
            )
        if len(ages) < 2:
            raise ValueError("Mortality table must have at least 2 ages.")

        if np.any(np.isnan(qx)) or np.any(np.isinf(qx)):
            raise ValueError("Mortality table qx array contains NaN or Inf values.")

        if np.any(qx < 0.0) or np.any(qx > 1.0):
            raise ValueError("All qx values must be in [0, 1].")

        min_age = int(ages[0])
        max_age = int(ages[-1])

        if min_age < 0:
            raise ValueError(f"Minimum age must be non-negative. Got {min_age}.")

        # Check ages are contiguous integers
        expected_ages = np.arange(min_age, min_age + len(ages), dtype=np.int64)
        if not np.array_equal(ages, expected_ages):
            raise ValueError(
                f"Ages must be contiguous integers (e.g., {min_age}, {min_age+1}, ..., {max_age})."
            )

        # Limiting age closure invariant: qx at omega must equal 1.0
        if not np.isclose(float(qx[-1]), 1.0, atol=1e-6):
            raise ValueError(
                f"Mortality table invariant violated: table ends at age {max_age} (omega), "
                f"but qx[{max_age}] = {float(qx[-1]):.6f} ≠ 1.0. Limiting age must have qx = 1.0 "
                f"to guarantee cohort closure."
            )

        # Pre-omega survivorship invariant: qx before omega must be strictly < 1.0
        if np.any(qx[:-1] >= 1.0):
            premature_idx = int(np.where(qx[:-1] >= 1.0)[0][0])
            premature_age = int(ages[premature_idx])
            raise ValueError(
                f"Mortality table invariant violated: qx[{premature_age}] = {float(qx[premature_idx])} >= 1.0 "
                f"prior to the limiting age omega ({max_age}). An earlier limiting age creates dead-end cohorts."
            )

        if radix <= 0:
            raise ValueError(f"Radix must be a positive integer. Got {radix}.")

    @property
    def omega(self) -> int:
        """Limiting age ω — the last age in the table.

        This is the age at which the entire cohort has died (qx[ω] = 1
        or lx[ω+1] ≈ 0).
        """
        return self.max_age

    @property
    def num_ages(self) -> int:
        """Number of ages in the table."""
        return len(self.qx)

    @property
    def ages(self) -> np.ndarray:
        """Array of ages in the table."""
        return self._ages.copy()

    def _idx(self, age: int) -> int:
        """Convert absolute age to array index.

        Args:
            age: Absolute age.

        Returns:
            Array index.

        Raises:
            ValueError: If age is out of range.
        """
        idx = age - self.min_age
        if idx < 0 or idx >= self.num_ages:
            raise ValueError(
                f"Age {age} is out of range [{self.min_age}, {self.max_age}]."
            )
        return idx

    def get_qx(self, age: int) -> float:
        """Get mortality rate for a specific age.

        Args:
            age: The age to query.

        Returns:
            Mortality rate qx at the given age.
        """
        return float(self.qx[self._idx(age)])

    def get_px(self, age: int) -> float:
        """Get survival probability for a specific age.

        Args:
            age: The age to query.

        Returns:
            Survival probability px = 1 - qx at the given age.
        """
        return float(self.px[self._idx(age)])

    def get_lx(self, age: int) -> float:
        """Get number of survivors at exact age.

        Args:
            age: The age to query. Can be up to max_age + 1.

        Returns:
            Number of survivors lx at exact age.
        """
        idx = age - self.min_age
        if idx < 0 or idx > self.num_ages:
            raise ValueError(
                f"Age {age} is out of range [{self.min_age}, {self.max_age + 1}]."
            )
        return float(self.lx[idx])

    def get_dx(self, age: int) -> float:
        """Get expected deaths between age x and x+1.

        Args:
            age: The age to query.

        Returns:
            Expected number of deaths dx at age x.
        """
        return float(self.dx[self._idx(age)])

    def get_tpx(self, x: int, t: int) -> float:
        """Compute t-year survival probability ₜpₓ.

        ₜpₓ = P(survive from age x to age x+t)
             = lx[x+t] / lx[x]
             = ∏ₖ₌₀ᵗ⁻¹ (1 - qx[x+k])

        Args:
            x: Starting age.
            t: Number of years.

        Returns:
            t-year survival probability.

        Raises:
            ValueError: If age range is out of bounds or duration exceeds mortality table data.
        """
        if t < 0:
            raise ValueError(f"Duration t must be non-negative. Got {t}.")
        if t == 0:
            return 1.0

        x_idx = self._idx(x)
        if x + t > self.max_age + 1:
            raise ValueError(
                f"Requested duration t={t} from age {x} (attained age {x + t}) "
                f"exceeds available mortality table data. Limiting age is {self.max_age} ({self.name})."
            )

        end_idx = x + t - self.min_age
        return float(self.lx[end_idx] / self.lx[x_idx])

    def get_tqx(self, x: int, t: int) -> float:
        """Compute t-year mortality probability ₜqₓ.

        ₜqₓ = 1 - ₜpₓ = P(die within t years from age x)

        Args:
            x: Starting age.
            t: Number of years.

        Returns:
            t-year mortality probability.
        """
        return 1.0 - self.get_tpx(x, t)

    def get_deferred_qx(self, x: int, u: int, t: int = 1) -> float:
        """Compute u-year deferred t-year mortality probability u|t_qx.

        u|t_qx = ₜpₓ · ₜqₓ₊ᵤ = probability of surviving u years then
        dying within the next t years.

        Args:
            x: Starting age.
            u: Deferral period (years).
            t: Death window (years), default 1.

        Returns:
            Deferred mortality probability.

        Raises:
            ValueError: If deferral window exceeds available mortality table data.
        """
        if u < 0:
            raise ValueError(f"u must be non-negative. Got {u}.")
        if t <= 0:
            raise ValueError(f"t must be positive. Got {t}.")
        if x + u + t > self.max_age + 1:
            raise ValueError(
                f"Requested deferred window x + u + t = {x + u + t} "
                f"exceeds available mortality table data ({self.max_age} in {self.name})."
            )
        return self.get_tpx(x, u) * self.get_tqx(x + u, t)

    def tpx_vector(self, x: int, max_t: Optional[int] = None) -> np.ndarray:
        """Vectorized computation of ₜpₓ for t = 0, 1, ..., max_t.

        Args:
            x: Starting age.
            max_t: Maximum duration. Defaults to ω - x.

        Returns:
            Array of survival probabilities [₀pₓ, ₁pₓ, ..., ₘₐₓₜpₓ].

        Raises:
            ValueError: If x is out of range, max_t is negative, or x + max_t > max_age.
        """
        x_idx = self._idx(x)
        if max_t is None:
            max_t = self.max_age - x
        elif max_t < 0:
            raise ValueError(f"max_t must be non-negative. Got {max_t}.")
        elif x + max_t > self.max_age:
            raise ValueError(
                f"Requested projection duration max_t ({max_t}) from age {x} "
                f"(attained age {x + max_t}) exceeds available mortality table data. "
                f"Maximum available duration is {self.max_age - x} years "
                f"(reaching limiting age {self.max_age} of {self.name})."
            )

        end_idx = x_idx + max_t + 1
        lx_x = self.lx[x_idx]
        return self.lx[x_idx:end_idx] / lx_x

    def tqx_vector(self, x: int, max_t: Optional[int] = None) -> np.ndarray:
        """Vectorized computation of ₜqₓ for t = 0, 1, ..., max_t.

        Args:
            x: Starting age.
            max_t: Maximum duration. Defaults to ω - x.

        Returns:
            Array of mortality probabilities [₀qₓ, ₁qₓ, ..., ₘₐₓₜqₓ].

        Raises:
            ValueError: If projection duration exceeds mortality table bounds.
        """
        return 1.0 - self.tpx_vector(x, max_t)

    @classmethod
    def from_csv(
        cls,
        path: Union[str, Path],
        name: Optional[str] = None,
        radix: int = _DEFAULT_RADIX,
        age_col: str = "age",
        qx_col: str = "qx",
    ) -> "MortalityTable":
        """Load a mortality table from a CSV file.

        Expected format: two columns with headers for age (integer) and
        qx (float). Rows must cover a contiguous range of ages.

        Args:
            path: Path to CSV file.
            name: Table name (defaults to filename stem).
            radix: Initial cohort size.
            age_col: Name of the age column.
            qx_col: Name of the qx column.

        Returns:
            Parsed MortalityTable instance.
        """
        path = Path(path)
        if name is None:
            name = path.stem

        df = pd.read_csv(path)
        if age_col not in df.columns or qx_col not in df.columns:
            raise ValueError(
                f"CSV must contain '{age_col}' and '{qx_col}' columns. "
                f"Found: {list(df.columns)}"
            )

        df = df.sort_values(age_col).reset_index(drop=True)
        ages = df[age_col].values.astype(np.int64)
        qx = df[qx_col].values.astype(np.float64)

        return cls(ages=ages, qx=qx, name=name, radix=radix)

    @classmethod
    def from_soa_ilt(cls, radix: int = _DEFAULT_RADIX) -> "MortalityTable":
        """Load the bundled SOA Illustrative Life Table.

        This is the standard reference table used in SOA exam problems
        (STAM/LTAM), covering ages 0–110 with qx[110] = 1.

        Args:
            radix: Initial cohort size (default 10,000,000).

        Returns:
            MortalityTable instance with SOA ILT data.
        """
        return cls.from_csv(
            path=_SOA_ILT_PATH,
            name="SOA Illustrative Life Table",
            radix=radix,
        )

    @classmethod
    def from_qx_array(
        cls,
        qx: Union[list[float], np.ndarray],
        start_age: int = 0,
        name: str = "custom",
        radix: int = _DEFAULT_RADIX,
    ) -> "MortalityTable":
        """Create a mortality table from a raw qx array.

        Convenient factory for testing and programmatic table construction.

        Args:
            qx: Sequence of mortality rates starting at start_age.
            start_age: Age corresponding to the first qx value.
            name: Table name.
            radix: Initial cohort size.

        Returns:
            MortalityTable instance.
        """
        qx_arr = np.asarray(qx, dtype=np.float64)
        ages = np.arange(start_age, start_age + len(qx_arr), dtype=np.int64)
        return cls(ages=ages, qx=qx_arr, name=name, radix=radix)

    def validate_contract(self, contract: Any) -> None:
        """Validate that a PolicyContract satisfies this mortality table's age limits.

        Ensures the mortality table is the source of truth for maximum and minimum age.

        Args:
            contract: PolicyContract instance to validate.

        Raises:
            ValueError: If the contract's issue age or term exceeds this table's boundaries.
        """
        contract.validate_against_table(self)

    def __repr__(self) -> str:
        return (
            f"MortalityTable(name='{self.name}', ages=[{self.min_age}..{self.max_age}], "
            f"radix={self.radix:,})"
        )

    def __len__(self) -> int:
        return self.num_ages
