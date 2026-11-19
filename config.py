"""
config.py — Configuration of the personal diary app.

Nothing about a concrete person's diagnosis lives in the code. Instead the app
ships a catalog of modular *restriction tags* (`gerd`, `low_fodmap`, ...).
A user activates the combination that matches their own medical situation and
every screen (product traffic light, menu generator, report) adapts to it.

Environment variables (all optional):
    APP_DATA_DIR       directory for the SQLite file          (default ./data)
    APP_DB_PATH        full path to the SQLite file
    APP_PROFILE_JSON   path to a personal JSON config with the profile + memo
    APP_HOST / APP_PORT  bind address for the launcher
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = Path(os.getenv("APP_DATA_DIR") or (BASE_DIR / "data"))
DB_PATH = Path(os.getenv("APP_DB_PATH") or (DATA_DIR / "diary.db"))

TEMPLATES_DIR = BASE_DIR / "templates"
INDEX_TEMPLATE = TEMPLATES_DIR / "index.html"

# Personal, git-ignored JSON that can override the seeded profile.
PROFILE_JSON_PATH = Path(os.getenv("APP_PROFILE_JSON") or (BASE_DIR / "profile_config.json"))
STATIC_DIR = BASE_DIR / "static"

HOST = os.getenv("APP_HOST", "127.0.0.1")
PORT = int(os.getenv("APP_PORT", "8000"))

APP_NAME = "Дневник питания и самонаблюдения"
APP_VERSION = "1.0.0"
APP_TAGLINE = "Еда, симптомы и лекарства — в одном месте"

# --------------------------------------------------------------------------- #
# Restriction tag catalog (the modular part of the app)
# --------------------------------------------------------------------------- #
# `checks`  — what the tag makes the app look after
# `focus`   — one-line explanation shown in settings
# `color`   — CSS custom property used for the tag chip
RESTRICTION_TAGS: dict[str, dict] = {
    "gerd": {
        "label": "Антирефлюкс / щадящий желудок",
        "short": "Желудок",
        "icon": "🔥",
        "color": "var(--tag-gerd)",
        "focus": "Убирает жирное, кислое, кофеин и газированное, что провоцирует изжогу и рефлюкс.",
        "checks": "изжога, рефлюксный кашель, тяжесть после еды",
    },
    "low_fodmap": {
        "label": "Снижение вздутия (СРК / СИБР)",
        "short": "Вздутие",
        "icon": "🎈",
        "color": "var(--tag-fodmap)",
        "focus": "Ограничивает ферментируемые углеводы: лук, чеснок, капусту, бобовые, часть фруктов.",
        "checks": "вздутие, газообразование, характер стула",
    },
    "low_purine": {
        "label": "Контроль пуринов и нагрузки на почки",
        "short": "Пурины",
        "icon": "🧪",
        "color": "var(--tag-purine)",
        "focus": "Снижает пурины (мясные бульоны, субпродукты, красное мясо, пиво) и лишнюю соль.",
        "checks": "объём выпитой воды, отёки, мочеиспускание",
    },
    "migraine_control": {
        "label": "Дневник головной боли и счётчик НПВС",
        "short": "Мигрень",
        "icon": "🧠",
        "color": "var(--tag-migraine)",
        "focus": "Включает трекер приступов и считает дни приёма обезболивающих за 30 дней.",
        "checks": "сторона и сила боли, принятое лекарство, абузусный риск",
    },
    "cardio_caution": {
        "label": "Проверка кардио-совместимости препаратов",
        "short": "Кардио",
        "icon": "❤️",
        "color": "var(--tag-cardio)",
        "focus": "Помечает препараты и продукты, которые стоит сверить с кардиологом.",
        "checks": "взаимодействия лекарств, соль, артериальное давление",
    },
}

ALL_TAG_IDS: list[str] = list(RESTRICTION_TAGS)

# --------------------------------------------------------------------------- #
# Traffic-light vocabulary
# --------------------------------------------------------------------------- #
STATUS_SAFE = "safe"
STATUS_CAUTION = "caution"
STATUS_TRIGGER = "trigger"

STATUS_META: dict[str, dict] = {
    STATUS_SAFE: {
        "label": "Можно",
        "short": "Можно",
        "icon": "🟢",
        "tone": "safe",
        "explain": "Подходит при всех выбранных ограничениях.",
    },
    STATUS_CAUTION: {
        "label": "Осторожно",
        "short": "Осторожно",
        "icon": "🟡",
        "tone": "caution",
        "explain": "Допустимо небольшой порцией, но следите за реакцией.",
    },
    STATUS_TRIGGER: {
        "label": "Лучше исключить",
        "short": "Исключить",
        "icon": "🔴",
        "tone": "trigger",
        "explain": "Нарушает одно из выбранных ограничений.",
    },
}

# --------------------------------------------------------------------------- #
# Symptoms / scales / options
# --------------------------------------------------------------------------- #
# Each symptom is a 0–3 scale so the daily check-in stays a 20-second action.
SYMPTOMS: list[dict] = [
    {
        "key": "bloating",
        "label": "Вздутие",
        "hint": "Распирание, живот «как барабан»",
        "tags": ["low_fodmap"],
    },
    {
        "key": "heaviness",
        "label": "Тяжесть в животе",
        "hint": "Ощущение переполнения после еды",
        "tags": ["gerd", "low_fodmap"],
    },
    {
        "key": "heartburn",
        "label": "Изжога",
        "hint": "Жжение за грудиной",
        "tags": ["gerd"],
    },
    {
        "key": "reflux_cough",
        "label": "Рефлюксный кашель",
        "hint": "Покашливание ночью или после еды",
        "tags": ["gerd"],
    },
    {
        "key": "pain",
        "label": "Боль / дискомфорт",
        "hint": "Любой болевой эпизод за день",
        "tags": ["gerd", "low_fodmap", "low_purine"],
    },
]

SEVERITY_SCALE: list[dict] = [
    {"value": 0, "label": "Нет", "tone": "safe"},
    {"value": 1, "label": "Слабо", "tone": "safe"},
    {"value": 2, "label": "Средне", "tone": "caution"},
    {"value": 3, "label": "Сильно", "tone": "trigger"},
]

STOOL_OPTIONS: list[dict] = [
    {"value": "unknown", "label": "Не отмечал", "tone": "neutral"},
    {"value": "normal", "label": "Оформленный", "tone": "safe"},
    {"value": "soft", "label": "Мягкий", "tone": "caution"},
    {"value": "loose", "label": "Жидкий", "tone": "trigger"},
    {"value": "hard", "label": "Плотный / сухой", "tone": "caution"},
    {"value": "none", "label": "Не было", "tone": "trigger"},
]

HEADACHE_SIDES: list[dict] = [
    {"value": "none", "label": "Нет боли"},
    {"value": "left", "label": "Слева"},
    {"value": "right", "label": "Справа"},
    {"value": "both", "label": "С двух сторон"},
    {"value": "behind_eyes", "label": "За глазами"},
]

MEAL_SLOTS: list[dict] = [
    {"key": "breakfast", "label": "Завтрак", "icon": "🌅", "time_hint": "08:00–09:00"},
    {"key": "lunch", "label": "Обед", "icon": "🍲", "time_hint": "13:00–14:00"},
    {"key": "dinner", "label": "Ужин", "icon": "🌙", "time_hint": "18:00–19:00"},
    {"key": "tea", "label": "К чаю", "icon": "🍵", "time_hint": "16:00"},
]
MEAL_SLOT_KEYS: list[str] = [slot["key"] for slot in MEAL_SLOTS]

# --------------------------------------------------------------------------- #
# Trackers & safety thresholds
# --------------------------------------------------------------------------- #
WATER_GOAL_DEFAULT = 8
NSIAD_WINDOW_DAYS = 30

# Intakes per rolling 30 days. Medication-overuse headache (MOH) risk starts
# when simple analgesics are taken on >= 10 days a month.
NSIAD_THRESHOLD_OK = 4        # 0–4   -> calm
NSIAD_THRESHOLD_WARN = 9      # 5–9   -> attention
NSIAD_MOH_DAYS_LIMIT = 10     # >=10 days with an intake -> overuse risk
ANALGESIC_MOH_DAYS_LIMIT = 15

WARNING_LEVELS: dict[str, dict] = {
    "ok": {"label": "Спокойно", "tone": "safe"},
    "attention": {"label": "Внимание", "tone": "caution"},
    "risk": {"label": "Повышенный риск", "tone": "trigger"},
}

# --------------------------------------------------------------------------- #
# Safety copy
# --------------------------------------------------------------------------- #
DISCLAIMER = (
    "Этот сервис — личный дневник самонаблюдения. Он помогает замечать связи между "
    "едой, симптомами и лекарствами, но не ставит диагноз, не назначает лечение и не "
    "заменяет врача. Любое изменение препаратов, диеты или дозировок согласуйте со "
    "своим лечащим врачом. При «красных флагах» обращайтесь за медицинской помощью "
    "сразу, не дожидаясь отчёта."
)

DEFAULT_MEDICAL_MEMO = """ПАМЯТКА ПО САМОНАБЛЮДЕНИЮ (редактируется под себя)

1. Регулярные препараты принимать по назначению врача и отмечать каждый приём в чек-листе.
2. Обезболивающие (НПВС) — не чаще 2–3 приёмов в неделю и не более 10 дней в месяц:
   чаще — это риск для желудка, почек и абузусной головной боли.
3. Вода: ориентир 6–8 стаканов в сутки, если врач не ограничил объём жидкости.
4. Есть медленно, 4–5 раз в день небольшими порциями; последний приём — за 3 часа до сна.
5. Новые препараты, БАДы и травяные сборы — только после согласования с врачом,
   особенно если активен тег «проверка кардио-совместимости».

КРАСНЫЕ ФЛАГИ — обратитесь к врачу сразу:
- боль в груди, одышка, перебои в работе сердца;
- кровь в стуле, чёрный стул, рвота кровью или «кофейной гущей»;
- неукротимая рвота, невозможность пить, отёки, резкое уменьшение мочи;
- головная боль «как никогда раньше», с температурой, слабостью или спутанностью;
- температура выше 38,5 °C более двух суток.
"""

# Names recognised as NSAIDs when the user types a medication by hand.
NSAID_NAME_HINTS: tuple[str, ...] = (
    "налгезин", "метамизол", "анальгин", "ибупрофен", "нурофен", "нимесулид",
    "найз", "диклофенак", "кеторолак", "кеторол", "аспирин", "ацетилсалицил",
    "индометацин", "мелоксикам", "мовалис", "целекоксиб", "этоксибенз",
    "декскетопрофен", "напроксен", "пироксикам", "лорноксикам",
)
PARACETAMOL_NAME_HINTS: tuple[str, ...] = ("парацетамол", "панадол", "эффералган", "цитрамон")


def looks_like_nsaid(name: str | None) -> bool:
    """Heuristic used only to pre-fill the NSAID counter, never to prescribe."""
    if not name:
        return False
    needle = name.strip().lower()
    return any(hint in needle for hint in NSAID_NAME_HINTS)


def looks_like_analgesic(name: str | None) -> bool:
    """Paracetamol-class analgesics: gentler on the stomach, still MOH-relevant."""
    if not name:
        return False
    needle = name.strip().lower()
    return any(hint in needle for hint in PARACETAMOL_NAME_HINTS)


# --------------------------------------------------------------------------- #
# Russian numerals
# --------------------------------------------------------------------------- #
def plural_ru(value: object, one: str, few: str, many: str) -> str:
    """
    Pick the correct Russian noun form for a count.

        plural_ru(1, "стакан", "стакана", "стаканов")  -> "стакан"
        plural_ru(3, ...)                              -> "стакана"
        plural_ru(7, ...)                              -> "стаканов"
        plural_ru(5.3, ...)                            -> "стакана"  (дробное)

    After a fraction Russian uses the genitive singular, hence the ``few``
    form for non-integers.
    """
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return many
    if number != int(number):
        return few
    count = abs(int(number))
    if count % 10 == 1 and count % 100 != 11:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many


def glasses_ru(value: object) -> str:
    """«1 стакан», «3 стакана», «7 стаканов» — с числом."""
    return f"{value} {plural_ru(value, 'стакан', 'стакана', 'стаканов')}"


# --------------------------------------------------------------------------- #
# Optional personal JSON config
# --------------------------------------------------------------------------- #
def load_profile_config() -> dict:
    """
    Read an optional `profile_config.json` (git-ignored) that personalises the
    seeded profile without touching the code, e.g.:

        {
          "name": "Мой профиль",
          "active_tags": ["gerd", "low_fodmap"],
          "medical_memo": "текст памятки",
          "medications": [{"name": "Аллопуринол", "dose": "100 мг", "schedule": "утро"}]
        }
    """
    if not PROFILE_JSON_PATH.exists():
        return {}
    try:
        data = json.loads(PROFILE_JSON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - config guard
        print(f"[config] не удалось прочитать {PROFILE_JSON_PATH}: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
