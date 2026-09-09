class BlueprintValidationError(Exception):
    """Raised when a blueprint violates graph integrity rules (cycles, disconnected nodes, missing config)."""
    pass

class BlueprintExecutionError(Exception):
    """Raised when a blueprint node fails during execution."""
    pass
