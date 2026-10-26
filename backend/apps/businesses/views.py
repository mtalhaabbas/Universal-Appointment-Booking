from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from drf_spectacular.utils import extend_schema, extend_schema_view

from apps.businesses.models import BusinessType, Business
from apps.businesses.serializers import BusinessTypeSerializer, BusinessSerializer
from apps.services.models import Service
from apps.services.serializers import ServiceSerializer
from apps.resources.models import Staff, Resource
from apps.resources.serializers import StaffSerializer, ResourceSerializer
from apps.bookings.models import ClassOccurrence
from apps.bookings.serializers import ClassOccurrenceSerializer


@extend_schema(tags=['Business Types'])
class BusinessTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BusinessType.objects.all()
    serializer_class = BusinessTypeSerializer
    lookup_field = 'slug'


@extend_schema(tags=['Businesses'])
class BusinessViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Business.objects.filter(status='active').prefetch_related('business_hours', 'branches')
    serializer_class = BusinessSerializer
    lookup_field = 'slug'

    @action(detail=True, methods=['get'])
    def services(self, request, slug=None):
        business = self.get_object()
        services = Service.objects.filter(business=business, is_active=True).prefetch_related('resource_requirements')
        serializer = ServiceSerializer(services, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def staff(self, request, slug=None):
        business = self.get_object()
        service_id = request.query_params.get('service_id')
        staff_qs = Staff.objects.filter(business=business, is_active=True).prefetch_related('assigned_services')
        if service_id:
            staff_qs = staff_qs.filter(assigned_services__id=service_id)
        serializer = StaffSerializer(staff_qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def resources(self, request, slug=None):
        business = self.get_object()
        resources = Resource.objects.filter(business=business, is_active=True)
        serializer = ResourceSerializer(resources, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def occurrences(self, request, slug=None):
        business = self.get_object()
        service_id = request.query_params.get('service_id')
        occurrences = ClassOccurrence.objects.filter(
            business=business,
            status='scheduled'
        ).select_related('service', 'instructor', 'resource')
        if service_id:
            occurrences = occurrences.filter(service_id=service_id)
        serializer = ClassOccurrenceSerializer(occurrences, many=True)
        return Response(serializer.data)
