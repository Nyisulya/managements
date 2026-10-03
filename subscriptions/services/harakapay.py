import re
import logging
import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def normalize_tanzanian_phone(phone_str: str) -> str:
    """
    Normalizes Tanzanian phone numbers to 07xxxxxxxx or 06xxxxxxxx
    """
    cleaned = re.sub(r'[\s\-\+\(\)]', '', str(phone_str or '')).strip()
    if cleaned.startswith('255'):
        cleaned = '0' + cleaned[3:]
    return cleaned


class HarakaPayService:
    @classmethod
    def get_api_key(cls):
        return getattr(settings, 'HARAKAPAY_API_KEY', '')

    @classmethod
    def get_base_url(cls):
        return getattr(settings, 'HARAKAPAY_BASE_URL', 'https://harakapay.net').rstrip('/')

    @classmethod
    def send_ussd_push(cls, phone: str, amount: int, description: str, webhook_url: str = None) -> dict:
        """
        Inatuma USSD Push kwenye simu ya mteja (M-Pesa, Tigo Pesa, Airtel Money, HaloPesa)
        kupitia HarakaPay API /api/v1/collect
        """
        clean_phone = normalize_tanzanian_phone(phone)
        if not clean_phone or len(clean_phone) != 10 or not (clean_phone.startswith('07') or clean_phone.startswith('06')):
            return {
                'success': False,
                'error': 'Tafadhali weka namba sahihi ya simu ya Tanzania (mfano: 0712345678 au 0687654321).'
            }

        try:
            num_amount = int(amount)
        except (ValueError, TypeError):
            return {'success': False, 'error': 'Kiasi cha malipo si sahihi.'}

        if num_amount < 500:
            return {'success': False, 'error': 'Kiwango cha chini cha malipo ni TZS 500.'}

        api_key = cls.get_api_key()
        if not api_key:
            return {'success': False, 'error': 'HarakaPay API Key haijawekwa kwenye mifumo.'}

        base_url = cls.get_base_url()
        endpoint = f"{base_url}/api/v1/collect"

        if not webhook_url:
            system_base = getattr(settings, 'BASE_URL', 'http://127.0.0.1:8000')
            webhook_url = f"{system_base}/api/payment/harakapay/webhook/"

        headers = {
            'Content-Type': 'application/json',
            'X-API-Key': api_key,
            'User-Agent': 'MifumoYanguSaaS/1.0'
        }

        payload = {
            'phone': clean_phone,
            'amount': num_amount,
            'description': description or 'Malipo ya Leseni ya Mfumo',
            'webhook_url': webhook_url
        }

        try:
            logger.info("HarakaPay USSD Push request to %s for %s TZS", clean_phone, num_amount)
            response = requests.post(endpoint, json=payload, headers=headers, timeout=25)
            data = response.json()
            logger.info("HarakaPay response status %s: %s", response.status_code, data)

            if response.status_code in [200, 201] and data.get('success'):
                order_id = data.get('order_id')
                return {
                    'success': True,
                    'order_id': order_id,
                    'message': data.get('message', 'Ombi la malipo (USSD Push) limetumwa kwenye simu yako. Tafadhali weka PIN kukamilisha.'),
                    'phone': clean_phone,
                    'amount': num_amount,
                    'raw_response': data
                }
            else:
                err_msg = data.get('error') or data.get('message') or f"Hitilafu kutoka HarakaPay (Kodi {response.status_code})"
                return {'success': False, 'error': err_msg, 'raw_response': data}

        except requests.exceptions.RequestException as e:
            logger.error("Network error connecting to HarakaPay: %s", str(e))
            return {'success': False, 'error': f"Hitilafu ya mtandao na HarakaPay Gateway: {str(e)}"}

    @classmethod
    def check_payment_status(cls, order_id: str) -> dict:
        """
        Inakagua hali ya malipo kwenye HarakaPay kwa kutumia order_id
        """
        if not order_id:
            return {'completed': False, 'status': 'unknown', 'error': 'Missing order_id'}

        api_key = cls.get_api_key()
        base_url = cls.get_base_url()
        endpoint = f"{base_url}/api/v1/status/{order_id}"

        headers = {
            'X-API-Key': api_key,
            'User-Agent': 'MifumoYanguSaaS/1.0'
        }

        try:
            response = requests.get(endpoint, headers=headers, timeout=20)
            data = response.json()

            if not data.get('success') or not data.get('payment'):
                return {
                    'completed': False,
                    'status': 'pending',
                    'message': data.get('message') or 'Inasubiri uthibitisho wa PIN kwenye simu.'
                }

            payment = data.get('payment', {})
            pay_status = str(payment.get('status', '')).lower().strip()

            if pay_status == 'completed':
                return {
                    'completed': True,
                    'status': 'completed',
                    'amount': payment.get('amount'),
                    'order_id': order_id,
                    'raw': payment
                }
            elif pay_status in ['failed', 'cancelled', 'canceled', 'declined', 'rejected', 'expired', 'timeout']:
                return {
                    'completed': False,
                    'status': 'failed',
                    'error': 'Muamala haukukamilika: Nenosiri (PIN) limekosewa, salio halitoshi, au malipo yamekatishwa.',
                    'raw': payment
                }
            else:
                return {
                    'completed': False,
                    'status': pay_status or 'pending',
                    'message': 'Inasubiri uthibitisho.'
                }

        except Exception as e:
            logger.error("Error polling HarakaPay status for order %s: %s", order_id, str(e))
            return {'completed': False, 'status': 'error', 'error': str(e)}


def process_successful_payment(transaction, payment_data=None):
    """
    Hushughulikia muamala uliokamilika:
    1. Huongeza siku kwenye leseni ya mteja (Tenant)
    2. Huweka transaction kama COMPLETED
    3. Hutuma resiti kupitia Resend au Gmail SMTP
    """
    if transaction.status == 'COMPLETED':
        return transaction

    transaction.status = 'COMPLETED'
    transaction.completed_at = timezone.now()
    if payment_data:
        transaction.gateway_response = payment_data
    transaction.save()

    tenant = transaction.tenant
    days_to_add = transaction.days_added or 30
    tenant.extend_subscription(days_to_add)

    # Dispatch email receipt & admin notification asynchronously or immediately
    try:
        from .email_service import send_payment_receipt_email, send_admin_new_payment_alert
        send_payment_receipt_email(transaction)
        send_admin_new_payment_alert(transaction)
        transaction.receipt_sent = True
        transaction.save(update_fields=['receipt_sent'])
    except Exception as e:
        logger.error("Error sending receipt for transaction %s: %s", transaction.order_id, str(e))

    return transaction
