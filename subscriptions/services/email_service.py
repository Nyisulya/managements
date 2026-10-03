import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def strip_html_tags(html_text: str) -> str:
    import re
    if not html_text:
        return ''
    clean = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', html_text, flags=re.IGNORECASE)
    clean = re.sub(r'<[^>]*>', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def send_raw_email(to_email: str, subject: str, html_body: str, plain_text: str = None) -> dict:
    """
    Hutuma barua pepe kwa njia mbili thabiti:
    1. Resend API (Kasi ya juu na 100% Inbox Delivery kupitia domain ya nyisu.com)
    2. Gmail SMTP (Kama Resend ikipata hitilafu au ikiwa offline)
    """
    resend_api_key = getattr(settings, 'RESEND_API_KEY', '')
    email_sender = getattr(settings, 'EMAIL_SENDER', 'Felician <info@nyisu.com>')
    plain = plain_text or strip_html_tags(html_body)

    # 1. Jaribu Resend API Kwanza
    if resend_api_key:
        try:
            logger.info("Attempting email delivery via Resend API to %s", to_email)
            resp = requests.post(
                'https://api.resend.com/emails',
                headers={
                    'Authorization': f'Bearer {resend_api_key}',
                    'Content-Type': 'application/json'
                },
                json={
                    'from': email_sender,
                    'to': [to_email],
                    'reply_to': 'info@nyisu.com',
                    'subject': subject,
                    'html': html_body,
                    'text': plain
                },
                timeout=15
            )
            data = resp.json()
            if resp.status_code in [200, 201] and data.get('id'):
                logger.info("Resend Success: Email sent to %s (ID: %s)", to_email, data.get('id'))
                return {'success': True, 'engine': 'RESEND', 'id': data.get('id')}
            else:
                logger.warning("Resend failed: %s. Falling back to Gmail SMTP...", data)
        except Exception as err:
            logger.warning("Resend error: %s. Falling back to Gmail SMTP...", str(err))

    # 2. Fallback: Gmail SMTP
    smtp_user = getattr(settings, 'SMTP_USER', '')
    smtp_pass = getattr(settings, 'SMTP_PASS', '')
    smtp_host = getattr(settings, 'SMTP_HOST', 'smtp.gmail.com')
    smtp_port = getattr(settings, 'SMTP_PORT', 587)

    if smtp_user and smtp_pass:
        try:
            logger.info("Attempting email delivery via Gmail SMTP to %s", to_email)
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"Felician <{smtp_user}>"
            msg['To'] = to_email
            msg['Reply-To'] = 'info@nyisu.com'

            part1 = MIMEText(plain, 'plain', 'utf-8')
            part2 = MIMEText(html_body, 'html', 'utf-8')
            msg.attach(part1)
            msg.attach(part2)

            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, [to_email], msg.as_string())

            logger.info("SMTP Success: Email sent to %s via %s", to_email, smtp_host)
            return {'success': True, 'engine': 'SMTP', 'id': 'smtp_delivered'}
        except Exception as smtp_err:
            logger.error("Gmail SMTP Failed for %s: %s", to_email, str(smtp_err))
            return {'success': False, 'error': str(smtp_err)}

    return {'success': False, 'error': 'Hakuna njia inayofanya kazi ya kutuma email'}


def send_subscription_reminder_email(tenant, days_left: int):
    """
    Hutuma email ya kikumbusho cha tarehe ya kuisha kwa mteja (Kanisa au Ofisi)
    ikiwa na Pay Link ya kulipia moja kwa moja kwa M-Pesa / Tigo / Airtel
    """
    from ..models import NotificationLog
    base_url = getattr(settings, 'BASE_URL', 'http://127.0.0.1:8000')
    pay_url = f"{base_url}/pay/{tenant.slug}/"
    expiry_formatted = tenant.subscription_end.strftime("%d/%m/%Y")

    if days_left > 1:
        subject = f"Kikumbusho cha Leseni: Huduma ya {tenant.app.name} inaisha baada ya siku {days_left} - {tenant.name}"
        urgency_badge = f"ZIMESALIA SIKU {days_left}"
        urgency_color = "#f59e0b"
        event_type = f"EXPIRY_{days_left}D" if days_left in [7, 3] else "EXPIRY_WARNING"
        msg_header = f"Kikumbusho cha Malipo ya Mwezi ({tenant.app.name})"
    elif days_left == 1:
        subject = f"MUHIMU: Leseni ya {tenant.app.name} inaisha KESHO! - {tenant.name}"
        urgency_badge = "INAISHA KESHO!"
        urgency_color = "#ea580c"
        event_type = "EXPIRY_1D"
        msg_header = "Leseni Yako Inaisha Kesho!"
    elif days_left == 0:
        subject = f"HARAKA: Leseni ya {tenant.app.name} inaisha LEO! - {tenant.name}"
        urgency_badge = "INAISHA LEO"
        urgency_color = "#ef4444"
        event_type = "EXPIRY_0D"
        msg_header = "Muda wa Leseni Unaisha Leo!"
    else:
        subject = f"TAARIFA: Muda wa leseni ya {tenant.app.name} Umeisha - {tenant.name}"
        urgency_badge = "MUDA UMEISHA &bull; IMEFUNGWA"
        urgency_color = "#dc2626"
        event_type = "EXPIRED_LOCK"
    system_link_row = ""
    if tenant.system_url:
        system_link_row = f"""<tr><td class="info-label">Tovuti ya Mfumo:</td><td class="info-value"><a href="{tenant.system_url}" style="color: #60a5fa; text-decoration: underline;">{tenant.system_url}</a></td></tr>"""

    html = f"""
    <!DOCTYPE html>
    <html lang="sw">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #080d1a; color: #f8fafc; margin: 0; padding: 24px; }}
        .card {{ max-width: 580px; margin: 0 auto; background: #0f172a; border: 1px solid #1e2e4a; border-radius: 20px; overflow: hidden; box-shadow: 0 20px 30px rgba(0,0,0,0.6); }}
        .top-brand {{ background: linear-gradient(135deg, #1e3a8a, #0f172a); padding: 32px 24px; text-align: center; border-bottom: 2px solid {urgency_color}; }}
        .felician-logo {{ font-size: 26px; font-weight: 900; letter-spacing: 1px; color: #ffffff; margin: 0; text-transform: uppercase; }}
        .brand-sub {{ font-size: 12px; color: #93c5fd; text-transform: uppercase; letter-spacing: 1.5px; margin-top: 4px; font-weight: 700; }}
        .badge {{ display: inline-block; background: {urgency_color}; color: #020617; font-weight: 800; font-size: 11px; padding: 6px 16px; border-radius: 20px; letter-spacing: 1px; text-transform: uppercase; margin: 16px 0 10px; }}
        .content {{ padding: 32px 28px; }}
        .info-table {{ width: 100%; border-collapse: collapse; background: #080d1a; border: 1px solid #1e2e4a; border-radius: 12px; overflow: hidden; margin: 20px 0; }}
        .info-table td {{ padding: 12px 16px; border-bottom: 1px solid #1e2e4a; font-size: 14px; }}
        .info-table tr:last-child td {{ border-bottom: none; }}
        .info-label {{ color: #94a3b8; font-weight: 500; width: 40%; }}
        .info-value {{ color: #f8fafc; font-weight: 700; text-align: right; }}
        .btn-pay {{ display: block; width: 100%; box-sizing: border-box; text-align: center; background: linear-gradient(135deg, #10b981, #059669); color: #ffffff; text-decoration: none; padding: 16px 20px; border-radius: 12px; font-weight: 800; font-size: 16px; margin: 26px 0 14px; box-shadow: 0 4px 16px rgba(16, 185, 129, 0.4); }}
        .btn-pay:hover {{ background: #059669; }}
        .footer {{ text-align: center; padding: 22px; font-size: 12px; color: #64748b; border-top: 1px solid #1e2e4a; background: #0b1120; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="top-brand">
          <div class="felician-logo">Felician</div>
          <div class="brand-sub">Usimamizi wa Mifumo &bull; System Administration</div>
          <div><span class="badge">{urgency_badge}</span></div>
          <h2 style="margin: 6px 0 0; color: #ffffff; font-size: 18px; font-weight: 700;">{msg_header}</h2>
        </div>
        <div class="content">
          <p style="font-size: 15px; margin-top: 0; color: #f8fafc;">Habari <b>{tenant.contact_person or tenant.name}</b>,</p>
          <p style="font-size: 14px; color: #cbd5e1; line-height: 1.6;">
            Tunapenda kukukumbusha kwamba muda wa leseni ya mfumo wako wa <strong>{tenant.app.name}</strong> unaisha rasmi tarehe <strong>{expiry_formatted}</strong>.
          </p>

          <table class="info-table">
            <tr><td class="info-label">Taasisi / Mteja:</td><td class="info-value">{tenant.name}</td></tr>
            <tr><td class="info-label">Mfumo Unaotumika:</td><td class="info-value" style="color: #60a5fa;">{tenant.app.name}</td></tr>
            {system_link_row}
            <tr><td class="info-label">Tarehe ya Kuisha:</td><td class="info-value" style="color: {urgency_color};">{expiry_formatted}</td></tr>
            <tr><td class="info-label">Siku Zilizobaki:</td><td class="info-value">{days_left if days_left >= 0 else 0} siku</td></tr>
            <tr><td class="info-label">Ada ya Kawaida ya Mwezi:</td><td class="info-value">TZS {tenant.monthly_rate_tzs:,.0f}</td></tr>
          </table>

          <p style="font-size: 13px; color: #94a3b8; line-height: 1.5;">
            Ili kuhakikisha huduma inaendelea kufanya kazi bila kukatika au kujifunga, unaweza kulipia moja kwa moja kupitia simu yako ya <strong>M-Pesa, Tigo Pesa, Airtel Money au HaloPesa</strong>:
          </p>

          <a href="{pay_url}" class="btn-pay">💳 Lipia Sasa Kupitia Simu Yako &rarr;</a>

          <p style="font-size: 12px; color: #64748b; text-align: center; margin-top: 14px;">
            Au fungua link hii ya moja kwa moja: <br>
            <a href="{pay_url}" style="color: #38bdf8; text-decoration: none;">{pay_url}</a>
          </p>
        </div>
        <div class="footer">
          <b>Felician &bull; Usimamizi wa Mifumo</b><br>
          Msaada & Huduma kwa Wateja: <a href="mailto:info@nyisu.com" style="color: #38bdf8; text-decoration: none;">info@nyisu.com</a>
        </div>
      </div>
    </body>
    </html>
    """

    res = send_raw_email(tenant.email, subject, html)
    NotificationLog.objects.create(
        tenant=tenant,
        channel=res.get('engine', 'RESEND'),
        event_type=event_type,
        recipient=tenant.email,
        subject=subject,
        success=res.get('success', False),
        response_details=str(res)
    )
    return res


def send_payment_receipt_email(transaction):
    """
    Hutuma resiti rasmi na ya kisomi kwa mteja mara tu malipo ya HarakaPay yanapokamilika
    """
    from ..models import NotificationLog
    tenant = transaction.tenant
    expiry_formatted = tenant.subscription_end.strftime("%d/%m/%Y")
    now_formatted = timezone.now().strftime("%d/%m/%Y saa %H:%M")

    subject = f"Resiti ya Malipo: TZS {transaction.amount_tzs:,.0f} - {tenant.name} - Felician"

    system_link_row = ""
    system_button = ""
    if tenant.system_url:
        system_link_row = f"""<tr><td class="info-label">Tovuti ya Mfumo:</td><td class="info-value"><a href="{tenant.system_url}" style="color: #60a5fa; text-decoration: underline;">{tenant.system_url}</a></td></tr>"""
        system_button = f"""
        <div style="text-align: center; margin: 22px 0 10px;">
          <a href="{tenant.system_url}" style="display: block; box-sizing: border-box; width: 100%; text-align: center; background: linear-gradient(135deg, #2563eb, #1d4ed8); color: white; padding: 15px 20px; border-radius: 12px; font-weight: 800; text-decoration: none; font-size: 15px; box-shadow: 0 4px 14px rgba(37,99,235,0.4);">
            🌐 Fungua Mfumo Wako Sasa (System Login) &rarr;
          </a>
        </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html lang="sw">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #080d1a; color: #f8fafc; margin: 0; padding: 24px; }}
        .card {{ max-width: 580px; margin: 0 auto; background: #0f172a; border: 1px solid #1e2e4a; border-radius: 20px; overflow: hidden; box-shadow: 0 20px 30px rgba(0,0,0,0.6); }}
        .top-brand {{ background: linear-gradient(135deg, #065f46, #0f172a); padding: 32px 24px; text-align: center; border-bottom: 2px solid #10b981; }}
        .felician-logo {{ font-size: 26px; font-weight: 900; letter-spacing: 1px; color: #ffffff; margin: 0; text-transform: uppercase; }}
        .brand-sub {{ font-size: 12px; color: #a7f3d0; text-transform: uppercase; letter-spacing: 1.5px; margin-top: 4px; font-weight: 700; }}
        .badge-success {{ display: inline-block; background: #10b981; color: #020617; font-weight: 800; font-size: 11px; padding: 6px 16px; border-radius: 20px; letter-spacing: 1px; text-transform: uppercase; margin: 16px 0 10px; }}
        .content {{ padding: 32px 28px; }}
        .amount-card {{ background: #080d1a; border: 1px solid #10b981; border-radius: 14px; padding: 22px; text-align: center; margin: 20px 0; }}
        .amount-val {{ font-size: 34px; font-weight: 900; color: #34d399; margin: 4px 0; }}
        .info-table {{ width: 100%; border-collapse: collapse; background: #080d1a; border: 1px solid #1e2e4a; border-radius: 12px; overflow: hidden; margin: 20px 0; }}
        .info-table td {{ padding: 12px 16px; border-bottom: 1px solid #1e2e4a; font-size: 14px; }}
        .info-table tr:last-child td {{ border-bottom: none; }}
        .info-label {{ color: #94a3b8; font-weight: 500; width: 42%; }}
        .info-value {{ color: #f8fafc; font-weight: 700; text-align: right; }}
        .footer {{ text-align: center; padding: 22px; font-size: 12px; color: #64748b; border-top: 1px solid #1e2e4a; background: #0b1120; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="top-brand">
          <div class="felician-logo">Felician</div>
          <div class="brand-sub">Usimamizi wa Mifumo &bull; System Administration</div>
          <div><span class="badge-success">MALIPO YAMEPOKELEWA KIKAMILIFU</span></div>
          <h2 style="margin: 6px 0 0; color: #ffffff; font-size: 18px; font-weight: 700;">Resiti Rasmi ya Malipo ya Huduma</h2>
        </div>
        <div class="content">
          <p style="font-size: 15px; margin-top: 0; color: #f8fafc;">Habari <b>{tenant.contact_person or tenant.name}</b>,</p>
          <p style="font-size: 14px; color: #cbd5e1; line-height: 1.6;">
            Tunathibitisha kupokea malipo yako kwa ufanisi kupitia <strong>Mobile Money (HarakaPay)</strong>.
            Siku <strong>+{transaction.days_added}</strong> zimeongezwa kiotomatiki kwenye leseni ya mfumo wako wa <strong>{tenant.app.name}</strong>.
          </p>

          <div class="amount-card">
            <div style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 700; letter-spacing: 0.8px;">Kiasi Kilicholipwa</div>
            <div class="amount-val">+TZS {transaction.amount_tzs:,.0f}</div>
            <div style="font-size: 13px; color: #34d399; margin-top: 6px; font-weight: 600;">
              Tarehe Mpya ya Kuisha: <b>{expiry_formatted}</b>
            </div>
          </div>

          <table class="info-table">
            <tr><td class="info-label">Namba ya Muamala:</td><td class="info-value" style="font-family: monospace; color: #60a5fa;">{transaction.order_id}</td></tr>
            <tr><td class="info-label">Mteja / Taasisi:</td><td class="info-value">{tenant.name}</td></tr>
            <tr><td class="info-label">Mfumo:</td><td class="info-value">{tenant.app.name}</td></tr>
            {system_link_row}
            <tr><td class="info-label">Simu Iliyolipia:</td><td class="info-value">{transaction.phone_number}</td></tr>
            <tr><td class="info-label">Njia ya Malipo:</td><td class="info-value">Mobile Money (HarakaPay USSD Push)</td></tr>
            <tr><td class="info-label">Tarehe & Saa:</td><td class="info-value">{now_formatted}</td></tr>
            <tr><td class="info-label">Hali ya Huduma:</td><td class="info-value" style="color: #34d399;">HAI / INAFANYA KAZI (ACTIVE)</td></tr>
          </table>

          {system_button}

          <div style="background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 12px; padding: 14px; margin-top: 18px; text-align: center;">
            <p style="font-size: 13px; color: #cbd5e1; margin: 0; line-height: 1.5;">
              Mfumo wako unaendelea kufanya kazi moja kwa moja bila kukatika. Asante sana kwa ushirikiano wako na kutuamini!
            </p>
          </div>
        </div>
        <div class="footer">
          <b>Felician &bull; Usimamizi wa Mifumo</b><br>
          Msaada & Huduma kwa Wateja: <a href="mailto:info@nyisu.com" style="color: #38bdf8; text-decoration: none;">info@nyisu.com</a>
        </div>
      </div>
    </body>
    </html>
    """

    res = send_raw_email(tenant.email, subject, html)
    NotificationLog.objects.create(
        tenant=tenant,
        channel=res.get('engine', 'RESEND'),
        event_type='PAYMENT_RECEIPT',
        recipient=tenant.email,
        subject=subject,
        success=res.get('success', False),
        response_details=str(res)
    )
    return res


def send_admin_new_payment_alert(transaction):
    """
    Hutuma taarifa ya papo hapo kwa Felician (wewe) kwamba mteja amelipa
    admin_email = getattr(settings, 'SMTP_USER', '')
    if not admin_email:
        # Fallback to extracting from EMAIL_SENDER
        sender = getattr(settings, 'EMAIL_SENDER', '')
        if '<' in sender and '>' in sender:
            admin_email = sender.split('<')[1].replace('>', '').strip()
        else:
            admin_email = sender
    if not admin_email:
        return
    tenant = transaction.tenant
    subject = f"Pesa Imeingia: TZS {transaction.amount_tzs:,.0f} kutoka {tenant.name} - Felician"
    html = f"""
    <!DOCTYPE html>
    <html lang="sw">
    <head><meta charset="utf-8"></head>
    <body style="font-family: sans-serif; background: #080d1a; color: #f8fafc; padding: 24px;">
      <div style="max-width: 520px; margin: 0 auto; background: #0f172a; border: 1px solid #1e2e4a; border-radius: 16px; padding: 28px;">
        <div style="font-size: 20px; font-weight: 900; color: #ffffff; margin-bottom: 2px;">Felician</div>
        <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 20px;">Usimamizi wa Mifumo</div>

        <h3 style="color: #34d399; margin: 0 0 14px;">Pesa Mpya Imeingia Kwenye HarakaPay!</h3>
        <p style="font-size: 14px; color: #cbd5e1; line-height: 1.5;">
          Mteja amelipia subscription yake kiotomatiki na siku zimeongezwa mara moja:
        </p>
        
        <table style="width: 100%; border-collapse: collapse; margin: 18px 0; font-size: 13px;">
          <tr><td style="padding: 6px 0; color: #94a3b8;">Mteja:</td><td style="font-weight: bold; color: white;">{tenant.name}</td></tr>
          <tr><td style="padding: 6px 0; color: #94a3b8;">Mfumo:</td><td style="font-weight: bold; color: #60a5fa;">{tenant.app.name}</td></tr>
          <tr><td style="padding: 6px 0; color: #94a3b8;">Kiasi:</td><td style="font-weight: 900; color: #34d399; font-size: 16px;">TZS {transaction.amount_tzs:,.0f}</td></tr>
          <tr><td style="padding: 6px 0; color: #94a3b8;">Simu:</td><td style="font-weight: bold; color: white;">{transaction.phone_number}</td></tr>
          <tr><td style="padding: 6px 0; color: #94a3b8;">Siku Zilizoongezwa:</td><td style="font-weight: bold; color: white;">+{transaction.days_added} siku</td></tr>
          <tr><td style="padding: 6px 0; color: #94a3b8;">Tarehe Mpya ya Kuisha:</td><td style="font-weight: bold; color: #34d399;">{tenant.subscription_end.strftime('%d/%m/%Y')}</td></tr>
          <tr><td style="padding: 6px 0; color: #94a3b8;">Order ID:</td><td style="font-family: monospace; color: #60a5fa;">{transaction.order_id}</td></tr>
        </table>
        
        <p style="font-size: 11px; color: #64748b; border-top: 1px solid #1e2e4a; padding-top: 12px; margin-bottom: 0;">
          Taarifa hii imezalishwa kiotomatiki na Mfumo wa Billing &bull; Felician
        </p>
      </div>
    </body>
    </html>
    """
    return send_raw_email(admin_email, subject, html)
