/* 飞运运输管理系统 · 框架层 */
var TOKEN = localStorage.getItem('tms_token') || '';
var ME = JSON.parse(localStorage.getItem('tms_user') || '{}');
var PERMS = ME.perms || [];
var TERM = '2026-2027-1';

function api(method, path, body, raw) {
  return fetch(PREFIX + path, {
    method: method,
    headers: Object.assign({'Content-Type': 'application/json'},
      TOKEN ? {Authorization: 'Bearer ' + TOKEN} : {}),
    body: (method === 'POST' || method === 'PUT') ? JSON.stringify(body || {}) : undefined
  }).then(function (r) {
    if (r.status === 401) { localStorage.clear(); location.href = 'login.html'; throw new Error('unauth'); }
    if (r.status >= 400) {
      return r.text().then(function (t) {
        var msg = 'HTTP ' + r.status;
        try { msg = (JSON.parse(t) || {}).message || msg; } catch (e) { /* 非 JSON */ }
        throw new Error(msg);
      });
    }
    return raw ? r.text() : r.json();
  }).then(function (j) {
    if (raw) return j;
    if (j && j.code && j.code !== 200) throw new Error(j.message || ('错误 ' + j.code));
    return j;
  });
}
function GET(p) { return api('GET', p); }
function POST(p, b) { return api('POST', p, b); }
function CSV(p) { return api('GET', p, null, true); }

function toast(msg, err) {
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = err ? '#cf2f4b' : '#1c2340';
  t.classList.remove('hidden');
  clearTimeout(t._tm);
  t._tm = setTimeout(function () { t.classList.add('hidden'); }, 2600);
}
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
  });
}
function perm(p) { return PERMS.indexOf('*') >= 0 || PERMS.indexOf(p) >= 0; }

/* ---------- 格式化 ---------- */
function fmtMoney(n, noSym) {
  if (n == null || n === '') return '—';
  var v = Number(n);
  var s = Math.abs(v) >= 10000
    ? v.toLocaleString('zh-CN', {maximumFractionDigits: 2})
    : v.toFixed(2);
  return (noSym ? '' : '¥') + s;
}
function fmtWan(n) {
  if (n == null || n === '') return '—';
  var v = Number(n);
  if (Math.abs(v) >= 100000000) return (v / 100000000).toFixed(2) + ' 亿';
  if (Math.abs(v) >= 10000) return (v / 10000).toFixed(2) + ' 万';
  return v.toFixed(2);
}
function fmtPct(x, digits) {
  if (x == null || x === '') return '—';
  return Number(x).toFixed(digits == null ? 2 : digits) + '%';
}
function fmtDate(s) { return s ? String(s).slice(0, 10) : '—'; }
function todayStr() {
  var d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' +
    String(d.getDate()).padStart(2, '0');
}

var NAV = [
  ['dash', '工作台', '◱'],
  ['waybill', '运单管理', '▤'],
  ['dispatch', '调度中心', '⇄'],
  ['tracking', '在途跟踪', '◉'],
  ['customer', '客户管理', '☺'],
  ['vehicle', '车辆管理', '⛭'],
  ['driver', '司机管理', '♟'],
  ['route', '线路管理', '⇢'],
  ['settle', '财务结算', '¥'],
  ['fuel', '油耗管理', '⛽'],
  ['risk', '风险预警', '⚠'],
  ['system', '系统管理', '⚙']
];

function boot() {
  if (!TOKEN) { location.href = 'login.html'; return; }
  GET('/api/me').then(function (r) {
    ME = r.data || {}; PERMS = ME.perms || [];
    localStorage.setItem('tms_user', JSON.stringify(ME));
    document.getElementById('who').textContent = ME.name + ' · ' + (ME.roleLabel || ME.role);
    var nav = document.getElementById('nav');
    nav.innerHTML = NAV.map(function (n) {
      return '<a href="#/' + n[0] + '" data-k="' + n[0] + '">' +
        '<span class="ic">' + n[2] + '</span>' + n[1] + '</a>';
    }).join('');
    nav.onclick = function (e) {
      var a = e.target.closest('a'); if (!a) return;
      e.preventDefault();
      go(a.getAttribute('data-k'));
    };
    var key = (location.hash || '#/dash').replace('#/', '');
    go(PAGES[key] ? key : 'dash');
    document.getElementById('btn-logout').onclick = function () {
      POST('/api/logout').then(function () {
        localStorage.clear(); location.href = 'login.html';
      }).catch(function () { localStorage.clear(); location.href = 'login.html'; });
    };
    window.addEventListener('hashchange', function () {
      var k = (location.hash || '#/dash').replace('#/', '');
      if (PAGES[k] && k !== CUR) go(k);
    });
    if (perm('risk.read')) {
      GET('/api/dashboard').then(function (d) {
        var n = ((d.data || {}).open_risks) || 0;
        if (!n) return;
        var a = document.querySelector('#nav a[data-k="risk"]');
        if (a) a.insertAdjacentHTML('beforeend', '<b class="badge">' + n + '</b>');
      }).catch(function () {});
    }
  }).catch(function (e) {
    if (e.message !== 'unauth') location.href = 'login.html';
  });
}

var CUR = null;
function go(key) {
  CUR = key;
  if (location.hash !== '#/' + key) location.hash = '#/' + key;
  document.querySelectorAll('#nav a').forEach(function (a) {
    a.classList.toggle('on', a.getAttribute('data-k') === key);
  });
  var main = document.getElementById('main');
  main.innerHTML = '<div class="empty">加载中…</div>';
  var task;
  try {
    task = PAGES[key](main);
  } catch (e) {
    task = Promise.reject(e);
  }
  Promise.resolve(task).catch(function (e) {
    if (e && e.message === 'unauth') return;
    main.innerHTML = '<div class="empty">加载失败：' + esc(e && e.message) + '</div>';
  });
}

function modal(html, wide) {
  var mask = document.getElementById('modal-mask');
  var box = document.getElementById('modal');
  box.innerHTML = html;
  box.className = 'modal' + (wide ? ' wide' : '');
  mask.classList.remove('hidden');
  mask.onclick = function (e) { if (e.target === mask) closeModal(); };
}
function closeModal() {
  document.getElementById('modal-mask').classList.add('hidden');
}

function table(headers, rows, rowHtml, empty) {
  if (!rows || !rows.length) return '<div class="empty">' + (empty || '暂无数据') + '</div>';
  return '<div class="tw"><table><thead><tr>' + headers.map(function (h) {
    if (h && h.charAt(0) === '~') return '<th class="num">' + h.slice(1) + '</th>';
    return '<th>' + h + '</th>';
  }).join('') + '</tr></thead><tbody>' + rows.map(rowHtml).join('') + '</tbody></table></div>';
}

function tag(text, cls) {
  return '<span class="tag ' + (cls || '') + '">' + esc(text) + '</span>';
}
function statusTag(s) {
  var m = {'在读': 'ok', '已缴清': 'ok', '已审批': 'ok', '已处理': 'ok',
           '启用': 'ok', '在职': 'ok', '开课': 'ok', '出勤': 'ok',
           '待审批': 'warn', '待缴': 'warn', '部分缴费': 'warn', '迟到': 'warn',
           '休学': '', '已驳回': 'err', '退学': 'err', '转出': 'err', '旷课': 'err',
           '病假': 'warn', '事假': 'warn', '待处理': 'err'};
  return tag(s, m[s] || '');
}
function levelTag(l) {
  var m = {'险': 'err', '警': 'warn', '提': 'pri'};
  return tag(l, m[l] || '');
}
function level2(l) {
  var m = {'优': 'ok', '良': 'pri', '中': 'warn', '及格': '', '不及格': 'err'};
  return tag(l, m[l] || '');
}
function kpi(v, label, cls) {
  return '<div class="kpi ' + (cls || '') + '"><b>' + esc(v) + '</b><span>' + esc(label) + '</span></div>';
}
function field(label, input, hint) {
  return '<label class="fld"><span>' + esc(label) + '</span>' + input +
    (hint ? '<i>' + esc(hint) + '</i>' : '') + '</label>';
}
function bar(pct, cls) {
  var w = Math.max(0, Math.min(100, pct));
  return '<div class="bar"><i class="' + (cls || '') + '" style="width:' + w + '%"></i></div>';
}
function dl(p, name) {
  CSV(p).then(function (t) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([t], {type: 'text/csv;charset=utf-8'}));
    a.download = name || 'export.csv';
    a.click();
  }).catch(function (e) { toast(e.message, true); });
}

/* 通用列表请求（?kw= 等） */
function qs(o) {
  var k = Object.keys(o || {}).filter(function (x) { return o[x]; });
  if (!k.length) return '';
  return '?' + k.map(function (x) { return x + '=' + encodeURIComponent(o[x]); }).join('&');
}

