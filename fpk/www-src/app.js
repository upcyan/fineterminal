/* FineTerminal Web 前端：多标签 xterm.js 客户端 */
/* global Terminal, FitAddon, WebLinksAddon */
(function () {
  "use strict";

  // ---------- 依赖保障：本地 vendor 缺失时自动回退 CDN ----------
  var CDN = [
    "https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js",
    "https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js",
    "https://cdn.jsdelivr.net/npm/xterm-addon-web-links@0.9.0/lib/xterm-addon-web-links.js",
  ];

  function depsReady() {
    return !!(window.Terminal && window.FitAddon && window.WebLinksAddon);
  }

  function showError(msg) {
    var bar = document.getElementById("errbar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "errbar";
      bar.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:9999;background:#c0392b;color:#fff;font:12px monospace;padding:6px 10px;white-space:pre-wrap;";
      document.body.appendChild(bar);
    }
    bar.textContent += msg + "\n";
  }

  window.onerror = function (msg, src, line) {
    showError("JS错误: " + msg + " @" + String(src || "?").split("/").pop() + ":" + line);
    return false;
  };

  function bootWhenReady() {
    if (depsReady()) { boot(); return; }
    var pending = CDN.slice();
    showError("本地依赖未加载，回退 CDN…");
    pending.forEach(function (src) {
      var s = document.createElement("script");
      s.src = src;
      s.onerror = function () { showError("CDN 加载失败: " + src); };
      document.head.appendChild(s);
    });
    var tries = 0;
    (function wait() {
      if (depsReady()) { boot(); return; }
      if (++tries > 100) { showError("依赖加载超时，请检查网络后刷新"); return; }
      setTimeout(wait, 150);
    })();
  }

  function boot() {
  if (window.__FT_BOOTED__) return;
  window.__FT_BOOTED__ = true;

  var THEMES = {
    "深色 Dark": { background: "#16181d", foreground: "#d8dee9", cursor: "#4fc3f7", selectionBackground: "#3a465c" },
    "黑绿 Linux": { background: "#000000", foreground: "#cfcfcf", cursor: "#28c840", selectionBackground: "#215b2b" },
    "Solarized Dark": { background: "#002b36", foreground: "#839496", cursor: "#93a1a1", selectionBackground: "#274642" },
    "Solarized Light": { background: "#fdf6e3", foreground: "#657b83", cursor: "#586e75", selectionBackground: "#eee8d5" },
    "Dracula": { background: "#282a36", foreground: "#f8f8f2", cursor: "#ff79c6", selectionBackground: "#44475a" },
    "Nord": { background: "#2e3440", foreground: "#d8dee9", cursor: "#88c0d0", selectionBackground: "#434c5e" },
    "浅色 Light": { background: "#ffffff", foreground: "#333333", cursor: "#0064c8", selectionBackground: "#b3d7ff" },
  };

  var LS = {
    get: function (k, d) { try { var v = localStorage.getItem("fineterminal." + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem("fineterminal." + k, JSON.stringify(v)); } catch (e) {} },
  };

  var termEls = document.getElementById("terms");
  var tabbar = document.getElementById("tabbar");
  var newtabBtn = document.getElementById("newtab");
  var themeSel = document.getElementById("theme");
  var qcInput = document.getElementById("qc");
  var toastEl = document.getElementById("toast");
  var toastTimer = null;

  var nextId = 1;
  var tabs = [];
  var activeTab = null;
  var sharedWs = null;
  var wsHandlers = {};
  var exitHandlers = {};
  var reconnectTimer = null;
  var fontSize = LS.get("fontSize", 14);
  var themeName = LS.get("theme", "深色 Dark");

  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("show"); }, 2200);
  }

  // ---------- 应用密码锁 ----------
  var lockEl = document.getElementById("lock");
  var lockPass = document.getElementById("lockPass");
  var lockPass2 = document.getElementById("lockPass2");
  var lockErr = document.getElementById("lockErr");
  var lockOk = document.getElementById("lockOk");
  var lockCancel = document.getElementById("lockCancel");
  var lockTitle = document.getElementById("lockTitle");
  var lockMode = "unlock";

  function showLock(mode) {
    lockMode = mode;
    lockErr.textContent = "";
    lockPass.value = "";
    lockPass2.value = "";
    if (mode === "set") {
      lockTitle.textContent = "设置锁屏密码";
      lockPass.placeholder = "新密码（至少 4 位）";
      lockPass2.classList.remove("hide");
      lockCancel.classList.remove("hide");
      lockOk.textContent = "保存";
    } else {
      lockTitle.textContent = "🔒 终端已锁定";
      lockPass.placeholder = "请输入解锁密码";
      lockPass2.classList.add("hide");
      lockCancel.classList.add("hide");
      lockOk.textContent = "解锁";
    }
    lockEl.classList.remove("hidden");
    lockPass.focus();
  }

  function hideLock() { lockEl.classList.add("hidden"); }

  lockOk.addEventListener("click", function () {
    var p1 = lockPass.value;
    if (lockMode === "set") {
      if (p1.length < 4) { lockErr.textContent = "密码至少 4 位"; return; }
      if (p1 !== lockPass2.value) { lockErr.textContent = "两次输入不一致"; return; }
      wsSend({ type: "config", password: p1 });
      hideLock();
      toast("锁屏密码已设置，下次打开需输入");
      return;
    }
    wsSend({ type: "auth", password: p1 });
  });
  lockPass.addEventListener("keydown", function (ev) { if (ev.key === "Enter") lockOk.click(); });
  lockPass2.addEventListener("keydown", function (ev) { if (ev.key === "Enter") lockOk.click(); });
  lockCancel.addEventListener("click", hideLock);
  document.getElementById("lockbtn").addEventListener("click", function () { showLock("set"); });

  // ---------- WebSocket（所有标签共享一条连接） ----------
  // 参考官方应用：网关不剥离前缀，固定 /app/fineterminal/ws 优先
  function wsOrigin() {
    var proto = location.protocol === "https:" ? "wss://" : "ws://";
    return proto + location.host;
  }
  function wsCandidates() {
    var path = location.pathname.replace(/\/+$/, "");
    var token = window.__FT_TOKEN || "";
    var list = [];
    ["/app/fineterminal", path, ""].forEach(function (p) {
      p = (p || "").replace(/\/+$/, "");
      if (list.indexOf(p) < 0) list.push(p);
    });
    return list.map(function (p) {
      return wsOrigin() + p + "/ws?ft=" + encodeURIComponent(token);
    });
  }
  var wsTryIndex = 0;
  var wsEverConnected = false;

  function connect() {
    if (sharedWs && (sharedWs.readyState === 0 || sharedWs.readyState === 1)) return;
    var candidates = wsCandidates();
    var url = candidates[wsTryIndex % candidates.length];
    var ws;
    try { ws = new WebSocket(url); } catch (e) { showError("WebSocket 创建失败: " + e.message); return; }
    ws.binaryType = "arraybuffer";
    sharedWs = ws;
    ws.onopen = function () {
      wsEverConnected = true;
      // 连接后先向服务端对账：恢复已保留的会话 / 重新附着本地标签
      wsSend({ type: "list" });
      toast("已连接");
    };
    ws.onmessage = function (ev) {
      if (ev.data instanceof ArrayBuffer) {
        if (ev.data.byteLength < 4) return;
        var dv = new DataView(ev.data);
        var sid = dv.getUint32(0);
        var fn = wsHandlers[sid];
        if (fn) fn(new Uint8Array(ev.data, 4));
        return;
      }
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === "exit") {
        var fn2 = exitHandlers[msg.id];
        if (fn2) fn2(msg.code);
      } else if (msg.type === "sessions") {
        reconcile(msg.items || [], msg.persist !== false);
      } else if (msg.type === "missing") {
        // 服务端会话已丢失：本地标签重建会话
        var tab = tabs.filter(function (t) { return t.id === msg.id; })[0];
        if (tab) wsSend({ type: "create", id: tab.id, cols: tab.term.cols, rows: tab.term.rows });
      } else if (msg.type === "auth_state") {
        if (lockEl.classList.contains("hidden")) showLock("unlock");
        if (msg.bad) lockErr.textContent = "密码错误";
      } else if (msg.type === "unlock") {
        hideLock();
        wsSend({ type: "list" });  // 解锁后重新对账，恢复会话
      } else if (msg.type === "pw_set") {
        toast(msg.set ? "锁屏密码已设置" : "锁屏密码已清除");
      }
    };
    ws.onclose = function () {
      if (!wsEverConnected) {
        wsTryIndex++;
        // 所有候选路径都试过仍连不上：令牌可能已失效，刷新页面重新获取
        var cands = wsCandidates().length;
        if (wsTryIndex >= cands * 2) {
          toast("无法连接，正在刷新页面…");
          setTimeout(function () { location.reload(); }, 1200);
          return;
        }
        toast("连接失败，切换路径重试…");
      } else {
        toast("连接断开，3 秒后重连…");
      }
      tabs.forEach(function (tab) { tab.term.write("\r\n\u001b[33m-- 连接断开 --\u001b[0m\r\n"); });
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, wsEverConnected ? 3000 : 800);
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
  }

  function wsSend(obj) {
    if (sharedWs && sharedWs.readyState === 1) sharedWs.send(JSON.stringify(obj));
  }
  function wsSendBin(sid, bytes) {
    if (sharedWs && sharedWs.readyState === 1) {
      var head = new Uint8Array(4);
      new DataView(head.buffer).setUint32(0, sid);
      var out = new Uint8Array(4 + bytes.length);
      out.set(head); out.set(bytes, 4);
      sharedWs.send(out);
    }
  }

  // fit 后立即把新尺寸上报服务端：shell/程序按 PTY 宽度换行，
  // 尺寸不同步会导致输出错位、旧内容残留（窗口缩放/软键盘/旋转后）
  function fitAndReport(tab) {
    if (!tab || !tab.term.element) return;
    tab.fit.fit();
    wsSend({ type: "resize", id: tab.id, cols: tab.term.cols, rows: tab.term.rows });
  }

  // ---------- 标签 ----------
  // opts: {id, title, banner, restore} —— restore=附着已有服务端会话而非新建
  function createTab(opts) {
    opts = opts || {};
    try {
      var id = opts.id || nextId++;
      if (opts.id && id >= nextId) nextId = id + 1;
      var wrap = document.createElement("div");
      wrap.className = "termwrap";
      termEls.appendChild(wrap);

      var term = new Terminal({
        fontSize: fontSize,
        fontFamily: '"Cascadia Mono","JetBrains Mono",Menlo,Consolas,"DejaVu Sans Mono",monospace',
        cursorBlink: true,
        scrollback: 5000,
        theme: THEMES[themeName] || THEMES["深色 Dark"],
        allowProposedApi: true,
      });
      var fit = new FitAddon.FitAddon();
      term.loadAddon(fit);
      term.loadAddon(new WebLinksAddon.WebLinksAddon());

      var tab = { id: id, title: opts.title || ("终端 " + id), term: term, fit: fit, wrap: wrap };
      tabs.push(tab);

      // 标签页 UI
      var tabEl = document.createElement("div");
      tabEl.className = "tab";
      tabEl.innerHTML = '<span class="t"></span><span class="x" title="关闭">✕</span>';
      tabEl.querySelector(".t").textContent = tab.title;
      tabEl.addEventListener("click", function (ev) {
        if (ev.target.classList.contains("x")) { closeTab(tab); return; }
        activate(tab);
      });
      tab.el = tabEl;
      tabbar.insertBefore(tabEl, newtabBtn);

      // 先激活（让容器可见），再 open —— 避免 0 尺寸初始化异常
      activate(tab);
      term.open(wrap);
      fit.fit();

      wsHandlers[id] = function (data) { term.write(data); };
      exitHandlers[id] = function () {
        term.write("\r\n\u001b[31m-- 会话已结束 --\u001b[0m\r\n");
        toast(tab.title + " 已退出");
      };
      term.onData(function (d) { wsSendBin(id, new TextEncoder().encode(d)); });
      term.onTitleChange(function (t) {
        if (t) {
          tab.title = t;
          tabEl.querySelector(".t").textContent = t;
          wsSend({ type: "title", id: id, title: t });  // 同步服务端，恢复时还原标签名
        }
      });
      term.attachCustomKeyEventHandler(function (ev) {
        if (ev.type === "keydown" && ev.ctrlKey && ev.shiftKey) {
          var k = ev.key.toLowerCase();
          if (k === "c" && term.hasSelection()) return true;
          if (k === "t") { createTab(); return false; }
          if (k === "w") { closeTab(tab); return false; }
        }
        return true;
      });

      if (opts.restore) {
        // 清空本地缓冲，等待服务端回放"横幅+历史"重建画面
        term.reset();
        wsSend({ type: "attach", id: id, cols: term.cols, rows: term.rows });
      } else {
        connect();
        wsSend({ type: "create", id: id, cols: term.cols, rows: term.rows });
      }
      return tab;
    } catch (e) {
      showError("创建终端失败: " + (e && e.message ? e.message : e));
      throw e;
    }
  }

  // 与服务端会话对账：本地标签附着/重建，服务端保留会话恢复为标签
  function reconcile(items, persist) {
    var toggle = document.getElementById("persistToggle");
    if (toggle) toggle.checked = !!persist;

    var localIds = {};
    tabs.forEach(function (t) { localIds[t.id] = 1; });
    var serverIds = {};
    items.forEach(function (s) { serverIds[s.id] = 1; });

    tabs.forEach(function (t) {
      if (serverIds[t.id]) {
        // 重连附着：清屏后由服务端回放历史，重建完整画面
        t.term.reset();
        wsSend({ type: "attach", id: t.id, cols: t.term.cols, rows: t.term.rows });
      } else {
        wsSend({ type: "create", id: t.id, cols: t.term.cols, rows: t.term.rows });
      }
    });

    var restored = 0;
    items.forEach(function (s) {
      if (!localIds[s.id]) {
        createTab({ id: s.id, title: s.title || undefined, banner: true, restore: true });
        restored++;
      }
    });

    if (tabs.length === 0) createTab();
    if (restored > 0) toast("已恢复 " + restored + " 个会话");
  }

  function activate(tab) {
    if (activeTab && activeTab !== tab) activeTab.wrap.classList.remove("active");
    tabs.forEach(function (t) { t.el.classList.remove("active"); });
    activeTab = tab;
    tab.wrap.classList.add("active");
    tab.el.classList.add("active");
    if (tab.term.element) { fitAndReport(tab); tab.term.focus(); }
  }

  function closeTab(tab) {
    var i = tabs.indexOf(tab);
    if (i < 0) return;
    tabs.splice(i, 1);
    tab.el.remove();
    tab.wrap.remove();
    delete wsHandlers[tab.id];
    delete exitHandlers[tab.id];
    wsSend({ type: "kill", id: tab.id });
    if (tabs.length === 0) { createTab(); return; }
    if (activeTab === tab) activate(tabs[Math.max(0, i - 1)]);
  }

  // ---------- 工具栏 ----------
  Object.keys(THEMES).forEach(function (name) {
    var opt = document.createElement("option");
    opt.value = name; opt.textContent = name;
    themeSel.appendChild(opt);
  });
  themeSel.value = themeName;
  themeSel.addEventListener("change", function () {
    themeName = themeSel.value;
    LS.set("theme", themeName);
    tabs.forEach(function (tab) { tab.term.options.theme = THEMES[themeName]; });
  });

  function setFontSize(delta) {
    fontSize = Math.min(30, Math.max(8, fontSize + delta));
    LS.set("fontSize", fontSize);
    tabs.forEach(function (tab) { tab.term.options.fontSize = fontSize; fitAndReport(tab); });
  }
  document.getElementById("fplus").addEventListener("click", function () { setFontSize(1); });
  document.getElementById("fminus").addEventListener("click", function () { setFontSize(-1); });

  document.getElementById("copy").addEventListener("click", function () {
    if (activeTab && activeTab.term.hasSelection()) {
      navigator.clipboard.writeText(activeTab.term.getSelection()).then(function () { toast("已复制"); });
    } else { toast("请先选中内容"); }
  });
  document.getElementById("paste").addEventListener("click", function () {
    navigator.clipboard.readText().then(function (t) {
      if (activeTab) activeTab.term.paste(t);
    }).catch(function () { toast("无法读取剪贴板，请用 Ctrl+Shift+V"); });
  });

  function sendQuick() {
    var cmd = qcInput.value.trim();
    if (!cmd || !activeTab) return;
    activeTab.term.paste(cmd + "\n");
    qcInput.value = "";
    activeTab.term.focus();
  }
  document.getElementById("qcsend").addEventListener("click", sendQuick);
  qcInput.addEventListener("keydown", function (ev) { if (ev.key === "Enter") sendQuick(); });

  // 保留会话开关：同步到服务端并持久化
  var persistToggle = document.getElementById("persistToggle");
  if (persistToggle) {
    persistToggle.addEventListener("change", function () {
      wsSend({ type: "config", persist: persistToggle.checked });
      toast(persistToggle.checked ? "已开启：关闭后保留会话" : "已关闭：关闭后结束会话");
    });
  }

  newtabBtn.addEventListener("click", createTab);

  window.addEventListener("resize", function () {
    if (activeTab) fitAndReport(activeTab);
  });
  // 移动端软键盘弹出/收起不总是触发 window.resize，visualViewport 才可靠
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", function () {
      if (activeTab) fitAndReport(activeTab);
    });
  }

  // 首屏等待服务端对账结果创建/恢复标签；连接迟迟不通则本地先建一个
  connect();
  setTimeout(function () { if (tabs.length === 0) createTab(); }, 4000);
  } // boot

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootWhenReady);
  } else {
    bootWhenReady();
  }
})();
