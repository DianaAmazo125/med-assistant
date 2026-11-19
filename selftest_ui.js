/*
 * selftest_ui.js — прогон клиентских функций шаблона в Node.js.
 *
 * Мы не можем поднять браузер, но можем выполнить реальный код из
 * templates/index.html и убедиться, что даты, снимок дня и темы ведут себя
 * правильно. Именно здесь ловится регрессия «сегодня [object Object]».
 *
 * Запускается автоматически из selftest.py (если Node доступен) либо вручную:
 *     node selftest_ui.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const templatePath = path.join(__dirname, 'templates', 'index.html');
const html = fs.readFileSync(templatePath, 'utf8');

const start = html.indexOf('function diary() {');
const end = html.indexOf("window.addEventListener('load'");
if (start === -1 || end === -1 || end < start) {
  console.error('Не удалось извлечь код компонента из шаблона');
  process.exit(2);
}
const source = html.slice(start, end);

let failures = 0;
let passed = 0;

function check(name, condition, detail) {
  if (condition) {
    passed += 1;
    console.log('  [ok]   ' + name);
  } else {
    failures += 1;
    console.log('  [FAIL] ' + name + (detail ? ' — ' + detail : ''));
  }
}

// --- минимальное окружение браузера ---------------------------------------
const stored = {};
const sandbox = {
  console,
  setTimeout,
  clearTimeout,
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  document: {
    documentElement: {
      _theme: 'warm',
      setAttribute(name, value) { if (name === 'data-theme') this._theme = value; },
      getAttribute(name) { return name === 'data-theme' ? this._theme : null; }
    },
    querySelectorAll: () => []
  },
  getComputedStyle: () => ({ getPropertyValue: () => '#2E7D6B' }),
  window: {
    localStorage: {
      getItem: (key) => (key in stored ? stored[key] : null),
      setItem: (key, value) => { stored[key] = String(value); }
    },
    location: { search: '' },
    history: { replaceState() {} }
  }
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);

const app = sandbox.diary();

console.log('Даты');
check('человекочитаемая дата', app.humanDate('2026-11-18') === '18.11.2026',
      app.humanDate('2026-11-18'));
check('длинный формат: 18 ноября 2026',
      app.humanDateLong('2026-11-18') === '18 ноября 2026', app.humanDateLong('2026-11-18'));
check('все месяцы названы по-русски',
      app.humanDateLong('2026-01-05') === '5 января 2026'
      && app.humanDateLong('2026-12-31') === '31 декабря 2026');
check('ISO со временем обрезается', app.isoOf('2026-11-18T10:30:00') === '2026-11-18');
check('мусор вместо даты не ломает вывод', app.humanDate('не дата') === '—');
check('пустая дата даёт прочерк', app.humanDate(undefined) === '—' && app.humanDateLong('') === '—');

console.log('\nРегрессия шапки: объект вместо даты');
// Раньше в this.today попадал снимок дня, и в шапке появлялось «[object Object]».
check('объект вместо даты больше не превращается в [object Object]',
      app.humanDate({ symptoms: {} }) === '—' && app.humanDateLong({}) === '—');
app.today = '2026-11-18';
app.date = '2026-11-18';
check('подпись в шапке для сегодняшнего дня',
      app.todayLabel() === 'Сегодня, 18 ноября 2026', app.todayLabel());
app.date = '2026-11-01';
check('подпись в шапке для другой даты',
      app.todayLabel() === '18 ноября 2026', app.todayLabel());
check('подпись в шапке не содержит [object Object]',
      !app.todayLabel().includes('[object'));

console.log('\nСчётчики записей');
app.date = '2026-11-18';
app.snapshot = {
  symptoms: { bloating: 1 },
  headaches: [{ id: 1 }],
  intakes: [{ id: 1 }, { id: 2 }],
  checklist: { taken_count: 2, items: [] },
  symptom_score: 4
};
check('счётчик записей за сегодня', app.todayRecords() === 'чек-ин, ГБ 1, таб. 2, приёмы 2',
      app.todayRecords());
check('бейдж вкладки «Сегодня»', app.dayBadge() === 'чек-ин · ГБ 1 · таб. 2', app.dayBadge());
check('оценка симптомов считается по снимку',
      app.scoreBadge().text === 'Суммарный балл: 4', app.scoreBadge().text);
app.date = '2026-11-01';
check('для чужой даты счётчик записей пуст', app.todayRecords() === '');
check('подсказка для пустого дня', app.todayRecordsTitle().includes('пока нет'));

console.log('\nАрифметика дат (пресеты отчёта)');
check('addDays назад', app.addDays('2026-11-18', -29) === '2026-10-20',
      app.addDays('2026-11-18', -29));
check('addDays через границу месяца', app.addDays('2026-03-01', -1) === '2026-02-28');
check('addDays переживает объект вместо даты',
      /^\d{4}-\d{2}-\d{2}$/.test(app.addDays({}, -1)), app.addDays({}, -1));
check('addDays переживает мусор',
      /^\d{4}-\d{2}-\d{2}$/.test(app.addDays('мусор', 5)), app.addDays('мусор', 5));

console.log('\nПриведение чисел для API');
check('num: пустая строка → значение по умолчанию', app.num('', 5) === 5);
check('num: строка с числом', app.num('7.5', 0) === 7.5);
check('optInt: пустая строка → null', app.optInt('') === null);
check('optInt: null остаётся null', app.optInt(null) === null);
check('optInt: число', app.optInt('7') === 7);

console.log('\nСклонение числительных');
check('1 → «стакан»', app.glassesLabel(1) === '1 стакан', app.glassesLabel(1));
check('2 → «стакана»', app.glassesLabel(2) === '2 стакана', app.glassesLabel(2));
check('4 → «стакана»', app.glassesLabel(4) === '4 стакана', app.glassesLabel(4));
check('5 → «стаканов»', app.glassesLabel(5) === '5 стаканов', app.glassesLabel(5));
check('0 → «0 стаканов»', app.glassesLabel(0) === '0 стаканов', app.glassesLabel(0));
check('11 → «11 стаканов»', app.glassesLabel(11) === '11 стаканов', app.glassesLabel(11));
check('21 → «21 стакан»', app.glassesLabel(21) === '21 стакан', app.glassesLabel(21));
check('22 → «22 стакана»', app.glassesLabel(22) === '22 стакана', app.glassesLabel(22));
check('дробное 5.3 → «5.3 стакана»', app.glassesLabel(5.3) === '5.3 стакана', app.glassesLabel(5.3));
check('мусор не ломает склонение', app.glassesLabel('abc') === 'abc', app.glassesLabel('abc'));
check('общий хелпер plural работает для других слов',
      app.plural(1, 'эпизод', 'эпизода', 'эпизодов') === 'эпизод'
      && app.plural(3, 'эпизод', 'эпизода', 'эпизодов') === 'эпизода'
      && app.plural(8, 'эпизод', 'эпизода', 'эпизодов') === 'эпизодов');

console.log('\nТрекер головной боли');
// Минимальный справочник: форма берёт стороны из bootstrap.
app.boot = {
  tags: [],
  medications: [],
  headache_sides: [
    { value: 'none', label: 'Нет боли' },
    { value: 'left', label: 'Слева' },
    { value: 'right', label: 'Справа' },
    { value: 'both', label: 'С двух сторон' },
    { value: 'behind_eyes', label: 'За глазами' }
  ]
};
app.date = '2026-11-18';
app.today = '2026-11-18';
app.snapshot = { symptoms: null, headaches: [], intakes: [], checklist: { taken_count: 0, items: [] } };
check('сторона по умолчанию пустая', app.form.headache.side === '');
check('вариант «Нет боли» исключён из формы',
      app.headacheSideOptions().every((option) => option.value !== 'none'));
check('в форме есть реальные стороны',
      app.headacheSideOptions().length >= 3, String(app.headacheSideOptions().length));

check('без стороны сохранение заблокировано', app.canSaveHeadache() === false);
check('причина блокировки названа', app.headacheBlockReason().includes('сторону'));
app.form.headache.side = 'none';
check('сторона «Нет боли» тоже блокирует', app.canSaveHeadache() === false);
app.form.headache.side = 'left';
app.form.headache.intensity = 0;
check('нулевая интенсивность блокирует', app.canSaveHeadache() === false);
check('причина — интенсивность', app.headacheBlockReason().includes('интенсивность'));
app.form.headache.intensity = 7;
check('корректный приступ сохранить можно', app.canSaveHeadache() === true);
check('причина блокировки исчезает', app.headacheBlockReason() === '');

check('компактный статус без приступов',
      app.headacheStatusText() === 'Сегодня голова не болела', app.headacheStatusText());
check('бейдж без приступов', app.headacheCountLabel() === 'не болела', app.headacheCountLabel());
app.snapshot.headaches = [{ id: 1, intensity: 6, side: 'left' }];
check('статус с одним приступом', app.headacheStatusText() === 'Записано: 1 эпизод',
      app.headacheStatusText());
check('бейдж склоняет один приступ', app.headacheCountLabel() === '1 эпизод');
app.snapshot.headaches = [{ id: 1 }, { id: 2 }, { id: 3 }];
check('бейдж склоняет три приступа', app.headacheCountLabel() === '3 эпизода',
      app.headacheCountLabel());
check('статус перечисляет записанное', app.headacheStatusText() === 'Записано: 3 эпизода',
      app.headacheStatusText());
app.snapshot.headaches = [];
app.date = '2026-11-01';
check('для другого дня формулировка меняется',
      app.headacheStatusText() === 'В этот день приступов не отмечено',
      app.headacheStatusText());

console.log('\nПрогрессивное раскрытие формы');
app.form.headache.side = 'left';
app.openHeadacheForm();
check('форма открывается', app.headacheFormOpen === true);
check('форма открывается с чистой стороны', app.form.headache.side === '',
      String(app.form.headache.side));
check('интенсивность по умолчанию 5', app.form.headache.intensity === 5);
app.closeHeadacheForm();
check('форма закрывается', app.headacheFormOpen === false);

console.log('\nТемы');
check('объявлены три темы', app.themes.length === 3);
check('набор тем — тёплая / светлая / тёмная',
      app.themes.map((t) => t.id).join(',') === 'warm,light,dark');
app.setTheme('dark');
check('setTheme выставляет data-theme',
      sandbox.document.documentElement.getAttribute('data-theme') === 'dark');
check('setTheme сохраняет выбор', stored['diary-theme'] === 'dark');
check('setTheme обновляет состояние', app.theme === 'dark');
app.setTheme('неизвестная-тема');
check('неизвестная тема откатывается к тёплой', app.theme === 'warm');
check('откат тоже сохраняется', stored['diary-theme'] === 'warm');

console.log('\n' + '='.repeat(62));
if (failures) {
  console.log('ПРОВАЛЕНО: ' + failures + ' из ' + (passed + failures));
  process.exit(1);
}
console.log('ВСЕ JS-ПРОВЕРКИ ПРОЙДЕНЫ: ' + passed);
