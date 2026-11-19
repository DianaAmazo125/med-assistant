"""
seed_data.py — Initial content for the diary.

Everything here is *generic*: no personal diagnosis is baked in. The seed ships

1. a default profile («Мой профиль») with all five restriction tags active,
   an editable medical memo and a starter list of regular medications;
2. a food catalog where each item carries ``tag_rules`` — which restriction tag
   it breaks and why — so the traffic light can explain every verdict;
3. a dish constructor: breakfast / lunch / dinner / tea ideas assembled only
   from allowed products, with short recipes.

Usage:
    python seed_data.py            # create the DB and seed it if it is empty
    python seed_data.py --reset    # wipe everything and seed again
    python seed_data.py --catalog  # refresh foods + dishes, keep the logs
"""

from __future__ import annotations

import argparse
import sys

import config
import database as db
import models

# Windows consoles default to cp866 — make Russian output readable.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (OSError, ValueError):  # pragma: no cover
            pass

# --------------------------------------------------------------------------- #
# Food catalog
# --------------------------------------------------------------------------- #
# ``tag_rules`` maps a restriction tag id to {"status": safe|caution|trigger,
# "reason": "<why>"}. An absent tag means "fine for this restriction".
# Statuses: trigger = лучше исключить, caution = небольшой порцией.

_TRIG = "trigger"
_CAUT = "caution"

FOODS_SEED: list[dict] = [
    # ------------------------------------------------------ безопасно всем
    {"name": "Белый рис", "category": "Злаки и гарниры", "portion": "150–200 г готового",
     "note": "Нейтральный гарнир, не раздражает желудок и почти не ферментируется.",
     "tag_rules": {}},
    {"name": "Овсянка на воде", "category": "Злаки и гарниры", "portion": "40–50 г сухой крупы",
     "note": "Вязкая каша обволакивает слизистую; варить без молока и сахара.",
     "tag_rules": {}},
    {"name": "Гречка на воде", "category": "Злаки и гарниры", "portion": "150–200 г готовой",
     "note": "Хороший источник медленных углеводов, при готовке не добавлять бульон.",
     "tag_rules": {}},
    {"name": "Кукурузная крупа (полента)", "category": "Злаки и гарниры", "portion": "150 г готовой",
     "note": "Безглютеновый гарнир с низким содержанием ферментируемых углеводов.",
     "tag_rules": {}},
    {"name": "Филе индейки", "category": "Белок", "portion": "120–150 г",
     "note": "Нежирный белок, готовить на пару, отваривать или запекать без кожи.",
     "tag_rules": {}},
    {"name": "Куриная грудка", "category": "Белок", "portion": "120–150 г",
     "note": "Диетический белок; варить или запекать, избегая жарки и панировки.",
     "tag_rules": {}},
    {"name": "Треска", "category": "Белок", "portion": "120–150 г",
     "note": "Нежирная белая рыба — безопасный белок при контроле пуринов.",
     "tag_rules": {}},
    {"name": "Минтай", "category": "Белок", "portion": "120–150 г",
     "note": "Нежирная белая рыба, готовить на пару или запекать в фольге.",
     "tag_rules": {}},
    {"name": "Яйцо куриное", "category": "Белок", "portion": "1–2 шт.",
     "note": "Готовить всмятку, пашот или паровой омлет — без масла и жарки.",
     "tag_rules": {}},
    {"name": "Тофу твёрдый", "category": "Белок", "portion": "100–150 г",
     "note": "Растительный белок, хорошо переносится при вздутии.",
     "tag_rules": {}},
    {"name": "Кабачок", "category": "Овощи", "portion": "150–200 г",
     "note": "Мягкий овощ, тушить или готовить на пару; кожуру снимать.",
     "tag_rules": {}},
    {"name": "Тыква", "category": "Овощи", "portion": "150–200 г",
     "note": "Запекать кусочками — сладковатый, но низкоферментируемый овощ.",
     "tag_rules": {}},
    {"name": "Морковь варёная", "category": "Овощи", "portion": "100–150 г",
     "note": "В варёном виде переносится лучше, чем сырая.",
     "tag_rules": {}},
    {"name": "Картофель варёный", "category": "Овощи", "portion": "150–200 г",
     "note": "Отваривать без бульона; пюре делать на воде, а не на молоке.",
     "tag_rules": {}},
    {"name": "Огурец без кожуры", "category": "Овощи", "portion": "100 г",
     "note": "Кожуру снять, семена лучше убрать — так меньше газообразования.",
     "tag_rules": {}},
    {"name": "Салат айсберг", "category": "Овощи", "portion": "50–80 г",
     "note": "Нейтральная зелень, заправлять оливковым маслом, не майонезом.",
     "tag_rules": {}},
    {"name": "Печёные яблоки", "category": "Фрукты и ягоды", "portion": "1–2 шт.",
     "note": "Запекание снижает содержание ферментируемых сахаров — безопасный десерт.",
     "tag_rules": {}},
    {"name": "Киви", "category": "Фрукты и ягоды", "portion": "1–2 шт.",
     "note": "Разрешён при низкоферментируемой диете, помогает при запорах.",
     "tag_rules": {}},
    {"name": "Адыгейский сыр", "category": "Молочное", "portion": "30–50 г",
     "note": "Свежий сыворотный сыр с низким содержанием лактозы.",
     "tag_rules": {}},
    {"name": "Белый зефир", "category": "Сладкое и снеки", "portion": "1–2 шт.",
     "note": "Разрешённая сладость: без шоколада, какао и орехов.",
     "tag_rules": {}},
    {"name": "Ромашковый чай", "category": "Напитки", "portion": "1–2 чашки",
     "note": "Тёплый напиток без кофеина — базовая замена кофе и крепкого чая.",
     "tag_rules": {}},
    {"name": "Имбирь", "category": "Жиры и специи", "portion": "по вкусу",
     "note": "Мягкая специя, помогает при тошноте; в чай — небольшой ломтик.",
     "tag_rules": {}},
    {"name": "Куркума", "category": "Жиры и специи", "portion": "по вкусу",
     "note": "Мягкая специя вместо острого перца.",
     "tag_rules": {}},
    {"name": "Оливковое масло", "category": "Жиры и специи", "portion": "1 ч. л.",
     "note": "Базовый жир: немного, но достаточно, чтобы овощи усваивались.",
     "tag_rules": {}},
    {"name": "Руккола", "category": "Овощи", "portion": "50–80 г",
     "note": "Низкоферментируемая зелень; в тушёном виде или в омлете переносится очень мягко.",
     "tag_rules": {}},
    {"name": "Петрушка и укроп", "category": "Жиры и специи", "portion": "по вкусу",
     "note": "Свежая зелень вместо лука и чеснока для вкуса.",
     "tag_rules": {}},

    # -------------------------------------------------------- капусты и овощи
    {"name": "Белокочанная капуста", "category": "Овощи", "portion": "—",
     "note": "Классический источник газообразования.",
     "tag_rules": {"low_fodmap": {"status": _TRIG, "reason": "Фруктаны и рафиноза сильно ферментируются и дают вздутие."}}},
    {"name": "Пекинская капуста", "category": "Овощи", "portion": "—",
     "note": "Близка к белокочанной по действию на живот.",
     "tag_rules": {"low_fodmap": {"status": _TRIG, "reason": "Фруктаны — провокатор вздутия и газов."}}},
    {"name": "Цветная капуста", "category": "Овощи", "portion": "—",
     "note": "Даже в небольших порциях часто даёт выраженное вздутие.",
     "tag_rules": {"low_fodmap": {"status": _TRIG, "reason": "Маннит и фруктаны — сильный триггер вздутия."}}},
    {"name": "Брокколи", "category": "Овощи", "portion": "до 50 г с осторожностью",
     "note": "Соцветия безопаснее стеблей; начинать с очень малой порции.",
     "tag_rules": {"low_fodmap": {"status": _TRIG, "reason": "Фруктаны в стеблях; допустима лишь малая порция соцветий."}}},
    {"name": "Лук репчатый", "category": "Овощи", "portion": "—",
     "note": "Самый частый скрытый триггер — встречается в готовой еде и бульонах.",
     "tag_rules": {
         "low_fodmap": {"status": _TRIG, "reason": "Высокое содержание фруктанов — сильнейший триггер вздутия."},
         "gerd": {"status": _CAUT, "reason": "Снижает тонус нижнего пищеводного сфинктера."},
     }},
    {"name": "Чеснок", "category": "Овощи", "portion": "—",
     "note": "Даже зубчик в готовом блюде может дать реакцию.",
     "tag_rules": {"low_fodmap": {"status": _TRIG, "reason": "Фруктаны; чувствителен даже к малым количествам."}}},
    {"name": "Помидор свежий", "category": "Овощи", "portion": "—",
     "note": "Кислый продукт; термически обработанный переносится хуже свежего.",
     "tag_rules": {"gerd": {"status": _TRIG, "reason": "Кислотность и ликопин расслабляют сфинктер, провоцируют изжогу."}}},
    {"name": "Квашеная капуста", "category": "Овощи", "portion": "—",
     "note": "Сочетает кислоту и брожение.",
     "tag_rules": {
         "gerd": {"status": _TRIG, "reason": "Кислый продукт брожения — прямая провокация изжоги."},
         "low_fodmap": {"status": _TRIG, "reason": "Фруктаны плюс продукты брожения."},
     }},
    {"name": "Грибы", "category": "Овощи", "portion": "100 г с осторожностью",
     "note": "Требуют проверки переносимости; грибной бульон исключить.",
     "tag_rules": {
         "low_fodmap": {"status": _CAUT, "reason": "Маннит — умеренный триггер вздутия."},
         "low_purine": {"status": _CAUT, "reason": "Содержат пурины среднего уровня."},
     }},
    {"name": "Шпинат", "category": "Овощи", "portion": "50–70 г",
     "note": "Полезен, но не сочетается с контролем пуринов и оксалатов.",
     "tag_rules": {
         "low_purine": {"status": _TRIG, "reason": "Заметный уровень пуринов и оксалатов."},
         "low_fodmap": {"status": _CAUT, "reason": "Фруктаны в больших порциях."},
     }},

    # ------------------------------------------------------- фрукты и ягоды
    {"name": "Арбуз", "category": "Фрукты и ягоды", "portion": "—",
     "note": "Много фруктозы и сорбитола в одной порции.",
     "tag_rules": {"low_fodmap": {"status": _TRIG, "reason": "Высокое содержание фруктозы и сорбитола вызывает брожение и осмотическую диарею."}}},
    {"name": "Виноград", "category": "Фрукты и ягоды", "portion": "—",
     "note": "Сладкий фрукт с неблагоприятным соотношением фруктозы и глюкозы.",
     "tag_rules": {"low_fodmap": {"status": _TRIG, "reason": "Избыток фруктозы провоцирует сильное газообразование и вздутие."}}},
    {"name": "Яблоко свежее", "category": "Фрукты и ягоды", "portion": "—",
     "note": "В печёном виде безопасно, в свежем — нет.",
     "tag_rules": {"low_fodmap": {"status": _TRIG, "reason": "Фруктоза и сорбитол; запекание снимает проблему."}}},
    {"name": "Груша", "category": "Фрукты и ягоды", "portion": "—",
     "note": "Содержит сразу фруктозу и сорбитол.",
     "tag_rules": {"low_fodmap": {"status": _TRIG, "reason": "Фруктоза + сорбитол — сильный триггер."}}},
    {"name": "Банан спелый", "category": "Фрукты и ягоды", "portion": "½ шт. с осторожностью",
     "note": "Недозрелый банан переносится лучше спелого.",
     "tag_rules": {"low_fodmap": {"status": _CAUT, "reason": "При созревании растёт содержание фруктанов."}}},
    {"name": "Апельсин", "category": "Фрукты и ягоды", "portion": "—",
     "note": "Цитрусовые — частая провокация изжоги.",
     "tag_rules": {
         "gerd": {"status": _TRIG, "reason": "Кислота и эфирные масла цедры провоцируют рефлюкс."},
         "migraine_control": {"status": _CAUT, "reason": "У части людей цитрусовые входят в число пищевых триггеров."},
     }},
    {"name": "Грейпфрут", "category": "Фрукты и ягоды", "portion": "—",
     "note": "Известный участник лекарственных взаимодействий.",
     "tag_rules": {
         "cardio_caution": {"status": _TRIG, "reason": "Подавляет CYP3A4 и меняет концентрацию статинов и ряда кардиопрепаратов — обязательна проверка у врача."},
         "gerd": {"status": _CAUT, "reason": "Высокая кислотность."},
     }},

    # ------------------------------------------------------------- молочное
    {"name": "Коровье молоко", "category": "Молочное", "portion": "—",
     "note": "Заменить на безлактозное или растительное.",
     "tag_rules": {
         "low_fodmap": {"status": _TRIG, "reason": "Лактоза — классический триггер вздутия и послабления."},
         "gerd": {"status": _TRIG, "reason": "Жир и объём жидкости повышают давление на сфинктер."},
     }},
    {"name": "Йогурт сладкий", "category": "Молочное", "portion": "100 г с осторожностью",
     "note": "Лучше натуральный без сахара и добавок.",
     "tag_rules": {
         "low_fodmap": {"status": _CAUT, "reason": "Остаточная лактоза и добавленные сахара."},
         "gerd": {"status": _CAUT, "reason": "Кисломолочный продукт может усиливать изжогу."},
     }},

    # --------------------------------------------------------------- белок
    {"name": "Говядина нежирная", "category": "Белок", "portion": "100 г, не чаще 2–3 раз в неделю",
     "note": "Отварная, без бульона и жира.",
     "tag_rules": {"low_purine": {"status": _CAUT, "reason": "Средний уровень пуринов — ограничить частоту и порцию."}}},
    {"name": "Свинина жирная", "category": "Белок", "portion": "—",
     "note": "Сочетает жир и пурины.",
     "tag_rules": {
         "gerd": {"status": _TRIG, "reason": "Жир надолго задерживает пищу в желудке."},
         "low_purine": {"status": _TRIG, "reason": "Высокое содержание пуринов."},
     }},
    {"name": "Варёная колбаса и сосиски", "category": "Белок", "portion": "—",
     "note": "Переработанное мясо: жир, соль, фосфаты, скрытые пурины.",
     "tag_rules": {
         "gerd": {"status": _TRIG, "reason": "Высокое содержание жира, соли, фосфатов и пуринов — нагрузка на желудок и почки."},
         "low_purine": {"status": _TRIG, "reason": "Высокое содержание жира, соли, фосфатов и пуринов — нагрузка на желудок и почки."},
     }},
    {"name": "Грудинка и сало", "category": "Белок", "portion": "—",
     "note": "Тугоплавкие жиры — самый тяжёлый для желудка и почек выбор.",
     "tag_rules": {
         "gerd": {"status": _TRIG, "reason": "Избыток тугоплавких жиров расслабляет пищеводный сфинктер и провоцирует заброс желчи и кислоты."},
         "low_purine": {"status": _TRIG, "reason": "Избыток тугоплавких жиров расслабляет пищеводный сфинктер и провоцирует заброс желчи и кислоты."},
     }},
    {"name": "Креветки", "category": "Белок", "portion": "—",
     "note": "Морепродукты — лидеры по пуринам.",
     "tag_rules": {"low_purine": {"status": _TRIG, "reason": "Очень высокое содержание пуринов."}}},
    {"name": "Сельдь и сардины", "category": "Белок", "portion": "—",
     "note": "Жирная солёная рыба — двойной удар по пуринам и соли.",
     "tag_rules": {"low_purine": {"status": _TRIG, "reason": "Максимальный уровень пуринов среди рыбы."}}},
    {"name": "Куриный бульон", "category": "Белок", "portion": "не крепкий, 1 чашка",
     "note": "Пурины переходят в бульон — мясо безопаснее бульона.",
     "tag_rules": {"low_purine": {"status": _CAUT, "reason": "Пурины экстрагируются в жидкость при варке."}}},

    # ------------------------------------------------------------- напитки
    {"name": "Кофе", "category": "Напитки", "portion": "—",
     "note": "Кофеин расслабляет сфинктер и входит в число триггеров головной боли.",
     "tag_rules": {
         "gerd": {"status": _TRIG, "reason": "Кофеин снижает тонус сфинктера и стимулирует кислотность."},
         "migraine_control": {"status": _TRIG, "reason": "Частый пищевой триггер приступа и фактор абузуса."},
     }},
    {"name": "Зелёный чай", "category": "Напитки", "portion": "1–2 чашки, не крепкий",
     "note": "Мягче кофе, но кофеин сохраняется.",
     "tag_rules": {
         "gerd": {"status": _CAUT, "reason": "Содержит кофеин, хотя и в меньшем количестве."},
         "migraine_control": {"status": _CAUT, "reason": "Умеренное количество кофеина."},
     }},
    {"name": "Пиво", "category": "Напитки", "portion": "—",
     "note": "Алкоголь и пурины одновременно.",
     "tag_rules": {
         "low_purine": {"status": _TRIG, "reason": "Пурины и алкоголь резко повышают мочевую кислоту."},
         "gerd": {"status": _TRIG, "reason": "Алкоголь расслабляет сфинктер, усиливает рефлюкс."},
         "migraine_control": {"status": _TRIG, "reason": "Частый провокатор приступа."},
     }},
    {"name": "Красное вино", "category": "Напитки", "portion": "—",
     "note": "Тирамин и сульфиты — известные триггеры.",
     "tag_rules": {
         "migraine_control": {"status": _TRIG, "reason": "Тирамин, сульфиты и гистамин провоцируют приступ."},
         "gerd": {"status": _TRIG, "reason": "Алкоголь и кислотность усиливают рефлюкс."},
     }},
    {"name": "Кокосовое молоко (Green Milk)", "category": "Напитки", "portion": "—",
     "note": "Промышленная растительная замена молока — состав нужно читать.",
     "tag_rules": {
         "low_fodmap": {"status": _TRIG, "reason": "Промышленные растительные напитки часто содержат инулин, камеди и жиры, провоцирующие вздутие и рефлюкс."},
         "gerd": {"status": _TRIG, "reason": "Промышленные растительные напитки часто содержат инулин, камеди и жиры, провоцирующие вздутие и рефлюкс."},
     }},

    # --------------------------------------------------------------- орехи
    {"name": "Грецкие орехи", "category": "Орехи", "portion": "15–20 г (3–4 половинки), в первой половине дня",
     "note": "Полезны, но жирны: лучше как добавка к каше, а не как перекус перед сном.",
     "tag_rules": {
         "gerd": {"status": _CAUT, "reason": "Высокая жирность замедляет опорожнение желудка — допустимо 15–20 г (3–4 половинки) в первой половине дня."},
     }},
    {"name": "Кешью и фисташки", "category": "Орехи", "portion": "—",
     "note": "Самые «бродящие» орехи: реакция часто зависит от порции.",
     "tag_rules": {
         "low_fodmap": {"status": _TRIG, "reason": "Высокое содержание галактанов (FODMAP) — провоцируют вздутие и послабление стула."},
     }},

    # --------------------------------------------------- сладкое и снеки
    {"name": "Шоколад", "category": "Сладкое и снеки", "portion": "—",
     "note": "Кофеин, теобромин и жир в одном продукте.",
     "tag_rules": {
         "gerd": {"status": _TRIG, "reason": "Кофеин и жир расслабляют сфинктер — типичная причина изжоги."},
         "migraine_control": {"status": _TRIG, "reason": "Фенилэтиламин и теобромин — частый триггер приступа."},
     }},
    {"name": "Мёд", "category": "Сладкое и снеки", "portion": "до 1 ч. л.",
     "note": "Свободные сахара и фруктоза в концентрированном виде.",
     "tag_rules": {
         "low_fodmap": {"status": _TRIG, "reason": "Избыток фруктозы относительно глюкозы."},
         "gerd": {"status": _CAUT, "reason": "Сладкое может провоцировать заброс."},
     }},
    {"name": "Чипсы и солёные снеки", "category": "Сладкое и снеки", "portion": "—",
     "note": "Соль, трансжиры, усилители вкуса.",
     "tag_rules": {
         "gerd": {"status": _TRIG, "reason": "Жир, соль и специи раздражают слизистую."},
         "cardio_caution": {"status": _TRIG, "reason": "Избыток натрия повышает давление и задерживает жидкость."},
         "low_purine": {"status": _CAUT, "reason": "Соль снижает выведение уратов."},
     }},
    {"name": "Хлеб пшеничный свежий", "category": "Злаки и гарниры", "portion": "1–2 ломтика подсушенного",
     "note": "Свежая выпечка хуже переносится, чем подсушенная.",
     "tag_rules": {"low_fodmap": {"status": _TRIG, "reason": "Фруктаны пшеницы; подсушенный хлеб переносится легче."}}},

    # ------------------------------------------------------ жиры и специи
    {"name": "Сливочное масло", "category": "Жиры и специи", "portion": "до 5 г",
     "note": "Немного на подсушенный хлеб — допустимо, жарить на нём не стоит.",
     "tag_rules": {"gerd": {"status": _CAUT, "reason": "Жир замедляет опорожнение желудка."}}},
    {"name": "Лакрица (солодка)", "category": "Жиры и специи", "portion": "—",
     "note": "Часто входит в травяные сборы и конфеты.",
     "tag_rules": {"cardio_caution": {"status": _TRIG, "reason": "Глицирризин повышает давление и снижает калий."}}},

    # ---------------------------------------------------------- лекарства
    {"name": "Налгезин (метамизол, НПВС)", "category": "Лекарства", "portion": "только по назначению",
     "note": "Обезболивающее из группы НПВС — считается счётчиком приёмов.",
     "is_drug": True,
     "tag_rules": {
         "gerd": {"status": _TRIG, "reason": "НПВС повреждают защитный слой слизистой желудка."},
         "low_purine": {"status": _TRIG, "reason": "НПВС снижают почечный клиренс уратов и задерживают жидкость."},
         "migraine_control": {"status": _TRIG, "reason": "Чаще 10 дней в месяц — риск абузусной головной боли."},
     }},
    {"name": "Аспирин (ацетилсалициловая кислота)", "category": "Лекарства", "portion": "только по назначению",
     "note": "НПВС и антиагрегант одновременно.",
     "is_drug": True,
     "tag_rules": {
         "gerd": {"status": _TRIG, "reason": "Повышает риск эрозий и кровотечения из желудка."},
         "low_purine": {"status": _TRIG, "reason": "Задерживает выведение уратов, повышает мочевую кислоту."},
         "migraine_control": {"status": _TRIG, "reason": "Учитывается в счётчике абузуса."},
         "cardio_caution": {"status": _CAUT, "reason": "Антиагрегант: любые изменения схемы — только с кардиологом."},
     }},
    {"name": "Парацетамол", "category": "Лекарства", "portion": "только по назначению",
     "note": "Не НПВС, но при частом приёме тоже ведёт к абузусной головной боли.",
     "is_drug": True,
     "tag_rules": {
         "migraine_control": {"status": _CAUT, "reason": "Безопаснее для желудка, но при приёме 15+ дней в месяц даёт абузус."},
     }},
    {"name": "Сыр выдержанный (чеддер, пармезан)", "category": "Молочное", "portion": "30 г",
     "note": "Зрелые сыры накапливают тирамин.",
     "tag_rules": {"migraine_control": {"status": _TRIG, "reason": "Тирамин — классический триггер приступа."}}},
]

# --------------------------------------------------------------------------- #
# Dish constructor
# --------------------------------------------------------------------------- #
MEAL_IDEAS_SEED: list[dict] = [
    # ---------------------------------------------------------------- breakfast
    {"slot": "breakfast", "title": "Овсянка на воде с печёным яблоком",
     "ingredients": ["Овсянка на воде", "Печёные яблоки", "Адыгейский сыр"],
     "recipe": "40 г овсянки сварить на 200 мл воды без соли и сахара. Печёное яблоко нарезать и добавить за минуту до готовности. Сверху — 20 г адыгейского сыра."},
    {"slot": "breakfast", "title": "Паровой омлет с кабачком",
     "ingredients": ["Яйцо куриное", "Кабачок", "Оливковое масло"],
     "recipe": "Два яйца взбить с 2 ст. л. воды, добавить мелко нарезанный кабачок. Готовить в пароварке 10–12 минут, перед подачей сбрызнуть ½ ч. л. оливкового масла."},
    {"slot": "breakfast", "title": "Рисовая каша с тыквой",
     "ingredients": ["Белый рис", "Тыква", "Оливковое масло"],
     "recipe": "50 г риса варить на воде до вязкости, добавить кубики тыквы за 10 минут до готовности. Заправить ½ ч. л. масла, не подсаливать."},
    {"slot": "breakfast", "title": "Гречка с индейкой",
     "ingredients": ["Гречка на воде", "Филе индейки", "Петрушка и укроп"],
     "recipe": "Отварить гречку на воде. Индейку готовить на пару 20 минут, нарезать ломтиками. Посыпать зеленью — она заменит лук."},

    # -------------------------------------------------------------------- lunch
    {"slot": "lunch", "title": "Индейка на пару с рисом и кабачком",
     "ingredients": ["Филе индейки", "Белый рис", "Кабачок", "Оливковое масло"],
     "recipe": "Индейку и кабачок готовить на пару 20 минут. Гарнир — отварной рис. Заправить чайной ложкой оливкового масла."},
    {"slot": "lunch", "title": "Треска, запечённая с картофелем",
     "ingredients": ["Треска", "Картофель варёный", "Оливковое масло", "Петрушка и укроп"],
     "recipe": "Треску запекать в фольге 20 минут при 190 °C. Картофель отварить отдельно. Подавать с зеленью и 1 ч. л. масла."},
    {"slot": "lunch", "title": "Куриная грудка с тыквой и морковью",
     "ingredients": ["Куриная грудка", "Тыква", "Морковь варёная"],
     "recipe": "Грудку без кожи отварить или запечь. Тыкву и морковь запечь кусочками в фольге — без корочки и специй."},
    {"slot": "lunch", "title": "Минтай тушёный с рисом и огурцом",
     "ingredients": ["Минтай", "Белый рис", "Огурец без кожуры"],
     "recipe": "Минтай тушить 15 минут в небольшом количестве воды с зеленью. Подавать с рисом и очищенным огурцом."},

    # ------------------------------------------------------------------- dinner
    {"slot": "dinner", "title": "Индейка с кабачком на пару",
     "ingredients": ["Филе индейки", "Кабачок", "Петрушка и укроп"],
     "recipe": "Лёгкий ужин: индейка и кабачок на пару 20 минут, зелень. За 3 часа до сна, небольшими кусочками."},
    {"slot": "dinner", "title": "Треска на пару с картофельным пюре на воде",
     "ingredients": ["Треска", "Картофель варёный", "Оливковое масло"],
     "recipe": "Треску готовить на пару 15 минут. Пюре сделать на воде без молока и масла, добавить ½ ч. л. оливкового масла."},
    {"slot": "dinner", "title": "Тофу с рисом и морковью",
     "ingredients": ["Тофу твёрдый", "Белый рис", "Морковь варёная"],
     "recipe": "Тофу нарезать кубиками и прогреть на пару 8 минут. Подавать с рисом и отварной морковью."},
    {"slot": "dinner", "title": "Куриная грудка с гречкой",
     "ingredients": ["Куриная грудка", "Гречка на воде", "Огурец без кожуры"],
     "recipe": "Грудку отварить целиком, нарезать. Гарнир — гречка на воде, свежий огурец без кожуры."},

    # ---------------------------------------------------------------------- tea
    {"slot": "tea", "title": "Ромашковый чай с белым зефиром",
     "ingredients": ["Ромашковый чай", "Белый зефир"],
     "recipe": "Заварить ромашку 5 минут. Один-два зефира — без шоколада и какао. Хорошая замена кофе и десертам с шоколадом."},
    {"slot": "tea", "title": "Печёное яблоко с ромашковым чаем",
     "ingredients": ["Печёные яблоки", "Ромашковый чай", "Имбирь"],
     "recipe": "Яблоко запечь 20 минут при 180 °C, посыпать щепоткой имбиря. Запить ромашковым чаем."},
    {"slot": "tea", "title": "Адыгейский сыр с чаем",
     "ingredients": ["Адыгейский сыр", "Ромашковый чай", "Киви"],
     "recipe": "30 г адыгейского сыра и один киви — небольшой перекус, который не даёт вздутия."},
    {"slot": "tea", "title": "Киви с ромашковым чаем",
     "ingredients": ["Киви", "Ромашковый чай"],
     "recipe": "Один-два киви за 30 минут до еды — мягкая поддержка при склонности к запорам."},
]

# --------------------------------------------------------------------------- #
# Default profile
# --------------------------------------------------------------------------- #
DEFAULT_PROFILE_NAME = "Мой профиль"

DEFAULT_MEDICATIONS: list[dict] = [
    {
        "name": "Аллопуринол",
        "dose": "100 мг",
        "schedule": "1 раз в день, утром после еды",
        "times": ["08:00"],
        "kind": "regular",
        "purpose": "Снижение уровня мочевой кислоты",
        "cardio_note": "",
        "sort_order": 10,
    },
    {
        "name": "Канефрон",
        "dose": "2 таблетки",
        "schedule": "3 раза в день",
        "times": ["08:00", "14:00", "20:00"],
        "kind": "regular",
        "purpose": "Растительный урологический сбор",
        "cardio_note": "Растительный состав: при приёме препаратов от давления уточните совместимость.",
        "sort_order": 20,
    },
    {
        "name": "Налгезин (метамизол)",
        "dose": "1 таблетка",
        "schedule": "по требованию, при головной боли",
        "times": [],
        "kind": "rescue",
        "is_nsaid": True,
        "purpose": "Обезболивающее «по требованию» — считается в счётчике НПВС",
        "cardio_note": "НПВС задерживают натрий и жидкость, могут повышать давление — сверьте с кардиологом.",
        "active": False,
        "sort_order": 30,
    },
]


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #
# Позиции, которые были переименованы или объединены с другими. Каталог
# обновляется по имени, поэтому старые строки нужно явно удалить — иначе в
# светофоре останутся дубли-призраки. Список намеренно задан явно, чтобы
# обновление каталога никогда не удаляло ничего «за компанию».
OBSOLETE_FOOD_NAMES: tuple[str, ...] = (
    "Кокосовое молоко",       # → «Кокосовое молоко (Green Milk)», категория «Напитки»
    "Колбаса варёная",        # → «Варёная колбаса и сосиски»
    "Грудинка копчёная",      # → «Грудинка и сало»
)


def seed_foods() -> int:
    sql = f"""
        INSERT INTO {models.FOODS} (name, category, note, portion, tag_rules, is_drug, sort_order)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            category   = excluded.category,
            note       = excluded.note,
            portion    = excluded.portion,
            tag_rules  = excluded.tag_rules,
            is_drug    = excluded.is_drug,
            sort_order = excluded.sort_order
    """
    rows = [
        (
            item["name"],
            item.get("category", "Прочее"),
            item.get("note", ""),
            item.get("portion", ""),
            models.json_dumps(item.get("tag_rules", {})),
            1 if item.get("is_drug") else 0,
            index * 10,
        )
        for index, item in enumerate(FOODS_SEED, start=1)
    ]
    with db.connect() as conn_ctx:
        conn_ctx.executemany(sql, rows)
        placeholders = ", ".join("?" for _ in OBSOLETE_FOOD_NAMES)
        conn_ctx.execute(
            f"DELETE FROM {models.FOODS} WHERE name IN ({placeholders})",
            OBSOLETE_FOOD_NAMES,
        )
    return len(rows)


def seed_meal_ideas() -> int:
    """Dishes are reference content: replace them so edits to the seed apply."""
    with db.connect() as conn_ctx:
        conn_ctx.execute(f"DELETE FROM {models.MEAL_IDEAS}")
        conn_ctx.executemany(
            f"""INSERT INTO {models.MEAL_IDEAS}
                (slot, title, recipe, ingredients, tag_rules, sort_order)
                VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    item["slot"],
                    item["title"],
                    item.get("recipe", ""),
                    models.json_dumps(item.get("ingredients", [])),
                    models.json_dumps(item.get("tag_rules", {})),
                    index * 10,
                )
                for index, item in enumerate(MEAL_IDEAS_SEED, start=1)
            ],
        )
    return len(MEAL_IDEAS_SEED)


def create_profile(overrides: dict | None = None) -> int:
    """Create the default (or personalised) profile together with its meds."""
    overrides = overrides or {}
    stamp = db.now_iso()

    name = str(overrides.get("name") or DEFAULT_PROFILE_NAME)
    active_tags = overrides.get("active_tags")
    if not isinstance(active_tags, list) or not active_tags:
        active_tags = list(config.ALL_TAG_IDS)
    # Never store an unknown tag id.
    active_tags = [tag for tag in active_tags if tag in config.RESTRICTION_TAGS]

    memo = overrides.get("medical_memo")
    if not isinstance(memo, str) or not memo.strip():
        memo = config.DEFAULT_MEDICAL_MEMO

    profile_id = db.insert(
        f"""INSERT INTO {models.PROFILES} (name, active_tags, medical_memo, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)""",
        (name, models.json_dumps(active_tags), memo, stamp, stamp),
    )

    meds = overrides.get("medications")
    if not isinstance(meds, list) or not meds:
        meds = DEFAULT_MEDICATIONS

    for index, med in enumerate(meds, start=1):
        if not isinstance(med, dict) or not str(med.get("name") or "").strip():
            continue
        med_name = str(med["name"]).strip()
        is_nsaid = bool(med.get("is_nsaid")) or config.looks_like_nsaid(med_name)
        is_analgesic = bool(med.get("is_analgesic")) or config.looks_like_analgesic(med_name)
        db.insert(
            f"""INSERT INTO {models.MEDICATIONS}
                (profile_id, name, dose, schedule, times, kind, is_nsaid, is_analgesic,
                 cardio_note, purpose, active, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                profile_id,
                med_name,
                str(med.get("dose") or ""),
                str(med.get("schedule") or ""),
                models.json_dumps(med.get("times") or []),
                str(med.get("kind") or ("nsaid" if is_nsaid else "regular")),
                1 if is_nsaid else 0,
                1 if is_analgesic else 0,
                str(med.get("cardio_note") or ""),
                str(med.get("purpose") or ""),
                0 if med.get("active") is False else 1,
                int(med.get("sort_order") or index * 10),
            ),
        )
    return profile_id


def repair_empty_headaches() -> int:
    """
    Удаляет пустые эпизоды головной боли, записанные до исправления формы.

    Раньше форма отправлялась со стороной «Нет боли» и ненулевой
    интенсивностью, поэтому в дневник попадали записи вида «Нет боли, 4/10»
    и искажали статистику и отчёт. Теперь API такие записи не принимает
    (см. ``services.add_headache``), но старые строки нужно убрать.
    """
    cursor = db.execute(
        f"DELETE FROM {models.HEADACHE_LOGS} WHERE side = 'none' OR intensity < 1"
    )
    return int(cursor.rowcount or 0)


def seed(reset: bool = False, catalog_only: bool = False) -> dict:
    """Seed the database; safe to call repeatedly."""
    db.init_db()

    if reset:
        db.drop_all()
        db.init_db()

    if catalog_only:
        seed_foods()
        seed_meal_ideas()
        return {"foods": len(FOODS_SEED), "meal_ideas": len(MEAL_IDEAS_SEED), "profile_id": None,
                "mode": "catalog"}

    if not db.is_empty():
        seed_foods()
        return {"foods": len(FOODS_SEED), "meal_ideas": len(MEAL_IDEAS_SEED), "profile_id": None,
                "mode": "already-seeded"}

    seed_foods()
    seed_meal_ideas()
    profile_id = create_profile(config.load_profile_config())
    db.set_setting("schema_version", config.APP_VERSION)
    db.set_setting("water_goal", str(config.WATER_GOAL_DEFAULT))
    return {
        "foods": len(FOODS_SEED),
        "meal_ideas": len(MEAL_IDEAS_SEED),
        "profile_id": profile_id,
        "mode": "fresh",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Наполнение базы дневника")
    parser.add_argument("--reset", action="store_true",
                        help="удалить все данные (включая дневник) и наполнить заново")
    parser.add_argument("--catalog", action="store_true",
                        help="обновить только каталог продуктов и блюд, дневник сохранить")
    parser.add_argument("--repair", action="store_true",
                        help="удалить пустые эпизоды головной боли («Нет боли»), "
                             "записанные старой версией формы")
    args = parser.parse_args(argv)

    if args.repair:
        db.init_db()
        removed = repair_empty_headaches()
        print(f"Удалено пустых эпизодов головной боли: {removed}")
        print("Остальные записи дневника не тронуты.")
        return 0

    if args.reset:
        print("! Внимание: --reset удалит профиль, записи дневника и приёмы лекарств.")
    result = seed(reset=args.reset, catalog_only=args.catalog)

    db.init_db()
    info = db.db_info()
    print(f"База данных: {info['path']}")
    print(f"Профилей: {info['profiles']}, продуктов: {info['foods']}, блюд: {info['meal_ideas']}")
    if result["mode"] == "already-seeded":
        print("База уже была наполнена — каталог продуктов обновлён, записи не тронуты.")
    elif result["mode"] == "catalog":
        print("Обновлён только каталог.")
    else:
        print(f"Создан профиль «{DEFAULT_PROFILE_NAME}» со всеми активными тегами "
              f"({', '.join(config.ALL_TAG_IDS)}).")
        print("Можно запускать: python main.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
