import datetime
from rest_framework import serializers
from apps.bookings.models import Booking, BookingStatusHistory, ClassOccurrence
from apps.services.serializers import ServiceSerializer
from apps.resources.serializers import StaffSerializer, ResourceSerializer
from apps.customers.serializers import CustomerSerializer


class BookingStatusHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingStatusHistory
        fields = ['id', 'previous_status', 'new_status', 'actor_name', 'notes', 'timestamp']


class BookingSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(read_only=True)
    service = ServiceSerializer(read_only=True)
    staff = StaffSerializer(read_only=True)
    assigned_resources = ResourceSerializer(many=True, read_only=True)
    status_history = BookingStatusHistorySerializer(many=True, read_only=True)
    business_name = serializers.CharField(source='business.name', read_only=True)
    business_slug = serializers.CharField(source='business.slug', read_only=True)
    business_timezone = serializers.CharField(source='business.time_zone', read_only=True)

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_reference', 'business', 'business_name', 'business_slug',
            'business_timezone', 'customer', 'service', 'staff',
            'assigned_resources', 'start_time', 'end_time', 'status',
            'source_channel', 'notes', 'idempotency_key', 'created_at',
            'status_history'
        ]


class CustomerInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)


class CreateBookingRequestSerializer(serializers.Serializer):
    service_id = serializers.UUIDField(required=True)
    start_time = serializers.DateTimeField(required=False)
    occurrence_id = serializers.UUIDField(required=False, allow_null=True)
    staff_id = serializers.UUIDField(required=False, allow_null=True)
    customer = CustomerInputSerializer(required=True)
    source_channel = serializers.ChoiceField(
        choices=['website', 'whatsapp', 'admin', 'api'],
        default='website'
    )
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    idempotency_key = serializers.CharField(max_length=128, required=False, allow_blank=True, default=None)

    def validate(self, data):
        if not data.get('occurrence_id') and not data.get('start_time'):
            raise serializers.ValidationError("Either 'start_time' or 'occurrence_id' must be provided.")
        return data


class RescheduleBookingSerializer(serializers.Serializer):
    new_start_time = serializers.DateTimeField(required=True)


class CancelBookingSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default='Cancelled by customer')


class AvailabilityQuerySerializer(serializers.Serializer):
    service_id = serializers.UUIDField(required=True)
    date = serializers.DateField(required=True)
    staff_id = serializers.UUIDField(required=False, allow_null=True)
    branch_id = serializers.UUIDField(required=False, allow_null=True)


class ClassOccurrenceSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    instructor_name = serializers.CharField(source='instructor.name', read_only=True)
    resource_name = serializers.CharField(source='resource.name', read_only=True)
    remaining_spots = serializers.IntegerField(read_only=True)

    class Meta:
        model = ClassOccurrence
        fields = [
            'id', 'service', 'service_name', 'instructor', 'instructor_name',
            'resource', 'resource_name', 'start_time', 'end_time',
            'capacity', 'booked_count', 'remaining_spots', 'status'
        ]
