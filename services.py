"""
services.py — the brain of the app.

All business logic lives here so that both the FastAPI layer (``main.py``) and
the zero-dependency fallback server (``run_local.py``) expose exactly the same
behaviour.  Functions take/return plain dicts; nothing here imports a web
framework.

The central idea is :func:`evaluate_rules`: every product and every dish carries
``tag_rules``, and the *user's* active tags decide whether the item is green,
yellow or red — with the reason spelled out tag by tag.
"""

from __future__ import annotations

import random
from datetime import date as date_cls, datetime, timedelta
from typing import Any, Iterable

import config
import database as db
import models

# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def norm_date(value: Any, default: str | None = None) -> str:
    """Accept 'YYYY-MM-DD' (or a date) and return an ISO date string."""
    if isinstance(value, date_cls):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        candidate = value.strip()[:10]
        try:
            return datetime.strptime(candidate, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    return default or db.today_iso()


def date_range(date_from: Any, date_to: Any, max_days: int = 366) -> tuple[str, str]:
    end = norm_date(date_to)
    start = norm_date(date_from, default=(date_cls.fromisoformat(end) - timedelta(days=29)).isoformat())
    if start > end:
        start, end = end, start
    span = (date_cls.fromisoformat(end) - date_cls.fromisoformat(start)).days
    if span > max_days:
        start = (date_cls.fromisoformat(end) - timedelta(days=max_days)).isoformat()
    return start, end


def clamp_int(value: Any, low: int, high: int, default: int = 0) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def clamp_float(value: Any, low: float, high: float, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def clean_str(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _step_dates(start: str, end: str) -> list[str]:
    first, last = date_cls.fromisoformat(start), date_cls.fromisoformat(end)
    return [(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)]


def tag_catalog() -> list[dict]:
    return [{"id": tag, **meta} for tag, meta in config.RESTRICTION_TAGS.items()]


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
def get_profile(profile_id: int | None = None) -> dict:
    if profile_id:
        row = db.fetch_one(f"SELECT * FROM {models.PROFILES} WHERE id = ?", (profile_id,))
    else:
        row = db.fetch_one(f"SELECT * FROM {models.PROFILES} ORDER BY id LIMIT 1")
    if row is None:
        return {
            "id": None,
            "name": "Профиль не создан",
            "active_tags": [],
            "medical_memo": "",
            "created_at": "",
            "updated_at": "",
        }
    return models.row_to_profile(row)


def update_profile(payload: dict, profile_id: int | None = None) -> dict:
    profile = get_profile(profile_id)
    if not profile["id"]:
        raise ValueError("Профиль не найден. Запустите: python seed_data.py")

    sets: list[str] = []
    params: list[Any] = []

    if payload.get("name") is not None:
        name = clean_str(payload["name"], 120)
        if not name:
            raise ValueError("Название профиля не может быть пустым")
        sets.append("name = ?")
        params.append(name)

    if payload.get("active_tags") is not None:
        raw = payload["active_tags"]
        if not isinstance(raw, list):
            raise ValueError("active_tags должен быть списком")
        tags = [str(tag) for tag in raw if str(tag) in config.RESTRICTION_TAGS]
        # Preserve the catalog order for stable UI rendering.
        tags = [tag for tag in config.ALL_TAG_IDS if tag in tags]
        sets.append("active_tags = ?")
        params.append(models.json_dumps(tags))

    if payload.get("medical_memo") is not None:
        sets.append("medical_memo = ?")
        params.append(clean_str(payload["medical_memo"], 20000))

    if sets:
        sets.append("updated_at = ?")
        params.append(db.now_iso())
        params.append(profile["id"])
        db.execute(f"UPDATE {models.PROFILES} SET {', '.join(sets)} WHERE id = ?", params)
    return get_profile(profile["id"])


def water_goal() -> int:
    return clamp_int(db.get_setting("water_goal", str(config.WATER_GOAL_DEFAULT)), 1, 40,
                     config.WATER_GOAL_DEFAULT)


# --------------------------------------------------------------------------- #
# Medications
# --------------------------------------------------------------------------- #
def list_medications(profile_id: int | None = None, active_only: bool = False) -> list[dict]:
    profile = get_profile(profile_id)
    sql = f"SELECT * FROM {models.MEDICATIONS} WHERE profile_id = ?"
    params: list[Any] = [profile["id"]]
    if active_only:
        sql += " AND active = 1"
    sql += " ORDER BY sort_order, id"
    return [models.row_to_medication(row) for row in db.fetch_all(sql, params)]


def get_medication(medication_id: int) -> dict | None:
    row = db.fetch_one(f"SELECT * FROM {models.MEDICATIONS} WHERE id = ?", (medication_id,))
    return models.row_to_medication(row) if row else None


def create_medication(profile_id: int | None, payload: dict) -> dict:
    profile = get_profile(profile_id)
    if not profile["id"]:
        raise ValueError("Профиль не найден")
    name = clean_str(payload.get("name"), 160)
    if not name:
        raise ValueError("Укажите название препарата")

    is_nsaid = bool(payload.get("is_nsaid")) or config.looks_like_nsaid(name)
    is_analgesic = bool(payload.get("is_analgesic")) or config.looks_like_analgesic(name)
    times = payload.get("times")
    times = [clean_str(t, 10) for t in times if clean_str(t, 10)] if isinstance(times, list) else []

    new_id = db.insert(
        f"""INSERT INTO {models.MEDICATIONS}
            (profile_id, name, dose, schedule, times, kind, is_nsaid, is_analgesic,
             cardio_note, purpose, active, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            profile["id"], name,
            clean_str(payload.get("dose"), 120),
            clean_str(payload.get("schedule"), 200),
            models.json_dumps(times),
            clean_str(payload.get("kind") or ("nsaid" if is_nsaid else "regular"), 40),
            1 if is_nsaid else 0,
            1 if is_analgesic else 0,
            clean_str(payload.get("cardio_note"), 500),
            clean_str(payload.get("purpose"), 300),
            0 if payload.get("active") is False else 1,
            clamp_int(payload.get("sort_order"), 0, 9999, 100),
        ),
    )
    return get_medication(new_id) or {}


def update_medication(medication_id: int, payload: dict) -> dict | None:
    current = get_medication(medication_id)
    if not current:
        return None

    name = clean_str(payload.get("name"), 160) or current["name"]
    is_nsaid = payload.get("is_nsaid")
    is_nsaid = current["is_nsaid"] if is_nsaid is None else (bool(is_nsaid) or config.looks_like_nsaid(name))
    is_analgesic = payload.get("is_analgesic")
    is_analgesic = (current["is_analgesic"] if is_analgesic is None
                    else (bool(is_analgesic) or config.looks_like_analgesic(name)))

    times = payload.get("times")
    if isinstance(times, list):
        times = [clean_str(t, 10) for t in times if clean_str(t, 10)]
    else:
        times = current["times"]

    db.execute(
        f"""UPDATE {models.MEDICATIONS} SET
              name = ?, dose = ?, schedule = ?, times = ?, kind = ?,
              is_nsaid = ?, is_analgesic = ?, cardio_note = ?, purpose = ?,
              active = ?, sort_order = ?
            WHERE id = ?""",
        (
            name,
            clean_str(payload.get("dose"), 120) if payload.get("dose") is not None else current["dose"],
            clean_str(payload.get("schedule"), 200) if payload.get("schedule") is not None else current["schedule"],
            models.json_dumps(times),
            clean_str(payload.get("kind"), 40) or current["kind"],
            1 if is_nsaid else 0,
            1 if is_analgesic else 0,
            clean_str(payload.get("cardio_note"), 500) if payload.get("cardio_note") is not None else current["cardio_note"],
            clean_str(payload.get("purpose"), 300) if payload.get("purpose") is not None else current["purpose"],
            (1 if payload.get("active") else 0) if payload.get("active") is not None else (1 if current["active"] else 0),
            clamp_int(payload.get("sort_order"), 0, 9999, current["sort_order"]),
            medication_id,
        ),
    )
    return get_medication(medication_id)


def delete_medication(medication_id: int) -> bool:
    cursor = db.execute(f"DELETE FROM {models.MEDICATIONS} WHERE id = ?", (medication_id,))
    return bool(cursor.rowcount)


# --------------------------------------------------------------------------- #
# Tag evaluation — the heart of the traffic light
# --------------------------------------------------------------------------- #
def evaluate_rules(tag_rules: dict | None, active_tags: Iterable[str]) -> dict:
    """
    Fold an item's ``tag_rules`` into one verdict for the user's active tags.

    Returns ``status`` (safe / caution / trigger), the per-tag ``reasons`` that
    produced it, and ``other_notes`` — rules for tags the user has *not*
    activated, kept so the reason text can still be shown on demand.
    """
    tag_rules = tag_rules or {}
    active = [tag for tag in active_tags if tag in config.RESTRICTION_TAGS]

    reasons: list[dict] = []
    other_notes: list[dict] = []

    for tag, rule in tag_rules.items():
        if tag not in config.RESTRICTION_TAGS or not isinstance(rule, dict):
            continue
        status = str(rule.get("status") or "").strip()
        if status not in (config.STATUS_SAFE, config.STATUS_CAUTION, config.STATUS_TRIGGER):
            continue
        meta = config.RESTRICTION_TAGS[tag]
        entry = {
            "tag": tag,
            "tag_label": meta["label"],
            "tag_short": meta["short"],
            "tag_icon": meta["icon"],
            "status": status,
            "status_label": config.STATUS_META[status]["label"],
            "tone": config.STATUS_META[status]["tone"],
            "reason": clean_str(rule.get("reason"), 400),
        }
        if tag in active:
            if status != config.STATUS_SAFE:
                reasons.append(entry)
        else:
            other_notes.append(entry)

    triggers = [item for item in reasons if item["status"] == config.STATUS_TRIGGER]
    cautions = [item for item in reasons if item["status"] == config.STATUS_CAUTION]

    if triggers:
        status = config.STATUS_TRIGGER
    elif cautions:
        status = config.STATUS_CAUTION
    else:
        status = config.STATUS_SAFE

    return {
        "status": status,
        "reasons": reasons,
        "triggers": triggers,
        "cautions": cautions,
        "other_notes": other_notes,
    }


def _verdict_sentence(status: str, reasons: list[dict], active_tags: list[str], is_drug: bool = False) -> str:
    labels = ", ".join(config.RESTRICTION_TAGS[tag]["short"] for tag in active_tags) or "нет активных тегов"
    if status == config.STATUS_SAFE:
        if not active_tags:
            return "Ограничения не выбраны — нейтральная позиция."
        return f"Не нарушает ни одного из ваших ограничений ({labels})."
    if status == config.STATUS_CAUTION:
        parts = "; ".join(f"{item['tag_icon']} {item['tag_short']}: {item['reason']}" for item in reasons)
        return f"Допустимо небольшой порцией. {parts}"
    parts = "; ".join(f"{item['tag_icon']} {item['tag_short']}: {item['reason']}" for item in reasons)
    prefix = "Препарат: " if is_drug else ""
    return f"{prefix}лучше исключить. {parts}"


def food_view(food: dict, active_tags: list[str]) -> dict:
    verdict = evaluate_rules(food["tag_rules"], active_tags)
    status = verdict["status"]
    meta = config.STATUS_META[status]
    return {
        "id": food["id"],
        "name": food["name"],
        "category": food["category"],
        "note": food["note"],
        "portion": food["portion"],
        "is_drug": food["is_drug"],
        "status": status,
        "status_label": meta["label"],
        "status_icon": meta["icon"],
        "tone": meta["tone"],
        "reasons": verdict["reasons"],
        "triggers": verdict["triggers"],
        "cautions": verdict["cautions"],
        "other_notes": verdict["other_notes"],
        "violated_tags": [item["tag_short"] for item in verdict["reasons"]],
        "explain": _verdict_sentence(status, verdict["reasons"], active_tags, food["is_drug"]),
    }


def list_foods(payload: dict | None = None) -> dict:
    payload = payload or {}
    profile = get_profile(payload.get("profile_id"))
    active_tags = payload.get("active_tags")
    if not isinstance(active_tags, list):
        active_tags = profile["active_tags"]
    active_tags = [tag for tag in active_tags if tag in config.RESTRICTION_TAGS]

    query = clean_str(payload.get("q"), 120).lower()
    status_filter = clean_str(payload.get("status"), 20)
    category_filter = clean_str(payload.get("category"), 80)

    rows = db.fetch_all(f"SELECT * FROM {models.FOODS} ORDER BY sort_order, name")
    all_views = [food_view(models.row_to_food(row), active_tags) for row in rows]
    categories = sorted({item["category"] for item in all_views})

    items = all_views
    if category_filter and category_filter not in ("all", "Все"):
        items = [item for item in items if item["category"] == category_filter]

    if query:
        def matches(item: dict) -> bool:
            haystack = " ".join([
                item["name"], item["category"], item["note"],
                " ".join(reason["reason"] for reason in item["reasons"]),
            ]).lower()
            return query in haystack
        items = [item for item in items if matches(item)]

    if status_filter in config.STATUS_META:
        items = [item for item in items if item["status"] == status_filter]

    # Counts describe the current search/category scope, not the status filter,
    # so the filter chips stay stable while you click through them.
    scope = [item for item in all_views
             if not item["is_drug"]
             and (not category_filter or category_filter in ("all", "Все")
                  or item["category"] == category_filter)]
    if query:
        scope = [item for item in scope
                 if query in " ".join([item["name"], item["category"], item["note"],
                                       " ".join(reason["reason"] for reason in item["reasons"])]).lower()]

    # Drugs are reference entries for the headache tab — keep them out of the
    # "what can I eat" list, they are returned separately.
    food_only = [item for item in items if not item["is_drug"]]
    drugs = [item for item in items if item["is_drug"]]
    counts = {status: sum(1 for item in scope if item["status"] == status)
              for status in config.STATUS_META}

    return {
        "items": food_only,
        "drugs": drugs,
        "counts": counts,
        "total": len(food_only),
        "scope_total": len(scope),
        "categories": categories,
        "active_tags": active_tags,
        "query": query,
        "status_filter": status_filter,
        "category_filter": category_filter,
    }


# --------------------------------------------------------------------------- #
# Meal constructor
# --------------------------------------------------------------------------- #
def _ingredient_views(names: list[str], foods_by_name: dict[str, dict], active_tags: list[str]) -> list[dict]:
    views: list[dict] = []
    for name in names:
        food = foods_by_name.get(name.lower())
        if food is None:
            views.append({
                "name": name, "status": config.STATUS_SAFE, "status_label": "Можно",
                "status_icon": "🟢", "tone": "safe", "known": False,
                "explain": "Продукт не найден в каталоге — проверьте вручную.",
                "reasons": [],
            })
            continue
        view = food_view(food, active_tags)
        view["known"] = True
        views.append(view)
    return views


def dish_view(idea: dict, foods_by_name: dict[str, dict], active_tags: list[str]) -> dict:
    ingredients = _ingredient_views(idea["ingredients"], foods_by_name, active_tags)
    verdict = evaluate_rules(idea["tag_rules"], active_tags)

    statuses = [item["status"] for item in ingredients] + ([verdict["status"]] if verdict["reasons"] else [])
    if config.STATUS_TRIGGER in statuses:
        status = config.STATUS_TRIGGER
    elif config.STATUS_CAUTION in statuses:
        status = config.STATUS_CAUTION
    else:
        status = config.STATUS_SAFE

    blocking = [
        {"name": item["name"], "reasons": item["reasons"]}
        for item in ingredients if item["status"] == config.STATUS_TRIGGER
    ]
    meta = config.STATUS_META[status]
    slot_meta = next((slot for slot in config.MEAL_SLOTS if slot["key"] == idea["slot"]), None)
    return {
        "id": idea["id"],
        "slot": idea["slot"],
        "slot_label": slot_meta["label"] if slot_meta else idea["slot"],
        "slot_icon": slot_meta["icon"] if slot_meta else "🍽",
        "time_hint": slot_meta["time_hint"] if slot_meta else "",
        "title": idea["title"],
        "recipe": idea["recipe"],
        "ingredients": ingredients,
        "ingredient_names": idea["ingredients"],
        "status": status,
        "status_label": meta["label"],
        "status_icon": meta["icon"],
        "tone": meta["tone"],
        "blocking": blocking,
        "ok": status != config.STATUS_TRIGGER,
    }


def _foods_by_name() -> dict[str, dict]:
    rows = db.fetch_all(f"SELECT * FROM {models.FOODS}")
    return {models.row_to_food(row)["name"].lower(): models.row_to_food(row) for row in rows}


def list_meal_ideas(active_tags: list[str] | None = None, slot: str | None = None) -> dict:
    if active_tags is None:
        active_tags = get_profile()["active_tags"]
    active_tags = [tag for tag in active_tags if tag in config.RESTRICTION_TAGS]
    foods_by_name = _foods_by_name()

    rows = db.fetch_all(f"SELECT * FROM {models.MEAL_IDEAS} ORDER BY sort_order, id")
    ideas = [dish_view(models.row_to_meal_idea(row), foods_by_name, active_tags) for row in rows]
    if slot and slot in config.MEAL_SLOT_KEYS:
        ideas = [idea for idea in ideas if idea["slot"] == slot]

    return {
        "ideas": ideas,
        "slots": config.MEAL_SLOTS,
        "active_tags": active_tags,
        "available": sum(1 for idea in ideas if idea["ok"]),
        "total": len(ideas),
    }


def generate_menu(profile_id: int | None = None, for_date: Any = None, per_slot: int = 2) -> dict:
    """
    Build a safe day plan for the profile's active tags.

    Deterministic for a given (date, tag set) so the plan is reproducible, and
    every excluded product is explained instead of silently dropped.
    """
    profile = get_profile(profile_id)
    active_tags = profile["active_tags"]
    target_date = norm_date(for_date)
    foods_by_name = _foods_by_name()

    rng = random.Random(f"{target_date}|{','.join(sorted(active_tags))}|v{config.APP_VERSION}")

    rows = db.fetch_all(f"SELECT * FROM {models.MEAL_IDEAS} ORDER BY sort_order, id")
    all_ideas = [models.row_to_meal_idea(row) for row in rows]

    slots: list[dict] = []
    safe_titles: list[str] = []
    for slot_meta in config.MEAL_SLOTS:
        candidates = [idea for idea in all_ideas if idea["slot"] == slot_meta["key"]]
        views = [dish_view(idea, foods_by_name, active_tags) for idea in candidates]

        allowed = [view for view in views if view["status"] == config.STATUS_SAFE]
        caution = [view for view in views if view["status"] == config.STATUS_CAUTION]
        blocked = [view for view in views if view["status"] == config.STATUS_TRIGGER]

        pool = allowed or caution
        if pool:
            picks = rng.sample(pool, k=min(per_slot, len(pool)))
        else:
            picks = []

        for pick in picks:
            role = "Основное блюдо" if len(picks) == 1 else "Вариант"
            safe_titles.append(pick["title"])
            pick["role"] = role

        slots.append({
            "key": slot_meta["key"],
            "label": slot_meta["label"],
            "icon": slot_meta["icon"],
            "time_hint": slot_meta["time_hint"],
            "dishes": picks,
            "blocked_count": len(blocked),
            "caution_count": len(caution),
            "has_safe_options": bool(allowed),
            "fallback_used": not allowed and bool(caution),
            "message": (
                "Подобраны блюда, полностью подходящие под ваши теги."
                if allowed else
                "Полностью безопасных блюд для этого приёма нет — варианты «осторожно» собраны из допустимых ингредиентов."
                if caution else
                "Нет блюд, подходящих под ваши ограничения. Проверьте каталог продуктов."
            ),
        })

    # What was removed from the day and why — the educational part.
    excluded_rows = db.fetch_all(f"SELECT * FROM {models.FOODS} WHERE is_drug = 0 ORDER BY sort_order, name")
    excluded: list[dict] = []
    for row in excluded_rows:
        view = food_view(models.row_to_food(row), active_tags)
        if view["status"] == config.STATUS_TRIGGER:
            excluded.append({
                "name": view["name"],
                "category": view["category"],
                "tags": view["violated_tags"],
                "reasons": view["reasons"],
            })

    by_tag: dict[str, dict] = {}
    for item in excluded:
        for reason in item["reasons"]:
            bucket = by_tag.setdefault(reason["tag"], {
                "tag": reason["tag"],
                "tag_label": reason["tag_label"],
                "tag_short": reason["tag_short"],
                "tag_icon": reason["tag_icon"],
                "items": [],
            })
            bucket["items"].append(item["name"])

    safe_foods = [food_view(models.row_to_food(row), active_tags)
                  for row in db.fetch_all(f"SELECT * FROM {models.FOODS} WHERE is_drug = 0 ORDER BY sort_order, name")]

    return {
        "date": target_date,
        "profile": {"id": profile["id"], "name": profile["name"], "active_tags": active_tags},
        "active_tags": active_tags,
        "tags": [{"id": tag, **config.RESTRICTION_TAGS[tag]} for tag in active_tags],
        "slots": slots,
        "planned_dishes": len(safe_titles),
        "excluded": excluded,
        "excluded_by_tag": list(by_tag.values()),
        "excluded_count": len(excluded),
        "allowed_count": sum(1 for item in safe_foods if item["status"] == config.STATUS_SAFE),
        "caution_count": sum(1 for item in safe_foods if item["status"] == config.STATUS_CAUTION),
        "water_goal": water_goal(),
        "memo": profile["medical_memo"],
        "rules_reminder": [
            "Есть медленно, небольшими порциями, 4–5 раз в день.",
            "Последний приём пищи — за 3 часа до сна.",
            "Не запивать еду большим объёмом жидкости, пить между приёмами.",
            "Новые продукты вводить по одному, чтобы видеть реакцию.",
        ],
        "disclaimer": config.DISCLAIMER,
    }


# --------------------------------------------------------------------------- #
# Symptom log
# --------------------------------------------------------------------------- #
def upsert_symptom_log(profile_id: int | None, payload: dict) -> dict:
    profile = get_profile(profile_id)
    if not profile["id"]:
        raise ValueError("Профиль не найден")
    log_date = norm_date(payload.get("log_date"))
    stamp = db.now_iso()
    stool_values = {option["value"] for option in config.STOOL_OPTIONS}
    stool = clean_str(payload.get("stool"), 20) or "unknown"
    if stool not in stool_values:
        stool = "unknown"

    db.execute(
        f"""INSERT INTO {models.SYMPTOM_LOGS}
              (profile_id, log_date, bloating, heaviness, heartburn, reflux_cough, pain,
               stool, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id, log_date) DO UPDATE SET
               bloating = excluded.bloating,
               heaviness = excluded.heaviness,
               heartburn = excluded.heartburn,
               reflux_cough = excluded.reflux_cough,
               pain = excluded.pain,
               stool = excluded.stool,
               note = excluded.note,
               updated_at = excluded.updated_at""",
        (
            profile["id"], log_date,
            clamp_int(payload.get("bloating"), 0, 3),
            clamp_int(payload.get("heaviness"), 0, 3),
            clamp_int(payload.get("heartburn"), 0, 3),
            clamp_int(payload.get("reflux_cough"), 0, 3),
            clamp_int(payload.get("pain"), 0, 3),
            stool,
            clean_str(payload.get("note"), 2000),
            stamp, stamp,
        ),
    )
    return get_symptom_log(profile["id"], log_date) or {}


def get_symptom_log(profile_id: int | None, log_date: Any) -> dict | None:
    profile = get_profile(profile_id)
    row = db.fetch_one(
        f"SELECT * FROM {models.SYMPTOM_LOGS} WHERE profile_id = ? AND log_date = ?",
        (profile["id"], norm_date(log_date)),
    )
    return models.row_to_symptom(row) if row else None


def list_symptom_logs(profile_id: int | None, date_from: Any, date_to: Any) -> list[dict]:
    profile = get_profile(profile_id)
    start, end = date_range(date_from, date_to)
    rows = db.fetch_all(
        f"""SELECT * FROM {models.SYMPTOM_LOGS}
            WHERE profile_id = ? AND log_date BETWEEN ? AND ?
            ORDER BY log_date""",
        (profile["id"], start, end),
    )
    return [models.row_to_symptom(row) for row in rows]


def delete_symptom_log(profile_id: int | None, log_date: Any) -> bool:
    profile = get_profile(profile_id)
    cursor = db.execute(
        f"DELETE FROM {models.SYMPTOM_LOGS} WHERE profile_id = ? AND log_date = ?",
        (profile["id"], norm_date(log_date)),
    )
    return bool(cursor.rowcount)


# --------------------------------------------------------------------------- #
# Headache tracker
# --------------------------------------------------------------------------- #
def add_headache(profile_id: int | None, payload: dict) -> dict:
    profile = get_profile(profile_id)
    if not profile["id"]:
        raise ValueError("Профиль не найден")

    log_date = norm_date(payload.get("log_date"))
    side = clean_str(payload.get("side"), 20) or "none"
    if side not in {option["value"] for option in config.HEADACHE_SIDES}:
        side = "none"
    intensity = clamp_int(payload.get("intensity"), 0, 10)

    # Пустой эпизод не должен попадать ни в статистику, ни в отчёт: запись
    # «Нет боли, 4/10» — это не приступ, а незаполненная форма.
    if side == "none" or intensity < 1:
        raise ValueError(
            "Эпизод не сохранён: укажите сторону головной боли и интенсивность "
            "от 1 до 10. Запись «Нет боли» в дневник не попадает."
        )

    triggers = payload.get("triggers")
    triggers = [clean_str(item, 60) for item in triggers if clean_str(item, 60)] if isinstance(triggers, list) else []

    medication_id = payload.get("medication_id")
    medication_id = int(medication_id) if str(medication_id or "").strip().isdigit() else None
    dose = clean_str(payload.get("dose"), 120)
    medication_name = clean_str(payload.get("medication"), 160)

    # Fill the name from the medications reference when only an id was sent.
    if medication_id and not medication_name:
        med = get_medication(medication_id)
        if med:
            medication_name = med["name"]
            dose = dose or med["dose"]

    relief = payload.get("relief")
    relief = None if relief in (None, "") else clamp_int(relief, 0, 10)

    headache_id = db.insert(
        f"""INSERT INTO {models.HEADACHE_LOGS}
            (profile_id, log_date, log_time, side, intensity, duration_hours, triggers,
             medication, medication_id, dose, relief, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            profile["id"], log_date,
            clean_str(payload.get("log_time"), 10),
            side,
            intensity,
            clamp_float(payload.get("duration_hours"), 0, 240),
            models.json_dumps(triggers),
            medication_name, medication_id, dose, relief,
            clean_str(payload.get("note"), 2000),
            db.now_iso(),
        ),
    )

    intake = None
    if payload.get("log_intake") and medication_name:
        intake = add_intake(profile["id"], {
            "name": medication_name,
            "dose": dose,
            "medication_id": medication_id,
            "reason": "Головная боль",
            "intake_date": log_date,
        })
        if intake:
            db.execute(
                f"UPDATE {models.HEADACHE_LOGS} SET medication_id = ? WHERE id = ? AND medication_id IS NULL",
                (intake.get("medication_id"), headache_id),
            )
            db.execute(
                f"UPDATE {models.MEDICATION_INTAKES} SET headache_id = ? WHERE id = ?",
                (headache_id, intake["id"]),
            )
            # Re-read so the response reflects the link that was just stored.
            row = db.fetch_one(f"SELECT * FROM {models.MEDICATION_INTAKES} WHERE id = ?",
                               (intake["id"],))
            intake = models.row_to_intake(row) if row else intake
    return {"headache": get_headache(headache_id) or {}, "intake": intake}


def get_headache(headache_id: int) -> dict | None:
    row = db.fetch_one(f"SELECT * FROM {models.HEADACHE_LOGS} WHERE id = ?", (headache_id,))
    return models.row_to_headache(row) if row else None


def list_headaches(profile_id: int | None, date_from: Any, date_to: Any) -> list[dict]:
    profile = get_profile(profile_id)
    start, end = date_range(date_from, date_to)
    rows = db.fetch_all(
        f"""SELECT * FROM {models.HEADACHE_LOGS}
            WHERE profile_id = ? AND log_date BETWEEN ? AND ?
            ORDER BY log_date DESC, id DESC""",
        (profile["id"], start, end),
    )
    return [models.row_to_headache(row) for row in rows]


def delete_headache(profile_id: int | None, headache_id: int) -> bool:
    profile = get_profile(profile_id)
    db.execute(
        f"UPDATE {models.MEDICATION_INTAKES} SET headache_id = NULL WHERE headache_id = ?",
        (headache_id,),
    )
    cursor = db.execute(
        f"DELETE FROM {models.HEADACHE_LOGS} WHERE id = ? AND profile_id = ?",
        (headache_id, profile["id"]),
    )
    return bool(cursor.rowcount)


# --------------------------------------------------------------------------- #
# Medication intakes + NSAID counter
# --------------------------------------------------------------------------- #
def add_intake(profile_id: int | None, payload: dict) -> dict:
    profile = get_profile(profile_id)
    if not profile["id"]:
        raise ValueError("Профиль не найден")

    name = clean_str(payload.get("name"), 160)
    medication_id = payload.get("medication_id")
    medication_id = int(medication_id) if str(medication_id or "").strip().isdigit() else None
    dose = clean_str(payload.get("dose"), 120)

    med = get_medication(medication_id) if medication_id else None
    if med and not name:
        name = med["name"]
    if not name:
        raise ValueError("Укажите препарат")

    override = payload.get("is_nsaid")
    if override is None:
        is_nsaid = bool(med["is_nsaid"]) if med else config.looks_like_nsaid(name)
    else:
        is_nsaid = bool(override) or config.looks_like_nsaid(name)
    is_analgesic = bool(med["is_analgesic"]) if med else config.looks_like_analgesic(name)
    is_analgesic = is_analgesic or config.looks_like_analgesic(name)

    intake_id = db.insert(
        f"""INSERT INTO {models.MEDICATION_INTAKES}
            (profile_id, medication_id, name, dose, is_nsaid, is_analgesic, reason,
             intake_date, headache_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            profile["id"], medication_id, name, dose,
            1 if is_nsaid else 0, 1 if is_analgesic else 0,
            clean_str(payload.get("reason"), 200),
            norm_date(payload.get("intake_date")),
            payload.get("headache_id"),
            db.now_iso(),
        ),
    )
    row = db.fetch_one(f"SELECT * FROM {models.MEDICATION_INTAKES} WHERE id = ?", (intake_id,))
    return models.row_to_intake(row) if row else {}


def list_intakes(profile_id: int | None, date_from: Any, date_to: Any) -> list[dict]:
    profile = get_profile(profile_id)
    start, end = date_range(date_from, date_to)
    rows = db.fetch_all(
        f"""SELECT * FROM {models.MEDICATION_INTAKES}
            WHERE profile_id = ? AND intake_date BETWEEN ? AND ?
            ORDER BY intake_date DESC, id DESC""",
        (profile["id"], start, end),
    )
    return [models.row_to_intake(row) for row in rows]


def delete_intake(profile_id: int | None, intake_id: int) -> bool:
    profile = get_profile(profile_id)
    cursor = db.execute(
        f"DELETE FROM {models.MEDICATION_INTAKES} WHERE id = ? AND profile_id = ?",
        (intake_id, profile["id"]),
    )
    return bool(cursor.rowcount)


def nsaid_summary(profile_id: int | None = None, days: int = config.NSIAD_WINDOW_DAYS,
                  end_date: Any = None) -> dict:
    """
    Rolling NSAID counter.

    Counts *days with an intake* as well as the raw number of tablets, because
    medication-overuse headache depends on the number of medication days.
    """
    profile = get_profile(profile_id)
    active_tags = profile["active_tags"]
    end = norm_date(end_date)
    window_days = clamp_int(days, 7, 180, config.NSIAD_WINDOW_DAYS)
    start = (date_cls.fromisoformat(end) - timedelta(days=window_days - 1)).isoformat()

    rows = db.fetch_all(
        f"""SELECT * FROM {models.MEDICATION_INTAKES}
            WHERE profile_id = ? AND intake_date BETWEEN ? AND ?""",
        (profile["id"], start, end),
    )
    intakes = [models.row_to_intake(row) for row in rows]
    nsaid = [item for item in intakes if item["is_nsaid"]]
    analgesic = [item for item in intakes if item["is_nsaid"] or item["is_analgesic"]]

    per_day: dict[str, int] = {}
    for item in nsaid:
        per_day[item["intake_date"]] = per_day.get(item["intake_date"], 0) + 1
    analgesic_days = {item["intake_date"] for item in analgesic}

    count = len(nsaid)
    days_with = len(per_day)

    if count <= config.NSIAD_THRESHOLD_OK and days_with < config.NSIAD_MOH_DAYS_LIMIT:
        level = "ok"
    elif count <= config.NSIAD_THRESHOLD_WARN and days_with < config.NSIAD_MOH_DAYS_LIMIT:
        level = "attention"
    else:
        level = "risk"

    intakes_word = config.plural_ru(count, "приём", "приёма", "приёмов")
    days_word = config.plural_ru(window_days, "день", "дня", "дней")
    messages = {
        "ok": f"{count} {intakes_word} НПВС за {window_days} {days_word} — спокойный диапазон.",
        "attention": (f"{count} {intakes_word} НПВС за {window_days} {days_word}. Уже стоит обсудить "
                      f"с врачом, чем заменять обезболивающее и что делать для профилактики."),
        "risk": (f"{count} {intakes_word} НПВС за {window_days} {days_word} — повышенный риск. "
                 f"Нужен разговор с врачом о профилактическом лечении, а не о новых таблетках."),
    }

    warnings: list[dict] = []
    if "gerd" in active_tags:
        warnings.append({
            "tag": "gerd", "tag_short": "Желудок",
            "text": "НПВС повреждают защитный слой слизистой: риск гастрита и кровотечения.",
        })
    if "low_purine" in active_tags:
        warnings.append({
            "tag": "low_purine", "tag_short": "Пурины/почки",
            "text": "НПВС снижают почечный клиренс уратов и задерживают жидкость.",
        })
    if "migraine_control" in active_tags:
        warnings.append({
            "tag": "migraine_control", "tag_short": "Мигрень",
            "text": "Приём обезболивающих 10+ дней в месяц сам поддерживает головную боль (абузус).",
        })
    if "cardio_caution" in active_tags:
        warnings.append({
            "tag": "cardio_caution", "tag_short": "Кардио",
            "text": "НПВС повышают давление и риск сердечно-сосудистых событий — сверьте с кардиологом.",
        })
    if not warnings:
        warnings.append({
            "tag": None, "tag_short": "Общее",
            "text": "Любые обезболивающие при частом приёме перестают работать и вредят желудку и почкам.",
        })

    moh = {
        "nsaid_days": days_with,
        "analgesic_days": len(analgesic_days),
        "nsaid_limit": config.NSIAD_MOH_DAYS_LIMIT,
        "analgesic_limit": config.ANALGESIC_MOH_DAYS_LIMIT,
        "nsaid_overuse": days_with >= config.NSIAD_MOH_DAYS_LIMIT,
        "analgesic_overuse": len(analgesic_days) >= config.ANALGESIC_MOH_DAYS_LIMIT,
    }
    if moh["nsaid_overuse"]:
        messages["risk"] += (f" Дней с НПВС: {days_with} — достигнут порог абузусной "
                             f"головной боли ({config.NSIAD_MOH_DAYS_LIMIT} дней).")

    return {
        "level": level,
        "level_label": config.WARNING_LEVELS[level]["label"],
        "tone": config.WARNING_LEVELS[level]["tone"],
        "count": count,
        "days_with_intake": days_with,
        "window_days": window_days,
        "message": messages[level],
        "warnings": warnings,
        "moh": moh,
        "window": {"from": start, "to": end},
        "per_day": [{"date": day, "count": per_day.get(day, 0)} for day in _step_dates(start, end)],
        "heatmap": [{"date": day, "count": per_day.get(day, 0)} for day in _step_dates(start, end)],
        "intakes": nsaid[:50],
        "last_intake": nsaid[0]["intake_date"] if nsaid else None,
        "thresholds": {
            "ok": config.NSIAD_THRESHOLD_OK,
            "warn": config.NSIAD_THRESHOLD_WARN,
            "moh_days": config.NSIAD_MOH_DAYS_LIMIT,
        },
    }


# --------------------------------------------------------------------------- #
# Adherence checklist + water
# --------------------------------------------------------------------------- #
def medication_checklist(profile_id: int | None, for_date: Any) -> dict:
    profile = get_profile(profile_id)
    target = norm_date(for_date)
    meds = list_medications(profile["id"], active_only=True)
    rows = db.fetch_all(
        f"""SELECT * FROM {models.MEDICATION_CHECKS}
            WHERE profile_id = ? AND check_date = ?""",
        (profile["id"], target),
    )
    taken_map = {row["medication_id"]: models.row_to_check(row) for row in rows}

    items: list[dict] = []
    for med in meds:
        check = taken_map.get(med["id"])
        items.append({
            **med,
            "taken": bool(check["taken"]) if check else False,
            "taken_at": check["taken_at"] if check else "",
        })

    return {
        "date": target,
        "items": items,
        "taken_count": sum(1 for item in items if item["taken"]),
        "total": len(items),
    }


def set_medication_check(profile_id: int | None, payload: dict) -> dict:
    profile = get_profile(profile_id)
    if not profile["id"]:
        raise ValueError("Профиль не найден")
    medication_id = payload.get("medication_id")
    medication_id = int(medication_id) if str(medication_id or "").strip().isdigit() else 0
    med = get_medication(medication_id)
    if not med or med["profile_id"] != profile["id"]:
        raise ValueError("Препарат не найден")

    target = norm_date(payload.get("check_date"))
    taken = payload.get("taken", True)
    taken = True if taken in (True, "true", "1", 1) else False

    db.execute(
        f"""INSERT INTO {models.MEDICATION_CHECKS}
              (profile_id, medication_id, check_date, taken, taken_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(medication_id, check_date) DO UPDATE SET
              taken = excluded.taken, taken_at = excluded.taken_at""",
        (profile["id"], medication_id, target, 1 if taken else 0,
         db.now_iso() if taken else ""),
    )
    return medication_checklist(profile["id"], target)


def adherence_summary(profile_id: int | None, date_from: Any, date_to: Any) -> list[dict]:
    profile = get_profile(profile_id)
    start, end = date_range(date_from, date_to)
    days = len(_step_dates(start, end))
    meds = list_medications(profile["id"], active_only=True)
    rows = db.fetch_all(
        f"""SELECT medication_id, SUM(taken) AS taken_days
            FROM {models.MEDICATION_CHECKS}
            WHERE profile_id = ? AND check_date BETWEEN ? AND ?
            GROUP BY medication_id""",
        (profile["id"], start, end),
    )
    taken_map = {row["medication_id"]: int(row["taken_days"] or 0) for row in rows}

    result: list[dict] = []
    for med in meds:
        taken_days = taken_map.get(med["id"], 0)
        percent = round(taken_days * 100 / days) if days else 0
        result.append({
            "medication_id": med["id"],
            "name": med["name"],
            "dose": med["dose"],
            "schedule": med["schedule"],
            "purpose": med["purpose"],
            "is_nsaid": med["is_nsaid"],
            "taken_days": taken_days,
            "days": days,
            "percent": percent,
            "tone": "safe" if percent >= 80 else ("caution" if percent >= 50 else "trigger"),
        })
    return result


def get_water(profile_id: int | None, for_date: Any) -> dict:
    profile = get_profile(profile_id)
    target = norm_date(for_date)
    row = db.fetch_one(
        f"SELECT * FROM {models.WATER_LOGS} WHERE profile_id = ? AND log_date = ?",
        (profile["id"], target),
    )
    goal = water_goal()
    if row is None:
        return {"log_date": target, "glasses": 0, "goal": goal, "percent": 0,
                "reached": False, "remaining": goal}
    data = models.row_to_water(row)
    glasses = min(data["glasses"], 40)
    return {
        "log_date": target,
        "glasses": glasses,
        "goal": data["goal"] or goal,
        "percent": min(100, round(glasses * 100 / (data["goal"] or goal))),
        "reached": glasses >= (data["goal"] or goal),
        "remaining": max(0, (data["goal"] or goal) - glasses),
    }


def set_water(profile_id: int | None, payload: dict) -> dict:
    profile = get_profile(profile_id)
    if not profile["id"]:
        raise ValueError("Профиль не найден")
    target = norm_date(payload.get("log_date"))
    goal = clamp_int(payload.get("goal"), 1, 40, water_goal())

    if payload.get("glasses") is None and payload.get("delta") is not None:
        current = get_water(profile["id"], target)["glasses"]
        glasses = clamp_int(current + clamp_int(payload.get("delta"), -40, 40), 0, 40)
    else:
        glasses = clamp_int(payload.get("glasses"), 0, 40)

    db.execute(
        f"""INSERT INTO {models.WATER_LOGS} (profile_id, log_date, glasses, goal)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(profile_id, log_date) DO UPDATE SET
              glasses = excluded.glasses, goal = excluded.goal""",
        (profile["id"], target, glasses, goal),
    )
    return get_water(profile["id"], target)


# --------------------------------------------------------------------------- #
# Daily snapshot
# --------------------------------------------------------------------------- #
def symptom_score(log: dict | None) -> int:
    if not log:
        return 0
    return sum(int(log.get(key) or 0) for key in ("bloating", "heaviness", "heartburn", "reflux_cough", "pain"))


def today_snapshot(profile_id: int | None = None, for_date: Any = None) -> dict:
    profile = get_profile(profile_id)
    target = norm_date(for_date)
    symptoms = get_symptom_log(profile["id"], target)
    headaches = list_headaches(profile["id"], target, target)
    intakes = list_intakes(profile["id"], target, target)
    return {
        "date": target,
        "profile": profile,
        "symptoms": symptoms,
        "symptom_score": symptom_score(symptoms),
        "headaches": headaches,
        "intakes": intakes,
        "checklist": medication_checklist(profile["id"], target),
        "water": get_water(profile["id"], target),
        "nsaid": nsaid_summary(profile["id"], config.NSIAD_WINDOW_DAYS, target),
        "symptoms_catalog": config.SYMPTOMS,
        "severity_scale": config.SEVERITY_SCALE,
        "stool_options": config.STOOL_OPTIONS,
        "headache_sides": config.HEADACHE_SIDES,
    }


# --------------------------------------------------------------------------- #
# Report for the doctor
# --------------------------------------------------------------------------- #
def build_report(profile_id: int | None = None, date_from: Any = None, date_to: Any = None) -> dict:
    profile = get_profile(profile_id)
    start, end = date_range(date_from, date_to)
    days = _step_dates(start, end)
    day_count = len(days)

    symptoms = list_symptom_logs(profile["id"], start, end)
    by_date = {item["log_date"]: item for item in symptoms}
    headaches = list_headaches(profile["id"], start, end)
    intakes = list_intakes(profile["id"], start, end)
    nsaid = nsaid_summary(profile["id"], config.NSIAD_WINDOW_DAYS, end)

    # ---- symptom aggregates
    symptom_stats: list[dict] = []
    for symptom in config.SYMPTOMS:
        key = symptom["key"]
        values = [int(item[key] or 0) for item in symptoms]
        days_any = sum(1 for value in values if value > 0)
        days_strong = sum(1 for value in values if value >= 2)
        symptom_stats.append({
            "key": key,
            "label": symptom["label"],
            "hint": symptom["hint"],
            "tags": symptom["tags"],
            "avg": round(sum(values) / len(values), 1) if values else 0,
            "max": max(values) if values else 0,
            "days_any": days_any,
            "days_strong": days_strong,
            "percent_any": round(days_any * 100 / day_count) if day_count else 0,
            "percent_strong": round(days_strong * 100 / day_count) if day_count else 0,
            "tone": "trigger" if day_count and days_strong * 100 / day_count >= 40
                    else ("caution" if days_any else "safe"),
        })

    stool_counts: list[dict] = []
    for option in config.STOOL_OPTIONS:
        count = sum(1 for item in symptoms if item["stool"] == option["value"])
        if count:
            stool_counts.append({
                "value": option["value"], "label": option["label"],
                "count": count, "tone": option["tone"],
                "percent": round(count * 100 / day_count) if day_count else 0,
            })

    # ---- headache aggregates
    intensities = [item["intensity"] for item in headaches if item["intensity"]]
    headache_days = sorted({item["log_date"] for item in headaches})
    side_counts: dict[str, int] = {}
    for item in headaches:
        side_counts[item["side"]] = side_counts.get(item["side"], 0) + 1
    side_labels = {option["value"]: option["label"] for option in config.HEADACHE_SIDES}
    headache_summary = {
        "episodes": len(headaches),
        "days": len(headache_days),
        "percent_days": round(len(headache_days) * 100 / day_count) if day_count else 0,
        "avg_intensity": round(sum(intensities) / len(intensities), 1) if intensities else 0,
        "max_intensity": max(intensities) if intensities else 0,
        "avg_duration": round(sum(item["duration_hours"] for item in headaches) / len(headaches), 1) if headaches else 0,
        "with_medication": sum(1 for item in headaches if item["medication"]),
        "sides": [{"value": value, "label": side_labels.get(value, value), "count": count}
                  for value, count in sorted(side_counts.items(), key=lambda pair: -pair[1])],
        "tone": "trigger" if day_count and len(headache_days) * 100 / day_count >= 30
                else ("caution" if headache_days else "safe"),
    }

    # ---- water
    water_rows = db.fetch_all(
        f"""SELECT * FROM {models.WATER_LOGS}
            WHERE profile_id = ? AND log_date BETWEEN ? AND ?""",
        (profile["id"], start, end),
    )
    glasses = [models.row_to_water(row) for row in water_rows]
    water_summary = {
        "logged_days": len(glasses),
        "avg_glasses": round(sum(item["glasses"] for item in glasses) / len(glasses), 1) if glasses else 0,
        "goal_days": sum(1 for item in glasses if item["glasses"] >= (item["goal"] or water_goal())),
        "goal": water_goal(),
        "tone": "safe",
    }
    if water_summary["logged_days"]:
        coverage = water_summary["goal_days"] * 100 / water_summary["logged_days"]
        water_summary["tone"] = "safe" if coverage >= 60 else ("caution" if coverage >= 30 else "trigger")

    # ---- daily table (compact, ready for print)
    rows: list[dict] = []
    intakes_by_day: dict[str, list[dict]] = {}
    for item in intakes:
        intakes_by_day.setdefault(item["intake_date"], []).append(item)
    headaches_by_day: dict[str, list[dict]] = {}
    for item in headaches:
        headaches_by_day.setdefault(item["log_date"], []).append(item)

    for day in days:
        log = by_date.get(day)
        day_headaches = headaches_by_day.get(day, [])
        day_intakes = intakes_by_day.get(day, [])
        if not log and not day_headaches and not day_intakes:
            continue
        rows.append({
            "date": day,
            "bloating": log["bloating"] if log else None,
            "heaviness": log["heaviness"] if log else None,
            "heartburn": log["heartburn"] if log else None,
            "reflux_cough": log["reflux_cough"] if log else None,
            "pain": log["pain"] if log else None,
            "score": symptom_score(log),
            "stool": next((option["label"] for option in config.STOOL_OPTIONS
                           if option["value"] == (log["stool"] if log else "unknown")), "—"),
            "headache": "; ".join(
                f"{side_labels.get(item['side'], item['side'])}, {item['intensity']}/10"
                for item in day_headaches
            ) or "—",
            "medications": "; ".join(
                f"{item['name']} {item['dose']}".strip() for item in day_intakes
            ) or "—",
            "nsaid_flag": any(item["is_nsaid"] for item in day_intakes),
            "note": " ".join(filter(None, [log["note"] if log else "", *[item["note"] for item in day_headaches]]))[:300],
        })

    observations: list[str] = []
    for stat in symptom_stats:
        if stat["days_any"]:
            observations.append(
                f"{stat['label']}: отмечено в {stat['percent_any']}% дней, "
                f"выраженно (2–3 балла) — в {stat['percent_strong']}%."
            )
    if headache_summary["episodes"]:
        episodes = headache_summary["episodes"]
        headache_days = headache_summary["days"]
        observations.append(
            f"Головная боль: {episodes} "
            f"{config.plural_ru(episodes, 'эпизод', 'эпизода', 'эпизодов')} за "
            f"{headache_days} {config.plural_ru(headache_days, 'день', 'дня', 'дней')}, "
            f"средняя интенсивность {headache_summary['avg_intensity']}/10."
        )
    observations.append(nsaid["message"])
    if water_summary["logged_days"]:
        observations.append(
            f"Вода: в среднем {config.glasses_ru(water_summary['avg_glasses'])} "
            f"в дни с записями, цель достигнута в {water_summary['goal_days']} из "
            f"{water_summary['logged_days']} "
            f"{config.plural_ru(water_summary['logged_days'], 'дня', 'дней', 'дней')}."
        )
    if not rows:
        observations.append("За выбранный период записи в дневнике отсутствуют.")

    return {
        "generated_at": db.now_iso(),
        "period": {"from": start, "to": end, "days": day_count},
        "profile": profile,
        "tags": [{"id": tag, **config.RESTRICTION_TAGS[tag]} for tag in profile["active_tags"]],
        "medical_memo": profile["medical_memo"],
        "medications": adherence_summary(profile["id"], start, end),
        "symptom_stats": symptom_stats,
        "stool": stool_counts,
        "headache": headache_summary,
        "headaches": headaches,
        "nsaid": nsaid,
        "intakes": intakes,
        "water": water_summary,
        "rows": rows,
        "logged_days": len(rows),
        "observations": observations,
        "disclaimer": config.DISCLAIMER,
        "app": {"name": config.APP_NAME, "version": config.APP_VERSION},
    }


# --------------------------------------------------------------------------- #
# Bootstrap payload for the UI
# --------------------------------------------------------------------------- #
def bootstrap() -> dict:
    profile = get_profile()
    info = db.db_info()

    # How many catalog items each tag would exclude *on its own* — lets the
    # settings screen show the weight of every restriction before switching it on.
    food_rows = db.fetch_all(f"SELECT * FROM {models.FOODS} WHERE is_drug = 0")
    parsed = [models.row_to_food(row) for row in food_rows]
    tag_impact = {
        tag: sum(1 for food in parsed
                 if evaluate_rules(food["tag_rules"], [tag])["status"] == config.STATUS_TRIGGER)
        for tag in config.ALL_TAG_IDS
    }

    return {
        "app": {
            "name": config.APP_NAME,
            "version": config.APP_VERSION,
            "tagline": config.APP_TAGLINE,
        },
        "profile": profile,
        "tags": tag_catalog(),
        "tag_impact": tag_impact,
        "statuses": config.STATUS_META,
        "symptoms": config.SYMPTOMS,
        "severity_scale": config.SEVERITY_SCALE,
        "stool_options": config.STOOL_OPTIONS,
        "headache_sides": config.HEADACHE_SIDES,
        "meal_slots": config.MEAL_SLOTS,
        "medications": list_medications(profile["id"]),
        "water_goal": water_goal(),
        "nsaid_window_days": config.NSIAD_WINDOW_DAYS,
        "nsaid_thresholds": {
            "ok": config.NSIAD_THRESHOLD_OK,
            "warn": config.NSIAD_THRESHOLD_WARN,
            "moh_days": config.NSIAD_MOH_DAYS_LIMIT,
        },
        "food_count": sum(1 for food in parsed),
        "default_memo": config.DEFAULT_MEDICAL_MEMO,
        "disclaimer": config.DISCLAIMER,
        "today": db.today_iso(),
        "db": info,
        "needs_seed": not info["profiles"] or not profile["id"],
    }
