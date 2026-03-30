from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from .models import UserProfile


class LGPDConsentMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        if user and user.is_authenticated:
            allowed_paths = {
                reverse("lgpd_consent"),
                reverse("logout"),
            }

            current_path = request.path

            if (
                current_path not in allowed_paths
                and not current_path.startswith("/admin/")
                and not current_path.startswith("/static/")
                and not current_path.startswith("/media/")
            ):
                profile, _ = UserProfile.objects.get_or_create(user=user)

                precisa_aceitar = (
                    not profile.lgpd_accepted
                    or not profile.lgpd_accepted_at
                    or profile.lgpd_accepted_at < (timezone.now() - timedelta(days=30))
                )

                if precisa_aceitar:
                    return redirect("lgpd_consent")

        response = self.get_response(request)
        return response