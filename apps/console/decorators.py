"""Access decorators for the Operator Console.

ADR-017: console access is granted to superusers and members of the 'Operator' group.
Use Django Admin to assign users to that group — do not rely on is_staff alone.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def _is_operator(user):
    return user.is_superuser or user.groups.filter(name="Operator").exists()


def staff_required(view_func):
    @wraps(view_func)
    @login_required(login_url="/admin/login/")
    def _wrapped(request, *args, **kwargs):
        if not _is_operator(request.user):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped


def superuser_required(view_func):
    @wraps(view_func)
    @login_required(login_url="/admin/login/")
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped
