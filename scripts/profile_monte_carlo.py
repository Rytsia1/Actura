import cProfile
import pstats
import io
import time
from actuary_engine.domain.stochastic.monte_carlo import StochasticValuationEngine
from actuary_engine.domain.stochastic.esg import VasicekESG, VasicekParams
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.tables.mortality_table import MortalityTable

def profile_stochastic_engine():
    """Profile the stochastic engine with 100,000 paths to find hotspots."""
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
    
    print("Starting profiler for 100,000 paths...")
    profiler = cProfile.Profile()
    profiler.enable()
    
    # Run the simulation
    result = engine.run_simulation(contract, gross_premium=1000.0, n_scenarios=100000, seed=42)
    
    profiler.disable()
    
    # Print top 15 functions by cumulative time
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats('cumtime').print_stats(25)
    
    print("\n[Profile] Top 25 Bottlenecks (by cumulative time):")
    print(stream.getvalue())
    
    return profiler, result

if __name__ == "__main__":
    profile_stochastic_engine()
