# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

nikkake-trade is a Japanese stock ("日本株") signal-scanning and paper-trading dashboard. Scheduled jobs scan a fixed watchlist of tickers, score them with a quant/sentiment engine, record "AI推奨シグナル" (AI-recommended entries) as paper trades, track their price performance over time, and notify LINE/Discord. A FastAPI server exposes the same data as a live dashboard and lets the user manually add/remove AI signals and real (actually-purchased) portfolio positions.

See [README.md](README.md) for the full spec: scoring formula breakdown, per-workflow cron schedule and thresholds, API endpoints, and env vars. This file only covers what you need to work in the code.

## Commands

Local dev server (also runnable via Docker: `docker-compose up`):
```bash
pip install -r requirements.txt
python server.py          # http://localhost:8000, auto-reloads
```

Run one of the scheduled jobs manually (each is also its own GitHub Actions workflow):
```bash
python modules/post_analysis/daily_scanner.py       # end-of-day scan, records new signals
python modules/real_time/intraday_alert.py           # intraday volume-spike alert
python modules/prediction/trend_predictor.py         # morning trend prediction
python modules/post_analysis/weekly_report_runner.py # weekly win-rate report + LINE push
```

Standalone backtest (not wired into the scanner):
```bash
python modules/post_analysis/backtester.py TICKER --hold-days 5 --vol-multiplier 3.0
```

There is no test suite, linter, or build step configured in this repo.

## Architecture

**Data flow:** scheduled scripts (`modules/*`) fetch prices via `yfinance`, score candidates, then call into `common/performance_tracker.py` to persist a signal and regenerate the dashboard. The FastAPI app (`server.py`) is a thin CRUD layer over the same `performance_tracker` functions, so the scanners and the web UI never diverge.

**Storage has two backends, chosen automatically by `common/performance_tracker.py` at import time** based on whether `SUPABASE_URL` is set:
- If set: reads/writes go through `common/database.py` (Supabase REST client, `supabase-py`, not raw Postgres — no DB password needed).
- If not set: falls back to local JSON files in `data/` (`signal_history.json`, `real_portfolio.json`).
- Every DB read/write is wrapped in try/except that falls back to the JSON path on error — so DB and file logic must be kept behaviorally equivalent when changed.
- `data/cache.json` (via `common/cache_manager.py`) is a separate, always-file-based TTL cache for expensive lookups (macro data, EDINET filings, etc.) — this one is never DB-backed.

**`dashboard.html` and `index.html` are generated output, not hand-edited source.** `generate_html_dashboard()` in `common/performance_tracker.py` renders both files identically (one Python f-string dashboard template with the current history/portfolio JSON embedded inline as `serverHistory`/`serverPortfolio` JS constants). It's called after every mutation (add/delete signal or portfolio item, `/api/refresh`, scanner runs) and also on server startup. If you need to change the dashboard UI, edit the template inside `generate_html_dashboard()`, not the HTML files directly — direct edits get overwritten on the next run.

**Signal lifecycle:** `record_signal()` appends an `OPEN` entry to history; `update_signal_performance()` (run on server startup, on every `/` page load via background task, and by the scanners) refetches current prices for all open signals via yfinance, updates `current_price`/`max_price`/`min_price`/`return_pct`/`pnl_yen`, and flips status to `WIN`/`LOSS` when target/stop-loss is crossed. Results feed both the dashboard and `generate_weekly_report()`.

**Scoring pipeline** (`modules/post_analysis/quant_analyzer.py` → `evaluate_quant_factors()`): combines technicals from `common/quant_math.py` (ATR, TTM squeeze, residual momentum, OBV), macro regime from `common/global_macro.py` (SOX/USDJPY/VIX/US10Y, cached 1h), EDINET large-shareholding/buyback disclosures (`modules/post_analysis/edinet_scraper.py`, cached 24h), and social sentiment scraped from Yahoo!リアルタイム検索 (`modules/post_analysis/advanced_scraper.py`). `modules/post_analysis/pro_analyzer.py` has a separate, older 100-point scorer — check which one a given caller actually uses before assuming they're interchangeable.

**Notifications** go through `common/notifier.py`, which sends to LINE (Messaging API push, needs `LINE_CHANNEL_ACCESS_TOKEN` + `LINE_USER_ID`) and/or Discord webhook (`DISCORD_WEBHOOK_URL`). These are read from GitHub Actions secrets in CI and from the environment (`.env`, gitignored) locally.

**Deployment:** Render.com, configured by `render.yaml` to build `Dockerfile` (Python 3.10-slim, runs `uvicorn server:app`). `data/` is a mounted volume in `docker-compose.yml` for local persistence; in production, Supabase is the durable store.

**Automation cadence (`.github/workflows/`, all JST-scheduled, cron times are UTC):**
- `intraday_alert.yml` — every 5 min, 09:00–16:00 JST weekdays
- `prediction.yml` — 08:00 JST daily
- `daily_scanner.yml` — 15:30 JST daily
- `weekly_performance.yml` — Saturday 10:00 JST; this one also commits `data/signal_history.json` and `dashboard.html` straight back to `main` with `[skip ci]` — expect the remote branch to move out from under local clones on Saturdays.
