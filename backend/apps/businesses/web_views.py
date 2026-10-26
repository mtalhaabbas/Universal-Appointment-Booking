import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q
from django.views import View

from apps.businesses.models import Business, BusinessType, Branch, BusinessHours, AuditLog
from apps.services.models import Service, ServiceResourceRequirement
from apps.resources.models import Staff, Resource
from apps.availability.models import StaffAvailability, AvailabilityBreak, AvailabilityException
from apps.customers.models import Customer
from apps.bookings.models import Booking, BookingStatusHistory, ClassOccurrence
from apps.bookings.services import BookingService, BookingConflictError, BookingPolicyError
from apps.notifications.models import NotificationTemplate, NotificationDelivery, OutboxEvent
from apps.integrations.models import CalendarConnection, CalendarEventMapping, WebhookLog


class LandingPageView(View):
    def get(self, request):
        businesses = Business.objects.filter(status='active').select_related('business_type').prefetch_related('services')
        return render(request, 'landing.html', {'businesses': businesses})


class PublicBookingView(View):
    def get(self, request, business_slug):
        business = get_object_or_404(Business, slug=business_slug, status='active')
        services = Service.objects.filter(business=business, is_active=True).prefetch_related('resource_requirements')
        staff_list = Staff.objects.filter(business=business, is_active=True)
        return render(request, 'booking/index.html', {
            'business': business,
            'services': services,
            'staff_list': staff_list,
        })


class PublicManageBookingView(View):
    def get(self, request, business_slug, reference):
        business = get_object_or_404(Business, slug=business_slug)
        booking = get_object_or_404(
            Booking.objects.select_related('service', 'staff', 'customer').prefetch_related('assigned_resources', 'status_history'),
            business=business,
            booking_reference__iexact=reference
        )
        return render(request, 'booking/manage.html', {
            'business': business,
            'booking': booking,
        })

    def post(self, request, business_slug, reference):
        business = get_object_or_404(Business, slug=business_slug)
        booking = get_object_or_404(Booking, business=business, booking_reference__iexact=reference)
        action = request.POST.get('action')
        booking_svc = BookingService(business)

        if action == 'cancel':
            reason = request.POST.get('reason', 'Cancelled by customer via self-service portal')
            try:
                booking_svc.cancel_booking(booking, reason=reason, bypass_policy=False)
                messages.success(request, f"Your appointment {reference} has been successfully cancelled.")
            except BookingPolicyError as e:
                messages.error(request, str(e))
            return redirect('public-manage-booking', business_slug=business.slug, reference=reference)

        elif action == 'reschedule':
            new_date = request.POST.get('new_date')
            new_time = request.POST.get('new_time')
            if not new_date or not new_time:
                messages.error(request, "Please choose both a new date and a new time.")
                return redirect('public-manage-booking', business_slug=business.slug, reference=reference)

            try:
                dt_str = f"{new_date} {new_time}"
                tz = ZoneInfo(business.time_zone)
                local_dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
                booking_svc.reschedule_booking(booking, new_start_time=local_dt, bypass_policy=False)
                messages.success(request, f"Your appointment {reference} has been rescheduled to {dt_str}.")
            except Exception as e:
                messages.error(request, f"Reschedule failed: {str(e)}")
            return redirect('public-manage-booking', business_slug=business.slug, reference=reference)

        return redirect('public-manage-booking', business_slug=business.slug, reference=reference)


# -------------------------------------------------------------
# ADMIN DASHBOARD VIEWS
# -------------------------------------------------------------

def get_admin_context(request, business_slug=None):
    all_businesses = Business.objects.filter(status='active').order_by('name')
    if business_slug:
        current_business = get_object_or_404(Business, slug=business_slug)
    else:
        current_business = all_businesses.first()
        if not current_business:
            # Fallback if no business exists
            return None, None
    return current_business, all_businesses


class DashboardOverviewView(View):
    def get(self, request, business_slug=None):
        business, all_businesses = get_admin_context(request, business_slug)
        if not business:
            return redirect('landing')

        now_utc = timezone.now()
        try:
            biz_tz = ZoneInfo(business.time_zone)
        except Exception:
            biz_tz = ZoneInfo("UTC")
        today_local = now_utc.astimezone(biz_tz).date()

        day_start_utc = datetime.datetime.combine(today_local, datetime.time.min, tzinfo=biz_tz).astimezone(ZoneInfo("UTC"))
        day_end_utc = datetime.datetime.combine(today_local, datetime.time.max, tzinfo=biz_tz).astimezone(ZoneInfo("UTC"))

        # Real DB KPI metrics
        today_appointments = Booking.objects.filter(
            business=business,
            start_time__gte=day_start_utc,
            start_time__lte=day_end_utc
        ).count()

        upcoming_bookings = Booking.objects.filter(
            business=business,
            status__in=['pending', 'confirmed'],
            start_time__gt=now_utc
        ).count()

        completed_bookings = Booking.objects.filter(
            business=business,
            status='completed'
        ).count()

        cancelled_bookings = Booking.objects.filter(
            business=business,
            status='cancelled'
        ).count()

        # Popular services
        popular_services = Service.objects.filter(business=business).annotate(
            booking_count=Count('bookings')
        ).order_by('-booking_count')[:5]

        # Recent bookings
        recent_bookings = Booking.objects.filter(
            business=business
        ).select_related('customer', 'service', 'staff').order_by('-created_at')[:10]

        # Total resources
        resources_count = Resource.objects.filter(business=business, is_active=True).count()
        staff_count = Staff.objects.filter(business=business, is_active=True).count()

        return render(request, 'admin/dashboard.html', {
            'business': business,
            'all_businesses': all_businesses,
            'today_appointments': today_appointments,
            'upcoming_bookings': upcoming_bookings,
            'completed_bookings': completed_bookings,
            'cancelled_bookings': cancelled_bookings,
            'popular_services': popular_services,
            'recent_bookings': recent_bookings,
            'resources_count': resources_count,
            'staff_count': staff_count,
            'today_local': today_local,
        })


class DashboardSetupWizardView(View):
    """
    8-step business setup wizard allowing business owners to configure
    a new industry vertical without modifying application source code!
    """
    def get(self, request, business_slug=None):
        business, all_businesses = get_admin_context(request, business_slug)
        business_types = BusinessType.objects.all()
        return render(request, 'admin/setup_wizard.html', {
            'business': business,
            'all_businesses': all_businesses,
            'business_types': business_types,
        })

    def post(self, request, business_slug=None):
        name = request.POST.get('business_name')
        type_slug = request.POST.get('business_type')
        time_zone = request.POST.get('time_zone', 'UTC')
        email = request.POST.get('contact_email', 'admin@example.local')
        phone = request.POST.get('contact_phone', '')
        tagline = request.POST.get('tagline', '')

        # Service details
        service_name = request.POST.get('service_name')
        duration = int(request.POST.get('service_duration', 30))
        buffer_time = int(request.POST.get('service_buffer', 10))
        capacity = int(request.POST.get('service_capacity', 1))
        price = Decimal(request.POST.get('service_price', '50.00'))

        # Staff & Resource details
        staff_name = request.POST.get('staff_name')
        staff_title = request.POST.get('staff_title', 'Staff Specialist')
        resource_name = request.POST.get('resource_name')
        resource_type = request.POST.get('resource_type', 'Standard Room')

        btype = get_object_or_404(BusinessType, slug=type_slug)

        # Create new Business
        new_business = Business.objects.create(
            name=name,
            business_type=btype,
            time_zone=time_zone,
            contact_email=email,
            contact_phone=phone,
            tagline=tagline,
            status='active',
            settings={
                'min_notice_hours': 1,
                'max_advance_days': 30,
                'slot_interval_minutes': 15,
                'cancellation_deadline_hours': 24,
                'confirmation_mode': 'auto',
            }
        )

        # Create Business Hours (Mon-Sat 09:00 - 18:00, Sun closed)
        for day in range(7):
            is_closed = (day == 6)
            BusinessHours.objects.create(
                business=new_business,
                day_of_week=day,
                open_time=datetime.time(9, 0) if not is_closed else None,
                close_time=datetime.time(18, 0) if not is_closed else None,
                is_closed=is_closed
            )

        # Create Initial Service
        if service_name:
            svc = Service.objects.create(
                business=new_business,
                name=service_name,
                duration_minutes=duration,
                buffer_time_minutes=buffer_time,
                capacity=capacity,
                price=price,
                booking_policies={'requires_staff': True, 'requires_resource': bool(resource_name)}
            )
            if resource_type:
                ServiceResourceRequirement.objects.create(
                    service=svc,
                    resource_type=resource_type,
                    quantity=1
                )

        # Create Staff
        if staff_name:
            st = Staff.objects.create(
                business=new_business,
                name=staff_name,
                title=staff_title,
                is_active=True
            )
            if service_name:
                st.assigned_services.add(svc)
            for d in range(6):
                StaffAvailability.objects.create(
                    staff=st,
                    day_of_week=d,
                    start_time=datetime.time(9, 0),
                    end_time=datetime.time(18, 0)
                )

        # Create Resource
        if resource_name:
            Resource.objects.create(
                business=new_business,
                name=resource_name,
                resource_type=resource_type,
                capacity=1,
                is_active=True
            )

        # Default Mock Calendar Connection
        CalendarConnection.objects.create(
            business=new_business,
            calendar_provider='mock',
            calendar_id=f"{new_business.slug}@mock.universalbooking.local",
            is_active=True
        )

        messages.success(request, f"Business '{name}' configured successfully via Setup Wizard!")
        return redirect('admin-dashboard', business_slug=new_business.slug)


class DashboardServicesView(View):
    def get(self, request, business_slug):
        business, all_businesses = get_admin_context(request, business_slug)
        services = Service.objects.filter(business=business).prefetch_related('resource_requirements', 'qualified_staff')
        return render(request, 'admin/services.html', {
            'business': business,
            'all_businesses': all_businesses,
            'services': services,
        })

    def post(self, request, business_slug):
        business = get_object_or_404(Business, slug=business_slug)
        action = request.POST.get('action')

        if action == 'create':
            name = request.POST.get('name')
            desc = request.POST.get('description', '')
            duration = int(request.POST.get('duration_minutes', 30))
            buffer_time = int(request.POST.get('buffer_time_minutes', 0))
            capacity = int(request.POST.get('capacity', 1))
            price = Decimal(request.POST.get('price', '0.00'))
            color = request.POST.get('color_hex', '#2563eb')
            res_type = request.POST.get('required_resource_type', '').strip()

            svc = Service.objects.create(
                business=business,
                name=name,
                description=desc,
                duration_minutes=duration,
                buffer_time_minutes=buffer_time,
                capacity=capacity,
                price=price,
                color_hex=color,
                booking_policies={'requires_staff': True, 'requires_resource': bool(res_type)}
            )
            if res_type:
                ServiceResourceRequirement.objects.create(
                    service=svc,
                    resource_type=res_type,
                    quantity=1
                )
            messages.success(request, f"Service '{name}' created successfully.")

        elif action == 'delete':
            service_id = request.POST.get('service_id')
            Service.objects.filter(business=business, id=service_id).delete()
            messages.success(request, "Service deleted.")

        return redirect('admin-services', business_slug=business.slug)


class DashboardStaffView(View):
    def get(self, request, business_slug):
        business, all_businesses = get_admin_context(request, business_slug)
        staff_members = Staff.objects.filter(business=business).prefetch_related('assigned_services', 'working_hours')
        services = Service.objects.filter(business=business, is_active=True)
        return render(request, 'admin/staff.html', {
            'business': business,
            'all_businesses': all_businesses,
            'staff_members': staff_members,
            'services': services,
        })

    def post(self, request, business_slug):
        business = get_object_or_404(Business, slug=business_slug)
        action = request.POST.get('action')

        if action == 'create':
            name = request.POST.get('name')
            email = request.POST.get('email', '')
            phone = request.POST.get('phone', '')
            title = request.POST.get('title', '')
            bio = request.POST.get('bio', '')
            service_ids = request.POST.getlist('assigned_services')

            st = Staff.objects.create(
                business=business,
                name=name,
                email=email,
                phone=phone,
                title=title,
                bio=bio,
                is_active=True
            )
            if service_ids:
                st.assigned_services.set(service_ids)

            # Default shift 09:00 - 17:00 Mon-Fri
            for d in range(5):
                StaffAvailability.objects.create(
                    staff=st,
                    day_of_week=d,
                    start_time=datetime.time(9, 0),
                    end_time=datetime.time(17, 0)
                )

            messages.success(request, f"Staff member '{name}' added successfully.")

        elif action == 'delete':
            staff_id = request.POST.get('staff_id')
            Staff.objects.filter(business=business, id=staff_id).delete()
            messages.success(request, "Staff member removed.")

        return redirect('admin-staff', business_slug=business.slug)


class DashboardResourcesView(View):
    def get(self, request, business_slug):
        business, all_businesses = get_admin_context(request, business_slug)
        resources = Resource.objects.filter(business=business)
        return render(request, 'admin/resources.html', {
            'business': business,
            'all_businesses': all_businesses,
            'resources': resources,
        })

    def post(self, request, business_slug):
        business = get_object_or_404(Business, slug=business_slug)
        action = request.POST.get('action')

        if action == 'create':
            name = request.POST.get('name')
            res_type = request.POST.get('resource_type')
            capacity = int(request.POST.get('capacity', 1))

            Resource.objects.create(
                business=business,
                name=name,
                resource_type=res_type,
                capacity=capacity,
                is_active=True
            )
            messages.success(request, f"Resource '{name}' created successfully.")

        elif action == 'delete':
            resource_id = request.POST.get('resource_id')
            Resource.objects.filter(business=business, id=resource_id).delete()
            messages.success(request, "Resource removed.")

        return redirect('admin-resources', business_slug=business.slug)


class DashboardHoursView(View):
    def get(self, request, business_slug):
        business, all_businesses = get_admin_context(request, business_slug)
        hours = BusinessHours.objects.filter(business=business).order_by('day_of_week')
        exceptions = AvailabilityException.objects.filter(business=business).order_by('start_datetime')
        return render(request, 'admin/hours.html', {
            'business': business,
            'all_businesses': all_businesses,
            'hours': hours,
            'exceptions': exceptions,
        })

    def post(self, request, business_slug):
        business = get_object_or_404(Business, slug=business_slug)
        action = request.POST.get('action')

        if action == 'update_hours':
            for d in range(7):
                is_closed = request.POST.get(f'closed_{d}') == 'on'
                open_str = request.POST.get(f'open_{d}')
                close_str = request.POST.get(f'close_{d}')
                open_t = datetime.datetime.strptime(open_str, "%H:%M").time() if open_str and not is_closed else None
                close_t = datetime.datetime.strptime(close_str, "%H:%M").time() if close_str and not is_closed else None

                BusinessHours.objects.update_or_create(
                    business=business,
                    branch=None,
                    day_of_week=d,
                    defaults={'open_time': open_t, 'close_time': close_t, 'is_closed': is_closed}
                )
            messages.success(request, "Operating hours updated successfully.")

        elif action == 'create_exception':
            notes = request.POST.get('notes', 'Holiday / Special event')
            exc_type = request.POST.get('exception_type', 'holiday')
            start_date_str = request.POST.get('start_date')
            end_date_str = request.POST.get('end_date')

            tz = ZoneInfo(business.time_zone)
            start_dt = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").replace(hour=0, minute=0, tzinfo=tz).astimezone(ZoneInfo("UTC"))
            end_dt = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=tz).astimezone(ZoneInfo("UTC"))

            AvailabilityException.objects.create(
                business=business,
                exception_type=exc_type,
                start_datetime=start_dt,
                end_datetime=end_dt,
                is_available=False,
                notes=notes
            )
            messages.success(request, f"Availability exception recorded.")

        return redirect('admin-hours', business_slug=business.slug)


class DashboardCalendarView(View):
    def get(self, request, business_slug):
        business, all_businesses = get_admin_context(request, business_slug)
        now_utc = timezone.now()
        start_of_week = now_utc - datetime.timedelta(days=now_utc.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=7)

        bookings = Booking.objects.filter(
            business=business,
            start_time__gte=start_of_week - datetime.timedelta(days=7),
            start_time__lte=end_of_week + datetime.timedelta(days=14)
        ).select_related('customer', 'service', 'staff').order_by('start_time')

        return render(request, 'admin/calendar.html', {
            'business': business,
            'all_businesses': all_businesses,
            'bookings': bookings,
            'business_timezone': business.time_zone,
        })


class DashboardBookingsView(View):
    def get(self, request, business_slug):
        business, all_businesses = get_admin_context(request, business_slug)
        status_filter = request.GET.get('status', '')
        search_query = request.GET.get('q', '').strip()

        bookings_qs = Booking.objects.filter(business=business).select_related('customer', 'service', 'staff')

        if status_filter:
            bookings_qs = bookings_qs.filter(status=status_filter)

        if search_query:
            bookings_qs = bookings_qs.filter(
                Q(booking_reference__icontains=search_query) |
                Q(customer__name__icontains=search_query) |
                Q(customer__email__icontains=search_query) |
                Q(service__name__icontains=search_query)
            )

        bookings = bookings_qs.order_by('-start_time')[:100]

        return render(request, 'admin/bookings.html', {
            'business': business,
            'all_businesses': all_businesses,
            'bookings': bookings,
            'status_filter': status_filter,
            'search_query': search_query,
        })

    def post(self, request, business_slug):
        business = get_object_or_404(Business, slug=business_slug)
        booking_id = request.POST.get('booking_id')
        action = request.POST.get('action')
        booking = get_object_or_404(Booking, business=business, id=booking_id)
        booking_svc = BookingService(business)

        if action == 'cancel':
            reason = request.POST.get('reason', 'Cancelled by administrator')
            booking_svc.cancel_booking(booking, reason=reason, actor=request.user if request.user.is_authenticated else None, bypass_policy=True)
            messages.success(request, f"Booking {booking.booking_reference} cancelled.")

        elif action == 'complete':
            prev = booking.status
            booking.status = 'completed'
            booking.save(update_fields=['status', 'updated_at'])
            BookingStatusHistory.objects.create(
                booking=booking,
                previous_status=prev,
                new_status='completed',
                actor_name='Admin',
                notes='Marked completed'
            )
            messages.success(request, f"Booking {booking.booking_reference} marked as completed.")

        return redirect('admin-bookings', business_slug=business.slug)


class DashboardCustomersView(View):
    def get(self, request, business_slug):
        business, all_businesses = get_admin_context(request, business_slug)
        q = request.GET.get('q', '').strip()
        customers_qs = Customer.objects.filter(business=business).annotate(
            booking_count=Count('bookings')
        )
        if q:
            customers_qs = customers_qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))

        customers = customers_qs.order_by('-created_at')[:100]

        return render(request, 'admin/customers.html', {
            'business': business,
            'all_businesses': all_businesses,
            'customers': customers,
            'search_query': q,
        })


class DashboardNotificationsView(View):
    def get(self, request, business_slug):
        business, all_businesses = get_admin_context(request, business_slug)
        templates = NotificationTemplate.objects.filter(business=business).order_by('event_type', 'channel')
        outbox_events = OutboxEvent.objects.filter(business=business).order_by('-created_at')[:30]
        deliveries = NotificationDelivery.objects.filter(business=business).order_by('-created_at')[:30]

        return render(request, 'admin/notifications.html', {
            'business': business,
            'all_businesses': all_businesses,
            'templates': templates,
            'outbox_events': outbox_events,
            'deliveries': deliveries,
        })

    def post(self, request, business_slug):
        business = get_object_or_404(Business, slug=business_slug)
        template_id = request.POST.get('template_id')
        template_body = request.POST.get('template_body')
        subject = request.POST.get('subject', '')

        tmpl = get_object_or_404(NotificationTemplate, id=template_id, business=business)
        tmpl.template_body = template_body
        tmpl.subject = subject
        tmpl.save(update_fields=['template_body', 'subject', 'updated_at'])

        messages.success(request, f"Template for '{tmpl.event_type}' ({tmpl.channel}) saved.")
        return redirect('admin-notifications', business_slug=business.slug)


class DashboardIntegrationsView(View):
    def get(self, request, business_slug):
        business, all_businesses = get_admin_context(request, business_slug)
        calendar_conn = CalendarConnection.objects.filter(business=business).first()
        webhook_logs = WebhookLog.objects.all().order_by('-created_at')[:15]

        return render(request, 'admin/integrations.html', {
            'business': business,
            'all_businesses': all_businesses,
            'calendar_conn': calendar_conn,
            'webhook_logs': webhook_logs,
        })


class DashboardSettingsView(View):
    def get(self, request, business_slug):
        business, all_businesses = get_admin_context(request, business_slug)
        return render(request, 'admin/settings.html', {
            'business': business,
            'all_businesses': all_businesses,
        })

    def post(self, request, business_slug):
        business = get_object_or_404(Business, slug=business_slug)
        business.name = request.POST.get('name', business.name)
        business.tagline = request.POST.get('tagline', business.tagline)
        business.description = request.POST.get('description', business.description)
        business.time_zone = request.POST.get('time_zone', business.time_zone)
        business.contact_email = request.POST.get('contact_email', business.contact_email)
        business.contact_phone = request.POST.get('contact_phone', business.contact_phone)
        business.address = request.POST.get('address', business.address)

        # Settings
        business.settings['min_notice_hours'] = int(request.POST.get('min_notice_hours', 1))
        business.settings['max_advance_days'] = int(request.POST.get('max_advance_days', 30))
        business.settings['slot_interval_minutes'] = int(request.POST.get('slot_interval_minutes', 15))
        business.settings['cancellation_deadline_hours'] = int(request.POST.get('cancellation_deadline_hours', 24))
        business.settings['confirmation_mode'] = request.POST.get('confirmation_mode', 'auto')

        business.save()
        messages.success(request, "Business settings updated successfully.")
        return redirect('admin-settings', business_slug=business.slug)
