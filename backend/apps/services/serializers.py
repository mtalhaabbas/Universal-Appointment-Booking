from rest_framework import serializers
from apps.services.models import Service, ServiceResourceRequirement


class ServiceResourceRequirementSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceResourceRequirement
        fields = ['id', 'resource_type', 'quantity']


class ServiceSerializer(serializers.ModelSerializer):
    resource_requirements = ServiceResourceRequirementSerializer(many=True, read_only=True)
    is_group_class = serializers.BooleanField(read_only=True)

    class Meta:
        model = Service
        fields = [
            'id', 'name', 'slug', 'description', 'duration_minutes',
            'price', 'buffer_time_minutes', 'capacity', 'color_hex',
            'booking_policies', 'is_group_class', 'is_active',
            'resource_requirements'
        ]
