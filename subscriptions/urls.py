from django.urls import path
from . import views

urlpatterns = [
    # Dashboard & Admin Management
    path('', views.dashboard_view, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    path('tenants/add/', views.add_tenant_view, name='add_tenant'),
    path('tenants/<uuid:tenant_id>/', views.tenant_detail_view, name='tenant_detail'),
    path('tenants/<uuid:tenant_id>/edit/', views.edit_tenant_view, name='edit_tenant'),
    path('tenants/<uuid:tenant_id>/extend/', views.manual_extend_view, name='manual_extend'),
    path('tenants/<uuid:tenant_id>/remind/', views.send_manual_reminder_view, name='send_reminder'),
    
    path('transactions/', views.transactions_list_view, name='transactions'),
    path('apps/', views.apps_list_view, name='apps_list'),
    path('apps/<int:app_id>/plans/add/', views.add_plan_view, name='add_plan'),

    # Public Client Self-Service Pay Portal
    path('pay/<slug:slug>/', views.client_pay_portal_view, name='client_pay'),

    # HarakaPay Mobile Money API & Webhook
    path('api/payment/initiate/', views.initiate_payment_api, name='api_payment_initiate'),
    path('api/payment/status/<str:order_id>/', views.check_order_status_api, name='api_payment_status'),
    path('api/payment/harakapay/webhook/', views.harakapay_webhook_view, name='harakapay_webhook'),

    # Remote License Verification for Church & Office software
    path('api/v1/license/verify/', views.verify_license_api, name='verify_license_api'),
]
