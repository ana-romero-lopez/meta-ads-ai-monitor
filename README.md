# 📊 Meta Ads AI Monitor

Automated performance monitoring tool for Meta Ads campaigns. Fetches daily metrics via the Meta Marketing API, calculates 7-day performance deltas, triggers threshold-based alerts, and delivers a formatted HTML report by email — no manual checking required.

---

## The problem

Managing multiple Meta Ads campaigns means checking CPL, CTR, CPM and frequency manually every day. By the time you spot a drop in performance or a frequency spike, budget has already been wasted. A human-in-the-loop daily check doesn't scale.

## The solution

A Python script that runs automatically each morning and does the work for you:

1. Pulls metrics for all campaigns in the ad account via Meta Marketing API
2. Compares last 7 days vs the previous 7-day period (delta analysis)
3. Flags campaigns that exceed alert thresholds
4. Sends a daily HTML email report with colour-coded deltas and alerts

## Output example

The daily email includes a campaign table with:

| Campaign | Status | Spend | CTR | CPM | CPL | Frequency | Conversions |
|---|---|---|---|---|---|---|---|
| Campaign A | ACTIVE | €105.00 | 1.78% ▲ 12% | €4.84 | €0.27 | 1.55 | 389 |
| Campaign B | ACTIVE | €444.94 | 1.32% ▼ 20% ⚠️ | €25.05 ▲ 30% ⚠️ | €1.90 | 1.70 | 234 |

Alerts are highlighted in red and surfaced at the top of the email so you can act immediately.

## Alert thresholds

Configurable in the script. Defaults:

| Metric | Threshold |
|---|---|
| CTR drop | > 20% vs previous 7 days |
| CPL increase | > 25% vs previous 7 days |
| CPM increase | > 30% vs previous 7 days |
| Frequency | > 3.0 |

## Tech stack

- **Python 3.11+**
- **Meta Marketing API v19** — campaign insights endpoint
- **smtplib** — HTML email delivery via Gmail SMTP
- **python-dotenv** — environment variable management

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/ana-romero-lopez/meta-ads-ai-monitor.git
cd meta-ads-ai-monitor
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```
META_ACCESS_TOKEN=your_long_lived_access_token
META_AD_ACCOUNT_ID=act_your_account_id
EMAIL_SENDER=your_gmail@gmail.com
EMAIL_PASSWORD=your_gmail_app_password
EMAIL_RECIPIENT=report@yourdomain.com
```

> **Meta access token:** generate a long-lived token via Meta Business Suite → System Users, with `ads_read` permission.
> **Gmail app password:** create one at myaccount.google.com → Security → App Passwords (requires 2FA enabled).

### 4. Run

```bash
python meta_ads_monitor.py
```

### 5. Automate (optional)

Schedule a daily run with cron:

```bash
# Run every day at 8:00 AM
0 8 * * * /usr/bin/python3 /path/to/meta_ads_monitor.py
```

Or use a task scheduler on Windows, or a cloud function (AWS Lambda, Google Cloud Run) for fully serverless execution.

---

## Roadmap

- [ ] Google Sheets integration — append daily metrics to a running log
- [ ] Slack / Telegram alert channel
- [ ] Anomaly detection using rolling averages instead of fixed thresholds
- [ ] Multi-account support

---

## Context

Built to solve a real operational problem at [Otomatico](https://otomatico.com), where managing multiple B2B lead generation campaigns required a reliable daily performance signal without depending on third-party reporting tools.

---

*Ana Romero · [Portfolio](https://ana-romero-lopez.github.io) · [LinkedIn](https://linkedin.com/in/ana-romero-lopez)*
