from django.contrib import admin
from django.contrib.auth import get_user_model

from .models import ServiceRequest, ServiceRequestAttachment

User = get_user_model()


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ("os_number", "full_name", "service_type", "status", "created_at")
    search_fields = ("os_number", "full_name", "document")
    list_filter = ("status", "service_type", "city")
    ordering = ("-created_at",)


@admin.register(ServiceRequestAttachment)
class ServiceRequestAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "file")
    search_fields = ("request__os_number",)


try:
    admin.site.register(User)
except admin.sites.AlreadyRegistered:
    pass