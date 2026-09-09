# Actura Reproducibility Guarantees

In stochastic and Monte Carlo modeling, the ability to exactly reproduce a run is essential for auditing, debugging, and regulatory compliance.

Actura guarantees numerical reproducibility for stochastic valuation runs when the same engine version, parameters, and pseudorandom seed are used.

## Reproducibility Metadata

When a stochastic run is initiated, Actura generates and stores a **computational identity** mapping to the run. This is captured in the `RunMetadata` structure, which includes:

- **Seed**: The exact 32-bit integer used to initialize the pseudorandom number generator for Monte Carlo scenario generation.
- **Engine Version**: The version of the Actura engine used (e.g., `0.2.3`).
- **Dependency Versions**: The versions of critical libraries like `numpy` and `pydantic`.
- **Valuation Configuration**: The `n_scenarios`, `product_type`, `issue_age`, `term`, `sum_assured`, and the mortality `table_id`.
- **Economic Model**: The short-rate model (e.g., `VASICEK`) and its calibrated parameters (`kappa`, `theta`, `sigma`, `r0`).
- **Creation Timestamp**: The exact unix timestamp of execution.

This metadata is persisted alongside the job in the underlying SQLite `jobs` table as JSON.

## Random Seed Handling

Actura supports two modes for seed management:

1. **User-Specified Seed**: If the API payload explicitly contains a `seed: int`, it is utilized directly.
2. **Auto-Generated Seed**: If the `seed` is omitted (`null`), Actura securely generates a random 32-bit integer, assigns it to the run, and crucially **persists it** in the metadata.

The seed is returned in the `run_metadata` field when polling the job status.

## Rerun Semantics

Actura provides a dedicated endpoint for rerunning an existing stochastic job:
`POST /api/v1/valuation/stochastic/rerun/{job_id}`

### Behavior:
- **Exact Configuration**: The rerun uses the exact same configuration payload that produced the original run.
- **Preserved Seed**: By default, the rerun uses the *same* seed as the original run, guaranteeing an identical numerical output. The system **never** silently generates a new seed on a rerun.
- **Seed Override**: Users can optionally supply a `?new_seed=...` query parameter to execute the same exact scenario configuration but under a different sequence of random shocks, which is useful for exploring model variance or increasing the effective simulation sample size.

## Limitations
- **Cross-Architecture Hardware**: Hardware changes (e.g., x86 vs ARM processors) and different BLAS library configurations (e.g., OpenBLAS vs MKL) may introduce floating-point drift at deep levels of precision.
- **Dependency Updates**: Upgrading `numpy` may change the implementation details of pseudorandom number sampling (`np.random`), breaking exact reproducibility with past runs. This is why the `numpy` version is recorded in the metadata.
