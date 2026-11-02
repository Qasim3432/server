# myapp/request_utils.py
#
# IP + request helpers shared across views.
#
# Why X-Forwarded-For matters:
#   In production, Django runs behind nginx / Cloudflare / ALB.
#   Without reading XFF, every request looks like 127.0.0.1 and
#   rate limits / audit logs become useless.

from django.conf import settings


def get_client_ip(request):
    """
    Return best-effort client IP.

    Priority:
        1. X-Forwarded-For (first non-private hop)   -- trusted proxies only
        2. REMOTE_ADDR                                -- direct connection
        3. "unknown"
    """
    if request is None:
        return "unknown"

    # Trusted proxies configured in settings (e.g. "127.0.0.1,::1")
    trusted_raw = getattr(settings, "TRUSTED_PROXY_IPS", "127.0.0.1,::1")
    trusted = {ip.strip() for ip in str(trusted_raw).split(",") if ip.strip()}

    remote = (request.META.get("REMOTE_ADDR") or "").strip()

    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff and (not trusted or remote in trusted):
        # XFF = "client, proxy1, proxy2"
        first = xff.split(",")[0].strip()
        if first:
            return first

    return remote or "unknown"