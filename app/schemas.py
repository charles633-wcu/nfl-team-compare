from pydantic import BaseModel


class Team(BaseModel):
    id: int
    name: str
    abbreviation: str | None = None
    logo: str | None = None


class TeamCompareStats(BaseModel):
    team: Team
    wins: int | None = None
    losses: int | None = None
    ties: int | None = None
    points_for: float | None = None
    points_against: float | None = None
