from dataclasses import dataclass

@dataclass(frozen=True)
class SiteConfig:
    # OLD direct local default kept for reference:
    # analytics_base_url: str = "http://127.0.0.1:8001"
    analytics_base_url: str = "http://localhost:9080/analytics"
    out_dir: str = "ui/dist"
    templates_dir: str = "ui/templates"
    static_dir: str = "ui/static"

    min_week: int = 0
    max_week: int = 18
