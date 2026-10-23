/* 飞运 TMS · 页面层 */
var PAGES = {};

var WB_TAG = {'待调度': '', '运输中': 'warn', '已签收': 'ok', '已取消': 'err'};
function wbTag(s) {
  var m = {'pending': '待调度', 'in_transit': '运输中', 'delivered': '已签收', 'cancelled': '已取消'};
  return tag(m[s] || s, WB_TAG[m[s] || s]);
}
function stTag(s) {
  var m = {'idle': tag('空闲', 'ok'), 'in_transit': tag('在途', 'warn'), 'maintenance': tag('维保', ''),
           'disabled': tag('停用', 'err'), 'rest': tag('休假', ''), 'resigned': tag('离职', 'err'),
           'active': tag('有效', 'warn'), 'done': tag('完成', 'ok'), 'replaced': tag('已撤销', 'err'),
           'open': tag('待结', 'warn'), 'closed': tag('已结', 'ok'), 'resolved': tag('已处理', 'ok')};
  return m[s] || tag(s);
}

/* ---------- 工作台 ---------- */
PAGES.dash = function (main) {
  main.innerHTML = '<h2>工作台</h2><div id="dash"></div>';
  return GET('/api/dashboard').then(function (d) {
    var k = d.data;
    document.getElementById('dash').innerHTML =
      '<div class="kpis">' +
      kpi(k.today_waybills, '今日运单') + kpi(k.pending, '待调度', 'warn') +
      kpi(k.in_transit, '运输中', 'warn') + kpi(k.delivered, '已签收', 'ok') +
      kpi('¥' + fmtWan(k.month_profit), '本月毛利', 'ok') +
      kpi(k.open_risks, '未处理预警', k.open_risks ? 'err' : '') +
      kpi(k.idle_vehicles, '空闲车辆') + kpi(k.idle_drivers, '空闲司机') +
      '</div>' +
      '<div class="card"><h3>最近运单</h3>' +
      table(['运单号', '客户', '货物', '~重量(kg)', '状态', '创建时间'], k.recent_waybills, function (r) {
        return '<tr><td>' + esc(r.no) + '</td><td>' + esc(r.customer_name) + '</td><td>' +
          esc(r.goods) + '</td><td class="num">' + r.weight_kg + '</td><td>' + wbTag(r.status) +
          '</td><td>' + esc(String(r.created_at).slice(0, 16)) + '</td></tr>';
      }) + '</div>';
  });
};

/* ---------- 运单 ---------- */
PAGES.waybill = function (main) {
  main.innerHTML = '<h2>运单管理</h2>' +
    '<div class="toolbar"><select id="f-status"><option value="">全部状态</option>' +
    '<option value="pending">待调度</option><option value="in_transit">运输中</option>' +
    '<option value="delivered">已签收</option><option value="cancelled">已取消</option></select>' +
    '<input id="f-kw" placeholder="运单号/货物">' +
    '<button class="btn sm" id="f-go">查询</button>' +
    '<button class="btn sm pri" id="btn-new">新建运单</button>' +
    '<button class="btn sm ghost" id="btn-csv">导出CSV</button><span id="cnt"></span></div>' +
    '<div id="list"></div>';
  function load() {
    var st = document.getElementById('f-status').value;
    var kw = document.getElementById('f-kw').value.trim();
    return GET('/api/waybills' + qs({status: st, keyword: kw})).then(function (r) {
      document.getElementById('cnt').textContent = ' 共 ' + r.data.total + ' 单';
      document.getElementById('list').innerHTML = table(
        ['运单号', '客户', '线路', '货物', '~重量', '~体积', '~报价', '状态', '签收人', '操作'], r.data.items, function (w) {
          var ops = '';
          if (w.status === 'pending' && (perm('tms.dispatch.write') || perm('*')))
            ops += '<a href="javascript:void(0)" data-act="disp" data-id="' + w.id + '">调度</a> ';
          if (w.status === 'in_transit' && (perm('tms.dispatch.write') || perm('*')))
            ops += '<a href="javascript:void(0)" data-act="deliver" data-id="' + w.id + '">签收</a> ';
          if (w.status !== 'cancelled' && (perm('tms.dispatch.write') || perm('*')))
            ops += '<a href="javascript:void(0)" data-act="cancel" data-id="' + w.id + '">取消</a>';
          return '<tr><td><b>' + esc(w.no) + '</b></td><td>' + esc(w.customer_name) + '</td><td>' +
            esc(w.route ? w.route.origin + ' → ' + w.route.dest : '—') + '</td><td>' + esc(w.goods) +
            '</td><td class="num">' + w.weight_kg + '</td><td class="num">' + w.volume_m3 +
            '</td><td class="num">¥' + fmtWan(w.quote) + '</td><td>' + wbTag(w.status) + '</td><td>' +
            esc(w.signer || '—') + '</td><td class="ops">' + ops + '</td></tr>';
        });
      var list = document.getElementById('list');
      list.onclick = function (e) {
        var a = e.target.closest('a'); if (!a) return;
        var id = a.getAttribute('data-id'), act = a.getAttribute('data-act');
        if (act === 'disp') openDispatch(id, load);
        if (act === 'deliver') {
          modal('<h3>签收确认</h3>' + field('签收人', '<input id="m-signer" value="仓库收货">') +
            '<div class="m-foot"><button class="btn pri" id="m-ok">确认签收</button></div>');
          document.getElementById('m-ok').onclick = function () {
            POST('/api/waybills/' + id + '/deliver', {signer: document.getElementById('m-signer').value})
              .then(function () { toast('签收成功，已自动生成结算'); closeModal(); load(); })
              .catch(function (e) { toast(e.message, true); });
          };
        }
        if (act === 'cancel') {
          POST('/api/waybills/' + id + '/cancel').then(function () { toast('已取消'); load(); })
            .catch(function (e) { toast(e.message, true); });
        }
      };
    });
  }
  document.getElementById('f-go').onclick = load;
  document.getElementById('f-status').onchange = load;
  document.getElementById('f-kw').onkeydown = function (e) { if (e.key === 'Enter') load(); };
  document.getElementById('btn-csv').onclick = function () { dl('/api/export/waybills', 'waybills.csv'); };
  document.getElementById('btn-new').onclick = function () {
    Promise.all([GET('/api/customers?size=100'), GET('/api/routes?size=100')]).then(function (rs) {
      var cs = rs[0].data.items, rt = rs[1].data.items;
      modal('<h3>新建运单</h3>' +
        field('客户', '<select id="m-cust">' + cs.map(function (c) {
          return '<option value="' + c.id + '">' + esc(c.code + ' ' + c.name) + '</option>'; }).join('') + '</select>') +
        field('线路', '<select id="m-route">' + rt.map(function (r) {
          return '<option value="' + r.id + '">' + esc(r.origin + ' → ' + r.dest + ' (' + r.distance_km + 'km)') + '</option>'; }).join('') + '</select>') +
        field('货物名称', '<input id="m-goods">') +
        field('重量(kg)', '<input id="m-w" type="number" value="1000">') +
        field('体积(m³)', '<input id="m-v" type="number" value="10">') +
        field('计价方式', '<select id="m-mode"><option value="weight">按重</option><option value="volume">按方</option><option value="trip">按趟</option></select>') +
        field('报价(分)', '<input id="m-quote" type="number" value="0">', '单位：分，如 48000 = ¥480.00') +
        '<div class="m-foot"><button class="btn pri" id="m-ok">创建</button></div>');
      document.getElementById('m-ok').onclick = function () {
        POST('/api/waybills', {
          customer_id: +document.getElementById('m-cust').value,
          route_id: +document.getElementById('m-route').value,
          goods: document.getElementById('m-goods').value || '杂货',
          weight_kg: +document.getElementById('m-w').value || 0,
          volume_m3: +document.getElementById('m-v').value || 0,
          price_mode: document.getElementById('m-mode').value,
          quote: +document.getElementById('m-quote').value || 0
        }).then(function () { toast('运单已创建'); closeModal(); load(); })
          .catch(function (e) { toast(e.message, true); });
      };
    });
  };
  return load();
};

function openDispatch(wid, done) {
  Promise.all([GET('/api/vehicles?status=idle&size=100'), GET('/api/drivers?status=idle&size=100')]).then(function (rs) {
    var vs = rs[0].data.items, ds = rs[1].data.items;
    if (!vs.length || !ds.length) { toast('无空闲车辆或司机', true); return; }
    modal('<h3>调度运单</h3>' +
      field('车辆', '<select id="m-veh">' + vs.map(function (v) {
        return '<option value="' + v.id + '">' + esc(v.plate + ' ' + (v.vtype || '')) + '</option>'; }).join('') + '</select>') +
      field('司机', '<select id="m-drv">' + ds.map(function (d) {
        return '<option value="' + d.id + '">' + esc(d.name + ' ' + (d.license_type || '')) + '</option>'; }).join('') + '</select>') +
      '<div class="m-foot"><button class="btn pri" id="m-ok">发车</button></div>');
    document.getElementById('m-ok').onclick = function () {
      POST('/api/waybills/' + wid + '/dispatch', {
        vehicle_id: +document.getElementById('m-veh').value,
        driver_id: +document.getElementById('m-drv').value
      }).then(function (r) { toast('已发车，ETA ' + r.data.eta); closeModal(); done && done(); })
        .catch(function (e) { toast(e.message, true); });
    };
  });
}

/* ---------- 调度 ---------- */
PAGES.dispatch = function (main) {
  main.innerHTML = '<h2>调度中心</h2><div id="list"></div>';
  function load() {
    return GET('/api/dispatches').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['ID', '运单号', '车牌', '司机', '发车时间', '预计到达', '实际到达', '状态'], r.data.items, function (d) {
          return '<tr><td>' + d.id + '</td><td>' + esc(d.waybill_no) + '</td><td>' + esc(d.plate) +
            '</td><td>' + esc(d.driver_name) + '</td><td>' + esc(String(d.depart_at || '—').slice(0, 16)) +
            '</td><td>' + esc(String(d.eta_ts || '—').slice(0, 16)) + '</td><td>' +
            esc(String(d.arrive_at || '—').slice(0, 16)) + '</td><td>' + stTag(d.status) + '</td></tr>';
        });
    });
  }
  return load();
};

/* ---------- 跟踪 ---------- */
PAGES.tracking = function (main) {
  main.innerHTML = '<h2>在途跟踪</h2>' +
    '<div class="toolbar"><input id="f-no" placeholder="运单号">' +
    '<button class="btn sm" id="f-go">查询</button></div><div id="list"></div>';
  function load() {
    var no = document.getElementById('f-no').value.trim();
    return GET('/api/trackings' + qs({waybill_no: no})).then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['时间', '运单号', '位置', '经度', '纬度', '事件'], r.data.items, function (t) {
          return '<tr><td>' + esc(t.ts) + '</td><td>' + esc(t.waybill_no) + '</td><td>' + esc(t.location || '—') +
            '</td><td class="num">' + t.lng + '</td><td class="num">' + t.lat + '</td><td>' + esc(t.event || '') + '</td></tr>';
        });
    });
  }
  document.getElementById('f-go').onclick = load;
  document.getElementById('f-no').onkeydown = function (e) { if (e.key === 'Enter') load(); };
  return load();
};

/* ---------- 客户 ---------- */
PAGES.customer = function (main) {
  main.innerHTML = '<h2>客户管理</h2>' +
    '<div class="toolbar"><input id="f-kw" placeholder="编码/名称/联系人">' +
    '<button class="btn sm" id="f-go">查询</button>' +
    '<button class="btn sm pri" id="btn-new">新建客户</button></div><div id="list"></div>';
  function load() {
    return GET('/api/customers' + qs({keyword: document.getElementById('f-kw').value.trim()})).then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['编码', '名称', '联系人', '电话', '结算方式', '~信用额度', '状态', '操作'], r.data.items, function (c) {
          return '<tr><td>' + esc(c.code) + '</td><td>' + esc(c.name) + '</td><td>' + esc(c.contact || '—') +
            '</td><td>' + esc(c.phone || '—') + '</td><td>' + (c.settle_type === 'monthly' ? '月结' : '现结') +
            '</td><td class="num">¥' + fmtWan(c.credit_limit) + '</td><td>' + (c.status ? tag('启用', 'ok') : tag('停用', 'err')) +
            '</td><td class="ops">' + (perm('tms.customer.write') || perm('*') ?
              '<a href="javascript:void(0)" data-id="' + c.id + '" data-act="edit">编辑</a>' : '') + '</td></tr>';
        });
      var list = document.getElementById('list');
      list.onclick = function (e) {
        var a = e.target.closest('a'); if (!a) return;
        var id = a.getAttribute('data-id');
        GET('/api/customers/' + id).then(function (d) {
          var c = d.data;
          modal('<h3>编辑客户</h3>' +
            field('名称', '<input id="m-name" value="' + esc(c.name) + '">') +
            field('联系人', '<input id="m-contact" value="' + esc(c.contact || '') + '">') +
            field('电话', '<input id="m-phone" value="' + esc(c.phone || '') + '">') +
            field('地址', '<input id="m-addr" value="' + esc(c.address || '') + '">') +
            field('信用额度(分)', '<input id="m-limit" type="number" value="' + c.credit_limit + '">') +
            '<div class="m-foot"><button class="btn pri" id="m-ok">保存</button></div>');
          document.getElementById('m-ok').onclick = function () {
            PUT('/api/customers/' + id, {
              name: document.getElementById('m-name').value,
              contact: document.getElementById('m-contact').value,
              phone: document.getElementById('m-phone').value,
              address: document.getElementById('m-addr').value,
              credit_limit: +document.getElementById('m-limit').value || 0
            }).then(function () { toast('已保存'); closeModal(); load(); })
              .catch(function (e) { toast(e.message, true); });
          };
        });
      };
    });
  }
  document.getElementById('f-go').onclick = load;
  document.getElementById('f-kw').onkeydown = function (e) { if (e.key === 'Enter') load(); };
  document.getElementById('btn-new').onclick = function () {
    modal('<h3>新建客户</h3>' +
      field('编码', '<input id="m-code" placeholder="C0XX">') +
      field('名称', '<input id="m-name">') +
      field('联系人', '<input id="m-contact">') +
      field('电话', '<input id="m-phone">') +
      field('结算方式', '<select id="m-st"><option value="monthly">月结</option><option value="cash">现结</option></select>') +
      field('信用额度(分)', '<input id="m-limit" type="number" value="100000">') +
      '<div class="m-foot"><button class="btn pri" id="m-ok">创建</button></div>');
    document.getElementById('m-ok').onclick = function () {
      POST('/api/customers', {
        code: document.getElementById('m-code').value.trim(),
        name: document.getElementById('m-name').value.trim(),
        contact: document.getElementById('m-contact').value,
        phone: document.getElementById('m-phone').value,
        settle_type: document.getElementById('m-st').value,
        credit_limit: +document.getElementById('m-limit').value || 0
      }).then(function () { toast('客户已创建'); closeModal(); load(); })
        .catch(function (e) { toast(e.message, true); });
    };
  };
  return load();
};

/* ---------- 车辆 ---------- */
PAGES.vehicle = function (main) {
  main.innerHTML = '<h2>车辆管理</h2>' +
    '<div class="toolbar"><select id="f-status"><option value="">全部</option>' +
    '<option value="idle">空闲</option><option value="in_transit">在途</option>' +
    '<option value="maintenance">维保</option><option value="disabled">停用</option></select>' +
    '<button class="btn sm pri" id="btn-new">新建车辆</button></div><div id="list"></div>';
  function load() {
    return GET('/api/vehicles' + qs({status: document.getElementById('f-status').value})).then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['车牌', '车型', '~载重(kg)', '~容积(m³)', '~里程表', '下次维保', '保险到期', '状态'], r.data.items, function (v) {
          return '<tr><td><b>' + esc(v.plate) + '</b></td><td>' + esc(v.vtype || '—') +
            '</td><td class="num">' + v.cap_weight + '</td><td class="num">' + v.cap_volume +
            '</td><td class="num">' + fmtWan(v.odometer) + ' km</td><td>' + esc(v.next_maint || '—') +
            '</td><td>' + esc(v.insurance_exp || '—') + '</td><td>' + stTag(v.status) + '</td></tr>';
        });
    });
  }
  document.getElementById('f-status').onchange = load;
  document.getElementById('btn-new').onclick = function () {
    modal('<h3>新建车辆</h3>' +
      field('车牌', '<input id="m-plate" placeholder="粤A00000">') +
      field('车型', '<input id="m-vtype" placeholder="9.6m厢式">') +
      field('载重(kg)', '<input id="m-cw" type="number" value="10000">') +
      field('容积(m³)', '<input id="m-cv" type="number" value="50">') +
      field('下次维保', '<input id="m-maint" type="date">') +
      field('保险到期', '<input id="m-ins" type="date">') +
      '<div class="m-foot"><button class="btn pri" id="m-ok">创建</button></div>');
    document.getElementById('m-ok').onclick = function () {
      POST('/api/vehicles', {
        plate: document.getElementById('m-plate').value.trim(),
        vtype: document.getElementById('m-vtype').value,
        cap_weight: +document.getElementById('m-cw').value || 0,
        cap_volume: +document.getElementById('m-cv').value || 0,
        next_maint: document.getElementById('m-maint').value || null,
        insurance_exp: document.getElementById('m-ins').value || null
      }).then(function () { toast('车辆已创建'); closeModal(); load(); })
        .catch(function (e) { toast(e.message, true); });
    };
  };
  return load();
};

/* ---------- 司机 ---------- */
PAGES.driver = function (main) {
  main.innerHTML = '<h2>司机管理</h2>' +
    '<div class="toolbar"><button class="btn sm pri" id="btn-new">新建司机</button></div><div id="list"></div>';
  function load() {
    return GET('/api/drivers').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['姓名', '手机', '驾照号', '驾照类型', '驾照到期', '~累计运单', '~累计里程', '状态'], r.data.items, function (d) {
          return '<tr><td><b>' + esc(d.name) + '</b></td><td>' + esc(d.phone || '—') +
            '</td><td>' + esc(d.license_no || '—') + '</td><td>' + esc(d.license_type || '—') +
            '</td><td>' + esc(d.license_exp || '—') + '</td><td class="num">' + d.total_trips +
            '</td><td class="num">' + fmtWan(d.total_km) + ' km</td><td>' + stTag(d.status) + '</td></tr>';
        });
    });
  }
  document.getElementById('btn-new').onclick = function () {
    modal('<h3>新建司机</h3>' +
      field('姓名', '<input id="m-name">') +
      field('手机', '<input id="m-phone">') +
      field('驾照号', '<input id="m-lno">') +
      field('驾照类型', '<select id="m-lt"><option>A2</option><option>B2</option><option>C1</option></select>') +
      field('驾照到期', '<input id="m-exp" type="date">') +
      '<div class="m-foot"><button class="btn pri" id="m-ok">创建</button></div>');
    document.getElementById('m-ok').onclick = function () {
      POST('/api/drivers', {
        name: document.getElementById('m-name').value.trim(),
        phone: document.getElementById('m-phone').value,
        license_no: document.getElementById('m-lno').value,
        license_type: document.getElementById('m-lt').value,
        license_exp: document.getElementById('m-exp').value || null
      }).then(function () { toast('司机已创建'); closeModal(); load(); })
        .catch(function (e) { toast(e.message, true); });
    };
  };
  return load();
};

/* ---------- 线路 ---------- */
PAGES.route = function (main) {
  main.innerHTML = '<h2>线路管理</h2>' +
    '<div class="toolbar"><button class="btn sm pri" id="btn-new">新建线路</button></div><div id="list"></div>';
  function load() {
    return GET('/api/routes').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['起点', '终点', '~里程(km)', '~时长(h)', '~基础运价(分/km)', '状态'], r.data.items, function (t) {
          return '<tr><td>' + esc(t.origin) + '</td><td>' + esc(t.dest) +
            '</td><td class="num">' + t.distance_km + '</td><td class="num">' + t.hours +
            '</td><td class="num">' + t.base_rate + '</td><td>' + (t.status ? tag('启用', 'ok') : tag('停用', 'err')) + '</td></tr>';
        });
    });
  }
  document.getElementById('btn-new').onclick = function () {
    modal('<h3>新建线路</h3>' +
      field('起点', '<input id="m-o">') + field('终点', '<input id="m-d">') +
      field('里程(km)', '<input id="m-km" type="number" value="100">') +
      field('标准时长(h)', '<input id="m-h" type="number" value="3">') +
      field('基础运价(分/km)', '<input id="m-r" type="number" value="60">') +
      '<div class="m-foot"><button class="btn pri" id="m-ok">创建</button></div>');
    document.getElementById('m-ok').onclick = function () {
      POST('/api/routes', {
        origin: document.getElementById('m-o').value.trim(),
        dest: document.getElementById('m-d').value.trim(),
        distance_km: +document.getElementById('m-km').value || 0,
        hours: +document.getElementById('m-h').value || 0,
        base_rate: +document.getElementById('m-r').value || 0
      }).then(function () { toast('线路已创建'); closeModal(); load(); })
        .catch(function (e) { toast(e.message, true); });
    };
  };
  return load();
};

/* ---------- 结算 ---------- */
PAGES.settle = function (main) {
  main.innerHTML = '<h2>财务结算</h2><div id="sum"></div>' +
    '<div class="toolbar"><select id="f-status"><option value="">全部</option>' +
    '<option value="open">待结</option><option value="closed">已结</option></select>' +
    '<button class="btn sm" id="f-go">查询</button>' +
    '<button class="btn sm ghost" id="btn-csv">导出CSV</button></div><div id="list"></div>';
  function load() {
    return Promise.all([
      GET('/api/settlements' + qs({status: document.getElementById('f-status').value})),
      GET('/api/settlements/summary')
    ]).then(function (rs) {
      var s = rs[1].data;
      document.getElementById('sum').innerHTML = '<div class="kpis">' +
        kpi('¥' + fmtWan(s.open_receivable), '应收(待结)', 'warn') +
        kpi('¥' + fmtWan(s.open_payable), '应付(待结)') +
        kpi('¥' + fmtWan(s.total_profit), '累计毛利', 'ok') +
        kpi(fmtPct(s.closed_ratio * 100, 1), '结清率') + '</div>';
      document.getElementById('list').innerHTML = table(
        ['运单号', '~收入(分)', '~油耗(分)', '~路桥(分)', '~司机应付(分)', '~毛利(分)', '状态', '操作'], rs[0].data.items, function (t) {
          var op = '';
          if (t.status === 'open' && (perm('tms.settlement.write') || perm('*')))
            op = '<a href="javascript:void(0)" data-id="' + t.id + '">结清</a>';
          return '<tr><td>' + esc(t.waybill_no || t.id) + '</td><td class="num">' + t.revenue +
            '</td><td class="num">' + t.fuel + '</td><td class="num">' + t.tolls +
            '</td><td class="num">' + t.driver_pay + '</td><td class="num"><b>' + t.profit + '</b></td><td>' +
            stTag(t.status) + '</td><td class="ops">' + op + '</td></tr>';
        });
      document.getElementById('list').onclick = function (e) {
        var a = e.target.closest('a'); if (!a) return;
        POST('/api/settlements/' + a.getAttribute('data-id') + '/close')
          .then(function () { toast('已结清'); load(); })
          .catch(function (e) { toast(e.message, true); });
      };
    });
  }
  document.getElementById('f-go').onclick = load;
  document.getElementById('f-status').onchange = load;
  document.getElementById('btn-csv').onclick = function () { dl('/api/settlements/export', 'settlements.csv'); };
  return load();
};

/* ---------- 油耗 ---------- */
PAGES.fuel = function (main) {
  main.innerHTML = '<h2>油耗管理</h2>' +
    '<div class="toolbar"><select id="f-veh"><option value="">全部车辆</option></select>' +
    '<button class="btn sm pri" id="btn-new">登记加油</button></div><div id="list"></div>';
  GET('/api/vehicles?size=100').then(function (r) {
    document.getElementById('f-veh').innerHTML += r.data.items.map(function (v) {
      return '<option value="' + v.id + '">' + esc(v.plate) + '</option>'; }).join('');
  });
  function load() {
    return GET('/api/fuel' + qs({vehicle_id: document.getElementById('f-veh').value})).then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['日期', '车牌', '~升数', '~单价', '~金额(分)', '~里程表'], r.data.items, function (f) {
          return '<tr><td>' + esc(f.date) + '</td><td>' + esc(f.plate) + '</td><td class="num">' + f.liters +
            '</td><td class="num">' + f.price + '</td><td class="num">' + f.amount +
            '</td><td class="num">' + fmtWan(f.odometer) + ' km</td></tr>';
        });
    });
  }
  document.getElementById('f-veh').onchange = load;
  document.getElementById('btn-new').onclick = function () {
    modal('<h3>登记加油</h3>' +
      field('车辆', '<select id="m-veh">' + document.getElementById('f-veh').innerHTML + '</select>') +
      field('日期', '<input id="m-date" type="date" value="' + todayStr() + '">') +
      field('升数', '<input id="m-l" type="number" value="200">') +
      field('单价(元/L)', '<input id="m-p" type="number" step="0.01" value="7.9">') +
      field('里程表(km)', '<input id="m-o" type="number" value="0">') +
      '<div class="m-foot"><button class="btn pri" id="m-ok">保存</button></div>');
    document.getElementById('m-ok').onclick = function () {
      POST('/api/fuel', {
        vehicle_id: +document.getElementById('m-veh').value,
        date: document.getElementById('m-date').value,
        liters: +document.getElementById('m-l').value || 0,
        price: +document.getElementById('m-p').value || 0,
        odometer: +document.getElementById('m-o').value || 0
      }).then(function () { toast('已登记'); closeModal(); load(); })
        .catch(function (e) { toast(e.message, true); });
    };
  };
  return load();
};

/* ---------- 风险 ---------- */
PAGES.risk = function (main) {
  main.innerHTML = '<h2>风险预警</h2>' +
    '<div class="toolbar"><button class="btn sm" id="btn-scan">立即扫描</button></div><div id="list"></div>';
  function load() {
    return GET('/api/risks').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['类型', '标题', '详情', '~评分', '状态', '处理'], r.data.items, function (t) {
          var m = {'waybill_overdue': '运单逾期', 'vehicle_maint': '车辆维保', 'vehicle_ins': '车辆保险',
                   'driver_license': '驾照到期', 'client_credit': '客户欠款'};
          return '<tr><td>' + esc(m[t.rtype] || t.rtype) + '</td><td>' + esc(t.title) + '</td><td>' +
            esc(t.detail || '') + '</td><td class="num">' + levelTag(t.score >= 60 ? '险' : t.score >= 35 ? '警' : t.score > 0 ? '提' : '正常') +
            ' ' + t.score + '</td><td>' + stTag(t.status) + '</td><td class="ops">' +
            (t.status === 'open' ? '<a href="javascript:void(0)" data-id="' + t.id + '">处理</a>' : esc(t.resolved_by || '')) + '</td></tr>';
        });
      document.getElementById('list').onclick = function (e) {
        var a = e.target.closest('a'); if (!a) return;
        PUT('/api/risks/' + a.getAttribute('data-id') + '/resolve', {note: '已人工确认'})
          .then(function () { toast('已处理'); load(); })
          .catch(function (e) { toast(e.message, true); });
      };
    });
  }
  document.getElementById('btn-scan').onclick = function () {
    POST('/api/risks/scan').then(function (r) { toast('扫描完成，新增 ' + r.data.new_risks + ' 条'); load(); })
      .catch(function (e) { toast(e.message, true); });
  };
  return load();
};

/* ---------- 系统 ---------- */
PAGES.system = function (main) {
  main.innerHTML = '<h2>系统管理</h2>' +
    '<div class="tabs"><button class="btn sm on" data-t="users">用户</button>' +
    '<button class="btn sm" data-t="keys">API Key</button>' +
    '<button class="btn sm" data-t="notices">公告</button>' +
    '<button class="btn sm" data-t="logs">审计日志</button></div><div id="pane"></div>';
  var cur = 'users';
  function loadPane() {
    var pane = document.getElementById('pane');
    if (cur === 'users') {
      return GET('/api/users').then(function (r) {
        pane.innerHTML = table(['ID', '用户名', '姓名', '角色', '状态', '创建时间'], r.data.items, function (u) {
          var rm = {'admin': '管理员', 'dispatcher': '调度', 'ops': '运营', 'finance': '财务', 'captain': '车队长', 'reader': '查看'};
          return '<tr><td>' + u.id + '</td><td>' + esc(u.username) + '</td><td>' + esc(u.name || '') +
            '</td><td>' + esc(rm[u.role] || u.role) + '</td><td>' + (u.status ? tag('启用', 'ok') : tag('停用', 'err')) +
            '</td><td>' + esc(String(u.created_at).slice(0, 16)) + '</td></tr>';
        });
      });
    }
    if (cur === 'keys') {
      return GET('/api/api-keys').then(function (r) {
        pane.innerHTML = '<div class="toolbar"><button class="btn sm pri" id="btn-key">生成 API Key</button></div>' +
          table(['ID', '名称', '前缀', '权限', '状态', '最近使用'], r.data.items, function (k) {
            return '<tr><td>' + k.id + '</td><td>' + esc(k.name) + '</td><td>' + esc(k.prefix || '') +
              '</td><td>' + esc(k.perms) + '</td><td>' + (k.status ? tag('有效', 'ok') : tag('已吊销', 'err')) +
              '</td><td>' + esc(k.last_used || '—') + '</td></tr>';
          });
        document.getElementById('btn-key').onclick = function () {
          POST('/api/api-keys', {name: 'key-' + Date.now()}).then(function (r2) {
            modal('<h3>API Key 已生成</h3><p style="word-break:break-all"><b>' + esc(r2.data.key) +
              '</b></p><p class="hint" style="color:var(--sub)">仅此一次显示明文，请立即保存。</p>' +
              '<div class="m-foot"><button class="btn pri" onclick="closeModal()">知道了</button></div>');
            loadPane();
          });
        };
      });
    }
    if (cur === 'notices') {
      return GET('/api/notices').then(function (r) {
        pane.innerHTML = table(['标题', '内容', '级别', '时间'], r.data.items, function (n) {
          return '<tr><td>' + esc(n.title) + '</td><td>' + esc(n.content || '') + '</td><td>' +
            esc(n.level) + '</td><td>' + esc(String(n.created_at).slice(0, 16)) + '</td></tr>';
        });
      });
    }
    return GET('/api/logs').then(function (r) {
      pane.innerHTML = table(['时间', '用户ID', '动作', '详情', 'IP'], r.data.items.slice(0, 100), function (l) {
        return '<tr><td>' + esc(l.ts) + '</td><td>' + (l.user_id || '—') + '</td><td>' + esc(l.action) +
          '</td><td>' + esc(l.detail || '') + '</td><td>' + esc(l.ip || '') + '</td></tr>';
      });
    });
  }
  main.querySelector('.tabs').onclick = function (e) {
    var b = e.target.closest('button'); if (!b) return;
    cur = b.getAttribute('data-t');
    main.querySelectorAll('.tabs button').forEach(function (x) { x.classList.toggle('on', x === b); });
    loadPane();
  };
  return loadPane();
};

/* PUT 支持 */
function PUT(p, b) { return api('PUT', p, b); }
