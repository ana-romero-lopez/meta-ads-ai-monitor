# 📊 Meta Ads AI Monitor

Automated performance monitoring tool for Meta Ads campaigns. Fetches daily metrics via the Meta Marketing API, calculates 7-day performance deltas, runs an AI-powered differential diagnosis per campaign, and delivers a formatted HTML report by email every morning at 6am — no manual checking required.

---

## The problem

Managing multiple Meta Ads campaigns means checking CPL, CTR, CPM and frequency manually every day. By the time you spot a drop in performance or a frequency spike, budget has already been wasted. And even when you catch the numbers, translating them into a clear action requires context, pattern recognition and time — every single day.

A human-in-the-loop daily check doesn't scale.

## The solution

A Python script that runs automatically at 6am and does the full analysis for you:

1. Pulls metrics for all campaigns in the ad account via Meta Marketing API
2. Compares last 7 days vs the previous 7-day period (delta analysis)
3. Flags campaigns that exceed alert thresholds (CTR drop, CPL rise, CPM rise, frequency)
4. Runs an **AI-powered differential diagnosis** per active campaign via Claude API — identifying the root cause (creative fatigue, audience exhaustion, budget restriction, learning phase) and generating a specific, actionable recommendation
5. Sends a daily HTML email report with colour-coded deltas, alerts and AI insights

## Output example

![Meta Ads AI Monitor — email preview](email-preview.png)

The daily email includes a full campaign metrics table (spend, impressions, reach, frequency, CTR, CPC, CPM) followed by an AI differential diagnosis per active campaign. Example diagnosis:

```
🚨 Campaign B [ACTIVE]
   Diagnosis: Creative fatigue (Confidence: HIGH)
   · CTR dropped -20.3% week-over-week while CPM fell only -11.9% — audience is
     seeing the ads at similar cost but engaging significantly less
   · Frequency 1.70 with declining CTR, consistent with creative wear-out
   → URGENT: Launch 2–3 new creative variants immediately. Keep current best-
     performing creative at 30% weight as control.
   🚫 Do not: increase budget to compensate — more spend on a fatigued creative
     will inflate CPL further without fixing the root cause.
```

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
- **Claude API (Anthropic)** — AI differential diagnosis per campaign
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
ANTHROPIC_API_KEY=your_anthropic_api_key
EMAIL_SENDER=your_gmail@gmail.com
EMAIL_PASSWORD=your_gmail_app_password
EMAIL_RECIPIENT=report@yourdomain.com
```

> **Meta access token:** generate a long-lived token via Meta Business Suite → System Users, with `ads_read` permission.
> **Anthropic API key:** get one at console.anthropic.com.
> **Gmail app password:** create one at myaccount.google.com → Security → App Passwords (requires 2FA enabled).

### 4. Run

```bash
python meta_ads_monitor.py
```

### 5. Automate

Schedule a daily run with cron:

```bash
# Run every day at 6:00 AM
0 6 * * * /usr/bin/python3 /path/to/meta_ads_monitor.py
```

Or use a cloud function (AWS Lambda, Google Cloud Run) for fully serverless execution.

---

## Roadmap

- [ ] Google Sheets integration — append daily metrics to a running log
- [ ] Slack / Telegram alert channel
- [ ] Anomaly detection using rolling averages instead of fixed thresholds
- [ ] Multi-account support

---

## Context

Built to solve a real operational problem at [Otomatico](https://otomatico.com), where managing multiple B2B lead generation campaigns required a reliable daily performance signal — with enough diagnostic depth to act on it immediately, without depending on third-party reporting tools.

---

*Ana Romero · [Portfolio](https://ana-romero-lopez.github.io) · [LinkedIn](https://linkedin.com/in/ana-romero-lopez)*
