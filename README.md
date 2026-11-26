# Macro Terminal

A personal markets dashboard (rates, FX, equities, commodities, economic data and headlines) that refreshes itself.

## How it works

1. Every 30 minutes, GitHub runs `scripts/refresh.py` for free (the schedule is in `.github/workflows/refresh.yml`).
2. The script downloads fresh numbers and saves them in `docs/data/`.
3. GitHub publishes the `docs/` folder as a website, so the dashboard shows the latest data. The page also re-reads the data every 5 minutes while it's open.

| Data | Source | How often |
|---|---|---|
| Stock ETFs, currencies, gold, silver, oil, bitcoin | Twelve Data | every 30 min, weekdays 06:00–22:00 UTC |
| 1-year daily price history (for charts) | Twelve Data | once a day |
| Treasury yields, Fed funds, credit spreads, VIX, dollar, CPI, jobs, GDP | FRED | every 30 min (FRED itself updates daily or monthly) |
| Headlines | Fed, ECB, MarketWatch, CNBC, BBC RSS feeds | every 30 min |

## The API keys

The keys are stored as **repository secrets** (Settings → Secrets and variables → Actions):

- `TWELVEDATA_API_KEY`
- `FRED_API_KEY`

They are never written into the code, the data files or the website. To change a key, open the secret and click **Update**.

## Free-plan limits

Twelve Data's free plan allows 800 calls a day and 8 a minute; each symbol is one call. The schedule uses about 530 a day. If you add symbols in `TD_SYMBOLS` (top of `scripts/refresh.py`), keep 32 × (number of symbols) + (number of symbols) under 800.

## Refresh by hand

Actions tab → **Refresh market data** → **Run workflow**. A manual run (or a code change) fetches everything immediately.

## Good to know

- GitHub can start scheduled runs a few minutes late, and pauses schedules in a repository with no activity for 60 days. The data commits count as activity, so this shouldn't happen while it's working.
- If a source fails, the page shows a yellow note at the top and keeps the last good numbers.
