import uuid
from django.db import models
from apps.businesses.models import Business


class Customer(models.Model):
    """
    Client or patient who books services with a business.
    Tenant-scoped so client records are private per business.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='customers')
    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)
    custom_fields = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = ('business', 'email')

    def __str__(self):
        contact = self.email or self.phone or 'No contact'
        return f"{self.name} ({contact}) - {self.business.name}"
