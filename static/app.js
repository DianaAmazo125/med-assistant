/*
 * app.js — локальный рантайм интерфейса.
 *
 * Заменяет внешний Alpine.js: приложение больше не обращается ни к каким CDN
 * и работает без интернета. Реализовано ровно то подмножество декларативных
 * директив, которое использует шаблон, — ничего лишнего.
 *
 * Поддержано:
 *   x-data, x-init, x-cloak
 *   x-text, x-show, x-if, x-for (:key игнорируется)
 *   x-model (модификатор .number)
 *   :attr (в т.ч. :class объектом и строкой, :style строкой и объектом)
 *   @event с модификаторами .prevent .stop .once .self .debounce.350ms
 *
 * Реактивность: Proxy + отслеживание зависимостей, как в Vue/Alpine.
 * Выражения вычисляются через `with (scope)`, поэтому имена из цикла
 * (item, tag, option) и свойства компонента видны одинаково.
 */
(function (global) {
  'use strict';

  var RUNTIME_VERSION = '1.0.0';

  /* ===================================================================== *
   * Реактивность
   * ===================================================================== */
  var currentEffect = null;
  var targetMap = new WeakMap();   // цель -> ключ -> Set(эффектов)
  var proxyCache = new WeakMap();  // сырой объект -> его Proxy
  var boundCache = new WeakMap();  // функция -> привязанная к scope копия
  var owners = [];                 // стек владельцев эффектов (для x-for)
  var ITERATE = Symbol('iterate');

  function track(target, key) {
    if (!currentEffect) return;
    var deps = targetMap.get(target);
    if (!deps) { deps = new Map(); targetMap.set(target, deps); }
    var set = deps.get(key);
    if (!set) { set = new Set(); deps.set(key, set); }
    if (!set.has(currentEffect)) {
      set.add(currentEffect);
      currentEffect.deps.push(set);
    }
  }

  function trigger(target, key) {
    var deps = targetMap.get(target);
    if (!deps) return;
    var runners = [];
    if (deps.has(key)) deps.get(key).forEach(function (e) { runners.push(e); });
    // Массив изменили по месту (push/splice) — перерисовываем и «итераторов».
    if (deps.has(ITERATE)) deps.get(ITERATE).forEach(function (e) { runners.push(e); });
    runners.forEach(function (effect) { effect(); });
  }

  function reactive(raw) {
    if (raw === null || typeof raw !== 'object') return raw;
    if (raw.__isReactive) return raw;
    var cached = proxyCache.get(raw);
    if (cached) return cached;

    var proxy = new Proxy(raw, {
      get: function (target, key, receiver) {
        if (key === '__isReactive') return true;
        if (key === Symbol.unscopables) return undefined;
        var value = Reflect.get(target, key, receiver);
        track(target, key);
        if (Array.isArray(target) && typeof key === 'string' && /^\d+$/.test(key)) {
          track(target, ITERATE);
        }
        if (typeof value === 'function') {
          var bound = boundCache.get(value);
          if (!bound) {
            bound = value.bind(proxy);
            boundCache.set(value, bound);
          }
          return bound;
        }
        return value !== null && typeof value === 'object' ? reactive(value) : value;
      },
      set: function (target, key, value) {
        var previous = target[key];
        var ok = Reflect.set(target, key, value);
        if (previous !== value) trigger(target, key);
        if (Array.isArray(target)) trigger(target, ITERATE);
        return ok;
      },
      deleteProperty: function (target, key) {
        var ok = Reflect.deleteProperty(target, key);
        trigger(target, key);
        return ok;
      },
      has: function (target, key) {
        // Нужно для `with`: иначе имена не находятся в области видимости.
        if (key === Symbol.unscopables) return false;
        return key in target;
      }
    });

    proxyCache.set(raw, proxy);
    return proxy;
  }

  function stopEffect(effect) {
    (effect.deps || []).forEach(function (set) { set.delete(effect); });
    effect.deps = [];
    effect.stopped = true;
  }

  function makeEffect(fn) {
    var effect = function () {
      if (effect.stopped || effect.running) return;
      effect.running = true;
      var previous = currentEffect;
      currentEffect = effect;
      try {
        fn();
      } catch (error) {
        warn(error, 'effect');
      } finally {
        currentEffect = previous;
        effect.running = false;
      }
    };
    effect.deps = [];
    effect.stopped = false;
    if (owners.length) owners[owners.length - 1].push(effect);
    effect();
    return effect;
  }

  function withOwner(bucket, fn) {
    owners.push(bucket);
    try { fn(); } finally { owners.pop(); }
  }

  /* ===================================================================== *
   * Область видимости и вычисление выражений
   * ===================================================================== */
  function makeScope(parent, locals) {
    var target = Object.create(null);
    if (locals) Object.keys(locals).forEach(function (k) { target[k] = locals[k]; });
    return new Proxy(target, {
      has: function (t, key) {
        if (typeof key === 'symbol') return false;
        if (key in t) return true;
        return parent ? key in parent : false;
      },
      get: function (t, key) {
        if (key === Symbol.unscopables) return undefined;
        if (key in t) return t[key];
        return parent ? parent[key] : undefined;
      },
      set: function (t, key, value) {
        if (key in t) { t[key] = value; return true; }
        if (parent && key in parent) { parent[key] = value; return true; }
        t[key] = value;
        return true;
      }
    });
  }

  var exprCache = new Map();
  var stmtCache = new Map();
  var warned = Object.create(null);

  function warn(error, where) {
    var key = where + '|' + (error && error.message);
    if (warned[key]) return;
    warned[key] = true;
    if (global.console && console.warn) {
      console.warn('[diary] ' + where + ':', error && error.message ? error.message : error);
    }
  }

  function compileExpr(expr) {
    var fn = exprCache.get(expr);
    if (!fn) {
      // new Function всегда создаёт нестрогую функцию, поэтому `with` допустим.
      fn = new Function('__scope', 'with (__scope) { return (' + expr + '); }');
      exprCache.set(expr, fn);
    }
    return fn;
  }

  function compileStmt(body) {
    var fn = stmtCache.get(body);
    if (!fn) {
      fn = new Function('__scope', '$event', 'with (__scope) { ' + body + '\n }');
      stmtCache.set(body, fn);
    }
    return fn;
  }

  function evaluate(expr, scope) {
    try {
      return compileExpr(expr)(scope);
    } catch (error) {
      warn(error, expr);
      return undefined;
    }
  }

  function runStatement(body, scope, event) {
    try {
      return compileStmt(body)(scope, event);
    } catch (error) {
      warn(error, body);
      return undefined;
    }
  }

  function assign(expr, scope, value) {
    try {
      compileStmt(expr + ' = $event')[0]; // прогрев кэша не нужен, оставлено намеренно
    } catch (error) { /* ignore */ }
    try {
      return compileStmt(expr + ' = __value')(scope, value);
    } catch (error) {
      warn(error, expr);
      return undefined;
    }
  }

  /* ===================================================================== *
   * Работа с DOM
   * ===================================================================== */
  var BOOLEAN_PROPS = { checked: 1, selected: 1, disabled: 1, value: 1, indeterminate: 1 };

  function applyAttribute(el, name, value) {
    if (BOOLEAN_PROPS[name]) {
      if (name === 'value') {
        if (String(el.value) !== String(value === null || value === undefined ? '' : value)) {
          el.value = value === null || value === undefined ? '' : value;
        }
      } else {
        el[name] = !!value;
      }
      return;
    }
    if (value === false || value === null || value === undefined) {
      el.removeAttribute(name);
    } else if (value === true) {
      el.setAttribute(name, '');
    } else {
      el.setAttribute(name, String(value));
    }
  }

  function applyClass(el, value) {
    var previous = el.__boundClasses || [];
    var next = [];
    if (typeof value === 'string') {
      next = value.split(/\s+/).filter(Boolean);
    } else if (value && typeof value === 'object') {
      Object.keys(value).forEach(function (name) {
        if (value[name]) next.push(name);
      });
    }
    previous.forEach(function (name) {
      if (next.indexOf(name) === -1 && el.classList) el.classList.remove(name);
    });
    next.forEach(function (name) {
      if (previous.indexOf(name) === -1 && el.classList) el.classList.add(name);
    });
    el.__boundClasses = next;
  }

  function applyStyle(el, value) {
    if (value === null || value === undefined || value === false) {
      el.removeAttribute('style');
      return;
    }
    if (typeof value === 'string') {
      if (el.getAttribute('style') !== value) el.setAttribute('style', value);
      return;
    }
    if (typeof value === 'object') {
      Object.keys(value).forEach(function (name) {
        var item = value[name];
        if (item === null || item === undefined || item === false) {
          el.style.removeProperty(name);
        } else if (name.indexOf('--') === 0) {
          el.style.setProperty(name, String(item));
        } else {
          el.style[name] = item;
        }
      });
    }
  }

  function debounce(fn, wait) {
    var timer = null;
    return function (event) {
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(null, args); }, wait);
    };
  }

  function setupEvent(el, attr, scope) {
    var parts = attr.slice(1).split('.');
    var eventName = parts.shift();
    var body = el.getAttribute(attr);
    var wait = 0;
    var flags = { prevent: false, stop: false, once: false, self: false };
    parts.forEach(function (modifier) {
      if (/^\d+ms$/.test(modifier)) wait = parseInt(modifier, 10);
      else if (modifier in flags) flags[modifier] = true;
      else if (modifier === 'preventDefault') flags.prevent = true;
    });

    var handler = function (event) {
      if (flags.self && event.target !== el) return;
      if (flags.prevent && event.preventDefault) event.preventDefault();
      if (flags.stop && event.stopPropagation) event.stopPropagation();
      runStatement(body, scope, event);
    };
    el.addEventListener(eventName, wait ? debounce(handler, wait) : handler,
                        flags.once ? { once: true } : undefined);
  }

  function setupModel(el, attr, expr, scope) {
    var modifiers = attr.split('.').slice(1);
    var isCheckbox = el.type === 'checkbox';
    var isNumber = modifiers.indexOf('number') !== -1;

    var apply = function (value) {
      if (isCheckbox) {
        var checked = !!value;
        if (el.checked !== checked) el.checked = checked;
        return;
      }
      var next = value === null || value === undefined ? '' : String(value);
      if (String(el.value) !== next) el.value = next;
    };

    var effect = makeEffect(function () { apply(evaluate(expr, scope)); });
    // Опции <select> создаёт x-for: применяем значение после того,
    // как всё дерево построено, иначе значение не найдёт свою опцию.
    if (typeof queueMicrotask === 'function') queueMicrotask(effect);

    var write = function () {
      var value = isCheckbox ? !!el.checked : el.value;
      if (isNumber) {
        var parsed = parseFloat(value);
        value = Number.isFinite(parsed) ? parsed : '';
      }
      runStatement(expr + ' = __modelValue', makeScope(scope, { __modelValue: value }), null);
    };
    el.addEventListener(isCheckbox || el.tagName === 'SELECT' ? 'change' : 'input', write);
  }

  function prepare(el, scope) {
    var attrs = Array.prototype.slice.call(el.attributes || []);
    var directives = [];
    for (var i = 0; i < attrs.length; i++) {
      var name = attrs[i].name;
      if (name === 'x-for' || name === 'x-if' || name === 'x-data' || name === 'x-cloak'
          || name === 'x-transition' || name.indexOf('x-transition.') === 0) continue;
      if (name.charAt(0) === ':' || name.charAt(0) === '@' || name.indexOf('x-') === 0) {
        directives.push(name);
      }
    }

    // x-if и x-for управляют собственным содержимым — обходим их отдельно.
    if (el.tagName === 'TEMPLATE') {
      if (el.hasAttribute('x-if')) setupIf(el, scope);
      else if (el.hasAttribute('x-for')) setupFor(el, scope);
      return;
    }

    var modelAttr = null;
    directives.forEach(function (name) {
      var expr = el.getAttribute(name);
      try {
        if (name === 'x-text') {
          makeEffect(function () {
            var value = evaluate(expr, scope);
            var text = value === null || value === undefined ? '' : String(value);
            if (el.textContent !== text) el.textContent = text;
          });
        } else if (name === 'x-show') {
          makeEffect(function () {
            var visible = !!evaluate(expr, scope);
            if (visible) {
              if (el.style.display === 'none') el.style.display = el.__shownDisplay || '';
            } else if (el.style.display !== 'none') {
              if (el.style.display) el.__shownDisplay = el.style.display;
              el.style.display = 'none';
            }
          });
        } else if (name === 'x-model') {
          modelAttr = name;
        } else if (name.charAt(0) === ':') {
          var target = name.slice(1);
          makeEffect(function () {
            var value = evaluate(expr, scope);
            if (target === 'class') applyClass(el, value);
            else if (target === 'style') applyStyle(el, value);
            else applyAttribute(el, target, value);
          });
        } else if (name.charAt(0) === '@') {
          setupEvent(el, name, scope);
        }
      } catch (error) {
        warn(error, name);
      }
    });

    if (modelAttr) {
      try {
        setupModel(el, modelAttr, el.getAttribute(modelAttr), scope);
      } catch (error) {
        warn(error, 'x-model');
      }
    }

    var children = Array.prototype.slice.call(el.children || []);
    children.forEach(function (child) { prepare(child, scope); });
  }

  function setupIf(template, scope) {
    var expr = template.getAttribute('x-if');
    var anchor = document.createComment('x-if');
    template.parentNode.insertBefore(anchor, template);
    var nodes = [];
    var bucket = [];

    makeEffect(function () {
      bucket.forEach(stopEffect);
      bucket.length = 0;
      nodes.forEach(function (node) { if (node.parentNode) node.parentNode.removeChild(node); });
      nodes = [];
      if (!evaluate(expr, scope)) return;
      var frag = template.content.cloneNode(true);
      nodes = Array.prototype.slice.call(frag.children);
      withOwner(bucket, function () {
        nodes.forEach(function (node) { prepare(node, scope); });
      });
      anchor.parentNode.insertBefore(frag, anchor);
    });
  }

  function setupFor(template, scope) {
    var expr = template.getAttribute('x-for') || '';
    var match = /^\s*\(?\s*([\w$]+)\s*(?:,\s*([\w$]+)\s*)?\)?\s+in\s+([\s\S]+?)\s*$/.exec(expr);
    if (!match) {
      warn(new Error('не разобрано выражение x-for'), expr);
      return;
    }
    var itemName = match[1];
    var indexName = match[2];
    var listExpr = match[3];

    var anchor = document.createComment('x-for');
    template.parentNode.insertBefore(anchor, template);
    var rendered = [];

    makeEffect(function () {
      rendered.forEach(function (entry) {
        entry.effects.forEach(stopEffect);
        entry.nodes.forEach(function (node) {
          if (node.parentNode) node.parentNode.removeChild(node);
        });
      });
      rendered = [];

      var list = evaluate(listExpr, scope);
      var items = list ? Array.prototype.slice.call(list) : [];

      items.forEach(function (item, index) {
        var frag = template.content.cloneNode(true);
        var nodes = Array.prototype.slice.call(frag.children);
        var locals = Object.create(null);
        locals[itemName] = item;
        if (indexName) locals[indexName] = index;
        var childScope = makeScope(scope, locals);
        var effects = [];
        withOwner(effects, function () {
          nodes.forEach(function (node) { prepare(node, childScope); });
        });
        anchor.parentNode.insertBefore(frag, anchor);
        rendered.push({ nodes: nodes, effects: effects });
      });
    });
  }

  /* ===================================================================== *
   * Запуск
   * ===================================================================== */
  function start(rootDocument) {
    var doc = rootDocument || (typeof document !== 'undefined' ? document : null);
    if (!doc) return null;

    var root = doc.querySelector('[x-data]');
    if (!root) return null;

    var factorySource = root.getAttribute('x-data');
    var data;
    try {
      data = new Function('return (' + factorySource + ');')();
    } catch (error) {
      warn(error, 'x-data');
      return null;
    }
    if (typeof data === 'function') data = data();
    if (!data || typeof data !== 'object') return null;

    var state = reactive(data);
    withOwner([], function () { prepare(root, state); });

    // x-init выполняется после того, как дети уже разобраны.
    var initAttr = root.getAttribute('x-init');
    if (initAttr) runStatement(initAttr, state, null);

    var cloaked = doc.querySelectorAll('[x-cloak]');
    for (var i = 0; i < cloaked.length; i++) cloaked[i].removeAttribute('x-cloak');

    return state;
  }

  var api = {
    version: RUNTIME_VERSION,
    reactive: reactive,
    makeScope: makeScope,
    evaluate: evaluate,
    runStatement: runStatement,
    assign: assign,
    makeEffect: makeEffect,
    stopEffect: stopEffect,
    applyClass: applyClass,
    applyStyle: applyStyle,
    applyAttribute: applyAttribute,
    prepare: prepare,
    start: start
  };

  if (typeof module === 'object' && module.exports) module.exports = api;
  global.DiaryRuntime = api;

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () { start(document); }, { once: true });
    } else {
      start(document);
    }
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
