"""
selftest.py — End-to-end self-test without any third-party dependency.

Boots the stdlib server in-process on a free port, pointing at a throwaway
SQLite file, then walks through every REST route and asserts the behaviour of
the modular restriction system.

    python selftest.py

Exit code 0 means every check passed. The real diary database is not touched.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from datetime import date as dt_date, timedelta as dt_timedelta
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path

# --------------------------------------------------------------------------- #
# Point the app at a throwaway database *before* importing its modules.
# The folder lives next to the project (and is git-ignored) so the test also
# works when the process may not write to the system temp directory.
# --------------------------------------------------------------------------- #
PROJECT_DIR = Path(__file__).resolve().parent
TEMP_DIR = PROJECT_DIR / ".selftest"
if TEMP_DIR.exists():
    shutil.rmtree(TEMP_DIR, ignore_errors=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

import config  # noqa: E402

config.DATA_DIR = TEMP_DIR
config.DB_PATH = TEMP_DIR / "selftest.db"

import database as db  # noqa: E402
import seed_data  # noqa: E402
import run_local  # noqa: E402
import services  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (OSError, ValueError):  # pragma: no cover
        pass

PASSED = 0
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    global PASSED
    if condition:
        PASSED += 1
        print(f"  [ok]   {name}")
    else:
        FAILED.append(name)
        print(f"  [FAIL] {name}{(' — ' + detail) if detail else ''}")
    return bool(condition)


VOID_TAGS = {"meta", "link", "br", "hr", "img", "input", "source", "area",
             "base", "col", "embed", "param", "track", "wbr"}


class TagBalance(HTMLParser):
    """Detects unbalanced tags and quote mistakes that break Alpine markup."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, tuple[int, int]]] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID_TAGS:
            self.stack.append((tag, self.getpos()))

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if not self.stack:
            self.errors.append(f"строка {self.getpos()[0]}: лишний </{tag}>")
            return
        if self.stack[-1][0] != tag:
            opened, position = self.stack[-1]
            self.errors.append(
                f"строка {self.getpos()[0]}: </{tag}> закрывает <{opened}> "
                f"из строки {position[0]}")
            if any(item == tag for item, _ in self.stack):
                while self.stack and self.stack.pop()[0] != tag:
                    pass
        else:
            self.stack.pop()


def static_checks() -> None:
    """Проверки шаблона без браузера: разметка и совпадение с роутерами."""
    print("Статические проверки шаблона")
    template = config.INDEX_TEMPLATE.read_text(encoding="utf-8")

    balance = TagBalance()
    balance.feed(template)
    check("HTML-разметка сбалансирована",
          not balance.errors and not balance.stack,
          f"{balance.errors[:2]} / незакрытые: {[tag for tag, _ in balance.stack]}")

    check("в шаблоне нет Jinja/Vue-скобок (рендерится и FastAPI, и stdlib)",
          not re.search(r"\{\{|\{%", template))

    template_paths = {re.sub(r"\{[^}]+\}", "{id}", path) for path in
                      re.findall(r"""['"`](/api/[a-z0-9\-]+)""", template)}
    check("шаблон вызывает хотя бы один API-маршрут", len(template_paths) > 5,
          str(sorted(template_paths)))

    stdlib_paths = {
        re.sub(r"\(\?P<[^>]+>[^)]+\)", "{id}", pattern.pattern.strip("^$"))
        for _method, pattern, _handler, _status in run_local.ROUTES
    }
    missing = template_paths - stdlib_paths
    check("все вызовы API из шаблона есть в stdlib-роутере", not missing, str(sorted(missing)))

    main_source = (PROJECT_DIR / "main.py").read_text(encoding="utf-8")
    fastapi_paths = {re.sub(r"\{[^}]+\}", "{id}", path) for path in
                     re.findall(r'@app\.(?:get|post|put|delete)\(\s*"(/api/[^"]+)"', main_source)}
    check("FastAPI и stdlib объявляют одинаковый набор маршрутов",
          fastapi_paths == stdlib_paths,
          str(sorted(fastapi_paths.symmetric_difference(stdlib_paths))))

    models_source = (PROJECT_DIR / "models.py").read_text(encoding="utf-8")
    dtos_in_main = set(re.findall(r"models\.([A-Z][A-Za-z0-9_]*)", main_source))
    declared = set(re.findall(r"^\s*([A-Z][A-Za-z0-9_]*)\s*[:=]", models_source, re.M))
    declared |= set(re.findall(r"^\s*class\s+([A-Za-z0-9_]+)", models_source, re.M))
    check("все имена из models.py, используемые main.py, объявлены",
          dtos_in_main <= declared, str(sorted(dtos_in_main - declared)))


def static_ui_checks() -> None:
    """Проверки интерфейса, которые нельзя проверить без браузера."""
    print("\nИнтерфейс: темы, шапка, вёрстка настроек")
    template = config.INDEX_TEMPLATE.read_text(encoding="utf-8")

    # --- регрессия: снимок дня не должен затирать строку даты ---------------
    check("снимок дня хранится в this.snapshot, а не в this.today",
          "this.snapshot = data" in template and "this.today = data" not in template)
    check("в шапке дата выводится в формате «18 ноября 2026»",
          'x-text="todayLabel()"' in template
          and "this.humanDateLong(this.today)" in template)
    check("в шапке не осталось старой склейки «сегодня » + дата",
          "'сегодня ' + humanDate(" not in template)
    check("длинный формат даты знает все месяцы",
          "ноября" in template and "января" in template and "декабря" in template)

    # --- темы ---------------------------------------------------------------
    for theme in ("warm", "light", "dark"):
        check(f"объявлена тема «{theme}»", f'[data-theme="{theme}"]' in template)
    check("тема применяется до первой отрисовки",
          "setAttribute('data-theme', theme)" in template)
    check("выбор темы сохраняется в localStorage",
          "localStorage.setItem('diary-theme'" in template)
    check("выбор темы читается из localStorage",
          "getItem('diary-theme')" in template)
    check("в шапке есть переключатель темы",
          'class="theme-switch"' in template and 'class="theme-btn' in template)
    check("тема «Тёплая» стоит по умолчанию",
          "var theme = 'warm'" in template)
    check("цвета тегов перечитываются при смене темы",
          "this.readTagColors()" in template and "readTagColors()" in template)

    # --- печать всегда светлая, даже в тёмной теме ---------------------------
    print_index = template.find("@media print")
    print_css = template[print_index:print_index + 3000] if print_index != -1 else ""
    check("печать переопределяет палитру темы на светлую",
          "--canvas: #FFFFFF" in print_css and "--ink: #0F172A" in print_css,
          "в @media print нет светлых переменных")
    check("печать печатает на белом листе",
          "background: #FFFFFF !important" in print_css)
    check("@media print идёт после описания тем",
          print_index > template.find('[data-theme="dark"]'))
    check("отчёт в печати без тени и рамки карточки",
          ".print-area" in print_css and "box-shadow: none !important" in print_css)

    # --- вёрстка настроек ---------------------------------------------------
    check("теги-ограничения оформлены сеткой карточек",
          'class="tag-grid"' in template and 'class="tag-card"' in template)
    check("активная карточка тега выделяется",
          "is-active" in template and ".tag-card.is-active" in template)
    check("сетка тегов двухколоночная на широком экране",
          "repeat(2, minmax(0, 1fr))" in template)

    # --- прочее -------------------------------------------------------------
    check("фон и границы карточек берутся из переменных темы",
          "border: 1px solid var(--line-soft)" in template)
    check("переключатель темы доступен с клавиатуры",
          'aria-label="Тема оформления"' in template)

    # --- полнота переменных темы -------------------------------------------
    # Пропущенная в тёмной теме переменная = невидимый текст, поэтому
    # сверяем наборы определений всех трёх тем между собой.
    def theme_block(theme: str) -> str:
        marker = f'[data-theme="{theme}"]'
        start = template.find(marker)
        if start == -1:
            return ""
        end = template.find("\n  }", start)
        return template[start:end if end != -1 else start + 4000]

    defs = {theme: set(re.findall(r"(--[a-z0-9-]+)\s*:", theme_block(theme)))
            for theme in ("warm", "light", "dark")}
    canonical = defs["warm"]
    for theme in ("light", "dark"):
        missing = canonical - defs[theme]
        check(f"тема «{theme}» определяет все переменные темы",
              not missing, f"нет: {sorted(missing)}")
    extra = defs["dark"] - canonical
    check("в тёмной теме нет лишних переменных", not extra, f"лишние: {sorted(extra)}")

    used = set(re.findall(r"var\((--[a-z0-9-]+)\)", template))
    defined_anywhere = set(re.findall(r"(--[a-z0-9-]+)\s*:", template))
    check("все используемые CSS-переменные где-то определены",
          used <= defined_anywhere, f"не определены: {sorted(used - defined_anywhere)}")
    check("ключевые переменные темы объявлены во всех трёх темах",
          all({"canvas", "card", "ink", "line", "accent", "safe", "warn", "danger"} <=
              {name.lstrip("-") for name in defs[theme]}
              for theme in ("warm", "light", "dark")))

    # --- современный стиль и воздух ----------------------------------------
    check("ширина основного контейнера ограничена",
          'class="page-container max-w-6xl mx-auto px-4 pb-24 pt-6 sm:px-6"' in template)
    check("карточки крупнее: rounded-3xl и p-6",
          "border-radius: 1.5rem" in template and ".card-pad { padding: 1.5rem; }" in template)
    check("вкладка «Сегодня» — сетка 2 колонки с gap-6",
          "grid grid-cols-1 items-start gap-6 lg:grid-cols-2" in template)
    check("кнопки крупнее и тактильнее",
          "padding: .625rem 1rem" in template and "border-radius: .75rem" in template
          and ".btn:hover:not(:disabled) { transform: translateY(-1px); }" in template)
    check("у заголовков карточек есть пастельная подложка с иконкой",
          'class="card-icon' in template and ".card-icon--safe" in template)
    check("версия убрана из шапки", "'v' + (boot ? boot.app.version : '')" not in
          template[template.find("<header"):template.find("</header>")])

    # --- отчёт: буллиты, дисклеймер, склонения ------------------------------
    check("в разметке нет литерального буллита (не будет двойных «• •»)",
          "• <span" not in template and "•<span" not in template)
    check("списки используют .bullet-list с маркером через CSS",
          'class="bullet-list' in template and ".bullet-list > li::before" in template)
    footer = template[template.find("<footer"):template.find("</footer>")]
    check("в подвале нет дисклеймера — он остался один, в отчёте",
          "disclaimer" not in footer)
    check("дисклеймер отчёта выводится ровно один раз",
          template.count("report.disclaimer") == 1)
    check("в подвале есть технические детали",
          "FastAPI + SQLite" in footer and "Alpine.js" in footer)
    check("склонение стаканов вынесено в хелперы",
          "glassesLabel(" in template and "plural(" in template)
    # Раньше слова были приклеены к числу константой: «2 стаканов».
    check("нет склейки числа со словом «стаканов» без склонения",
          "стаканов в день" not in template and "стаканов в дни" not in template
          and "+ ' стаканов'" not in template)
    check("таблицы отчёта выровнены по колонкам",
          ".num { text-align: center" in template and 'class="num-left' in template)
    check("метрики отчёта оформлены карточками",
          ".metric-grid" in template and 'class="metric print-card"' in template)

    # --- трекер головной боли ----------------------------------------------
    check("форма приступа скрыта за прогрессивным раскрытием",
          "headacheFormOpen" in template and 'x-show="headacheFormOpen"' in template)
    check("в форме приступа нет варианта «Нет боли»",
          "headacheSideOptions()" in template and "option.value !== 'none'" in template)
    check("компактный статус «Сегодня голова не болела» на месте",
          "headacheStatusText()" in template and "Сегодня голова не болела" in template)
    check("сохранение блокируется без стороны и интенсивности",
          "canSaveHeadache()" in template and "headacheBlockReason()" in template)
    check("сторона по умолчанию пустая, а не «Нет боли»",
          "side: '', log_time: ''" in template)


def run_ui_harness() -> None:
    """
    Выполняет клиентский JS шаблона в Node.js.

    Проверки без браузера: длинный формат даты, отсутствие «[object Object]»
    в шапке, счётчики записей, арифметика дат для пресетов отчёта и
    переключение темы с сохранением в localStorage.
    """
    print("\nКлиентский JS шаблона (Node.js)")
    harness = PROJECT_DIR / "selftest_ui.js"
    if not harness.exists():
        print("  [skip] selftest_ui.js не найден")
        return

    node = shutil.which("node") or shutil.which("node.exe")
    if not node:
        print("  [skip] Node.js не найден — JS-проверки пропущены "
              "(они не обязательны для работы приложения)")
        return

    try:
        completed = subprocess.run(
            [node, str(harness)],
            cwd=str(PROJECT_DIR),
            capture_output=True, text=True,
            # Node пишет UTF-8, а локаль Windows может быть cp1251 —
            # без явной кодировки чтение вывода падает с UnicodeDecodeError.
            encoding="utf-8", errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        check("клиентский JS шаблона выполняется в Node", False, str(exc))
        return

    output = completed.stdout or ""
    for line in output.rstrip().splitlines():
        if line.strip():
            print("  " + line.rstrip())
    if completed.returncode != 0 and completed.stderr:
        for line in completed.stderr.rstrip().splitlines()[-5:]:
            print("  ! " + line.rstrip())

    count = output.count("[ok]")
    check(f"клиентский JS шаблона: {count} проверок в Node.js пройдено",
          completed.returncode == 0 and count > 0,
          f"код возврата {completed.returncode}")


def request(base: str, method: str, path: str, body: dict | None = None,
            expect: int | None = 200) -> tuple[int, object]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            status = response.status
            payload = json.loads(raw) if raw.lstrip().startswith(("{", "[")) else raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        status = exc.code
    if expect is not None and status != expect:
        raise AssertionError(f"{method} {path} → HTTP {status} (ожидался {expect}): {payload}")
    return status, payload


# --------------------------------------------------------------------------- #
def main() -> int:
    print(f"Временная база: {config.DB_PATH}")
    result = run_local.prepare()
    print(f"Наполнение: {result}")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), run_local.DiaryHandler)
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"Сервер поднят: {base}\n")

    try:
        # ------------------------------------------------- статические проверки
        static_checks()
        static_ui_checks()
        run_ui_harness()

        # ------------------------------------------------------------ meta
        print("\nМета и интерфейс")
        _, page = request(base, "GET", "/", expect=200)
        check("GET / отдаёт HTML-шаблон", isinstance(page, str) and "diary()" in page)
        check("в шаблоне есть вкладка отчёта", "print-area" in str(page))

        _, health = request(base, "GET", "/api/health")
        check("GET /api/health", isinstance(health, dict) and health.get("status") == "ok")

        _, boot = request(base, "GET", "/api/bootstrap")
        check("bootstrap: 5 тегов ограничений", len(boot["tags"]) == 5)
        check("bootstrap: профиль «Мой профиль»", boot["profile"]["name"] == "Мой профиль")
        check("bootstrap: все 5 тегов активны по умолчанию", len(boot["profile"]["active_tags"]) == 5)
        check("bootstrap: каталог продуктов >= 35", boot["food_count"] >= 35,
              f"их {boot['food_count']}")
        check("bootstrap: регулярные препараты Аллопуринол и Канефрон",
              {med["name"] for med in boot["medications"]} >= {"Аллопуринол", "Канефрон"})
        check("bootstrap: памятка не пустая", len(boot["profile"]["medical_memo"]) > 100)
        check("bootstrap: есть влияние тегов на каталог", len(boot["tag_impact"]) == 5)

        # --------------------------------------------------- светофор
        print("\nСветофор продуктов (модульные теги)")
        _, foods = request(base, "GET", "/api/foods")
        by_name = {item["name"]: item for item in foods["items"]}
        check("белый рис разрешён при всех тегах", by_name["Белый рис"]["status"] == "safe")
        check("овсянка на воде разрешена", by_name["Овсянка на воде"]["status"] == "safe")
        check("ромашковый чай разрешён", by_name["Ромашковый чай"]["status"] == "safe")
        check("белый зефир разрешён", by_name["Белый зефир"]["status"] == "safe")

        cabbage = by_name["Белокочанная капуста"]
        check("белокочанная капуста исключена", cabbage["status"] == "trigger")
        check("причина капусты — low_fodmap",
              [reason["tag"] for reason in cabbage["reasons"]] == ["low_fodmap"])

        milk = by_name["Коровье молоко"]
        check("коровье молоко нарушает и low_fodmap, и gerd",
              {reason["tag"] for reason in milk["reasons"]} == {"low_fodmap", "gerd"})

        coffee = by_name["Кофе"]
        check("кофе нарушает gerd и migraine_control",
              {reason["tag"] for reason in coffee["reasons"]} == {"gerd", "migraine_control"})

        nalgezin = {item["name"]: item for item in foods["drugs"]}["Налгезин (метамизол, НПВС)"]
        check("Налгезин нарушает gerd + low_purine + migraine_control",
              {reason["tag"] for reason in nalgezin["reasons"]}
              == {"gerd", "low_purine", "migraine_control"})
        check("у каждого триггера есть текстовое объяснение",
              all(reason["reason"] for item in foods["items"] for reason in item["reasons"]))

        _, searched = request(base, "GET", "/api/foods?q=%D0%BA%D0%B0%D0%BF%D1%83%D1%81%D1%82")
        check("живой поиск по слову «капуст»", searched["total"] >= 3,
              f"найдено {searched['total']}")
        _, red_only = request(base, "GET", "/api/foods?status=trigger")
        check("фильтр «исключить»", all(item["status"] == "trigger" for item in red_only["items"]))
        check("счётчики фильтров согласованы",
              red_only["counts"]["trigger"] == red_only["total"])

        # ------------------------------------- новые позиции каталога
        print("\nРасширение каталога (орехи, руккола, растительное молоко)")
        check("каталог вырос до 66 продуктов", len(foods["items"]) == 66,
              f"их {len(foods['items'])}")
        check("появилась категория «Орехи»", "Орехи" in foods["categories"])

        check("руккола разрешена при всех тегах",
              by_name["Руккола"]["status"] == "safe")

        walnuts = by_name["Грецкие орехи"]
        check("грецкие орехи — «осторожно» из-за gerd",
              walnuts["status"] == "caution"
              and [reason["tag"] for reason in walnuts["reasons"]] == ["gerd"])
        check("у грецких орехов указана безопасная порция",
              "15–20 г" in walnuts["reasons"][0]["reason"])

        nuts = by_name["Кешью и фисташки"]
        check("кешью и фисташки исключены при low_fodmap",
              nuts["status"] == "trigger"
              and [reason["tag"] for reason in nuts["reasons"]] == ["low_fodmap"])

        green_milk = by_name["Кокосовое молоко (Green Milk)"]
        check("кокосовое молоко (Green Milk) — в категории «Напитки»",
              green_milk["category"] == "Напитки")
        check("кокосовое молоко (Green Milk) нарушает low_fodmap и gerd",
              {reason["tag"] for reason in green_milk["reasons"]} == {"low_fodmap", "gerd"})

        sausage = by_name["Варёная колбаса и сосиски"]
        check("варёная колбаса и сосиски нарушают gerd и low_purine",
              {reason["tag"] for reason in sausage["reasons"]} == {"gerd", "low_purine"})

        brisket = by_name["Грудинка и сало"]
        check("грудинка и сало нарушают gerd и low_purine",
              {reason["tag"] for reason in brisket["reasons"]} == {"gerd", "low_purine"})

        check("у арбуза причина — фруктоза и сорбитол",
              "сорбитола" in by_name["Арбуз"]["reasons"][0]["reason"])
        check("у винограда причина — газообразование",
              "газообразование" in by_name["Виноград"]["reasons"][0]["reason"])

        for obsolete in ("Кокосовое молоко", "Колбаса варёная", "Грудинка копчёная"):
            check(f"переименованная позиция «{obsolete}» не осталась дублем",
                  obsolete not in by_name)

        # --------------------------------------------- переключение тегов
        print("\nПереключение набора тегов (ядро модульности)")
        _, only_gerd = request(base, "PUT", "/api/profile", {"active_tags": ["gerd"]})
        check("профиль сохранён с одним тегом", only_gerd["active_tags"] == ["gerd"])

        _, foods_gerd = request(base, "GET", "/api/foods")
        gerd_by_name = {item["name"]: item for item in foods_gerd["items"]}
        check("при теге gerd арбуз снова разрешён (low_fodmap выключен)",
              gerd_by_name["Арбуз"]["status"] == "safe")
        check("при теге gerd кофе по-прежнему исключён",
              gerd_by_name["Кофе"]["status"] == "trigger")
        check("выключенный тег уходит в раздел «при других тегах»",
              any(note["tag"] == "low_fodmap" for note in gerd_by_name["Арбуз"]["other_notes"]))

        _, restored = request(base, "PUT", "/api/profile",
                              {"active_tags": ["gerd", "low_fodmap", "low_purine",
                                               "migraine_control", "cardio_caution"]})
        check("все 5 тегов включены обратно", len(restored["active_tags"]) == 5)

        _, bad_tag = request(base, "PUT", "/api/profile",
                             {"active_tags": ["gerd", "не_существует"]}, expect=200)
        check("неизвестный тег отбрасывается", bad_tag["active_tags"] == ["gerd"])
        request(base, "PUT", "/api/profile",
                {"active_tags": ["gerd", "low_fodmap", "low_purine", "migraine_control",
                                 "cardio_caution"]})

        # -------------------------------------------------------- меню
        print("\nКонструктор меню")
        _, menu = request(base, "GET", "/api/menu?date=2026-11-18")
        check("4 приёма пищи сформированы", len(menu["slots"]) == 4)
        check("в каждом приёме есть блюда",
              all(slot["dishes"] for slot in menu["slots"]),
              str([(slot["label"], len(slot["dishes"])) for slot in menu["slots"]]))
        check("все предложенные блюда не нарушают теги",
              all(dish["status"] != "trigger" for slot in menu["slots"] for dish in slot["dishes"]))
        check("у блюд есть краткие рецепты",
              all(dish["recipe"] for slot in menu["slots"] for dish in slot["dishes"]))
        check("показано, что исключено", menu["excluded_count"] > 0)
        check("исключения сгруппированы по тегам", len(menu["excluded_by_tag"]) > 0)
        check("рацион детерминирован для одной даты",
              request(base, "GET", "/api/menu?date=2026-11-18")[1]["planned_dishes"]
              == menu["planned_dishes"])

        _, ideas = request(base, "GET", "/api/meal-ideas?slot=breakfast")
        check("конструктор блюд фильтруется по слоту",
              ideas["ideas"] and all(idea["slot"] == "breakfast" for idea in ideas["ideas"]))

        # ------------------------------------------------ дневник дня
        print("\nДневник: чек-ин, головная боль, счётчик НПВС")
        today = boot["today"]
        _, snapshot = request(base, "GET", "/api/today")
        check("GET /api/today отдаёт сводку дня",
              {"symptoms", "checklist", "water", "nsaid"} <= set(snapshot))

        request(base, "PUT", "/api/symptoms", {
            "log_date": today, "bloating": 2, "heaviness": 1, "heartburn": 3,
            "reflux_cough": 1, "pain": 0, "stool": "loose",
            "note": "после кофе с утра",
        })
        _, saved = request(base, "GET", "/api/symptoms")
        entry = next((item for item in saved["items"] if item["log_date"] == today), None)
        check("чек-ин симптомов сохранён", entry is not None)
        check("значения симптомов записаны верно",
              entry and entry["heartburn"] == 3 and entry["stool"] == "loose")
        check("пустое значение вне шкалы обрезается до 3",
              request(base, "PUT", "/api/symptoms",
                      {"log_date": today, "heartburn": 99})[1]["heartburn"] == 3)
        check("повторный чек-ин перезаписывает день, а не дублирует",
              len([item for item in request(base, "GET", "/api/symptoms")[1]["items"]
                   if item["log_date"] == today]) == 1)

        nsaid_med = next(med for med in boot["medications"] if med["is_nsaid"])

        # Пустой эпизод не должен попадать в дневник и в отчёт.
        request(base, "POST", "/api/headaches", {"side": "none", "intensity": 4}, expect=400)
        check("эпизод «Нет боли» отклоняется сервером", True)
        request(base, "POST", "/api/headaches", {"side": "left", "intensity": 0}, expect=400)
        check("эпизод с интенсивностью 0 отклоняется сервером", True)
        request(base, "POST", "/api/headaches", {"side": "none", "intensity": 0}, expect=400)
        check("полностью пустой эпизод отклоняется сервером", True)
        _, empty_list = request(base, "GET", "/api/headaches")
        check("после отказов в дневнике нет пустых записей",
              all(item["side"] != "none" and item["intensity"] >= 1
                  for item in empty_list["items"]))

        _, created = request(base, "POST", "/api/headaches", {
            "log_date": today, "side": "right", "intensity": 7, "duration_hours": 4,
            "triggers": ["Недосып"], "medication_id": nsaid_med["id"],
            "medication": nsaid_med["name"], "dose": "1 таблетка",
            "log_intake": True,
        }, expect=201)
        check("эпизод головной боли создан", created["headache"]["intensity"] == 7)
        check("приём НПВС попал в счётчик", created["intake"] is not None
              and created["intake"]["is_nsaid"] is True)

        _, nsaid = request(base, "GET", "/api/nsaid")
        check("счётчик НПВС считает приём", nsaid["count"] == 1)
        check("счётчик НПВС считает дни", nsaid["days_with_intake"] == 1)
        check("счётчик предупреждает о желудке, почках и абузусе",
              {warning["tag_short"] for warning in nsaid["warnings"]}
              >= {"Желудок", "Пурины/почки", "Мигрень"})
        check("порог абузуса описан", nsaid["moh"]["nsaid_limit"] == 10)

        # Абузусный сценарий: 11 дней с приёмом за месяц → уровень риска.
        for offset in range(1, 11):
            day = request(base, "GET", "/api/today?date=" +
                          (f"{today[:8]}{max(1, int(today[8:]) - offset):02d}"))[1]["date"]
            request(base, "POST", "/api/intakes",
                    {"name": "Налгезин (метамизол)", "is_nsaid": True, "intake_date": day},
                    expect=201)
        _, risky = request(base, "GET", "/api/nsaid")
        check("11 дней с НПВС → повышенный риск", risky["level"] == "risk", risky["level"])
        check("сработал порог абузусной головной боли", risky["moh"]["nsaid_overuse"] is True)

        _, headaches = request(base, "GET", "/api/headaches")
        check("эпизод виден в списке", len(headaches["items"]) >= 1)
        request(base, "DELETE", f"/api/headaches/{created['headache']['id']}")
        check("эпизод удаляется",
              all(item["id"] != created["headache"]["id"] for item in
                  request(base, "GET", "/api/headaches")[1]["items"]))

        # --------------------------------------------- чек-лист и вода
        print("\nЧек-лист препаратов и вода")
        _, checklist = request(base, "GET", "/api/checklist")
        check("в чек-листе 2 регулярных препарата (НПВС скрыт)",
              checklist["total"] == 2, f"их {checklist['total']}")
        first = checklist["items"][0]
        _, after = request(base, "POST", "/api/checklist",
                           {"medication_id": first["id"], "check_date": today, "taken": True})
        check("отметка приёма сохраняется", after["taken_count"] == 1)
        _, toggled_off = request(base, "POST", "/api/checklist",
                                 {"medication_id": first["id"], "check_date": today, "taken": False})
        check("отметку можно снять", toggled_off["taken_count"] == 0)

        _, water = request(base, "POST", "/api/water", {"log_date": today, "glasses": 5})
        check("вода записана", water["glasses"] == 5 and water["remaining"] == 3)
        _, water2 = request(base, "POST", "/api/water", {"log_date": today, "glasses": 99})
        check("вода ограничена максимумом 40", water2["glasses"] == 40)

        # ------------------------------------------------------- препараты
        print("\nCRUD препаратов")
        _, new_med = request(base, "POST", "/api/medications",
                             {"name": "Тестовый препарат", "dose": "5 мг",
                              "schedule": "вечером", "active": True}, expect=201)
        check("препарат создан", new_med["name"] == "Тестовый препарат")
        _, updated_med = request(base, "PUT", f"/api/medications/{new_med['id']}",
                                 {"name": "Тестовый препарат", "dose": "10 мг"})
        check("препарат изменён", updated_med["dose"] == "10 мг")
        _, auto_nsaid = request(base, "POST", "/api/medications",
                                {"name": "Ибупрофен", "active": False}, expect=201)
        check("НПВС распознаётся по названию", auto_nsaid["is_nsaid"] is True)
        request(base, "DELETE", f"/api/medications/{new_med['id']}")
        request(base, "DELETE", f"/api/medications/{auto_nsaid['id']}")
        check("препарат удалён",
              all(med["id"] != new_med["id"] for med in
                  request(base, "GET", "/api/medications")[1]["items"]))

        # ---------------------------------------------------------- отчёт
        print("\nОтчёт для врача")
        today = db.today_iso()
        from_date = (date_cls.fromisoformat(today) - timedelta(days=29)).isoformat()
        _, report = request(base, "GET", f"/api/report?date_from={from_date}&date_to={today}")
        for key in ("period", "profile", "tags", "medical_memo", "medications",
                    "symptom_stats", "headache", "nsaid", "rows", "observations",
                    "disclaimer"):
            check(f"отчёт содержит блок «{key}»", key in report)
        check("в отчёте есть дисклеймер о самонаблюдении",
              "не заменяет врача" in report["disclaimer"])
        check("в отчёте есть строки дневника", len(report["rows"]) >= 1)
        check("в отчёте посчитаны наблюдения", len(report["observations"]) >= 2)
        check("отчёт считает приверженность лечению", len(report["medications"]) == 2)
        check("отчёт считает дни с НПВС", report["nsaid"]["days_with_intake"] >= 1)

        # --------------------------------------------------------- экспорт
        _, export = request(base, "GET", "/api/export")
        check("экспорт JSON содержит профиль и дневник",
              {"profile", "symptoms", "headaches", "intakes", "medications"} <= set(export))

        # ----------------------------------------------------- ошибки/404
        print("\nОбработка ошибок")
        request(base, "GET", "/api/does-not-exist", expect=404)
        check("неизвестный путь → 404", True)
        request(base, "DELETE", "/api/headaches/999999", expect=404)
        check("удаление несуществующей записи → 404", True)
        request(base, "POST", "/api/medications", {"name": "  "}, expect=400)
        check("пустое название препарата → 400", True)
        request(base, "POST", "/api/water", {"glasses": "abc"}, expect=200)
        check("нечисловое значение воды не ломает запрос", True)
        status, bad_method = request(base, "PATCH", "/api/profile", {}, expect=405)
        check("неподдерживаемый метод → 405", "error" in bad_method, str(bad_method))
        status, _ = request(base, "GET", "/api/profile")
        check("GET /api/profile работает", status == 200)

        # -------------------------------------------------- чистота данных
        print("\nЦелостность")
        info = db.db_info()
        check("каталог продуктов наполнен", info["foods"] >= 35, str(info))
        check("конструктор блюд наполнен", info["meal_ideas"] >= 12, str(info))
        check("теги в базе — только известные",
              set(services.get_profile()["active_tags"]) <= set(config.ALL_TAG_IDS))

    except Exception as exc:  # noqa: BLE001 - self-test reports whatever happened
        FAILED.append(f"{type(exc).__name__}: {exc}")
        print(f"\n  [FAIL] {type(exc).__name__}: {exc}")
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("\n" + "=" * 62)
    if FAILED:
        print(f"ПРОВАЛЕНО: {len(FAILED)} из {PASSED + len(FAILED)}")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print(f"ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ: {PASSED}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
