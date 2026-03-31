"""
Meta Ads AI Monitor
-------------------
Fetches campaign metrics from the Meta Marketing API, calculates 7-day
performance deltas, triggers threshold-based alerts, and sends a daily
HTML report by email.

Required environment variables (copy .env.example → .env and fill in):
    META_ACCESS_TOKEN   – long-lived Meta user / system-user access token
    META_AD_ACCOUNT_ID  – ad account id, e.g. act_123456789
    EMAIL_SENDER        – Gmail address used to send the report
    EMAIL_PASSWORD      – Gmail App Password (not your account password)
    EMAIL_RECIPIENT     – address that receives the daily report
"""

import os
import smtplib
import json
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

ACCESS_TOKEN   = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT_ID  = os.getenv("META_AD_ACCOUNT_ID")   # e.g. act_123456789
EMAIL_SENDER   = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT")

API_VERSION = "v19.0"
BASE_URL    = f"https://graph.facebook.com/{API_VERSION}"

# Alert thresholds – tweak to match your account benchmarks
THRESHOLDS = {
    "ctr_drop_pct":       20,   # alert if CTR falls >20% vs previous 7 days
    "cpl_increase_pct":   25,   # alert if CPL rises  >25%
    "cpm_increase_pct":   30,   # alert if CPM rises  >30%
    "frequency_max":       3.0, # alert if frequency exceeds this value
}

# ── API helpers ───────────────────────────────────────────────────────────────

def get_campaigns() -> list[dict]:
    """Return all campaigns in the ad account."""
    url    = f"{BASE_URL}/{AD_ACCOUNT_ID}/campaigns"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "id,name,status",
        "limit": 100,
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json().get("data", [])


def get_insights(campaign_id: str, date_from: date, date_to: date) -> dict | None:
    """Return aggregated insights for one campaign over a date range."""
    url    = f"{BASE_URL}/{campaign_id}/insights"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "impressions,reach,clicks,spend,ctr,cpm,frequency,actions",
        "time_range": json.dumps({
            "since": str(date_from),
            "until": str(date_to),
        }),
        "level": "campaign",
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    return data[0] if data else None


def extract_conversions(insights: dict) -> float:
    """Pull lead / purchase conversions from the actions array."""
    if not insights:
        return 0.0
    for action in insights.get("actions", []):
        if action.get("action_type") in ("lead", "offsite_conversion.fb_pixel_purchase"):
            return float(action.get("value", 0))
    return 0.0


def safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calc_delta(current: float, previous: float) -> float | None:
    """Percentage change from previous to current. None if no previous data."""
    if previous == 0:
        return None
    return ((current - previous) / previous) * 100


def cpl(spend: float, conversions: float) -> float:
    return spend / conversions if conversions > 0 else 0.0

# ── Core logic ────────────────────────────────────────────────────────────────

def build_report() -> list[dict]:
    """
    For each active campaign, fetch metrics for:
      - current  period: last 7 days
      - previous period: 7 days before that
    Then compute deltas and flag alerts.
    """
    today    = date.today()
    cur_end  = today - timedelta(days=1)
    cur_start = cur_end - timedelta(days=6)
    prev_end  = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)

    campaigns = get_campaigns()
    results   = []

    for camp in campaigns:
        cid    = camp["id"]
        name   = camp["name"]
        status = camp["status"]

        cur  = get_insights(cid, cur_start, cur_end)
        prev = get_insights(cid, prev_start, prev_end)

        if not cur:
            results.append({"name": name, "status": status, "no_data": True})
            continue

        spend_cur  = safe_float(cur.get("spend"))
        conv_cur   = extract_conversions(cur)
        ctr_cur    = safe_float(cur.get("ctr"))
        cpm_cur    = safe_float(cur.get("cpm"))
        freq_cur   = safe_float(cur.get("frequency"))
        cpl_cur    = cpl(spend_cur, conv_cur)

        if prev:
            spend_prev = safe_float(prev.get("spend"))
            conv_prev  = extract_conversions(prev)
            ctr_prev   = safe_float(prev.get("ctr"))
            cpm_prev   = safe_float(prev.get("cpm"))
            cpl_prev   = cpl(spend_prev, conv_prev)
        else:
            ctr_prev = cpm_prev = cpl_prev = 0.0

        delta_ctr = calc_delta(ctr_cur, ctr_prev)
        delta_cpm = calc_delta(cpm_cur, cpm_prev)
        delta_cpl = calc_delta(cpl_cur, cpl_prev)

        alerts = []
        if delta_ctr is not None and delta_ctr < -THRESHOLDS["ctr_drop_pct"]:
            alerts.append(f"⚠️ CTR dropped {delta_ctr:.1f}% vs last week")
        if delta_cpl is not None and delta_cpl > THRESHOLDS["cpl_increase_pct"]:
            alerts.append(f"⚠️ CPL increased {delta_cpl:.1f}% vs last week")
        if delta_cpm is not None and delta_cpm > THRESHOLDS["cpm_increase_pct"]:
            alerts.append(f"⚠️ CPM increased {delta_cpm:.1f}% vs last week")
        if freq_cur > THRESHOLDS["frequency_max"]:
            alerts.append(f"⚠️ Frequency {freq_cur:.2f} exceeds threshold ({THRESHOLDS['frequency_max']})")

        results.append({
            "name":      name,
            "status":    status,
            "no_data":   False,
            "spend":     spend_cur,
            "ctr":       ctr_cur,
            "cpm":       cpm_cur,
            "cpl":       cpl_cur,
            "frequency": freq_cur,
            "conversions": conv_cur,
            "delta_ctr": delta_ctr,
            "delta_cpm": delta_cpm,
            "delta_cpl": delta_cpl,
            "alerts":    alerts,
        })

    return results

# ── Email report ──────────────────────────────────────────────────────────────

def delta_html(value: float | None, invert: bool = False) -> str:
    """Format a delta value as a coloured HTML span."""
    if value is None:
        return "<span style='color:#888'>—</span>"
    positive_is_good = not invert
    good  = value > 0 if positive_is_good else value < 0
    color = "#22c55e" if good else "#ef4444"
    arrow = "▲" if value > 0 else "▼"
    return f"<span style='color:{color}'>{arrow} {abs(value):.1f}%</span>"


def build_html(report: list[dict], report_date: date) -> str:
    today_str = report_date.strftime("%d %b %Y")
    total_alerts = sum(len(r.get("alerts", [])) for r in report if not r.get("no_data"))

    rows = ""
    for r in report:
        if r.get("no_data"):
            rows += f"""
            <tr>
              <td>{r['name']}</td>
              <td><span style='color:#6b7280'>{r['status']}</span></td>
              <td colspan='7' style='color:#9ca3af;font-style:italic'>No data for this period</td>
            </tr>"""
            continue

        alert_html = ""
        if r["alerts"]:
            alert_html = "<br>" + "<br>".join(
                f"<span style='color:#ef4444;font-size:12px'>{a}</span>" for a in r["alerts"]
            )

        status_color = "#22c55e" if r["status"] == "ACTIVE" else "#6b7280"

        rows += f"""
        <tr>
          <td style='font-weight:500'>{r['name']}{alert_html}</td>
          <td><span style='color:{status_color}'>{r['status']}</span></td>
          <td>€{r['spend']:.2f}</td>
          <td>{r['ctr']:.2f}% {delta_html(r['delta_ctr'])}</td>
          <td>€{r['cpm']:.2f} {delta_html(r['delta_cpm'], invert=True)}</td>
          <td>€{r['cpl']:.2f} {delta_html(r['delta_cpl'], invert=True)}</td>
          <td>{r['frequency']:.2f}</td>
          <td>{int(r['conversions'])}</td>
        </tr>"""

    alert_banner = ""
    if total_alerts:
        alert_banner = f"""
        <div style='background:#fef2f2;border-left:4px solid #ef4444;padding:12px 16px;
                    margin-bottom:24px;border-radius:4px;color:#991b1b'>
          🚨 <strong>{total_alerts} alert{"s" if total_alerts > 1 else ""} require attention</strong>
          — review flagged campaigns below.
        </div>"""

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body   {{ font-family: Arial, sans-serif; font-size: 14px; color: #111827; background: #f9fafb; margin:0; padding:0; }}
        .wrap  {{ max-width: 900px; margin: 32px auto; background: #fff; border-radius: 8px;
                  padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
        h1     {{ font-size: 20px; margin: 0 0 4px; }}
        .sub   {{ color: #6b7280; font-size: 13px; margin-bottom: 24px; }}
        table  {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th     {{ background: #1e3a5f; color: #fff; padding: 10px 12px; text-align: left; }}
        td     {{ padding: 10px 12px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }}
        tr:hover td {{ background: #f3f4f6; }}
        .foot  {{ color: #9ca3af; font-size: 12px; margin-top: 24px; }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <h1>📊 Meta Ads Daily Report</h1>
        <p class="sub">Performance snapshot · {today_str} · Last 7 days vs previous 7 days</p>
        {alert_banner}
        <table>
          <thead>
            <tr>
              <th>Campaign</th><th>Status</th><th>Spend</th>
              <th>CTR</th><th>CPM</th><th>CPL</th>
              <th>Frequency</th><th>Conversions</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        <p class="foot">
          Generated automatically by <strong>Meta Ads AI Monitor</strong> ·
          Thresholds: CTR drop &gt;{THRESHOLDS['ctr_drop_pct']}% |
          CPL rise &gt;{THRESHOLDS['cpl_increase_pct']}% |
          CPM rise &gt;{THRESHOLDS['cpm_increase_pct']}% |
          Frequency &gt;{THRESHOLDS['frequency_max']}
        </p>
      </div>
    </body>
    </html>"""


def send_email(html: str, report_date: date) -> None:
    subject = f"📊 Meta Ads Report — {report_date.strftime('%d %b %Y')}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECIPIENT
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())

    print(f"✉️  Email sent to {EMAIL_RECIPIENT}")

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Fetching campaigns...")
    report = build_report()

    total   = len(report)
    alerts  = sum(len(r.get("alerts", [])) for r in report if not r.get("no_data"))
    print(f"Processed {total} campaigns — {alerts} alert(s) triggered")

    today = date.today()
    html  = build_html(report, today)
    send_email(html, today)
