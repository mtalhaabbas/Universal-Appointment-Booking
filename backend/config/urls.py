from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

from apps.businesses.views import BusinessTypeViewSet, BusinessViewSet
from apps.bookings.views import AvailabilityAPIView, BookingViewSet, AdminBookingViewSet
from apps.integrations.views import WhatsAppWebhookView
from apps.businesses.web_views import (
    LandingPageView,
    PublicBookingView,
    PublicManageBookingView,
    DashboardOverviewView,
    DashboardSetupWizardView,
    DashboardServicesView,
    DashboardStaffView,
    DashboardResourcesView,
    DashboardHoursView,
    DashboardCalendarView,
    DashboardBookingsView,
    DashboardCustomersView,
    DashboardNotificationsView,
    DashboardIntegrationsView,
    DashboardSettingsView,
)

router = DefaultRouter()
router.register(r'business-types', BusinessTypeViewSet, basename='businesstype')
router.register(r'businesses', BusinessViewSet, basename='business')
router.register(r'admin/bookings', AdminBookingViewSet, basename='admin-bookings')

urlpatterns = [
    # Django Admin
    path('django-admin/', admin.site.urls),

    # OpenAPI Schema & Interactive Docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # DRF Router API endpoints
    path('api/v1/', include(router.urls)),

    # Custom Business Availability & Booking API Endpoints
    path('api/v1/businesses/<slug:business_slug>/availability/', AvailabilityAPIView.as_view(), name='api-availability'),
    path('api/v1/businesses/<slug:business_slug>/bookings/', BookingViewSet.as_view({'post': 'create'}), name='api-booking-create'),
    path('api/v1/businesses/<slug:business_slug>/bookings/<uuid:pk>/', BookingViewSet.as_view({'get': 'retrieve'}), name='api-booking-detail'),
    path('api/v1/businesses/<slug:business_slug>/bookings/<uuid:pk>/cancel/', BookingViewSet.as_view({'post': 'cancel'}), name='api-booking-cancel'),
    path('api/v1/businesses/<slug:business_slug>/bookings/<uuid:pk>/reschedule/', BookingViewSet.as_view({'post': 'reschedule'}), name='api-booking-reschedule'),
    path('api/v1/businesses/<slug:business_slug>/bookings/ref/<str:reference>/', BookingViewSet.as_view({'get': 'by_reference'}), name='api-booking-by-ref'),

    # WhatsApp Cloud API Webhook
    path('api/v1/integrations/whatsapp/webhook/', WhatsAppWebhookView.as_view(), name='whatsapp-webhook'),

    # ------------------------------------------------------------------
    # WEB APPLICATION & TAILWIND ADMIN UI
    # ------------------------------------------------------------------
    path('', LandingPageView.as_view(), name='landing'),
    path('book/<slug:business_slug>/', PublicBookingView.as_view(), name='public-booking'),
    path('book/<slug:business_slug>/manage/<str:reference>/', PublicManageBookingView.as_view(), name='public-manage-booking'),

    # Admin Dashboard Pages
    path('dashboard/', DashboardOverviewView.as_view(), name='admin-dashboard-default'),
    path('dashboard/<slug:business_slug>/', DashboardOverviewView.as_view(), name='admin-dashboard'),
    path('dashboard/<slug:business_slug>/setup/', DashboardSetupWizardView.as_view(), name='admin-setup-wizard'),
    path('dashboard/<slug:business_slug>/services/', DashboardServicesView.as_view(), name='admin-services'),
    path('dashboard/<slug:business_slug>/staff/', DashboardStaffView.as_view(), name='admin-staff'),
    path('dashboard/<slug:business_slug>/resources/', DashboardResourcesView.as_view(), name='admin-resources'),
    path('dashboard/<slug:business_slug>/hours/', DashboardHoursView.as_view(), name='admin-hours'),
    path('dashboard/<slug:business_slug>/calendar/', DashboardCalendarView.as_view(), name='admin-calendar'),
    path('dashboard/<slug:business_slug>/bookings/', DashboardBookingsView.as_view(), name='admin-bookings'),
    path('dashboard/<slug:business_slug>/customers/', DashboardCustomersView.as_view(), name='admin-customers'),
    path('dashboard/<slug:business_slug>/notifications/', DashboardNotificationsView.as_view(), name='admin-notifications'),
    path('dashboard/<slug:business_slug>/integrations/', DashboardIntegrationsView.as_view(), name='admin-integrations'),
    path('dashboard/<slug:business_slug>/settings/', DashboardSettingsView.as_view(), name='admin-settings'),
]
