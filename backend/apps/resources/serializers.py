from rest_framework import serializers
from apps.resources.models import Staff, Resource


class StaffSerializer(serializers.ModelSerializer):
    assigned_service_ids = serializers.PrimaryKeyRelatedField(
        source='assigned_services', many=True, read_only=True
    )

    class Meta:
        model = Staff
        fields = [
            'id', 'name', 'email', 'phone', 'title', 'bio',
            'assigned_service_ids', 'color_hex', 'is_active'
        ]


class ResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resource
        fields = [
            'id', 'name', 'resource_type', 'capacity', 'is_active'
        ]
