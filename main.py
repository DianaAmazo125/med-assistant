"""
main.py — FastAPI application (primary stack).

Run:
    python main.py
    # или
    uvicorn main:app --reload

Interactive API documentation is available at /docs.

If FastAPI is not installed, the same REST API is served by the
zero-dependency fallback: ``python run_local.py``.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from typing import Any


def _force_utf8_console() -> None:
    """Windows consoles default to cp866; make Russian output readable."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):  # pragma: no cover
                pass


_force_utf8_console()

try:
    from fastapi import Body, FastAPI, HTTPException, Query, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.templating import Jinja2Templates
except ImportError as exc:  # pragma: no cover - depends on the environment
    raise SystemExit(
        "Не установлены зависимости основного стека (FastAPI).\n"
        "\n"
        "  Вариант 1 — основной стек:\n"
        "      python -m venv .venv\n"
        "      .venv\\Scripts\\pip install -r requirements.txt   (Windows)\n"
        "      source .venv/bin/pip install -r requirements.txt  (Linux/macOS)\n"
        "      python main.py\n"
        "\n"
        "  Вариант 2 — без зависимостей, тот же интерфейс и API:\n"
        "      python run_local.py\n"
        f"\nПодробность: {exc}"
    ) from exc

import config
import database as db
import models
import seed_data
import services


# --------------------------------------------------------------------------- #
# Application lifecycle
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    if db.is_empty():
        result = seed_data.seed()
        print(f"[startup] база создана и наполнена: продуктов {result['foods']}, "
              f"блюд {result['meal_ideas']}")
    print(f"[startup] {config.APP_NAME} v{config.APP_VERSION}")
    print(f"[startup] база: {config.DB_PATH}")
    yield


app = FastAPI(
    title=config.APP_NAME,
    version=config.APP_VERSION,
    description=(
        "Универсальный персональный дневник питания, симптомов и контроля приёма "
        "лекарств с модульной системой ограничений (теги: gerd, low_fodmap, "
        "low_purine, migraine_control, cardio_caution).\n\n"
        "Сервис является дневником самонаблюдения и не заменяет врача."
    ),
    lifespan=lifespan,
)

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))

# Статика — локальный CSS и JS без CDN.
STATIC_DIR = config.BASE_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _dump(payload: Any) -> dict:
    """pydantic v2 / v1 compatible model → dict."""
    if payload is None:
        return {}
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)
    if hasattr(payload, "dict"):
        return payload.dict(exclude_unset=True)
    return dict(payload)


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
# The page loads every value from ``/api/bootstrap``; nothing is rendered
# server-side, so the same template works under the stdlib fallback too.
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="index.html", context={})


@app.get("/print", include_in_schema=False)
async def print_view() -> RedirectResponse:
    """Deep link that opens the app already on the printable report tab."""
    return RedirectResponse(url="/?tab=report", status_code=307)


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #
@app.get("/api/health", tags=["meta"], summary="Проверка работоспособности")
async def health() -> dict:
    return {"status": "ok", "app": config.APP_NAME, "version": config.APP_VERSION,
            "db": db.db_info()}


@app.get("/api/bootstrap", tags=["meta"], summary="Все данные для старта интерфейса")
async def bootstrap() -> dict:
    return services.bootstrap()


@app.get("/api/export", tags=["meta"], summary="Полный экспорт дневника в JSON")
async def export_data() -> dict:
    """Личный бэкап: профиль, препараты, дневник, приёмы, вода и настройки."""
    profile = services.get_profile()
    everything = "1970-01-01"
    today = db.today_iso()
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
@app.get("/api/profile", tags=["profile"], summary="Профиль с активными тегами")
async def get_profile() -> dict:
    return services.get_profile()


@app.put("/api/profile", tags=["profile"], summary="Обновить профиль, теги и памятку")
async def put_profile(payload: models.ProfileUpdate = Body(...)) -> dict:
    try:
        return services.update_profile(_dump(payload))
    except ValueError as exc:
        raise _fail(exc)


# --------------------------------------------------------------------------- #
# Medications
# --------------------------------------------------------------------------- #
@app.get("/api/medications", tags=["medications"], summary="Список препаратов")
async def get_medications(active_only: bool = Query(default=False)) -> dict:
    profile = services.get_profile()
    return {"items": services.list_medications(profile["id"], active_only=active_only)}


@app.post("/api/medications", tags=["medications"], summary="Добавить препарат", status_code=201)
async def post_medication(payload: models.MedicationIn = Body(...)) -> dict:
    try:
        return services.create_medication(None, _dump(payload))
    except ValueError as exc:
        raise _fail(exc)


@app.put("/api/medications/{medication_id}", tags=["medications"], summary="Изменить препарат")
async def put_medication(medication_id: int, payload: models.MedicationIn = Body(...)) -> dict:
    updated = services.update_medication(medication_id, _dump(payload))
    if updated is None:
        raise HTTPException(status_code=404, detail="Препарат не найден")
    return updated


@app.delete("/api/medications/{medication_id}", tags=["medications"], summary="Удалить препарат")
async def delete_medication(medication_id: int) -> dict:
    if not services.delete_medication(medication_id):
        raise HTTPException(status_code=404, detail="Препарат не найден")
    return {"deleted": medication_id}


# --------------------------------------------------------------------------- #
# Foods / dishes / menu
# --------------------------------------------------------------------------- #
@app.get("/api/foods", tags=["food"], summary="Светофор продуктов с объяснением")
async def get_foods(
    q: str = Query(default="", description="Поиск по названию, категории и причинам"),
    status: str = Query(default="", description="safe | caution | trigger"),
    category: str = Query(default="", description="Категория продукта"),
) -> dict:
    return services.list_foods({"q": q, "status": status, "category": category})


@app.get("/api/meal-ideas", tags=["food"], summary="Конструктор блюд по слотам")
async def get_meal_ideas(slot: str = Query(default="")) -> dict:
    return services.list_meal_ideas(slot=slot or None)


@app.get("/api/menu", tags=["food"], summary="Безопасный рацион на день")
async def get_menu(
    date: str = Query(default="", description="YYYY-MM-DD"),
    per_slot: int = Query(default=2, ge=1, le=6),
) -> dict:
    return services.generate_menu(for_date=date or None, per_slot=per_slot)


# --------------------------------------------------------------------------- #
# Daily check-in
# --------------------------------------------------------------------------- #
@app.get("/api/today", tags=["diary"], summary="Сводка за день")
async def get_today(date: str = Query(default="")) -> dict:
    return services.today_snapshot(for_date=date or None)


@app.get("/api/symptoms", tags=["diary"], summary="Записи симптомов за период")
async def get_symptoms(date_from: str = Query(default=""), date_to: str = Query(default="")) -> dict:
    return {"items": services.list_symptom_logs(None, date_from or None, date_to or None)}


@app.put("/api/symptoms", tags=["diary"], summary="Сохранить чек-ин симптомов за день")
async def put_symptoms(payload: models.SymptomLogIn = Body(...)) -> dict:
    try:
        return services.upsert_symptom_log(None, _dump(payload))
    except ValueError as exc:
        raise _fail(exc)


@app.delete("/api/symptoms", tags=["diary"], summary="Удалить чек-ин за день")
async def delete_symptoms(date: str = Query(default="")) -> dict:
    if not services.delete_symptom_log(None, date or None):
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return {"deleted": services.norm_date(date or None)}


# --------------------------------------------------------------------------- #
# Headache + NSAID
# --------------------------------------------------------------------------- #
@app.get("/api/headaches", tags=["headache"], summary="Эпизоды головной боли")
async def get_headaches(date_from: str = Query(default=""), date_to: str = Query(default="")) -> dict:
    return {"items": services.list_headaches(None, date_from or None, date_to or None)}


@app.post("/api/headaches", tags=["headache"], summary="Добавить эпизод головной боли",
          status_code=201)
async def post_headache(payload: models.HeadacheIn = Body(...)) -> dict:
    try:
        return services.add_headache(None, _dump(payload))
    except ValueError as exc:
        raise _fail(exc)


@app.delete("/api/headaches/{headache_id}", tags=["headache"], summary="Удалить эпизод")
async def delete_headache(headache_id: int) -> dict:
    if not services.delete_headache(None, headache_id):
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return {"deleted": headache_id}


@app.get("/api/intakes", tags=["headache"], summary="Приёмы препаратов за период")
async def get_intakes(date_from: str = Query(default=""), date_to: str = Query(default="")) -> dict:
    return {"items": services.list_intakes(None, date_from or None, date_to or None)}


@app.post("/api/intakes", tags=["headache"], summary="Отметить приём препарата", status_code=201)
async def post_intake(payload: models.IntakeIn = Body(...)) -> dict:
    try:
        return services.add_intake(None, _dump(payload))
    except ValueError as exc:
        raise _fail(exc)


@app.delete("/api/intakes/{intake_id}", tags=["headache"], summary="Удалить приём")
async def delete_intake(intake_id: int) -> dict:
    if not services.delete_intake(None, intake_id):
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return {"deleted": intake_id}


@app.get("/api/nsaid", tags=["headache"], summary="Счётчик НПВС за 30 дней с предупреждениями")
async def get_nsaid(days: int = Query(default=config.NSIAD_WINDOW_DAYS, ge=7, le=180),
                    date: str = Query(default="")) -> dict:
    return services.nsaid_summary(days=days, end_date=date or None)


# --------------------------------------------------------------------------- #
# Adherence + water
# --------------------------------------------------------------------------- #
@app.get("/api/checklist", tags=["diary"], summary="Чек-лист регулярных препаратов на день")
async def get_checklist(date: str = Query(default="")) -> dict:
    return services.medication_checklist(None, date or None)


@app.post("/api/checklist", tags=["diary"], summary="Отметить приём препарата из чек-листа")
async def post_checklist(payload: models.MedicationCheckIn = Body(...)) -> dict:
    try:
        return services.set_medication_check(None, _dump(payload))
    except ValueError as exc:
        raise _fail(exc)


@app.get("/api/water", tags=["diary"], summary="Трекер воды за день")
async def get_water(date: str = Query(default="")) -> dict:
    return services.get_water(None, date or None)


@app.post("/api/water", tags=["diary"], summary="Изменить количество стаканов воды")
async def post_water(payload: models.WaterIn = Body(...)) -> dict:
    try:
        return services.set_water(None, _dump(payload))
    except ValueError as exc:
        raise _fail(exc)


# --------------------------------------------------------------------------- #
# Doctor report
# --------------------------------------------------------------------------- #
@app.get("/api/report", tags=["report"], summary="Сводка для врача за период")
async def get_report(
    date_from: str = Query(default="", description="YYYY-MM-DD"),
    date_to: str = Query(default="", description="YYYY-MM-DD"),
) -> dict:
    return services.build_report(None, date_from or None, date_to or None)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def run() -> None:
    import uvicorn

    print(f"{config.APP_NAME} v{config.APP_VERSION}")
    print(f"Откройте в браузере: http://{config.HOST}:{config.PORT}")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    run()
