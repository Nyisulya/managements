import json
import logging
from datetime import timedelta
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.conf import settings

from .models import SystemApp, PricingPlan, ClientTenant, PaymentTransaction, NotificationLog
from .services.harakapay import HarakaPayService, process_successful_payment, normalize_tanzanian_phone
from .services.email_service import (
    send_subscription_reminder_email,
    send_payment_receipt_email,
    send_admin_new_payment_alert,
    send_raw_email
)

logger = logging.getLogger(__name__)


# ========================================================
# 1. ADMIN DASHBOARD & MANAGEMENT VIEWS
# ========================================================

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        user = authenticate(request, username=u, password=p)
        if user:
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, 'Jina la mtumiaji au nenosiri si sahihi.')
    return render(request, 'auth/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def dashboard_view(request):
    today = timezone.now().date()
    
    # Auto-refresh tenant statuses
    for t in ClientTenant.objects.exclude(status='SUSPENDED'):
        t.update_status_field()
        t.save(update_fields=['status'])

    # Filtering
    filter_status = request.GET.get('status', 'all')
    search_q = request.GET.get('q', '').strip()
    app_id = request.GET.get('app')

    tenants_qs = ClientTenant.objects.select_related('app').all()

    if app_id:
        tenants_qs = tenants_qs.filter(app_id=app_id)

    if search_q:
        tenants_qs = tenants_qs.filter(
            Q(name__icontains=search_q) |
            Q(contact_person__icontains=search_q) |
            Q(phone__icontains=search_q) |
            Q(email__icontains=search_q)
        )

    if filter_status == 'active':
        tenants_qs = tenants_qs.filter(status='ACTIVE')
    elif filter_status == 'expiring':
        tenants_qs = tenants_qs.filter(status='EXPIRING_SOON')
    elif filter_status == 'grace':
        tenants_qs = tenants_qs.filter(status='GRACE_PERIOD')
    elif filter_status == 'expired':
        tenants_qs = tenants_qs.filter(status='EXPIRED')
    elif filter_status == 'suspended':
        tenants_qs = tenants_qs.filter(status='SUSPENDED')

    # Aggregates
    total_tenants = ClientTenant.objects.count()
    active_count = ClientTenant.objects.filter(status='ACTIVE').count()
    expiring_soon_count = ClientTenant.objects.filter(status='EXPIRING_SOON').count()
    expired_count = ClientTenant.objects.filter(status__in=['EXPIRED', 'GRACE_PERIOD']).count()

    # MRR (Monthly Recurring Revenue)
    mrr_val = ClientTenant.objects.filter(status__in=['ACTIVE', 'EXPIRING_SOON']).aggregate(Sum('monthly_rate_tzs'))['monthly_rate_tzs__sum'] or 0

    # Total collected this month
    first_of_month = today.replace(day=1)
    month_revenue = PaymentTransaction.objects.filter(
        status='COMPLETED',
        created_at__date__gte=first_of_month
    ).aggregate(Sum('amount_tzs'))['amount_tzs__sum'] or 0

    recent_transactions = PaymentTransaction.objects.select_related('tenant', 'tenant__app').order_by('-created_at')[:8]
    apps = SystemApp.objects.all()

    context = {
        'tenants': tenants_qs,
        'total_tenants': total_tenants,
        'active_count': active_count,
        'expiring_soon_count': expiring_soon_count,
        'expired_count': expired_count,
        'mrr_val': mrr_val,
        'month_revenue': month_revenue,
        'recent_transactions': recent_transactions,
        'apps': apps,
        'filter_status': filter_status,
        'search_q': search_q,
        'selected_app': app_id,
        'today': today,
    }
    return render(request, 'dashboard/index.html', context)


@login_required
def tenant_detail_view(request, tenant_id):
    tenant = get_object_or_404(ClientTenant.objects.select_related('app'), id=tenant_id)
    payments = tenant.payments.order_by('-created_at')
    notifications = tenant.notifications.order_by('-sent_at')[:15]
    plans = tenant.app.plans.filter(is_active=True)

    context = {
        'tenant': tenant,
        'payments': payments,
        'notifications': notifications,
        'plans': plans,
    }
    return render(request, 'dashboard/tenant_detail.html', context)


@login_required
def add_tenant_view(request):
    apps = SystemApp.objects.all()
    if request.method == 'POST':
        name = request.POST.get('name')
        app_id = request.POST.get('app_id')
        contact_person = request.POST.get('contact_person', '')
        phone = request.POST.get('phone', '')
        email = request.POST.get('email', '')
        system_url = request.POST.get('system_url', '').strip()
        monthly_rate = request.POST.get('monthly_rate_tzs', 50000)
        days = int(request.POST.get('initial_days', 30))
        notes = request.POST.get('notes', '')

        app = get_object_or_404(SystemApp, id=app_id)
        start_date = timezone.now().date()
        end_date = start_date + timedelta(days=days)

        tenant = ClientTenant.objects.create(
            name=name,
            app=app,
            contact_person=contact_person,
            phone=phone,
            email=email,
            system_url=system_url,
            monthly_rate_tzs=monthly_rate,
            subscription_start=start_date,
            subscription_end=end_date,
            notes=notes
        )
        messages.success(request, f'Mteja "{tenant.name}" amesajiliwa kikamilifu!')
        return redirect('tenant_detail', tenant_id=tenant.id)

    return render(request, 'dashboard/tenant_form.html', {'apps': apps})


@login_required
def edit_tenant_view(request, tenant_id):
    tenant = get_object_or_404(ClientTenant, id=tenant_id)
    apps = SystemApp.objects.all()
    if request.method == 'POST':
        tenant.name = request.POST.get('name')
        tenant.app_id = request.POST.get('app_id')
        tenant.contact_person = request.POST.get('contact_person', '')
        tenant.phone = request.POST.get('phone', '')
        tenant.email = request.POST.get('email', '')
        tenant.system_url = request.POST.get('system_url', '').strip()
        tenant.monthly_rate_tzs = request.POST.get('monthly_rate_tzs', tenant.monthly_rate_tzs)
        
        # Expiry date manual edit
        end_date_str = request.POST.get('subscription_end')
        if end_date_str:
            from datetime import datetime
            tenant.subscription_end = datetime.strptime(end_date_str, '%Y-%m-%d').date()

        status = request.POST.get('status')
        if status in dict(ClientTenant.STATUS_CHOICES):
            tenant.status = status

        tenant.notes = request.POST.get('notes', '')
        tenant.update_status_field()
        tenant.save()
        messages.success(request, f'Taarifa za mteja zimesasishwa!')
        return redirect('tenant_detail', tenant_id=tenant.id)

    return render(request, 'dashboard/tenant_edit.html', {'tenant': tenant, 'apps': apps})


@login_required
@require_POST
def manual_extend_view(request, tenant_id):
    """
    Kitufe cha kuongeza siku za leseni mkononi (kwa mfano mteja akilipa kwa pesa taslimu au benki)
    """
    tenant = get_object_or_404(ClientTenant, id=tenant_id)
    days = int(request.POST.get('days', 30))
    amount = request.POST.get('amount_tzs') or (tenant.monthly_rate_tzs * (days // 30 or 1))
    notes = request.POST.get('notes', 'Malipo ya mkononi (Manual Extension)')

    # Add transaction record
    import uuid
    order_id = f"MANUAL_{uuid.uuid4().hex[:10].upper()}"
    tx = PaymentTransaction.objects.create(
        tenant=tenant,
        order_id=order_id,
        amount_tzs=amount,
        phone_number=tenant.phone or 'MANUAL',
        days_added=days,
        status='COMPLETED',
        gateway='manual_admin',
        gateway_response={'notes': notes, 'admin': request.user.username},
        completed_at=timezone.now()
    )

    tenant.extend_subscription(days)
    messages.success(request, f'Siku +{days} zimeongezwa kwa mteja "{tenant.name}". Tarehe mpya ya kuisha ni {tenant.subscription_end.strftime("%d/%m/%Y")}!')
    return redirect('tenant_detail', tenant_id=tenant.id)


@login_required
def send_manual_reminder_view(request, tenant_id):
    """
    Tuma kikumbusho cha barua pepe mara moja kwa mteja
    """
    tenant = get_object_or_404(ClientTenant, id=tenant_id)
    res = send_subscription_reminder_email(tenant, tenant.days_remaining)
    if res.get('success'):
        messages.success(request, f'Barua pepe ya kikumbusho imetumwa kwa {tenant.email} kupitia {res.get("engine", "Email")}!')
    else:
        messages.error(request, f'Imeshindikana kutuma barua pepe: {res.get("error")}')
    return redirect('tenant_detail', tenant_id=tenant.id)


@login_required
def transactions_list_view(request):
    transactions = PaymentTransaction.objects.select_related('tenant', 'tenant__app').all().order_by('-created_at')
    status_filter = request.GET.get('status')
    if status_filter:
        transactions = transactions.filter(status=status_filter)

    total_amount = transactions.filter(status='COMPLETED').aggregate(Sum('amount_tzs'))['amount_tzs__sum'] or 0

    return render(request, 'dashboard/transactions.html', {
        'transactions': transactions,
        'total_amount': total_amount,
        'status_filter': status_filter
    })


@login_required
def apps_list_view(request):
    apps = SystemApp.objects.prefetch_related('plans', 'tenants').all()
    if request.method == 'POST':
        name = request.POST.get('name')
        code = request.POST.get('code')
        desc = request.POST.get('description', '')
        icon = request.POST.get('icon', 'bi-laptop')
        SystemApp.objects.create(name=name, code=code, description=desc, icon=icon)
        messages.success(request, f'Mfumo mpya "{name}" umeongezwa!')
        return redirect('apps_list')
    return render(request, 'dashboard/apps.html', {'apps': apps})


@login_required
def add_plan_view(request, app_id):
    app = get_object_or_404(SystemApp, id=app_id)
    if request.method == 'POST':
        name = request.POST.get('name')
        duration_days = int(request.POST.get('duration_days', 30))
        price_tzs = Decimal(request.POST.get('price_tzs', 50000))
        desc = request.POST.get('description', '')
        is_pop = bool(request.POST.get('is_popular'))
        PricingPlan.objects.create(
            app=app,
            name=name,
            duration_days=duration_days,
            price_tzs=price_tzs,
            description=desc,
            is_popular=is_pop
        )
        messages.success(request, f'Kifurushi kimeongezwa kwa {app.name}!')
    return redirect('apps_list')


# ========================================================
# 2. CLIENT SELF-SERVICE PUBLIC PAY PORTAL (/pay/<slug>/)
# ========================================================

def client_pay_portal_view(request, slug):
    """
    Ukurasa wa wazi wa mteja (Kanisa au Ofisi) kujilipia kwa M-Pesa / Tigo / Airtel
    """
    tenant = get_object_or_404(ClientTenant.objects.select_related('app'), slug=slug)
    plans = tenant.app.plans.filter(is_active=True).order_by('duration_days')

    # If no custom plans exist, provide default 1 month, 3 months, 6 months
    default_plans = []
    if not plans.exists():
        base_rate = tenant.monthly_rate_tzs
        default_plans = [
            {'id': 'custom_30', 'name': 'Mwezi 1 (Kawaida)', 'duration_days': 30, 'price_tzs': base_rate, 'is_popular': False},
            {'id': 'custom_90', 'name': 'Miezi 3 (Robo Mwaka)', 'duration_days': 90, 'price_tzs': int(base_rate * 3 * Decimal('0.95')), 'is_popular': True},
            {'id': 'custom_180', 'name': 'Miezi 6 (Nusu Mwaka)', 'duration_days': 180, 'price_tzs': int(base_rate * 6 * Decimal('0.90')), 'is_popular': False},
            {'id': 'custom_365', 'name': 'Mwaka 1 (Ofa ya Mwaka)', 'duration_days': 365, 'price_tzs': int(base_rate * 12 * Decimal('0.85')), 'is_popular': False},
        ]

    context = {
        'tenant': tenant,
        'plans': plans,
        'default_plans': default_plans,
        'today': timezone.now().date(),
    }
    return render(request, 'portal/pay.html', context)


@csrf_exempt
@require_POST
def initiate_payment_api(request):
    """
    API Inayoitwa na ukurasa wa malipo kutuma USSD Push kupitia HarakaPay
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST

    tenant_id = data.get('tenant_id')
    phone = data.get('phone')
    plan_id = data.get('plan_id')
    custom_amount = data.get('amount')
    custom_days = data.get('days')

    tenant = get_object_or_404(ClientTenant, id=tenant_id)

    # Determine amount and days
    amount = 0
    days_to_add = 30
    plan_obj = None

    if plan_id and not str(plan_id).startswith('custom_'):
        try:
            plan_obj = PricingPlan.objects.get(id=plan_id, app=tenant.app)
            amount = int(plan_obj.price_tzs)
            days_to_add = plan_obj.duration_days
        except PricingPlan.DoesNotExist:
            pass

    if not amount:
        if str(plan_id).startswith('custom_'):
            try:
                days_to_add = int(str(plan_id).split('_')[1])
                mult = days_to_add / 30
                # Apply small discount
                discount = Decimal('0.95') if days_to_add == 90 else (Decimal('0.90') if days_to_add == 180 else (Decimal('0.85') if days_to_add >= 365 else Decimal('1.0')))
                amount = int(tenant.monthly_rate_tzs * Decimal(mult) * discount)
            except Exception:
                amount = int(tenant.monthly_rate_tzs)
        elif custom_amount:
            amount = int(custom_amount)
            days_to_add = int(custom_days or 30)
        else:
            amount = int(tenant.monthly_rate_tzs)
            days_to_add = 30

    # Description
    desc = f"Malipo ya {tenant.app.name} ({days_to_add} days) - {tenant.name}"

    # Call HarakaPay USSD Push
    push_res = HarakaPayService.send_ussd_push(
        phone=phone,
        amount=amount,
        description=desc
    )

    if not push_res.get('success'):
        return JsonResponse({
            'success': False,
            'error': push_res.get('error', 'Imeshindikana kutuma ombi la USSD Push.')
        }, status=400)

    order_id = push_res.get('order_id')
    clean_phone = push_res.get('phone', phone)

    # Create Pending Transaction
    tx = PaymentTransaction.objects.create(
        tenant=tenant,
        order_id=order_id,
        plan=plan_obj,
        amount_tzs=amount,
        phone_number=clean_phone,
        days_added=days_to_add,
        status='PENDING',
        gateway='harakapay',
        gateway_response=push_res.get('raw_response', {})
    )

    return JsonResponse({
        'success': True,
        'order_id': order_id,
        'amount': amount,
        'phone': clean_phone,
        'days_added': days_to_add,
        'message': push_res.get('message')
    })


@require_GET
def check_order_status_api(request, order_id):
    """
    Inaitwa kila baada ya sekunde 3 na ukurasa wa mteja kukagua kama ameshaweka PIN
    """
    try:
        tx = PaymentTransaction.objects.select_related('tenant').get(order_id=order_id)
    except PaymentTransaction.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Muamala haupatikani'}, status=404)

    if tx.status == 'COMPLETED':
        return JsonResponse({
            'success': True,
            'completed': True,
            'status': 'completed',
            'new_expiry': tx.tenant.subscription_end.strftime('%d/%m/%Y'),
            'message': 'Malipo yamekamilika na siku zimeongezwa kikamilifu!'
        })

    # Poll HarakaPay status
    poll_result = HarakaPayService.check_payment_status(order_id)

    if poll_result.get('completed'):
        process_successful_payment(tx, poll_result.get('raw'))
        return JsonResponse({
            'success': True,
            'completed': True,
            'status': 'completed',
            'new_expiry': tx.tenant.subscription_end.strftime('%d/%m/%Y'),
            'message': 'Hongera! Malipo yako yamekamilika kwa ufanisi.'
        })
    elif poll_result.get('status') == 'failed':
        tx.status = 'FAILED'
        tx.save(update_fields=['status'])
        return JsonResponse({
            'success': False,
            'completed': False,
            'status': 'failed',
            'error': poll_result.get('error', 'Malipo yameshindikana au yamekatishwa.')
        })

    return JsonResponse({
        'success': True,
        'completed': False,
        'status': 'pending',
        'message': 'Inasubiri kuweka PIN kwenye simu yako...'
    })


# ========================================================
# 3. HARAKAPAY WEBHOOK ENDPOINT
# ========================================================

@csrf_exempt
@require_POST
def harakapay_webhook_view(request):
    """
    Webhook inapokea taarifa za papo hapo kutoka HarakaPay mara tu mteja anapoweka PIN
    """
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception as e:
        logger.error("Invalid webhook payload: %s", str(e))
        return HttpResponse("Bad Request", status=400)

    logger.info("HarakaPay Webhook received: %s", payload)

    order_id = payload.get('order_id')
    status = str(payload.get('status', '')).lower()
    amount = payload.get('amount')

    if not order_id:
        return HttpResponse("Missing order_id", status=400)

    try:
        tx = PaymentTransaction.objects.select_related('tenant').get(order_id=order_id)
    except PaymentTransaction.DoesNotExist:
        logger.warning("Webhook received for unknown order_id: %s", order_id)
        return HttpResponse("Order not found", status=404)

    if status == 'completed':
        process_successful_payment(tx, payload)
        logger.info("Transaction %s successfully completed via webhook!", order_id)
    elif status in ['failed', 'cancelled', 'canceled', 'declined', 'timeout']:
        tx.status = 'FAILED'
        tx.gateway_response = payload
        tx.save()

    return JsonResponse({'received': True})


# ========================================================
# 4. REMOTE LICENSE VERIFICATION API (FOR CHURCH/OFFICE APPS)
# ========================================================

@csrf_exempt
def verify_license_api(request):
    """
    Hii ndio API ambayo mifumo ya makanisa au ofisi inaitumia kujua kama mteja bado analipia au muda umeisha.
    Usage:
    GET /api/v1/license/verify/?key=lic_xxxxxxxxxxxx
    or
    POST /api/v1/license/verify/ with JSON: {"api_key": "lic_xxxxxxxxxxxx"}
    or
    Header: "X-License-Key: lic_xxxxxxxxxxxx"
    """
    api_key = request.headers.get('X-License-Key')
    if not api_key:
        if request.method == 'POST':
            try:
                body = json.loads(request.body.decode('utf-8'))
                api_key = body.get('api_key')
            except Exception:
                api_key = request.POST.get('api_key')
        else:
            api_key = request.GET.get('key') or request.GET.get('api_key')

    if not api_key:
        return JsonResponse({
            'valid': False,
            'error': 'API Key ya leseni inahitajika (Tuma kupitia header X-License-Key au param key).'
        }, status=401)

    try:
        tenant = ClientTenant.objects.select_related('app').get(api_key=api_key)
    except ClientTenant.DoesNotExist:
        return JsonResponse({
            'valid': False,
            'status': 'INVALID_KEY',
            'error': 'Leseni hii haijasajiliwa au imeondolewa kwenye mfumo mkuu.'
        }, status=403)

    tenant.update_status_field()
    tenant.save(update_fields=['status'])

    base_url = getattr(settings, 'BASE_URL', 'http://127.0.0.1:8000')
    pay_url = f"{base_url}/pay/{tenant.slug}/"
    is_accessible = tenant.is_service_accessible
    days_left = tenant.days_remaining

    if is_accessible:
        message = f"Leseni ya {tenant.app.name} iko hai. Zimesalia siku {days_left}."
    else:
        message = f"Huduma imefungwa kwa kuwa muda wa matumizi umeisha tarehe {tenant.subscription_end.strftime('%d/%m/%Y')}. Tafadhali lipia kupitia link hii: {pay_url}"

    return JsonResponse({
        'valid': is_accessible,
        'status': tenant.status,
        'tenant_name': tenant.name,
        'app_name': tenant.app.name,
        'days_remaining': days_left,
        'subscription_start': tenant.subscription_start.strftime('%Y-%m-%d'),
        'subscription_end': tenant.subscription_end.strftime('%Y-%m-%d'),
        'grace_period_days': tenant.grace_period_days,
        'monthly_rate_tzs': int(tenant.monthly_rate_tzs),
        'pay_url': pay_url,
        'message': message
    })
