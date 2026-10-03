import uuid
import secrets
from datetime import date, timedelta
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class SystemApp(models.Model):
    """
    Mifumo mbalimbali unayoisimamia (mf. Kanisa, Shule, Ofisi/POS, Hospitali)
    """
    name = models.CharField(max_length=150, verbose_name="Jina la Mfumo")
    code = models.SlugField(max_length=80, unique=True, verbose_name="Code ya Mfumo")
    description = models.TextField(blank=True, verbose_name="Maelezo Mafupi")
    icon = models.CharField(max_length=50, default="bi-laptop", verbose_name="Alama ya Icon")
    is_active = models.BooleanField(default=True, verbose_name="Inapatikana")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mfumo (System App)"
        verbose_name_plural = "Mifumo Yote"
        ordering = ['name']

    def __str__(self):
        return self.name

    def active_tenants_count(self):
        return self.tenants.filter(subscription_end__gte=timezone.now().date()).count()


class PricingPlan(models.Model):
    """
    Vifurushi vya malipo kwa mfumo (mf. Mwezi 1, Miezi 3, Mwaka 1)
    """
    app = models.ForeignKey(SystemApp, on_delete=models.CASCADE, related_name="plans", verbose_name="Mfumo")
    name = models.CharField(max_length=100, verbose_name="Jina la Kifurushi (mf. Mwezi 1)")
    duration_days = models.PositiveIntegerField(default=30, verbose_name="Idadi ya Siku (mf. 30)")
    price_tzs = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Bei (TZS)")
    description = models.CharField(max_length=255, blank=True, verbose_name="Maelezo ya Ziada")
    is_popular = models.BooleanField(default=False, verbose_name="Pendekezo Kuu (Popular)")
    is_active = models.BooleanField(default=True, verbose_name="Kinafanya kazi")

    class Meta:
        verbose_name = "Kifurushi (Pricing Plan)"
        verbose_name_plural = "Vifurushi vya Malipo"
        ordering = ['duration_days']

    def __str__(self):
        return f"{self.app.name} - {self.name} ({self.price_tzs:,.0f} TZS / siku {self.duration_days})"


class ClientTenant(models.Model):
    """
    Mteja anayetumia mfumo wako (Kanisa, Ofisi, Shule, Kliniki n.k.)
    """
    STATUS_CHOICES = [
        ('ACTIVE', 'Hai / Salama (Active)'),
        ('EXPIRING_SOON', 'Inakaribia Kuisha (Expiring Soon)'),
        ('GRACE_PERIOD', 'Muda wa Nyongeza (Grace Period)'),
        ('EXPIRED', 'Muda Umeisha / Imefungwa (Expired)'),
        ('SUSPENDED', 'Imezimwa (Suspended)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, verbose_name="Jina la Mteja / Taasisi (mf. KKKT Mwenge)")
    slug = models.SlugField(max_length=150, unique=True, verbose_name="Slug ya Malipo (Pay Link URL)")
    app = models.ForeignKey(SystemApp, on_delete=models.PROTECT, related_name="tenants", verbose_name="Mfumo Anao-tumia")
    contact_person = models.CharField(max_length=150, blank=True, verbose_name="Mtu wa Mawasiliano")
    phone = models.CharField(max_length=30, verbose_name="Namba ya Simu (M-Pesa/Tigo/Airtel)")
    email = models.EmailField(verbose_name="Barua Pepe (Email ya Mteja)")
    system_url = models.URLField(max_length=255, blank=True, verbose_name="Link ya Mfumo wa Mteja (System URL)")
    
    # Remote Verification Key for client systems (optional)
    api_key = models.CharField(max_length=64, unique=True, blank=True, verbose_name="API Key ya Leseni")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE', verbose_name="Hali ya Leseni")
    subscription_start = models.DateField(default=timezone.now, verbose_name="Tarehe ya Kuanza")
    subscription_end = models.DateField(verbose_name="Tarehe ya Kuisha (Expiry Date)")
    grace_period_days = models.PositiveIntegerField(default=3, verbose_name="Siku za Nyongeza Baada ya Kuisha")
    monthly_rate_tzs = models.DecimalField(max_digits=12, decimal_places=0, default=50000, verbose_name="Gharama ya Mwezi (TZS)")
    
    auto_email_reminders = models.BooleanField(default=True, verbose_name="Tuma Vikumbusho Kiotomatiki kwa Email")
    last_reminder_sent = models.DateField(null=True, blank=True, verbose_name="Kikumbusho cha Mwisho Kutumwa")
    notes = models.TextField(blank=True, verbose_name="Maelezo ya Ndani (Admin Notes)")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Mteja / Kanisa / Ofisi"
        verbose_name_plural = "Wateja & Taasisi Zote"
        ordering = ['subscription_end']

    def __str__(self):
        return f"{self.name} ({self.app.name})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        if not self.api_key:
            self.api_key = f"lic_{secrets.token_hex(20)}"
        if not self.subscription_end:
            # Default to 30 days from start
            self.subscription_end = (self.subscription_start or timezone.now().date()) + timedelta(days=30)
        
        # Auto update status based on dates
        self.update_status_field()
        super().save(*args, **kwargs)

    @property
    def days_remaining(self):
        today = timezone.now().date()
        diff = (self.subscription_end - today).days
        return diff

    def update_status_field(self):
        if self.status == 'SUSPENDED':
            return
        days = self.days_remaining
        if days > 5:
            self.status = 'ACTIVE'
        elif 0 <= days <= 5:
            self.status = 'EXPIRING_SOON'
        elif -self.grace_period_days <= days < 0:
            self.status = 'GRACE_PERIOD'
        else:
            self.status = 'EXPIRED'

    @property
    def is_service_accessible(self):
        if self.status == 'SUSPENDED':
            return False
        today = timezone.now().date()
        cutoff_date = self.subscription_end + timedelta(days=self.grace_period_days)
        return today <= cutoff_date

    def extend_subscription(self, days):
        today = timezone.now().date()
        if self.subscription_end >= today:
            # Current subscription still active; push further
            self.subscription_end += timedelta(days=days)
        else:
            # Already expired; start fresh from today
            self.subscription_end = today + timedelta(days=days)
        self.update_status_field()
        self.save()


class PaymentTransaction(models.Model):
    """
    Kumbukumbu zote za malipo kupitia HarakaPay Mobile Money au Benki
    """
    STATUS_CHOICES = [
        ('PENDING', 'Inasubiri Malipo / PIN (Pending)'),
        ('COMPLETED', 'Imekamilika (Completed)'),
        ('FAILED', 'Imefeli (Failed)'),
        ('CANCELLED', 'Imesitishwa (Cancelled)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(ClientTenant, on_delete=models.CASCADE, related_name="payments", verbose_name="Mteja")
    order_id = models.CharField(max_length=100, unique=True, verbose_name="Order ID ya HarakaPay")
    plan = models.ForeignKey(PricingPlan, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Kifurushi")
    amount_tzs = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Kiasi Kilicholipwa (TZS)")
    phone_number = models.CharField(max_length=30, verbose_name="Namba ya Simu Iliyolipia")
    days_added = models.PositiveIntegerField(default=30, verbose_name="Siku Zilizoongezwa")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', verbose_name="Hali ya Malipo")
    gateway = models.CharField(max_length=50, default='harakapay', verbose_name="Gateway")
    gateway_response = models.JSONField(default=dict, blank=True, verbose_name="Jibu la Gateway API")
    receipt_sent = models.BooleanField(default=False, verbose_name="Resiti Imetumwa kwa Email")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Muamala wa Malipo (Transaction)"
        verbose_name_plural = "Miamala Yote ya Malipo"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.tenant.name} - TZS {self.amount_tzs:,.0f} ({self.status})"


class NotificationLog(models.Model):
    """
    Kumbukumbu ya barua pepe na ujumbe uliotumwa kwa mteja
    """
    CHANNEL_CHOICES = [
        ('RESEND', 'Resend API'),
        ('SMTP', 'Gmail SMTP Fallback'),
        ('SMS', 'SMS Gateway'),
    ]
    EVENT_CHOICES = [
        ('EXPIRY_7D', 'Kikumbusho cha Siku 7'),
        ('EXPIRY_3D', 'Kikumbusho cha Siku 3'),
        ('EXPIRY_1D', 'Kikumbusho cha Siku 1 (Kesho Inaisha)'),
        ('EXPIRED_LOCK', 'Taarifa ya Kufungwa kwa Mfumo'),
        ('PAYMENT_RECEIPT', 'Resiti ya Malipo'),
        ('MANUAL_REMINDER', 'Kikumbusho cha Mkononi na Admin'),
    ]

    tenant = models.ForeignKey(ClientTenant, on_delete=models.CASCADE, related_name="notifications")
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default='RESEND')
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    recipient = models.CharField(max_length=150)
    subject = models.CharField(max_length=255)
    success = models.BooleanField(default=True)
    response_details = models.TextField(blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kumbukumbu ya Ujumbe (Notification)"
        verbose_name_plural = "Kumbukumbu za Ujumbe"
        ordering = ['-sent_at']

    def __str__(self):
        return f"{self.tenant.name} - {self.get_event_type_display()} ({'Imefanikiwa' if self.success else 'Imeshindikana'})"
