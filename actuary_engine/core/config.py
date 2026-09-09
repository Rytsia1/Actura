from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # Application
    ENVIRONMENT: str = Field(default="development")
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Actura Engine"
    
    # Server
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    
    # Backend Dependencies
    MORTALITY_TABLE_PATH: str = Field(default="soa_ilt.csv")
    DATABASE_URL: str = Field(default="sqlite:///./actura.db")
    
    # Stochastic Defaults
    DEFAULT_NUM_PATHS: int = Field(default=10000)
    DEFAULT_RANDOM_SEED: int = Field(default=42)
    VASICEK_KAPPA: float = Field(default=0.15)
    VASICEK_THETA: float = Field(default=0.05)
    VASICEK_SIGMA: float = Field(default=0.02)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )

settings = Settings()
