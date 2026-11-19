"""
models.py — Domain schema of the diary.

Two layers live here on purpose:

* ``SCHEMA_SQL``  — the authoritative SQLite DDL (tables + indexes).
* request DTOs     — thin validation models used by the FastAPI layer.

The DB is plain SQLite accessed through ``database.py``; no ORM is required, so
the app keeps working on a bare Python installation.  List-valued columns are
stored as JSON text and decoded by the ``row_to_*`` helpers below.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

# --------------------------------------------------------------------------- #
# Table names
# --------------------------------------------------------------------------- #
PROFILES = "profiles"
MEDICATIONS = "medications"
FOODS = "foods"
MEAL_IDEAS = "meal_ideas"
SYMPTOM_LOGS = "symptom_logs"
HEADACHE_LOGS = "headache_logs"
MEDICATION_INTAKES = "medication_intakes"
MEDICATION_CHECKS = "medication_checks"
WATER_LOGS = "water_logs"
APP_SETTINGS = "app_settings"

# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
SCHEMA_SQL: tuple[str, ...] = (
    # ------------------------------------------------------------------ users
    f"""
    CREATE TABLE IF NOT EXISTS {PROFILES} (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT    NOT NULL,
        active_tags   TEXT    NOT NULL DEFAULT '[]',
        medical_memo  TEXT    NOT NULL DEFAULT '',
        created_at    TEXT    NOT NULL,
        updated_at    TEXT    NOT NULL
    )
    """,
    # ------------------------------------------------------------ medications
    f"""
    CREATE TABLE IF NOT EXISTS {MEDICATIONS} (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id   INTEGER NOT NULL REFERENCES {PROFILES}(id) ON DELETE CASCADE,
        name         TEXT    NOT NULL,
        dose         TEXT    NOT NULL DEFAULT '',
        schedule     TEXT    NOT NULL DEFAULT '',
        times        TEXT    NOT NULL DEFAULT '[]',
        kind         TEXT    NOT NULL DEFAULT 'regular',
        is_nsaid     INTEGER NOT NULL DEFAULT 0,
        is_analgesic INTEGER NOT NULL DEFAULT 0,
        cardio_note  TEXT    NOT NULL DEFAULT '',
        purpose      TEXT    NOT NULL DEFAULT '',
        active       INTEGER NOT NULL DEFAULT 1,
        sort_order   INTEGER NOT NULL DEFAULT 0
    )
    """,
    # ------------------------------------------------------------------ foods
    f"""
    CREATE TABLE IF NOT EXISTS {FOODS} (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT    NOT NULL UNIQUE,
        category   TEXT    NOT NULL DEFAULT 'Прочее',
        note       TEXT    NOT NULL DEFAULT '',
        portion    TEXT    NOT NULL DEFAULT '',
        tag_rules  TEXT    NOT NULL DEFAULT '{{}}',
        is_drug    INTEGER NOT NULL DEFAULT 0,
        sort_order INTEGER NOT NULL DEFAULT 100
    )
    """,
    # ------------------------------------------------------------- meal ideas
    f"""
    CREATE TABLE IF NOT EXISTS {MEAL_IDEAS} (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        slot        TEXT    NOT NULL,
        title       TEXT    NOT NULL,
        recipe      TEXT    NOT NULL DEFAULT '',
        ingredients TEXT    NOT NULL DEFAULT '[]',
        tag_rules   TEXT    NOT NULL DEFAULT '{{}}',
        sort_order  INTEGER NOT NULL DEFAULT 100
    )
    """,
    # ----------------------------------------------------------- symptom logs
    f"""
    CREATE TABLE IF NOT EXISTS {SYMPTOM_LOGS} (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id   INTEGER NOT NULL REFERENCES {PROFILES}(id) ON DELETE CASCADE,
        log_date     TEXT    NOT NULL,
        bloating     INTEGER NOT NULL DEFAULT 0,
        heaviness    INTEGER NOT NULL DEFAULT 0,
        heartburn    INTEGER NOT NULL DEFAULT 0,
        reflux_cough INTEGER NOT NULL DEFAULT 0,
        pain         INTEGER NOT NULL DEFAULT 0,
        stool        TEXT    NOT NULL DEFAULT 'unknown',
        note         TEXT    NOT NULL DEFAULT '',
        created_at   TEXT    NOT NULL,
        updated_at   TEXT    NOT NULL,
        UNIQUE (profile_id, log_date)
    )
    """,
    # ---------------------------------------------------------- headache logs
    f"""
    CREATE TABLE IF NOT EXISTS {HEADACHE_LOGS} (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id     INTEGER NOT NULL REFERENCES {PROFILES}(id) ON DELETE CASCADE,
        log_date       TEXT    NOT NULL,
        log_time       TEXT    NOT NULL DEFAULT '',
        side           TEXT    NOT NULL DEFAULT 'none',
        intensity      INTEGER NOT NULL DEFAULT 0,
        duration_hours REAL    NOT NULL DEFAULT 0,
        triggers       TEXT    NOT NULL DEFAULT '[]',
        medication     TEXT    NOT NULL DEFAULT '',
        medication_id  INTEGER REFERENCES {MEDICATIONS}(id) ON DELETE SET NULL,
        dose           TEXT    NOT NULL DEFAULT '',
        relief         INTEGER,
        note           TEXT    NOT NULL DEFAULT '',
        created_at     TEXT    NOT NULL
    )
    """,
    # ----------------------------------------------------- medication intakes
    f"""
    CREATE TABLE IF NOT EXISTS {MEDICATION_INTAKES} (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id    INTEGER NOT NULL REFERENCES {PROFILES}(id) ON DELETE CASCADE,
        medication_id INTEGER REFERENCES {MEDICATIONS}(id) ON DELETE SET NULL,
        name          TEXT    NOT NULL,
        dose          TEXT    NOT NULL DEFAULT '',
        is_nsaid      INTEGER NOT NULL DEFAULT 0,
        is_analgesic  INTEGER NOT NULL DEFAULT 0,
        reason        TEXT    NOT NULL DEFAULT '',
        intake_date   TEXT    NOT NULL,
        headache_id   INTEGER REFERENCES {HEADACHE_LOGS}(id) ON DELETE SET NULL,
        created_at    TEXT    NOT NULL
    )
    """,
    # ----------------------------------------------------- adherence checks
    f"""
    CREATE TABLE IF NOT EXISTS {MEDICATION_CHECKS} (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id    INTEGER NOT NULL REFERENCES {PROFILES}(id) ON DELETE CASCADE,
        medication_id INTEGER NOT NULL REFERENCES {MEDICATIONS}(id) ON DELETE CASCADE,
        check_date    TEXT    NOT NULL,
        taken         INTEGER NOT NULL DEFAULT 1,
        taken_at      TEXT    NOT NULL DEFAULT '',
        UNIQUE (medication_id, check_date)
    )
    """,
    # ------------------------------------------------------------ water logs
    f"""
    CREATE TABLE IF NOT EXISTS {WATER_LOGS} (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        profile_id INTEGER NOT NULL REFERENCES {PROFILES}(id) ON DELETE CASCADE,
        log_date   TEXT    NOT NULL,
        glasses    INTEGER NOT NULL DEFAULT 0,
        goal       INTEGER NOT NULL DEFAULT 8,
        UNIQUE (profile_id, log_date)
    )
    """,
    # ----------------------------------------------------------- app settings
    f"""
    CREATE TABLE IF NOT EXISTS {APP_SETTINGS} (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)

INDEX_SQL: tuple[str, ...] = (
    f"CREATE INDEX IF NOT EXISTS ix_symptom_profile_date ON {SYMPTOM_LOGS} (profile_id, log_date)",
    f"CREATE INDEX IF NOT EXISTS ix_headache_profile_date ON {HEADACHE_LOGS} (profile_id, log_date)",
    f"CREATE INDEX IF NOT EXISTS ix_intake_profile_date ON {MEDICATION_INTAKES} (profile_id, intake_date)",
    f"CREATE INDEX IF NOT EXISTS ix_check_profile_date ON {MEDICATION_CHECKS} (profile_id, check_date)",
    f"CREATE INDEX IF NOT EXISTS ix_food_category ON {FOODS} (category)",
    f"CREATE INDEX IF NOT EXISTS ix_meal_slot ON {MEAL_IDEAS} (slot)",
)

# --------------------------------------------------------------------------- #
# JSON helpers for text columns
# --------------------------------------------------------------------------- #
def json_loads(raw: Any, fallback: Any) -> Any:
    """Decode a JSON text column, tolerating NULL / legacy garbage."""
    if raw is None or raw == "":
        return fallback
    if isinstance(raw, (list, dict)):
        return raw
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Row mappers
# --------------------------------------------------------------------------- #
def row_to_profile(row: Any) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "active_tags": json_loads(row["active_tags"], []),
        "medical_memo": row["medical_memo"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_medication(row: Any) -> dict:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "name": row["name"],
        "dose": row["dose"] or "",
        "schedule": row["schedule"] or "",
        "times": json_loads(row["times"], []),
        "kind": row["kind"] or "regular",
        "is_nsaid": bool(row["is_nsaid"]),
        "is_analgesic": bool(row["is_analgesic"]),
        "cardio_note": row["cardio_note"] or "",
        "purpose": row["purpose"] or "",
        "active": bool(row["active"]),
        "sort_order": row["sort_order"],
    }


def row_to_food(row: Any) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"] or "Прочее",
        "note": row["note"] or "",
        "portion": row["portion"] or "",
        "tag_rules": json_loads(row["tag_rules"], {}),
        "is_drug": bool(row["is_drug"]),
        "sort_order": row["sort_order"],
    }


def row_to_meal_idea(row: Any) -> dict:
    return {
        "id": row["id"],
        "slot": row["slot"],
        "title": row["title"],
        "recipe": row["recipe"] or "",
        "ingredients": json_loads(row["ingredients"], []),
        "tag_rules": json_loads(row["tag_rules"], {}),
        "sort_order": row["sort_order"],
    }


def row_to_symptom(row: Any) -> dict:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "log_date": row["log_date"],
        "bloating": row["bloating"],
        "heaviness": row["heaviness"],
        "heartburn": row["heartburn"],
        "reflux_cough": row["reflux_cough"],
        "pain": row["pain"],
        "stool": row["stool"] or "unknown",
        "note": row["note"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_headache(row: Any) -> dict:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "log_date": row["log_date"],
        "log_time": row["log_time"] or "",
        "side": row["side"] or "none",
        "intensity": row["intensity"],
        "duration_hours": row["duration_hours"],
        "triggers": json_loads(row["triggers"], []),
        "medication": row["medication"] or "",
        "medication_id": row["medication_id"],
        "dose": row["dose"] or "",
        "relief": row["relief"],
        "note": row["note"] or "",
        "created_at": row["created_at"],
    }


def row_to_intake(row: Any) -> dict:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "medication_id": row["medication_id"],
        "name": row["name"],
        "dose": row["dose"] or "",
        "is_nsaid": bool(row["is_nsaid"]),
        "is_analgesic": bool(row["is_analgesic"]),
        "reason": row["reason"] or "",
        "intake_date": row["intake_date"],
        "headache_id": row["headache_id"],
        "created_at": row["created_at"],
    }


def row_to_check(row: Any) -> dict:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "medication_id": row["medication_id"],
        "check_date": row["check_date"],
        "taken": bool(row["taken"]),
        "taken_at": row["taken_at"] or "",
    }


def row_to_water(row: Any) -> dict:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "log_date": row["log_date"],
        "glasses": row["glasses"],
        "goal": row["goal"],
    }


# --------------------------------------------------------------------------- #
# Request DTOs (optional: only when pydantic is installed)
# --------------------------------------------------------------------------- #
try:  # pragma: no cover - depends on the environment
    from pydantic import BaseModel, Field, field_validator

    _DateStr = str

    class ProfileUpdate(BaseModel):
        name: str | None = Field(default=None, max_length=120)
        active_tags: list[str] | None = None
        medical_memo: str | None = Field(default=None, max_length=20000)

    class MedicationIn(BaseModel):
        name: str = Field(min_length=1, max_length=160)
        dose: str = Field(default="", max_length=120)
        schedule: str = Field(default="", max_length=200)
        times: list[str] = Field(default_factory=list)
        kind: str = Field(default="regular", max_length=40)
        is_nsaid: bool = False
        is_analgesic: bool = False
        cardio_note: str = Field(default="", max_length=500)
        purpose: str = Field(default="", max_length=300)
        active: bool = True
        sort_order: int = 0

    class SymptomLogIn(BaseModel):
        log_date: _DateStr | None = None
        bloating: int = Field(default=0, ge=0, le=3)
        heaviness: int = Field(default=0, ge=0, le=3)
        heartburn: int = Field(default=0, ge=0, le=3)
        reflux_cough: int = Field(default=0, ge=0, le=3)
        pain: int = Field(default=0, ge=0, le=3)
        stool: str = "unknown"
        note: str = Field(default="", max_length=2000)

    class HeadacheIn(BaseModel):
        log_date: _DateStr | None = None
        log_time: str = Field(default="", max_length=10)
        side: str = "none"
        intensity: int = Field(default=0, ge=0, le=10)
        duration_hours: float = Field(default=0, ge=0, le=240)
        triggers: list[str] = Field(default_factory=list)
        medication: str = Field(default="", max_length=160)
        medication_id: int | None = None
        dose: str = Field(default="", max_length=120)
        relief: int | None = Field(default=None, ge=0, le=10)
        note: str = Field(default="", max_length=2000)
        log_intake: bool = False

    class IntakeIn(BaseModel):
        name: str = Field(min_length=1, max_length=160)
        dose: str = Field(default="", max_length=120)
        is_nsaid: bool | None = None
        reason: str = Field(default="", max_length=200)
        intake_date: _DateStr | None = None
        medication_id: int | None = None

    class MedicationCheckIn(BaseModel):
        medication_id: int
        check_date: _DateStr | None = None
        taken: bool = True

    class WaterIn(BaseModel):
        log_date: _DateStr | None = None
        glasses: int = Field(default=0, ge=0, le=40)
        goal: int | None = Field(default=None, ge=1, le=40)

    class ProfileConfigIn(BaseModel):
        """Payload of the optional personal ``profile_config.json``."""

        name: str | None = None
        active_tags: list[str] | None = None
        medical_memo: str | None = None
        medications: list[dict] | None = None

    DTO_NAMES: tuple[str, ...] = (
        "ProfileUpdate", "MedicationIn", "SymptomLogIn", "HeadacheIn",
        "IntakeIn", "MedicationCheckIn", "WaterIn", "ProfileConfigIn",
    )
    HAS_PYDANTIC = True

except ImportError:  # pragma: no cover - stdlib-only environment
    HAS_PYDANTIC = False
    DTO_NAMES = ()


def iter_dtos() -> Iterable[str]:
    return DTO_NAMES
