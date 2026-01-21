from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    apisports_key: str = Field(..., alias="APISPORTS_KEY")
    apisports_base_url: str = Field(
        "https://v1.american-football.api-sports.io",
        alias="APISPORTS_BASE_URL",
    )
    nfl_league_id: int = Field(1, alias="NFL_LEAGUE_ID")
    season: int = Field(2025, alias="SEASON")

settings = Settings()
