#!/usr/bin/env python3
"""
Meta Marketing API - Campaign Report con Alertas
"""

import os
import json
import smtplib
import anthropic
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv(override=True)

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID")
GMAIL_FROM = os.getenv("GMAIL_FROM")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
GMAIL_TO = os.getenv("GMAIL_TO")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

SYSTEM_PROMPT = """
You are an expert Meta Ads strategist embedded in an automated reporting pipeline.
Your job is to perform differential diagnosis on campaign performance data — not to
label symptoms, but to identify root causes and recommend specific, prioritized actions.

You will receive a JSON object with the current metrics for one or more Meta campaigns.
For each campaign you must:

## 1. CROSS-VARIABLE DIAGNOSIS
Never trigger an alert based on a single metric in isolation. Always cross-reference:
- CTR + CPM + Frequency → to distinguish audience fatigue vs. market competition vs. creative failure
- Spend vs. Budget (daily usage %) + Impressions → to distinguish delivery restriction
  vs. learning phase vs. audience size problem
- CPL trend + CTR trend → to separate funnel problems (post-click) from ad relevance problems (pre-click)

## 2. DIAGNOSTIC CATEGORIES (use exactly these, do not invent others)
Assign one PRIMARY category per campaign:
- AUDIENCE_EXHAUSTION: High frequency (>2.5), CTR declining, CPM stable or rising
- CREATIVE_FATIGUE: Frequency moderate (1.5-2.5), CTR declining, CPM stable
- MARKET_COMPETITION: CPM rising, CTR stable or improving, frequency normal
- DELIVERY_RESTRICTION: Daily spend <30% of budget, impressions very low or zero, campaign ACTIVE
- LEARNING_PHASE: New campaign (<3 days or <50 events), low delivery, do not pathologize
- FUNNEL_INEFFICIENCY: CTR good, CPL rising — post-click problem
- HEALTHY_HIGH_COMPETITION: Good CTR, rising CPM and CPC — performing well, monitor only
- PAUSED_NO_DATA: Campaign PAUSED with no spend — skip deep analysis
- INSUFFICIENT_DATA: Active with zero impressions, no baseline — flag for manual review

## 3. OUTPUT FORMAT
Return ONLY a valid JSON array. No preamble, no text outside the JSON.
[
  {
    "campaign_name": "string",
    "status": "ACTIVE | PAUSED",
    "primary_diagnosis": "one of the categories above",
    "confidence": "HIGH | MEDIUM | LOW",
    "confidence_reason": "brief explanation if not HIGH, else empty string",
    "key_signals": ["signal combining 2+ metrics", "signal combining 2+ metrics"],
    "recommended_action": {
      "priority": "URGENT | MONITOR | NO_ACTION",
      "action": "specific action, not generic",
      "rationale": "why this action and not another"
    },
    "do_not_do": "one common wrong action and why it would be a mistake"
  }
]

## 4. STRICT RULES
- Never recommend pausing a campaign solely because CPL or CPC rises if CTR is strong
- Never diagnose AUDIENCE_EXHAUSTION if frequency is below 2.0
- Never treat 0% daily budget as automatically critical without checking eligibility first
- Never output generic advice without specifying exactly what to test and why
- Return ONLY the JSON array, nothing else
"""

if not ACCESS_TOKEN or not AD_ACCOUNT_ID:
    print("Error: faltan META_ACCESS_TOKEN o META_AD_ACCOUNT_ID en .env")
    exit(1)

import requests
from tabulate import tabulate

BASE_URL = "https://graph.facebook.com/v21.0"

# Ventanas de comparación
TODAY = date.today()
LAST_7D_UNTIL = TODAY - timedelta(days=1)
LAST_7D_SINCE = TODAY - timedelta(days=7)
PREV_7D_UNTIL = TODAY - timedelta(days=8)
PREV_7D_SINCE = TODAY - timedelta(days=14)


def get_campaigns():
    url = f"{BASE_URL}/{AD_ACCOUNT_ID}/campaigns"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "id,name,status,daily_budget,lifetime_budget,budget_remaining",
        "limit": 100,
    }
    campaigns = []
    while url:
        r = requests.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        campaigns.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = {}
    return campaigns


def get_insights(campaign_id, date_preset=None, since=None, until=None):
    """Obtiene insights para un periodo. Usa date_preset O since/until."""
    url = f"{BASE_URL}/{campaign_id}/insights"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "spend,impressions,reach,frequency,ctr,cpc,cpm,actions",
    }
    if date_preset:
        params["date_preset"] = date_preset
    else:
        params["time_range"] = json.dumps({
            "since": since.isoformat(),
            "until": until.isoformat(),
        })
    r = requests.get(url, params=params)
    if not r.ok:
        return {}
    data = r.json().get("data", [])
    return data[0] if data else {}


def calc_cpl(ins):
    """CPL = gasto / total acciones. None si no hay datos suficientes."""
    try:
        spend = float(ins.get("spend", 0))
        actions = ins.get("actions", [])
        total = sum(float(a["value"]) for a in actions)
        if total > 0:
            return spend / total
    except (TypeError, ValueError):
        pass
    return None


def fmt_budget(campaign):
    daily = campaign.get("daily_budget")
    lifetime = campaign.get("lifetime_budget")
    remaining = campaign.get("budget_remaining")
    if daily and int(daily) > 0:
        label = f"Daily: {int(daily)/100:.2f}€"
    elif lifetime and int(lifetime) > 0:
        label = f"Total: {int(lifetime)/100:.2f}€"
    else:
        label = "—"
    if remaining and int(remaining) > 0:
        label += f" (rem: {int(remaining)/100:.2f}€)"
    return label


def fmt_float(val, decimals=2, suffix=""):
    try:
        return f"{float(val):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def pct_change(new_val, old_val):
    """Variación relativa entre dos valores. None si no es calculable."""
    try:
        n, o = float(new_val), float(old_val)
        if o == 0:
            return None
        return (n - o) / o
    except (TypeError, ValueError):
        return None


def build_campaign_payload(campaign, ins_all, ins_7d, ins_prev7d):
    """Construye el dict de contexto que se enviará a Claude para diagnóstico."""
    daily_budget_raw = campaign.get("daily_budget")
    daily_budget = int(daily_budget_raw) / 100 if daily_budget_raw and int(daily_budget_raw) > 0 else None

    # Utilización diaria media (últimos 7 días)
    utilization = None
    if daily_budget:
        try:
            spend_7d = float(ins_7d.get("spend", 0))
            utilization = round((spend_7d / 7) / daily_budget * 100, 1)
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    # Variaciones 7d vs 7d anterior
    def delta_pct(key):
        d = pct_change(ins_7d.get(key), ins_prev7d.get(key))
        return round(d * 100, 1) if d is not None else None

    cpl_7d = calc_cpl(ins_7d)
    cpl_prev = calc_cpl(ins_prev7d)
    cpl_delta = pct_change(cpl_7d, cpl_prev)

    return {
        "campaign_name": campaign.get("name", "—"),
        "status": campaign.get("status", "—"),
        "spend_total": ins_all.get("spend"),
        "daily_budget_eur": daily_budget,
        "budget_remaining_eur": int(campaign.get("budget_remaining", 0)) / 100 if campaign.get("budget_remaining") else None,
        "avg_daily_spend_utilization_pct": utilization,
        "impressions": ins_all.get("impressions"),
        "reach": ins_all.get("reach"),
        "frequency": ins_all.get("frequency"),
        "ctr_total": ins_all.get("ctr"),
        "cpc_total": ins_all.get("cpc"),
        "cpm_total": ins_all.get("cpm"),
        "last_7d": {
            "spend": ins_7d.get("spend"),
            "impressions": ins_7d.get("impressions"),
            "ctr": ins_7d.get("ctr"),
            "cpc": ins_7d.get("cpc"),
            "cpm": ins_7d.get("cpm"),
            "cpl": round(cpl_7d, 2) if cpl_7d else None,
        },
        "vs_prev_7d": {
            "ctr_change_pct": delta_pct("ctr"),
            "cpc_change_pct": delta_pct("cpc"),
            "cpm_change_pct": delta_pct("cpm"),
            "cpl_change_pct": round(cpl_delta * 100, 1) if cpl_delta is not None else None,
        },
    }


def diagnose_campaigns(payloads):
    """Llama a Claude API con todos los payloads y devuelve lista de diagnósticos."""
    if not ANTHROPIC_API_KEY:
        print("⚠️  ANTHROPIC_API_KEY no configurada — usando diagnóstico básico de fallback.")
        return []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Diagnose these campaigns and return ONLY the JSON array:\n{json.dumps(payloads, ensure_ascii=False, indent=2)}"
                }
            ]
        )
        raw = response.content[0].text.strip()
        # Limpiar posibles backticks si el modelo los añade
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        # Intentar parsear; si falla por respuesta truncada, recuperar objetos completos
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Buscar el último objeto JSON completo dentro del array
            last_close = raw.rfind("}]")
            if last_close == -1:
                # Cerrar el array manualmente tras el último objeto completo
                last_obj_end = raw.rfind("},")
                if last_obj_end != -1:
                    raw = raw[:last_obj_end + 1] + "]"
                else:
                    last_obj_end = raw.rfind("}")
                    if last_obj_end != -1:
                        raw = raw[:last_obj_end + 1] + "]"
            else:
                raw = raw[:last_close + 2]
            return json.loads(raw)
    except Exception as e:
        print(f"⚠️  Error llamando a Claude API: {e}")
        return []


PRIORITY_EMOJI = {
    "URGENT": "🚨",
    "MONITOR": "⚠️",
    "NO_ACTION": "✅",
}

DIAGNOSIS_LABEL = {
    "AUDIENCE_EXHAUSTION":    "Saturación de audiencia",
    "CREATIVE_FATIGUE":       "Fatiga creativa",
    "MARKET_COMPETITION":     "Mercado competitivo",
    "DELIVERY_RESTRICTION":   "Restricción de distribución",
    "LEARNING_PHASE":         "Fase de aprendizaje",
    "FUNNEL_INEFFICIENCY":    "Ineficiencia de funnel (post-clic)",
    "HEALTHY_HIGH_COMPETITION": "Rendimiento saludable en subasta competitiva",
    "PAUSED_NO_DATA":         "Campaña pausada sin datos",
    "INSUFFICIENT_DATA":      "Datos insuficientes para diagnóstico",
}


def build_html_email(rows, headers, diagnoses, total):
    """Genera el cuerpo HTML del email con diagnósticos de Claude."""
    today_str = date.today().strftime("%d/%m/%Y")

    # Tabla de campañas
    thead = "".join(f"<th style='padding:6px 10px;background:#f0f0f0;border:1px solid #ccc;white-space:nowrap'>{h}</th>" for h in headers)
    tbody = ""
    for row in rows:
        cells = "".join(f"<td style='padding:5px 10px;border:1px solid #ddd;white-space:nowrap'>{cell}</td>" for cell in row)
        tbody += f"<tr>{cells}</tr>"

    table_html = f"""
    <table style='border-collapse:collapse;font-size:13px;font-family:monospace'>
      <thead><tr>{thead}</tr></thead>
      <tbody>{tbody}</tbody>
    </table>
    <p style='font-size:13px'><strong>Total campañas: {total}</strong></p>
    """

    # Sección de diagnósticos con razonamiento diferencial
    if diagnoses:
        diag_rows = ""
        for d in diagnoses:
            priority = d.get("recommended_action", {}).get("priority", "MONITOR")
            emoji = PRIORITY_EMOJI.get(priority, "⚠️")
            diag_label = DIAGNOSIS_LABEL.get(d.get("primary_diagnosis", ""), d.get("primary_diagnosis", "—"))
            confidence = d.get("confidence", "")
            confidence_note = f" <span style='color:#888;font-size:11px'>({d.get('confidence_reason', '')})</span>" if confidence == "LOW" and d.get("confidence_reason") else ""

            signals_html = "".join(
                f"<li style='margin:2px 0;color:#444;font-size:12px'>{s}</li>"
                for s in d.get("key_signals", [])
            )

            action = d.get("recommended_action", {})
            do_not = d.get("do_not_do", "")

            diag_rows += f"""
            <div style='margin-bottom:18px;padding:12px;border-left:4px solid {"#c0392b" if priority=="URGENT" else "#e67e22" if priority=="MONITOR" else "#27ae60"};background:#fafafa'>
              <p style='margin:0 0 4px 0'><strong>{emoji} {d.get("campaign_name","—")}</strong>
                &nbsp;<span style='font-size:12px;color:#555'>({d.get("status","—")})</span></p>
              <p style='margin:2px 0;font-size:13px'><strong>Diagnóstico:</strong> {diag_label}
                &nbsp;<span style='font-size:11px;color:#777'>Confianza: {confidence}</span>{confidence_note}</p>
              <ul style='margin:6px 0 6px 16px;padding:0'>{signals_html}</ul>
              <p style='margin:4px 0;font-size:13px'><strong>Acción recomendada ({priority}):</strong> {action.get("action","—")}</p>
              <p style='margin:2px 0;font-size:12px;color:#555'><em>Por qué:</em> {action.get("rationale","—")}</p>
              {f'<p style="margin:6px 0 0 0;font-size:12px;color:#c0392b"><strong>🚫 No hacer:</strong> {do_not}</p>' if do_not else ""}
            </div>
            """

        alerts_section = f"""
        <hr/>
        <h3 style='color:#c0392b'>🧠 DIAGNÓSTICO DIFERENCIAL — IA</h3>
        {diag_rows}
        """
    else:
        alerts_section = "<hr/><p>✅ Sin alertas activas o diagnóstico no disponible.</p>"

    return f"""
    <html><body style='font-family:Arial,sans-serif;font-size:14px;color:#222'>
      <h2>📊 Meta Ads Report — {today_str}</h2>
      {table_html}
      {alerts_section}
      <hr/>
      <p style='color:#888;font-size:12px'>Diagnóstico generado automáticamente por IA · Meta Ads Monitor</p>
    </body></html>
    """


def send_email(subject, html_body):
    """Envía el email via Gmail SMTP."""
    if not GMAIL_FROM or not GMAIL_APP_PASSWORD or not GMAIL_TO:
        print("⚠️  Credenciales de Gmail no configuradas en .env — email no enviado.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_FROM
    msg["To"] = GMAIL_TO
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_FROM, GMAIL_TO, msg.as_string())
        print(f"\n✉️  Email enviado a {GMAIL_TO}")
    except Exception as e:
        print(f"\n❌ Error enviando email: {e}")


def main():
    print("Obteniendo campañas...")
    campaigns = get_campaigns()
    if not campaigns:
        print("No se encontraron campañas.")
        return

    print(f"Encontradas {len(campaigns)} campañas. Obteniendo métricas...\n")

    rows = []
    payloads = []  # datos para Claude

    for c in campaigns:
        name = c.get("name", "—")
        ins_all = get_insights(c["id"], date_preset="maximum")
        ins_7d = get_insights(c["id"], since=LAST_7D_SINCE, until=LAST_7D_UNTIL)
        ins_prev = get_insights(c["id"], since=PREV_7D_SINCE, until=PREV_7D_UNTIL)

        rows.append([
            name[:40],
            c.get("status", "—"),
            fmt_float(ins_all.get("spend"), 2, "€"),
            fmt_budget(c),
            fmt_float(ins_all.get("impressions"), 0),
            fmt_float(ins_all.get("reach"), 0),
            fmt_float(ins_all.get("frequency"), 2),
            fmt_float(ins_all.get("ctr"), 2, "%"),
            fmt_float(ins_all.get("cpc"), 2, "€"),
            fmt_float(ins_all.get("cpm"), 2, "€"),
        ])

        payloads.append(build_campaign_payload(c, ins_all, ins_7d, ins_prev))

    headers = [
        "Campaña", "Estado", "Gasto", "Presupuesto",
        "Impresiones", "Alcance", "Frecuencia",
        "CTR", "CPC", "CPM"
    ]

    print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))
    print(f"\nTotal campañas: {len(campaigns)}")

    # Diagnóstico diferencial con Claude — solo campañas activas
    active_payloads = [p for p in payloads if p.get("status") == "ACTIVE"]
    print(f"\n🧠 Generando diagnóstico diferencial con IA ({len(active_payloads)} campañas activas)...")
    diagnoses = diagnose_campaigns(active_payloads)

    # Mostrar diagnósticos en consola
    if diagnoses:
        print("\n" + "─" * 70)
        print("  DIAGNÓSTICO DIFERENCIAL")
        print("─" * 70)
        for d in diagnoses:
            priority = d.get("recommended_action", {}).get("priority", "—")
            emoji = PRIORITY_EMOJI.get(priority, "⚠️")
            diag_label = DIAGNOSIS_LABEL.get(d.get("primary_diagnosis", ""), d.get("primary_diagnosis", "—"))
            print(f"\n  {emoji} {d.get('campaign_name','—')} [{d.get('status','—')}]")
            print(f"     Diagnóstico: {diag_label} (Confianza: {d.get('confidence','—')})")
            for s in d.get("key_signals", []):
                print(f"     · {s}")
            action = d.get("recommended_action", {})
            print(f"     → {priority}: {action.get('action','—')}")
            if d.get("do_not_do"):
                print(f"     🚫 No hacer: {d.get('do_not_do')}")
        print("\n" + "─" * 70)
    else:
        print("\n⚠️  No se obtuvieron diagnósticos de IA.")

    # Envío de email
    today_str = date.today().strftime("%d/%m/%Y")
    urgent = any(
        d.get("recommended_action", {}).get("priority") == "URGENT"
        for d in diagnoses
    )
    has_monitor = any(
        d.get("recommended_action", {}).get("priority") == "MONITOR"
        for d in diagnoses
    )
    emoji_subject = "🚨" if urgent else ("⚠️" if has_monitor else "✅")
    num_diag = len(diagnoses)
    subject = f"📊 Meta Ads Report — {today_str} {emoji_subject} {num_diag} campaña{'s' if num_diag != 1 else ''} analizadas"

    html_body = build_html_email(rows, headers, diagnoses, len(campaigns))
    send_email(subject, html_body)


if __name__ == "__main__":
    main()

