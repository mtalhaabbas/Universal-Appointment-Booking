import datetime
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from rest_framework import views, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from apps.businesses.models import Business
from apps.services.models import Service
from apps.resources.models import Staff, Resource
from apps.bookings.models import Booking
from apps.bookings.serializers import (
    BookingSerializer,
    CreateBookingRequestSerializer,
    RescheduleBookingSerializer,
    CancelBookingSerializer,
    AvailabilityQuerySerializer
)
from apps.availability.services import AvailabilityService
from apps.bookings.services import BookingService, BookingConflictError, BookingPolicyError


class AvailabilityAPIView(views.APIView):
    """
    Computes real-time bookable slots for a service on a given date.
    Calculates business hours, staff shifts, breaks, buffer times, and room availability.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=['Availability'],
        parameters=[
            OpenApiParameter(name='service_id', description='UUID of the Service', required=True, type=str),
            OpenApiParameter(name='date', description='Target Date (YYYY-MM-DD)', required=True, type=str),
            OpenApiParameter(name='staff_id', description='Optional UUID of preferred staff member', required=False, type=str),
        ],
        responses={200: OpenApiResponse(description='List of available booking slots')}
    )
    def get(self, request, business_slug):
        business = get_object_or_404(Business, slug=business_slug, status='active')

        query_serializer = AvailabilityQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(query_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = query_serializer.validated_data
        service = get_object_or_404(Service, id=data['service_id'], business=business, is_active=True)

        staff = None
        if data.get('staff_id'):
            staff = get_object_or_404(Staff, id=data['staff_id'], business=business, is_active=True)

        availability_svc = AvailabilityService(business)
        slots = availability_svc.get_available_slots(
            service=service,
            target_date=data['date'],
            staff=staff
        )

        return Response({
            "business_slug": business.slug,
            "business_timezone": business.time_zone,
            "service_id": str(service.id),
            "service_name": service.name,
            "date": data['date'].isoformat(),
            "is_group_class": service.is_group_class,
            "slots_count": len(slots),
            "slots": slots
        })


class BookingViewSet(viewsets.ViewSet):
    """
    Unified booking creation, cancellation, and rescheduling API.
    Used identically by the Public Website, WhatsApp Bot, and Admin tools.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=['Bookings'],
        request=CreateBookingRequestSerializer,
        responses={
            201: BookingSerializer,
            200: BookingSerializer,
            400: OpenApiResponse(description='Validation error'),
            409: OpenApiResponse(description='Slot or resource conflict')
        }
    )
    def create(self, request, business_slug):
        business = get_object_or_404(Business, slug=business_slug, status='active')
        serializer = CreateBookingRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        service = get_object_or_404(Service, id=data['service_id'], business=business, is_active=True)

        staff = None
        if data.get('staff_id'):
            staff = get_object_or_404(Staff, id=data['staff_id'], business=business, is_active=True)

        booking_svc = BookingService(business)

        try:
            booking, created = booking_svc.create_booking(
                service=service,
                start_time=data.get('start_time'),
                occurrence_id=str(data['occurrence_id']) if data.get('occurrence_id') else None,
                customer_data=data['customer'],
                staff=staff,
                source_channel=data.get('source_channel', 'website'),
                notes=data.get('notes', ''),
                idempotency_key=data.get('idempotency_key'),
                actor=request.user if request.user.is_authenticated else None
            )
        except BookingConflictError as err:
            return Response({"error": "conflict", "detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except ValidationError as err:
            return Response({"error": "validation", "detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        resp_serializer = BookingSerializer(booking)
        http_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(resp_serializer.data, status=http_status)

    @extend_schema(tags=['Bookings'])
    def retrieve(self, request, business_slug, pk=None):
        business = get_object_or_404(Business, slug=business_slug)
        booking = get_object_or_404(
            Booking.objects.prefetch_related('assigned_resources', 'status_history'),
            business=business,
            id=pk
        )
        serializer = BookingSerializer(booking)
        return Response(serializer.data)

    @extend_schema(
        tags=['Bookings'],
        request=CancelBookingSerializer,
        responses={200: BookingSerializer}
    )
    @action(detail=True, methods=['post'])
    def cancel(self, request, business_slug, pk=None):
        business = get_object_or_404(Business, slug=business_slug)
        booking = get_object_or_404(Booking, business=business, id=pk)

        serializer = CancelBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data.get('reason', 'Cancelled by customer')

        # Allow staff to bypass cancellation deadline
        is_staff_override = request.user.is_authenticated and request.user.is_staff

        booking_svc = BookingService(business)
        try:
            booking = booking_svc.cancel_booking(
                booking=booking,
                reason=reason,
                actor=request.user if request.user.is_authenticated else None,
                bypass_policy=is_staff_override
            )
        except BookingPolicyError as err:
            return Response({"error": "policy_violation", "detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(BookingSerializer(booking).data)

    @extend_schema(
        tags=['Bookings'],
        request=RescheduleBookingSerializer,
        responses={200: BookingSerializer}
    )
    @action(detail=True, methods=['post'])
    def reschedule(self, request, business_slug, pk=None):
        business = get_object_or_404(Business, slug=business_slug)
        booking = get_object_or_404(Booking, business=business, id=pk)

        serializer = RescheduleBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_start_time = serializer.validated_data['new_start_time']

        is_staff_override = request.user.is_authenticated and request.user.is_staff

        booking_svc = BookingService(business)
        try:
            booking = booking_svc.reschedule_booking(
                booking=booking,
                new_start_time=new_start_time,
                actor=request.user if request.user.is_authenticated else None,
                bypass_policy=is_staff_override
            )
        except BookingConflictError as err:
            return Response({"error": "conflict", "detail": str(err)}, status=status.HTTP_409_CONFLICT)
        except BookingPolicyError as err:
            return Response({"error": "policy_violation", "detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(BookingSerializer(booking).data)

    @extend_schema(tags=['Bookings'])
    @action(detail=False, methods=['get'], url_path='ref/(?P<reference>[^/.]+)')
    def by_reference(self, request, business_slug, reference=None):
        business = get_object_or_404(Business, slug=business_slug)
        booking = get_object_or_404(
            Booking.objects.prefetch_related('assigned_resources', 'status_history'),
            business=business,
            booking_reference__iexact=reference
        )
        return Response(BookingSerializer(booking).data)


@extend_schema(tags=['Admin Bookings'])
class AdminBookingViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Tenant-scoped booking list for admin dashboards and reports.
    """
    serializer_class = BookingSerializer
    permission_classes = [AllowAny]  # Can be restricted to IsAuthenticated in production

    def get_queryset(self):
        qs = Booking.objects.select_related('business', 'customer', 'service', 'staff').prefetch_related('assigned_resources')
        business_slug = self.request.query_params.get('business')
        if business_slug:
            qs = qs.filter(business__slug=business_slug)

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        date_param = self.request.query_params.get('date')
        if date_param:
            try:
                target_date = datetime.date.fromisoformat(date_param)
                qs = qs.filter(start_time__date=target_date)
            except ValueError:
                pass

        return qs.order_by('-start_time')
