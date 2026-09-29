from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_GET


@require_GET
def health(request):
    return JsonResponse({"status": "ok", "service": "PIVOT-SASS"})


@require_GET
def home(request):
    if request.user.is_authenticated:
        return redirect("accounts:post-login")
    return redirect("accounts:login")


@require_GET
@login_required
def private_health(request):
    return JsonResponse({"status": "ok", "authenticated": True})
