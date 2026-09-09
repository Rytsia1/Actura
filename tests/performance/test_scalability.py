import pytest
import time
import tracemalloc
import numpy as np
from actuary_engine.domain.stochastic.monte_carlo import StochasticValuationEngine
from actuary_engine.domain.stochastic.esg import VasicekESG, VasicekParams
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.tables.mortality_table import MortalityTable

@pytest.mark.performance
@pytest.mark.parametrize("num_paths", [
    1000,
    10000,
    100000,
    # 1000000,  # Omitted by default to prevent OOM on typical CI runners, uncomment to test locally
])
def test_monte_carlo_scalability(benchmark, num_paths):
    """
    Benchmark Monte Carlo performance across different simulation sizes.
    Measures: Execution time, Peak memory usage.
    """
    mortality = MortalityTable.from_soa_ilt()
    params = VasicekParams(
        r0=0.05,
        kappa=0.15,
        theta=0.05,
        sigma=0.02
    )
    esg = VasicekESG(params=params)
    contract = PolicyContract(
        issue_age=30,
        product_type=ProductType.WHOLE_LIFE,
        sum_assured=100000.0
    )
    
    engine = StochasticValuationEngine(table=mortality, esg=esg)
    
    # Memory tracking
    tracemalloc.start()
    
    # Time measurement using pytest-benchmark
    def run_simulation():
        return engine.run_simulation(contract, gross_premium=1000.0, n_scenarios=num_paths, seed=42)
    
    result = benchmark(run_simulation)
    
    # Capture memory
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    # Print performance summary
    print(f"\n📊 Performance Summary:")
    print(f"   Paths: {num_paths:,}")
    print(f"   Time: {benchmark.stats.stats.mean:.4f} seconds")
    print(f"   Peak Memory: {peak / 1024 / 1024:.2f} MB")
    
    # Optional: Assert time doesn't exceed threshold (soft warning)
    if num_paths == 10000 and benchmark.stats.stats.mean > 5.0:
        print(f"⚠️ WARNING: 10k paths took {benchmark.stats.stats.mean:.2f}s (>5s threshold)")
        print("   Consider Celery/Redis for this workload.")
    
    # Ensure results are correct (don't sacrifice accuracy for speed)
    assert result.mean_bel is not None
    assert result.var_95 is not None
