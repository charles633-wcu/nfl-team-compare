# Elo Artifact Schema (`elo/elo_2024.json`)

This project computes NFL Elo ratings (with margin-of-victory scaling) as an **offline batch job** and writes the results to a single JSON artifact:

- **Artifact path:** `elo/elo_2024.json`
- **Produced by:** `analytics-api/compute_elo.py`
- **Served by:** `analytics-api/analytics_api.py`

The analytics API is a read-only view over this artifact.

---

## Top-level shape

```json
{
  "season": 2024,
  "baseline": 1500,
  "k_factor": 25,
  "weeks": 18,
  "elo": { "...": "..." },
  "teams": { "...": "..." }
}
