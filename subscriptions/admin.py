from django.contrib import admin
from .models import SystemApp, PricingPlan, ClientTenant, PaymentTransaction, NotificationLog


@admin.register(SystemApp)
class SystemAppAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_active', 'created_at')
    prepopulated_fields = {'code': ('name',)}
    search_fields = ('name', 'code')


@admin.register(PricingPlan)
class PricingPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'app', 'duration_days', 'price_tzs', 'is_popular', 'is_active')
    list_filter = ('app', 'is_active', 'duration_days')
    search_fields = ('name', 'app__name')


@admin.register(ClientTenant)
class ClientTenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'app', 'status', 'subscription_end', 'days_remaining_display', 'phone', 'email')
    list_filter = ('status', 'app', 'auto_email_reminders')
    search_fields = ('name', 'contact_person', 'phone', 'email', 'slug', 'api_key')
    readonly_fields = ('api_key', 'created_at', 'updated_at')
    prepopulated_fields = {'slug': ('name',)}

    def days_remaining_display(self, obj):
        days = obj.days_remaining
        if days > 5:
            return f"{days} siku (Salama)"
        elif days >= 0:
            return f"{days} siku (Inakaribia kuisha!)"
        else:
            return f"Imeisha siku {abs(days)} zilizopita"
    days_remaining_display.short_description = "Siku Zilizobaki"


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'tenant', 'amount_tzs', 'phone_number', 'days_added', 'status', 'created_at', 'receipt_sent')
    list_filter = ('status', 'gateway', 'receipt_sent')
    search_fields = ('order_id', 'tenant__name', 'phone_number')
    readonly_fields = ('created_at', 'completed_at', 'gateway_response')


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'event_type', 'channel', 'recipient', 'success', 'sent_at')
    list_filter = ('channel', 'event_type', 'success')
    search_fields = ('tenant__name', 'recipient', 'subject')
    readonly_fields = ('sent_at',)
