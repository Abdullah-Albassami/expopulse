"""
HTTP JSON receiver for simulated equipment telemetry (PROTOTYPE).

POST /api/equipment/readings/

Security baseline (local demonstration only)
--------------------------------------------
* Callers must send the shared token in the X-Equipment-Token header. The
  expected value is read from the EXPOPULSE_EQUIPMENT_API_TOKEN environment
  variable and is never logged or returned.
* The view is csrf_exempt because it is a machine-to-machine endpoint: the
  caller is a script, not a browser session with cookies. In this prototype
  the API token replaces browser CSRF protection.
* Do not expose this development endpoint to the public internet.
"""

import hmac
import json
import os

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from incidents.services.equipment_monitoring import (
    EquipmentReadingError,
    UnknownLocationError,
    process_reading,
)

TOKEN_ENV_VAR = "EXPOPULSE_EQUIPMENT_API_TOKEN"
TOKEN_HEADER = "X-Equipment-Token"
MAX_BODY_BYTES = 4096


def _error(message, status):
    return JsonResponse({"accepted": False, "error": message}, status=status)


def _token_is_valid(request):
    expected = os.environ.get(TOKEN_ENV_VAR, "")
    supplied = request.headers.get(TOKEN_HEADER, "")
    if not expected or not supplied:
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


@csrf_exempt
def equipment_reading(request):
    if request.method != "POST":
        response = _error("Method not allowed. Use POST.", 405)
        response["Allow"] = "POST"
        return response

    if not os.environ.get(TOKEN_ENV_VAR):
        return _error(
            f"Equipment endpoint is not configured: set {TOKEN_ENV_VAR} on the server.",
            503,
        )

    if not _token_is_valid(request):
        return _error(f"Missing or invalid {TOKEN_HEADER} header.", 401)

    if request.content_type != "application/json":
        return _error("Content-Type must be application/json.", 415)

    try:
        declared_length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return _error("Invalid Content-Length header.", 400)
    if declared_length > MAX_BODY_BYTES:
        return _error(f"Request body too large (max {MAX_BODY_BYTES} bytes).", 413)

    body = request.body
    if len(body) > MAX_BODY_BYTES:
        return _error(f"Request body too large (max {MAX_BODY_BYTES} bytes).", 413)

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _error("Request body is not valid JSON.", 400)

    try:
        result = process_reading(payload)
    except EquipmentReadingError as exc:
        return _error(str(exc), 400)
    except UnknownLocationError as exc:
        return _error(str(exc), 404)

    status = 201 if result["action"] == "created" else 200
    return JsonResponse(result, status=status)
