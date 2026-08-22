# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

nikkake-trade is a Japanese stock ("日本株") signal-scanning and paper-trading dashboard. Scheduled jobs scan a watchlist of tickers (managed by `common/watchlist.py`: Supabase `watchlist` table → `data/watchlist.json` → hardcoded default, with `tier: core/rotation` per ticker), score them with a quant/sentiment engine, record "AI推奨シグナル" (AI-recommended entries) as paper trades, track their price performance over time, and notify LINE/Discord. A FastAPI server exposes the same data as a live dashboard and lets the user manually add/remove AI signals, watchlist tickers (`/api/watchlist`), and real (actually-purchased) portfolio positions. `common/market_data.py` wraps the J-Quants API V2 (JPX official; `JQUANTS_API_KEY`, x-api-key header, 12-week-delayed Free plan, auto-retries 429s) for universe/factor/backtest data — current-day prices still come from yfinance. `common/factor_engine.py` cross-sectionally scores the whole TSE Prime universe (momentum 12-1, 3-month return, ROE, PBR, 20-day volatility) using ~25 J-Quants API calls per run (fetches full-universe snapshots at specific trading-day offsets rather than per-ticker history, then only pulls fundamentals for the momentum-shortlisted candidates). `modules/post_analysis/universe_rotator.py` runs this weekly (`.github/workflows/universe_rotator.yml`, Sunday) to propose IN/OUT changes to the watchlist's `rotation` tier only (`core` tier is untouched); it's currently a notify-only dry run (`apply=False`) pending walk-forward validation — flip to `apply=True` once backtested.

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

**Supabase is the single source of truth**, read/written through `common/database.py` (REST client via `supabase-py`, not raw Postgres). `SUPABASE_URL`/`SUPABASE_KEY` are set on Render and, as GitHub Actions secrets, on the `daily_scanner`/`prediction`/`weekly_performance` workflows (the ones that call `record_signal`/`update_signal_performance`; `intraday_alert` doesn't persist anything so it has no DB creds). `common/performance_tracker.py` falls back to local JSON files in `data/` (`signal_history.json`, `real_portfolio.json`) only if `SUPABASE_URL` is unset or a DB call throws — that path exists for local dev without Supabase credentials, not as a parallel production store. `data/cache.json` (via `common/cache_manager.py`) is a separate, always-file-based TTL cache for expensive lookups (macro data, EDINET filings, etc.) — this one is never DB-backed.

**`dashboard.html` and `index.html` are generated output, not hand-edited source.** `generate_html_dashboard()` in `common/performance_tracker.py` renders both files identically (one Python f-string dashboard template with the current history/portfolio JSON embedded inline as `serverHistory`/`serverPortfolio` JS constants). It's called after every mutation (add/delete signal or portfolio item, `/api/refresh`, scanner runs) and also on server startup. If you need to change the dashboard UI, edit the template inside `generate_html_dashboard()`, not the HTML files directly — direct edits get overwritten on the next run.

**Signal lifecycle:** `record_signal()` appends an `OPEN` entry to history; `update_signal_performance()` (run on server startup, on every `/` page load via background task, and by the scanners) refetches current prices for all open signals via yfinance, updates `current_price`/`max_price`/`min_price`/`return_pct`/`pnl_yen`, and flips status to `WIN`/`LOSS` when target/stop-loss is crossed. Results feed both the dashboard and `generate_weekly_report()`.

**Scoring pipeline** (`modules/post_analysis/quant_analyzer.py` → `evaluate_quant_factors()`): combines technicals from `common/quant_math.py` (ATR, TTM squeeze, residual momentum, OBV), macro regime from `common/global_macro.py` (SOX/USDJPY/VIX/US10Y, cached 1h), EDINET large-shareholding/buyback disclosures (`modules/post_analysis/edinet_scraper.py`, cached 24h), and social sentiment scraped from Yahoo!リアルタイム検索 (`modules/post_analysis/advanced_scraper.py`). `modules/post_analysis/pro_analyzer.py` has a separate, older 100-point scorer — check which one a given caller actually uses before assuming they're interchangeable. Dividend yield and yutai (shareholder perk) info come from a separate call, `get_stock_financial_perks()` in `advanced_scraper.py` (not part of the score); both scanners merge it into the signal's `details` dict as `配当利回り`/`株主優待` right before `record_signal()`, and `generate_html_dashboard()`'s `formatMetricsHTML()` JS renders those two keys (plus PER/PBR/EPS/ATR/Theme) into the AI signal table's "指標" column.

**Notifications** go through `common/notifier.py`, which sends to LINE (Messaging API push, needs `LINE_CHANNEL_ACCESS_TOKEN` + `LINE_USER_ID`) and/or Discord webhook (`DISCORD_WEBHOOK_URL`). These are read from GitHub Actions secrets in CI and from the environment (`.env`, gitignored) locally.

**Deployment:** Render.com, configured by `render.yaml` to build `Dockerfile` (Python 3.10-slim, runs `uvicorn server:app`). `data/` is a mounted volume in `docker-compose.yml` for local persistence; in production, Supabase is the durable store.

**Automation cadence (`.github/workflows/`, all JST-scheduled, cron times are UTC):**
- `intraday_alert.yml` — every 5 min, 09:00–16:00 JST weekdays
- `prediction.yml` — 08:00 JST daily
- `daily_scanner.yml` — 15:30 JST daily
- `weekly_performance.yml` — Saturday 10:00 JST, sends the win-rate report. It used to also commit `data/signal_history.json`/`dashboard.html` straight back to `main`; that step was removed once Supabase became the source of truth, so `main` no longer moves on its own.
