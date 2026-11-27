# Macro Terminal

A personal markets dashboard (rates, FX, equities, commodities, economic data and headlines) that refreshes itself.

## How it works

1. Every 10 minutes, GitHub runs `scripts/refresh.py` for free (the schedule is in `.github/workflows/refresh.yml`).
2. Each data source has its own timer (`SCHEDULE` at the top of the script), so no service's limits are hit. The script saves the data in `docs/data/`, which is kept in GitHub's Actions cache between runs rather than in the repository history. The files committed in `docs/data/` are only a starting copy.
3. GitHub publishes the `docs/` folder as a website. Under every panel the page shows, in UK time, when that source was last checked and when it last had new data. The page re-reads the data every 2 minutes while it's open.

| Data | Source | How often |
|---|---|---|
| Currencies (7 dollar pairs plus USD/CNY; the page works out all 28 crosses between EUR, GBP, JPY, CHF, CAD, AUD, NZD and USD), gold, bitcoin | Twelve Data | every 20 min, weekdays 06:00–22:00 UTC |
| Stock, silver and oil ETFs | Twelve Data | every 20 min while US markets are open |
| 1-year daily price history (for charts) | Twelve Data | once a day |
| Treasury yields, Fed funds, credit spreads, VIX, dollar, CPI, jobs, GDP | FRED | every 30 min (FRED itself updates daily or monthly) |
| Futures positioning (COT): speculators' net long minus short, 21 markets, 10 years weekly | CFTC public reporting API (no key) | quick check every 10 min; new report each Friday |
| UK Bank Rate, SONIA, gilt yields, sterling | Bank of England database (no key) | every 30 min |
| This week's economic calendar (forecast, previous) | Forex Factory public feed (no key) | every 30 min |
| Fed meeting odds (cut / hold / hike) and expected rate path | Kalshi public market data (no key) + Fed target range from FRED | every 30 min |
| Bank of England expected Bank Rate path | Bank of England SONIA forward curve (no key) | every 30 min (published daily) |
| Big-company earnings dates | Finnhub (`FINNHUB_API_KEY` secret) | hourly |
| Later US release dates | FRED | hourly |
| Research | Public research feeds: ING Think, Nordea, WSJ, CaixaBank Research (daily markets report), Fed Beige Book (headlines, dates and the publishers' own feed summaries), plus a library of links to other banks' free research pages | hourly |
| Fundamentals: GDP, inflation, jobs, wages, retail sales, confidence surveys, trade, policy rates and 10-year yields for USD, EUR, GBP, JPY, CHF, CAD, AUD and NZD since 2000 | FRED, ONS (via DBnomics), ECB, Statistics Bureau of Japan (via DBnomics), SNB, Statistics Canada, RBA, OECD and BIS; only FRED needs a key (see `scripts/fundamentals.py`) | every 6 hours |
| Scanner tab: unusual moves vs normal volatility, 50/200-day average crosses, trend ranking (1w/1m/3m), stretched COT positioning, correlation map and broken relationships | worked out from the data above by `scripts/scanner.py` (no extra API calls) | every run |

## The API keys

The keys are stored as **repository secrets** (Settings → Secrets and variables → Actions):

- `TWELVEDATA_API_KEY`
- `FRED_API_KEY`
- `FINNHUB_API_KEY`

They are never written into the code, the data files or the website. To change a key, open the secret and click **Update**.

## Free-plan limits

Twelve Data's free plan allows 800 calls a day and 8 a minute; each symbol is one call. The schedule uses about 650 a day. If you add symbols in `TD_SYMBOLS` (top of `scripts/refresh.py`), slow their timer in `SCHEDULE` to stay under 800.

## Refresh by hand

Actions tab → **Refresh market data** → **Run workflow**. A manual run fetches everything immediately (about 32 Twelve Data calls).

## Good to know

- GitHub can start scheduled runs late or skip some when it's busy, and pauses schedules in a repository with no activity for 60 days. The data commits count as activity, so this shouldn't happen while it's working.
- If a source fails, the page shows a yellow note at the top and keeps the last good numbers.
- Central bank pricing uses each bank's published meeting dates, typed into `FOMC_DATES` and `MPC_DATES` in `scripts/refresh.py`. Add the next year's dates once the Fed and the Bank of England publish them (usually mid-year and September).
