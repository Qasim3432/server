# myapp/services/security_audit.py
#
# Central helper for writing SecurityAuditLog rows.
# Called from auth.py, pin_management.py, gift.py etc.
#
# IMPORTANT: log_event must NEVER raise. If audit logging fails
# (DB error, bad request object), we log to console and continue —
# business logic must not break because audit failed.

import logging

from ..models import SecurityAuditLog


logger = logging.getLogger("myapp.security_audit")


def log_event(request, event_type, device_token="", detail=""):
    """
    Write a SecurityAuditLog row.

    Args:
        request: Django HttpRequest (may be None in rare cases)
        event_type: one of SecurityAuditLog.EVENT_CHOICES keys
        device_token: player device token (optional)
        detail: free-form text (truncated to 4000 chars)

    Never raises.
    """
    try:
        ip = None
        ua = ""

        if request is not None:
            try:
                from ..request_utils import get_client_ip  # local import — avoids cycle
                ip = get_client_ip(request)
                if ip == "unknown":
                    ip = None
            except Exception:
                ip = None

            try:
                ua = (request.META.get("HTTP_USER_AGENT", "") or "")[:255]
            except Exception:
                ua = ""

        SecurityAuditLog.objects.create(
            event_type=str(event_type)[:30],
            device_token=str(device_token or "")[:255],
            ip_address=ip,
            user_agent=ua,
            detail=str(detail or "")[:4000],
        )
    except Exception as exc:
        logger.warning(
            "SECURITY AUDIT WRITE FAILED | event=%s | device=%s | err=%s",
            event_type,
            (device_token or "")[:24],
            exc,
        )