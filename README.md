# NFL Team Comparison Web App

This project is a deployed full-stack web application that allows users to compare two NFL teams from a selected season using real game data. The application aggregates official game results and standings data from a third-party sports API and presents computed season statistics through a clean, server-rendered interface.

The project was built to demonstrate backend API integration, data validation, and server-side rendering in a production-style environment.

---

## Overview

Users can select two NFL teams and view a side-by-side comparison that includes:

- Wins, losses, and ties
- Points For (PF)
- Points Against (PA)

Season totals are computed dynamically from completed regular-season games rather than relying solely on precomputed summary fields.

---

## Data Handling and Logic

### Team Data
- Team metadata is retrieved from the external API and filtered to exclude non-franchise placeholders (e.g., conference entries).
- Team identifiers are used consistently across endpoints to ensure data integrity.

### Record (Wins / Losses / Ties)
- Team records are sourced from the standings endpoint for the selected season.
- The standings data is cached in memory to minimize repeated API calls.

### Points For / Points Against
- PF and PA are computed by aggregating scores from individual games.
- Only regular-season games are included.
- Preseason and postseason games are explicitly excluded.
- Game totals are derived from final score fields provided by the API.
- This approach ensures transparency and avoids reliance on potentially incomplete summary statistics.

---

## Architecture

### Backend
- Built with FastAPI using asynchronous request handling.
- External API access is encapsulated in a dedicated client module.
- Data models are defined using Pydantic for validation and clarity.
- In-memory caching is used to reduce redundant API calls and improve responsiveness.

### Frontend
- Server-rendered HTML using Jinja2 templates.
- Static assets (CSS) are served directly by the application.
- The UI is intentionally minimal to emphasize data correctness and clarity.

---

## Design Considerations

- The application prioritizes correctness and explainability of data over visual complexity.
- API response structures are validated directly against observed JSON payloads.
- Logic is defensive against missing or inconsistent external data.
- Configuration and secrets are managed via environment variables and are not embedded in source code.

---

## Purpose

This project was created as a portfolio application to demonstrate:

- Integration with real-world third-party APIs
- Debugging and adapting to undocumented or inconsistent external data
- Clean separation of concerns in a small full-stack system
- Practical use of FastAPI and server-side rendering for data-driven applications

