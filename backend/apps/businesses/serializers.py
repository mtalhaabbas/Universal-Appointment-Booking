from rest_framework import serializers
from apps.businesses.models import BusinessType, Business, Branch, BusinessHours


class BusinessTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessType
        fields = ['id', 'name', 'slug', 'description', 'icon', 'default_settings']


class BusinessHoursSerializer(serializers.ModelSerializer):
    day_name = serializers.CharField(source='get_day_of_week_display', read_only=True)

    class Meta:
        model = BusinessHours
        fields = ['id', 'day_of_week', 'day_name', 'open_time', 'close_time', 'is_closed']


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ['id', 'name', 'slug', 'address', 'phone', 'time_zone', 'is_active']


class BusinessSerializer(serializers.ModelSerializer):
    business_type_name = serializers.CharField(source='business_type.name', read_only=True)
    business_type_slug = serializers.CharField(source='business_type.slug', read_only=True)
    hours = BusinessHoursSerializer(source='business_hours', many=True, read_only=True)
    branches = BranchSerializer(many=True, read_only=True)

    class Meta:
        model = Business
        fields = [
            'id', 'name', 'slug', 'tagline', 'description', 'business_type',
            'business_type_name', 'business_type_slug', 'time_zone',
            'contact_email', 'contact_phone', 'address', 'status',
            'settings', 'hours', 'branches', 'created_at'
        ]
