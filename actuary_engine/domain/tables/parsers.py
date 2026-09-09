"""
Mortality Table Parsers and Data Integrity Validators.

Supports parsing and validating custom mortality tables in CSV, TSV, and SOA XTbML (XML) formats.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from typing import Optional, Union

import numpy as np
import pandas as pd

from actuary_engine.domain.tables.mortality_table import MortalityTable


class TableParsingError(ValueError):
    """Raised when parsing or validating a mortality table file fails."""


def parse_csv_mortality_table(
    content: Union[str, bytes, io.IOBase],
    name: str = "Custom Table",
    radix: int = 10_000_000,
) -> MortalityTable:
    """Parse a mortality table from CSV or TSV text content.

    Supported headers (case-insensitive, whitespace-trimmed):
    - Age: 'age', 'x', 'attained_age', 'issue_age', 'ages'
    - Mortality Rate: 'qx', 'q_x', 'q(x)', 'mortality_rate', 'mortality', 'rate', 'qx_male', 'qx_female', 'qx_total'
    - Survival Probability: 'px', 'p_x', 'p(x)', 'survival_rate', 'survival_prob'
    - In-force Cohort / Lives: 'lx', 'l_x', 'lives', 'survivors'

    Args:
        content: Raw CSV text, bytes, or file-like object.
        name: Name for the parsed mortality table.
        radix: Radix cohort size for lx calculations.

    Returns:
        Validated MortalityTable instance.

    Raises:
        TableParsingError: If columns are missing or data contains invalid bounds.
    """
    try:
        if isinstance(content, bytes):
            content_str = content.decode("utf-8-sig").strip()
            if not content_str:
                raise TableParsingError("Mortality table CSV file is empty.")
            df = pd.read_csv(io.StringIO(content_str))
        elif isinstance(content, str):
            content_str = content.strip()
            if not content_str:
                raise TableParsingError("Mortality table CSV file is empty.")
            df = pd.read_csv(io.StringIO(content_str))
        else:
            df = pd.read_csv(content)
    except TableParsingError:
        raise
    except pd.errors.EmptyDataError:
        raise TableParsingError("Mortality table CSV file is empty.")
    except Exception as e:
        raise TableParsingError(f"Failed to read CSV format: {e}") from e

    if df.empty:
        raise TableParsingError("Mortality table CSV file is empty.")

    # Normalize column names: lower, trim, replace spaces/dots
    col_map = {col: str(col).strip().lower().replace(" ", "_").replace(".", "_") for col in df.columns}
    df = df.rename(columns=col_map)

    # 1. Detect Age column
    age_candidates = ["age", "x", "attained_age", "issue_age", "ages", "exact_age"]
    age_col = next((c for c in age_candidates if c in df.columns), None)
    if not age_col:
        raise TableParsingError(
            f"Missing required age column. Expected one of: {age_candidates}. Found: {list(df.columns)}"
        )

    # Convert and validate age column
    try:
        df[age_col] = pd.to_numeric(df[age_col], errors="raise")
    except Exception as e:
        raise TableParsingError(f"Invalid non-numeric values found in age column: {e}") from e

    df = df.dropna(subset=[age_col])
    df[age_col] = df[age_col].astype(int)
    df = df.sort_values(by=age_col).drop_duplicates(subset=[age_col])

    ages = df[age_col].to_numpy(dtype=np.int64, copy=True).copy()
    if len(ages) < 2:
        raise TableParsingError(f"Table must have at least 2 distinct ages (found {len(ages)}).")

    if ages[0] < 0 or ages[-1] > 130:
        raise TableParsingError(f"Age range [{ages[0]}, {ages[-1]}] outside valid limits (0 to 130).")

    # Check contiguous ages
    expected_ages = np.arange(ages[0], ages[0] + len(ages))
    if not np.array_equal(ages, expected_ages):
        raise TableParsingError(
            f"Ages must be contiguous integers without gaps. Found range [{ages[0]}, {ages[-1]}] with missing ages."
        )

    # 2. Detect Mortality / Survival columns
    qx_candidates = ["qx", "q_x", "q(x)", "mortality_rate", "mortality", "rate", "qx_male", "qx_female", "qx_total", "mortality_probability"]
    px_candidates = ["px", "p_x", "p(x)", "survival_rate", "survival_prob", "survival_probability"]
    lx_candidates = ["lx", "l_x", "lives", "survivors", "inforce"]

    qx_col = next((c for c in qx_candidates if c in df.columns), None)
    px_col = next((c for c in px_candidates if c in df.columns), None)
    lx_col = next((c for c in lx_candidates if c in df.columns), None)

    if qx_col:
        try:
            qx = pd.to_numeric(df[qx_col], errors="raise").to_numpy(dtype=np.float64, copy=True).copy()
        except Exception as e:
            raise TableParsingError(f"Invalid non-numeric values in mortality column '{qx_col}': {e}") from e
    elif px_col:
        try:
            px = pd.to_numeric(df[px_col], errors="raise").to_numpy(dtype=np.float64, copy=True).copy()
            qx = (1.0 - px).copy()
        except Exception as e:
            raise TableParsingError(f"Invalid non-numeric values in survival column '{px_col}': {e}") from e
    elif lx_col:
        try:
            lx_vals = pd.to_numeric(df[lx_col], errors="raise").to_numpy(dtype=np.float64, copy=True).copy()
            if np.any(lx_vals < 0):
                raise TableParsingError("Survivorship (lx) values cannot be negative.")
            # qx[k] = (lx[k] - lx[k+1]) / lx[k]
            qx = np.zeros(len(lx_vals), dtype=np.float64)
            for k in range(len(lx_vals) - 1):
                if lx_vals[k] > 0:
                    qx[k] = (lx_vals[k] - lx_vals[k + 1]) / lx_vals[k]
                else:
                    qx[k] = 1.0
            qx[-1] = 1.0
        except Exception as e:
            raise TableParsingError(f"Invalid non-numeric values in lx column '{lx_col}': {e}") from e
    else:
        raise TableParsingError(
            f"No valid mortality rate column found. Expected one of: {qx_candidates}, {px_candidates}, or {lx_candidates}."
        )

    # 3. Validate Probability Bounds
    if np.any(np.isnan(qx)):
        raise TableParsingError("Mortality table contains NaN values.")

    if np.any(qx < 0.0) or np.any(qx > 1.0):
        invalid_idx = np.where((qx < 0.0) | (qx > 1.0))[0]
        sample_bad = [(int(ages[i]), float(qx[i])) for i in invalid_idx[:3]]
        raise TableParsingError(
            f"Mortality probabilities must satisfy 0 <= qx <= 1. Invalid values at ages: {sample_bad}"
        )

    # If terminal age has qx < 1.0, enforce qx[-1] = 1.0 for valid life table termination
    if qx[-1] < 1.0:
        qx[-1] = 1.0

    try:
        return MortalityTable(ages=ages, qx=qx, name=name, radix=radix)
    except ValueError as e:
        raise TableParsingError(str(e)) from e


def parse_xtbml_mortality_table(
    content: Union[str, bytes, io.IOBase],
    name: str = "XTbML Table",
    radix: int = 10_000_000,
) -> MortalityTable:
    """Parse an SOA XTbML (XML) format mortality table.

    Args:
        content: Raw XML content (str, bytes, or stream).
        name: Name for the parsed table.
        radix: Radix cohort size.

    Returns:
        Validated MortalityTable instance.

    Raises:
        TableParsingError: If XML structure is malformed or invalid.
    """
    try:
        if isinstance(content, str):
            root = ET.fromstring(content)
        elif isinstance(content, bytes):
            root = ET.fromstring(content.decode("utf-8"))
        else:
            tree = ET.parse(content)
            root = tree.getroot()
    except Exception as e:
        raise TableParsingError(f"Malformed XTbML XML document: {e}") from e

    # Look for table name in metadata
    meta_name = None
    table_name_node = root.find(".//TableName") or root.find(".//TableIdentity")
    if table_name_node is not None and table_name_node.text:
        meta_name = table_name_node.text.strip()

    final_name = name if name != "XTbML Table" else (meta_name or name)

    # Find Axis / Y data points
    # XTbML typical structure: <Table> <Values> <Axis Def="Age"> <Y t="0">0.001</Y> ...
    y_nodes = root.findall(".//Y") or root.findall(".//Point")
    if not y_nodes:
        raise TableParsingError("No <Y> or <Point> mortality rate elements found in XTbML structure.")

    ages_list = []
    qx_list = []

    for idx, node in enumerate(y_nodes):
        # Age can be in attribute 't', 'x', 'Age', or inferred from index
        age_attr = node.get("t") or node.get("x") or node.get("Age") or node.get("age")
        if age_attr is not None:
            try:
                age_val = int(age_attr)
            except ValueError:
                age_val = idx
        else:
            age_val = idx

        try:
            val_text = node.text.strip() if node.text else "0"
            qx_val = float(val_text)
        except ValueError as e:
            raise TableParsingError(f"Invalid mortality rate value in node <{node.tag}>: {node.text}") from e

        ages_list.append(age_val)
        qx_list.append(qx_val)

    ages = np.array(ages_list, dtype=np.int64)
    qx = np.array(qx_list, dtype=np.float64)

    # Sort and remove duplicates
    sort_idx = np.argsort(ages)
    ages = ages[sort_idx]
    qx = qx[sort_idx]

    # Validate contiguous ages
    expected = np.arange(ages[0], ages[0] + len(ages))
    if not np.array_equal(ages, expected):
        raise TableParsingError(f"XTbML ages must be contiguous integers. Found range [{ages[0]}, {ages[-1]}].")

    if np.any(qx < 0.0) or np.any(qx > 1.0):
        raise TableParsingError("XTbML mortality rates must be in range [0, 1].")

    if qx[-1] < 1.0:
        qx[-1] = 1.0

    try:
        return MortalityTable(ages=ages, qx=qx, name=final_name, radix=radix)
    except ValueError as e:
        raise TableParsingError(str(e)) from e


def parse_mortality_file(
    filename: str,
    content: Union[str, bytes],
    name: Optional[str] = None,
    radix: int = 10_000_000,
) -> MortalityTable:
    """Auto-detect format and parse mortality table file."""
    ext = filename.lower().split(".")[-1]
    table_name = name or re.sub(r"\.[^.]+$", "", filename).replace("_", " ").title()

    if ext in ("xml", "xtbml"):
        return parse_xtbml_mortality_table(content, name=table_name, radix=radix)
    elif ext in ("csv", "tsv", "txt"):
        return parse_csv_mortality_table(content, name=table_name, radix=radix)
    else:
        # Fallback to CSV parser
        try:
            return parse_csv_mortality_table(content, name=table_name, radix=radix)
        except Exception:
            # Try XTbML
            return parse_xtbml_mortality_table(content, name=table_name, radix=radix)
