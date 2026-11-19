"""
run_local.py — zero-dependency launcher.

The project's primary stack is FastAPI (``main.py``).  This module serves exactly
the same REST API and the same single-page UI using only the Python standard
library (``http.server`` + ``sqlite3``), which is handy when the machine has no
internet access or you simply do not want to install anything::

    python run_local.py            # http://127.0.0.1:8000
    python run_local.py --port 8080
    python run_local.py --open

Every route delegates to ``services.py``, so the behaviour is identical to the
FastAPI version.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urlparse

import config
import database as db
import models
import seed_data
import services

if hasattr(sys.stdout, "reconfigure"):
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (OSError, ValueError):  # pragma: no cover
            pass


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
Route = tuple[str, re.Pattern, Callable[..., Any], int]
ROUTES: list[Route] = []


def route(method: str, pattern: str, status: int = 200):
    """
    Register ``handler(query, body, params)`` for one method + path regex.

    ``status`` mirrors the ``status_code=201`` declarations of the FastAPI
    adapter so both servers answer identically.
    """
    compiled = re.compile(pattern)

    def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
        ROUTES.append((method.upper(), compiled, handler, status))
        return handler

    return decorator


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def dispatch(method: str, path: str, query: dict[str, str], body: dict[str, Any]) -> tuple[int, Any]:
    """Resolve a request to ``(status_code, payload)``."""
    allowed: set[str] = set()
    for route_method, pattern, handler, success_status in ROUTES:
        match = pattern.match(path)
        if not match:
            continue
        allowed.add(route_method)
        if route_method != method.upper():
            continue
        params = {key: value for key, value in match.groupdict().items()}
        try:
            payload = handler(query, body, params)
        except ApiError as exc:
            return exc.status, {"error": exc.message}
        except ValueError as exc:
            return 400, {"error": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive
            return 500, {"error": f"Внутренняя ошибка: {exc}"}
        return success_status, payload
    if allowed:
        return 405, {"error": f"Метод {method} не поддерживается для {path}"}
    return 404, {"error": f"Не найдено: {path}"}


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #
@route("GET", r"^/api/health$")
def _health(query, body, params):
    return {"status": "ok", "app": config.APP_NAME, "version": config.APP_VERSION,
            "db": db.db_info(), "server": "stdlib"}


@route("GET", r"^/api/bootstrap$")
def _bootstrap(query, body, params):
    return services.bootstrap()


@route("GET", r"^/api/export$")
def _export(query, body, params):
    """Личный бэкап: профиль, препараты, дневник, приёмы, вода и настройки."""
    profile = services.get_profile()
    everything, today = "1970-01-01", db.today_iso()
    water_rows = db.fetch_all(
        f"SELECT * FROM {models.WATER_LOGS} WHERE profile_id = ? ORDER BY log_date",
        (profile["id"],),
    )
    check_rows = db.fetch_all(
        f"SELECT * FROM {models.MEDICATION_CHECKS} WHERE profile_id = ? ORDER BY check_date",
        (profile["id"],),
    )
    return {
        "app": {"name": config.APP_NAME, "version": config.APP_VERSION},
        "exported_at": db.now_iso(),
        "profile": profile,
        "medications": services.list_medications(profile["id"]),
        "symptoms": services.list_symptom_logs(profile["id"], everything, today),
        "headaches": services.list_headaches(profile["id"], everything, today),
        "intakes": services.list_intakes(profile["id"], everything, today),
        "water": [models.row_to_water(row) for row in water_rows],
        "medication_checks": [models.row_to_check(row) for row in check_rows],
        "settings": db.all_settings(),
        "note": "Личный экспорт данных дневника. Храните файл в защищённом месте.",
    }


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #
@route("GET", r"^/api/profile$")
def _get_profile(query, body, params):
    return services.get_profile()


@route("PUT", r"^/api/profile$")
@route("POST", r"^/api/profile$")
def _put_profile(query, body, params):
    return services.update_profile(body)


# --------------------------------------------------------------------------- #
# Medications
# --------------------------------------------------------------------------- #
@route("GET", r"^/api/medications$")
def _get_medications(query, body, params):
    profile = services.get_profile()
    active_only = str(query.get("active_only", "")).lower() in ("1", "true", "yes")
    return {"items": services.list_medications(profile["id"], active_only=active_only)}


@route("POST", r"^/api/medications$", status=201)
def _post_medication(query, body, params):
    return services.create_medication(None, body)


@route("PUT", r"^/api/medications/(?P<medication_id>\d+)$")
def _put_medication(query, body, params):
    updated = services.update_medication(_int(params["medication_id"]), body)
    if updated is None:
        raise ApiError(404, "Препарат не найден")
    return updated


@route("DELETE", r"^/api/medications/(?P<medication_id>\d+)$")
def _delete_medication(query, body, params):
    medication_id = _int(params["medication_id"])
    if not services.delete_medication(medication_id):
        raise ApiError(404, "Препарат не найден")
    return {"deleted": medication_id}


# --------------------------------------------------------------------------- #
# Foods / dishes / menu
# --------------------------------------------------------------------------- #
@route("GET", r"^/api/foods$")
def _foods(query, body, params):
    return services.list_foods({
        "q": query.get("q", ""),
        "status": query.get("status", ""),
        "category": query.get("category", ""),
    })


@route("GET", r"^/api/meal-ideas$")
def _meal_ideas(query, body, params):
    return services.list_meal_ideas(slot=query.get("slot") or None)


@route("GET", r"^/api/menu$")
def _menu(query, body, params):
    return services.generate_menu(for_date=query.get("date") or None,
                                  per_slot=_int(query.get("per_slot", 2), 2))


# --------------------------------------------------------------------------- #
# Daily check-in
# --------------------------------------------------------------------------- #
@route("GET", r"^/api/today$")
def _today(query, body, params):
    return services.today_snapshot(for_date=query.get("date") or None)


@route("GET", r"^/api/symptoms$")
def _get_symptoms(query, body, params):
    return {"items": services.list_symptom_logs(None, query.get("date_from") or None,
                                                query.get("date_to") or None)}


@route("PUT", r"^/api/symptoms$")
@route("POST", r"^/api/symptoms$")
def _put_symptoms(query, body, params):
    return services.upsert_symptom_log(None, body)


@route("DELETE", r"^/api/symptoms$")
def _delete_symptoms(query, body, params):
    target = query.get("date") or (body or {}).get("date")
    if not services.delete_symptom_log(None, target):
        raise ApiError(404, "Запись не найдена")
    return {"deleted": services.norm_date(target)}


# --------------------------------------------------------------------------- #
# Headache + NSAID
# --------------------------------------------------------------------------- #
@route("GET", r"^/api/headaches$")
def _get_headaches(query, body, params):
    return {"items": services.list_headaches(None, query.get("date_from") or None,
                                             query.get("date_to") or None)}


@route("POST", r"^/api/headaches$", status=201)
def _post_headache(query, body, params):
    return services.add_headache(None, body)


@route("DELETE", r"^/api/headaches/(?P<headache_id>\d+)$")
def _delete_headache(query, body, params):
    headache_id = _int(params["headache_id"])
    if not services.delete_headache(None, headache_id):
        raise ApiError(404, "Запись не найдена")
    return {"deleted": headache_id}


@route("GET", r"^/api/intakes$")
def _get_intakes(query, body, params):
    return {"items": services.list_intakes(None, query.get("date_from") or None,
                                           query.get("date_to") or None)}


@route("POST", r"^/api/intakes$", status=201)
def _post_intake(query, body, params):
    return services.add_intake(None, body)


@route("DELETE", r"^/api/intakes/(?P<intake_id>\d+)$")
def _delete_intake(query, body, params):
    intake_id = _int(params["intake_id"])
    if not services.delete_intake(None, intake_id):
        raise ApiError(404, "Запись не найдена")
    return {"deleted": intake_id}


@route("GET", r"^/api/nsaid$")
def _nsaid(query, body, params):
    days = _int(query.get("days", config.NSIAD_WINDOW_DAYS), config.NSIAD_WINDOW_DAYS)
    return services.nsaid_summary(days=days, end_date=query.get("date") or None)


# --------------------------------------------------------------------------- #
# Adherence + water
# --------------------------------------------------------------------------- #
@route("GET", r"^/api/checklist$")
def _get_checklist(query, body, params):
    return services.medication_checklist(None, query.get("date") or None)


@route("POST", r"^/api/checklist$")
def _post_checklist(query, body, params):
    return services.set_medication_check(None, body)


@route("GET", r"^/api/water$")
def _get_water(query, body, params):
    return services.get_water(None, query.get("date") or None)


@route("POST", r"^/api/water$")
def _post_water(query, body, params):
    return services.set_water(None, body)


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
@route("GET", r"^/api/report$")
def _report(query, body, params):
    return services.build_report(None, query.get("date_from") or None, query.get("date_to") or None)


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
def _read_index() -> bytes:
    if not config.INDEX_TEMPLATE.exists():
        return ("<!doctype html><meta charset='utf-8'>"
                "<h1>templates/index.html не найден</h1>").encode("utf-8")
    return config.INDEX_TEMPLATE.read_bytes()


class DiaryHandler(BaseHTTPRequestHandler):
    server_version = f"DiaryLocal/{config.APP_VERSION}"
    protocol_version = "HTTP/1.1"

    # ---------------------------------------------------------------- helpers
    def _send(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._send(status, data, "application/json; charset=utf-8")

    def _read_body(self) -> dict:
        length = _int(self.headers.get("Content-Length", 0), 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "Тело запроса должно быть корректным JSON")
        return parsed if isinstance(parsed, dict) else {}

    # --------------------------------------------------------------- dispatch
    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}

        if method in ("GET", "HEAD") and path in ("/", "/index.html", "/print"):
            self._send(200, _read_index(), "text/html; charset=utf-8")
            return

        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return

        if path.startswith("/static/") and method in ("GET", "HEAD"):
            # Отдаём статические файлы: app.css и app.js — без внешних CDN.
            relative = path[len("/static/"):].lstrip("/")
            spath = config.STATIC_DIR / relative
            if spath.is_file() and spath.relative_to(config.STATIC_DIR):
                raw = spath.read_bytes()
                ext = spath.suffix
                ctype = {"css": "text/css; charset=utf-8",
                         "js": "application/javascript; charset=utf-8"}.get(ext,
                                "application/octet-stream")
                self._send(200, raw, ctype)
                return
            self._send(404, b'{"error":"static file not found"}', "application/json")
            return

        try:
            body = self._read_body()
        except ApiError as exc:
            self._send_json(exc.status, {"error": exc.message})
            return

        status, payload = dispatch(method, path, query, body)
        self._send_json(status, payload)

    def do_GET(self) -> None:      # noqa: N802 - stdlib naming
        self._handle("GET")

    def do_HEAD(self) -> None:     # noqa: N802
        self._handle("HEAD")

    def do_POST(self) -> None:     # noqa: N802
        self._handle("POST")

    def do_PUT(self) -> None:      # noqa: N802
        self._handle("PUT")

    def do_DELETE(self) -> None:   # noqa: N802
        self._handle("DELETE")

    # http.server answers 501 for methods without a ``do_*`` method; routing
    # these through the dispatcher gives the same JSON 405 as FastAPI.
    def do_PATCH(self) -> None:    # noqa: N802
        self._handle("PATCH")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, POST, PUT, DELETE, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def prepare() -> dict:
    db.init_db()
    if db.is_empty():
        return seed_data.seed()
    return {"mode": "existing"}


def serve(host: str, port: int, open_browser: bool = False) -> None:
    result = prepare()
    if result.get("mode") == "fresh":
        print(f"База создана и наполнена: продуктов {result['foods']}, блюд {result['meal_ideas']}")

    httpd = ThreadingHTTPServer((host, port), DiaryHandler)
    url = f"http://{host}:{port}"
    print(f"{config.APP_NAME} v{config.APP_VERSION} (stdlib-сервер)")
    print(f"База данных: {config.DB_PATH}")
    print(f"Откройте в браузере: {url}")
    print("Остановка: Ctrl+C")

    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        httpd.server_close()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Локальный сервер дневника без зависимостей")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--open", action="store_true", help="открыть браузер автоматически")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        serve(args.host, args.port, args.open)
    except OSError as exc:
        print(f"Не удалось запустить сервер на {args.host}:{args.port} — {exc}")
        print("Попробуйте другой порт: python run_local.py --port 8080")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
