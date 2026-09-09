"""
Dynamic Thread-Safe Mortality Table Registry.

Manages in-memory storage and dynamic lookups of standard and user-uploaded
MortalityTable instances.
"""

from __future__ import annotations

import threading
from typing import Any, Optional
import numpy as np
from pydantic import BaseModel, Field

from actuary_engine.domain.tables.mortality_table import MortalityTable


class TableMetadata(BaseModel):
    """Metadata summary of a registered mortality table."""

    table_id: str = Field(..., description="Unique identifier for the mortality table.")
    name: str = Field(..., description="Human-readable table name.")
    description: str = Field(default="", description="Detailed description or source notes.")
    min_age: int = Field(..., description="Minimum issue age available.")
    max_age: int = Field(..., description="Maximum age (omega).")
    omega: int = Field(..., description="Limiting age.")
    radix: int = Field(..., description="Initial cohort size.")
    is_builtin: bool = Field(default=False, description="Whether this is a bundled system table.")
    sample_qx: dict[str, float] = Field(default_factory=dict, description="Sample mortality rates.")


class TableRegistry:
    """Thread-safe singleton registry for mortality tables."""

    _instance: Optional[TableRegistry] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> TableRegistry:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._tables: dict[str, MortalityTable] = {}
        self._metadata: dict[str, TableMetadata] = {}
        self._reg_lock = threading.Lock()
        self._load_default_tables()
        self._initialized = True

    def _load_default_tables(self) -> None:
        """Pre-load standard actuarial mortality tables."""
        try:
            soa_table = MortalityTable.from_soa_ilt()
            self.register_table(
                table_id="soa_ilt",
                table=soa_table,
                description="Society of Actuaries (SOA) Illustrative Life Table (ω=110)",
                is_builtin=True,
            )
        except Exception as e:
            # Fallback table if SOA ILT csv is not reachable
            ages = np.arange(0, 111)
            qx = np.clip((ages / 110.0) ** 3, 0.0, 1.0)
            qx[-1] = 1.0
            fallback_table = MortalityTable(ages=ages, qx=qx, name="SOA Illustrative Life Table (Fallback)")
            self.register_table(
                table_id="soa_ilt",
                table=fallback_table,
                description="SOA Illustrative Life Table (Built-in Fallback)",
                is_builtin=True,
            )

    def register_table(
        self,
        table_id: str,
        table: MortalityTable,
        description: str = "",
        is_builtin: bool = False,
    ) -> TableMetadata:
        """Register a mortality table in the registry.

        Args:
            table_id: Unique identifier (e.g. 'soa_ilt', 'custom_tmi_2024').
            table: MortalityTable instance.
            description: Optional description notes.
            is_builtin: If True, marks table as protected system table.

        Returns:
            TableMetadata object.
        """
        clean_id = table_id.strip().lower().replace(" ", "_")

        sample_ages = [20, 30, 40, 50, 60, 70, 80, 90, 100]
        sample_qx = {}
        for a in sample_ages:
            if table.min_age <= a <= table.max_age:
                sample_qx[f"q{a}"] = round(float(table.get_tqx(a, 1)), 6)

        meta = TableMetadata(
            table_id=clean_id,
            name=table.name,
            description=description,
            min_age=table.min_age,
            max_age=table.max_age,
            omega=table.omega,
            radix=table.radix,
            is_builtin=is_builtin,
            sample_qx=sample_qx,
        )

        with self._reg_lock:
            self._tables[clean_id] = table
            self._metadata[clean_id] = meta

        return meta

    def get_table(self, table_id: str = "soa_ilt") -> MortalityTable:
        """Retrieve a registered MortalityTable by ID.

        Args:
            table_id: Table identifier. Defaults to 'soa_ilt'.

        Returns:
            MortalityTable instance.

        Raises:
            KeyError: If table_id is not found in registry.
        """
        clean_id = (table_id or "soa_ilt").strip().lower().replace(" ", "_")
        with self._reg_lock:
            if clean_id not in self._tables:
                available = list(self._tables.keys())
                raise KeyError(
                    f"Mortality table '{clean_id}' not found in registry. Available tables: {available}"
                )
            return self._tables[clean_id]

    def get_metadata(self, table_id: str = "soa_ilt") -> TableMetadata:
        """Retrieve table metadata by ID."""
        clean_id = (table_id or "soa_ilt").strip().lower().replace(" ", "_")
        with self._reg_lock:
            if clean_id not in self._metadata:
                available = list(self._metadata.keys())
                raise KeyError(f"Metadata for table '{clean_id}' not found. Available: {available}")
            return self._metadata[clean_id]

    def list_tables(self) -> list[TableMetadata]:
        """List metadata for all currently registered mortality tables."""
        with self._reg_lock:
            return list(self._metadata.values())

    def has_table(self, table_id: str) -> bool:
        """Check if a table ID exists in the registry."""
        clean_id = table_id.strip().lower().replace(" ", "_")
        with self._reg_lock:
            return clean_id in self._tables

    def delete_table(self, table_id: str, force: bool = False) -> bool:
        """Delete a custom registered table. Built-in tables cannot be deleted unless force=True."""
        clean_id = table_id.strip().lower().replace(" ", "_")
        with self._reg_lock:
            if clean_id not in self._tables:
                return False
            if self._metadata[clean_id].is_builtin and not force:
                raise ValueError(f"Cannot delete built-in system table '{clean_id}'.")
            del self._tables[clean_id]
            del self._metadata[clean_id]
            return True

    def reset_to_defaults(self) -> None:
        """Clear all custom user-uploaded tables and reset to standard baseline."""
        with self._reg_lock:
            self._tables.clear()
            self._metadata.clear()
            self._load_default_tables()


# Global table registry singleton instance
table_registry = TableRegistry()
