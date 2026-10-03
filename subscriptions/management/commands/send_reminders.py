from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from subscriptions.models import ClientTenant
from subscriptions.services.email_service import send_subscription_reminder_email


class Command(BaseCommand):
    help = "Inatuma vikumbusho vya barua pepe (Email) kwa wateja ambao tarehe yao ya kuisha inakaribia (Siku 7, 3, 1, au leo)"

    def handle(self, *args, **options):
        today = timezone.now().date()
        self.stdout.write(self.style.NOTICE(f"--- Kuanza ukaguzi wa leseni kwa tarehe {today.strftime('%d/%m/%Y')} ---"))

        tenants = ClientTenant.objects.filter(
            auto_email_reminders=True
        ).exclude(status='SUSPENDED')

        sent_count = 0
        for tenant in tenants:
            tenant.update_status_field()
            tenant.save(update_fields=['status'])

            days = tenant.days_remaining

            # Send reminders at 7, 3, 1, 0, or -1 (first day of lock)
            if days in [7, 3, 1, 0, -1]:
                # Don't send more than once per day
                if tenant.last_reminder_sent == today:
                    continue

                self.stdout.write(f"Inatuma kikumbusho kwa {tenant.name} ({tenant.email}) - Siku zilizobaki: {days}...")
                res = send_subscription_reminder_email(tenant, days)

                if res.get('success'):
                    tenant.last_reminder_sent = today
                    tenant.save(update_fields=['last_reminder_sent'])
                    sent_count += 1
                    self.stdout.write(self.style.SUCCESS(f"  -> Imefanikiwa kupitia {res.get('engine', 'Email')}"))
                else:
                    self.stdout.write(self.style.ERROR(f"  -> Imeshindikana: {res.get('error')}"))

        self.stdout.write(self.style.SUCCESS(f"Ukaguzi umekamilika. Vikumbusho {sent_count} vimetumwa."))
