(function () {
  "use strict";

  var token = "";
  var zoom = 1;
  var values = {};
  var layout = null;
  var ws = null;
  var seatsTimer = null;
  var pinchStart = 0;
  var pinchZoom = 1;

  var landing = document.getElementById("landing");
  var sheetEl = document.getElementById("sheet");
  var pinInput = document.getElementById("pin");
  var nameInput = document.getElementById("name");
  var statusEl = document.getElementById("status");
  var seatsEl = document.getElementById("seats");
  var tape = document.getElementById("tape");
  var playerName = document.getElementById("player-name");
  var viewport = document.getElementById("viewport");

  function setStatus(text, isError) {
    statusEl.textContent = text || "";
    statusEl.className = isError ? "error" : "";
  }

  function authHeaders(extra) {
    var headers = extra ? Object.assign({}, extra) : {};
    if (token) {
      headers.Authorization = "Bearer " + token;
    }
    return headers;
  }

  function startSeatsPoll() {
    stopSeatsPoll();
    seatsTimer = setInterval(loadSeats, 2000);
  }

  function stopSeatsPoll() {
    if (seatsTimer) {
      clearInterval(seatsTimer);
      seatsTimer = null;
    }
  }

  async function loadSeats() {
    var pin = pinInput.value.trim();
    if (pin.length !== 4) {
      seatsEl.innerHTML = "";
      return;
    }
    var resp = await fetch("/api/seats?pin=" + encodeURIComponent(pin));
    var data = await resp.json();
    if (!resp.ok) {
      setStatus(data.error || "Неверный PIN", true);
      seatsEl.innerHTML = "";
      return;
    }
    setStatus("");
    seatsEl.innerHTML = "";
    (data.seats || []).forEach(function (seat) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      var label = seat.sheet_name;
      if (seat.occupied_by) {
        label += " — занят (" + seat.occupied_by + ")";
        btn.disabled = true;
      }
      btn.textContent = label;
      btn.addEventListener("click", function () {
        joinSeat(seat.instance_id);
      });
      li.appendChild(btn);
      seatsEl.appendChild(li);
    });
  }

  async function joinSeat(instanceId) {
    var name = nameInput.value.trim();
    if (!name) {
      setStatus("Введите имя", true);
      return;
    }
    var resp = await fetch("/api/join", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pin: pinInput.value.trim(),
        name: name,
        instance_id: instanceId,
      }),
    });
    var data = await resp.json();
    if (!resp.ok) {
      setStatus(data.error || "Вход не удался", true);
      return;
    }
    token = data.token;
    playerName.textContent = name;
    landing.hidden = true;
    sheetEl.hidden = false;
    stopSeatsPoll();
    await loadSheet();
    openWs();
  }

  function captureDrafts() {
    var drafts = {};
    tape.querySelectorAll(".field.input").forEach(function (fieldEl) {
      var fid = fieldEl.dataset.fieldId;
      if (!fid) {
        return;
      }
      var control = fieldEl.querySelector("input, textarea, select");
      if (!control || control.type === "file") {
        return;
      }
      if (control.type === "checkbox") {
        drafts[fid] = control.checked;
      } else {
        drafts[fid] = control.value;
      }
    });
    return drafts;
  }

  async function loadSheet() {
    var resp = await fetch("/api/sheet", { headers: authHeaders() });
    var data = await resp.json();
    if (!resp.ok) {
      setStatus(data.error || "Лист недоступен", true);
      return;
    }
    var drafts = captureDrafts();
    values = Object.assign({}, data.values || {}, drafts);
    layout = data.layout;
    renderLayout();
  }

  function renderLayout() {
    tape.innerHTML = "";
    if (!layout || !layout.pages) {
      return;
    }
    layout.pages.forEach(function (page) {
      var pageEl = document.createElement("div");
      pageEl.className = "page";
      pageEl.style.width = page.width;
      pageEl.style.height = page.height;
      (page.fields || []).forEach(function (field) {
        pageEl.appendChild(renderField(field));
      });
      tape.appendChild(pageEl);
    });
    applyZoom();
  }

  function renderField(field) {
    var el = document.createElement("div");
    el.className = "field " + field.type + (field.input ? " input" : "");
    el.dataset.fieldId = field.id;
    el.style.left = field.css.left;
    el.style.top = field.css.top;
    el.style.width = field.css.width;
    el.style.height = field.css.height;
    el.style.fontSize = (field.font_size || 10) + "pt";
    if (!field.input) {
      if (field.type === "label") {
        el.textContent = field.content || "";
      }
      return el;
    }
    var current = values[field.id];
    if (current === undefined || current === null) {
      current = field.content || "";
    }
    if (field.type === "textarea") {
      var ta = document.createElement("textarea");
      ta.value = String(current);
      bindCommit(ta, field, function () { return ta.value; });
      el.appendChild(ta);
    } else if (field.type === "checkbox") {
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = Boolean(current) && current !== "false";
      cb.addEventListener("change", function () {
        commit(field.id, cb.checked);
      });
      el.appendChild(cb);
    } else if (field.type === "dropdown") {
      var sel = document.createElement("select");
      (field.options || []).forEach(function (opt) {
        var o = document.createElement("option");
        o.value = opt;
        o.textContent = opt;
        sel.appendChild(o);
      });
      sel.value = String(current);
      sel.addEventListener("change", function () {
        commit(field.id, sel.value);
      });
      el.appendChild(sel);
    } else if (field.type === "image") {
      var img = document.createElement("img");
      if (typeof current === "number") {
        img.src = "/api/image/" + current + "?token=" + encodeURIComponent(token);
      }
      var file = document.createElement("input");
      file.type = "file";
      file.accept = "image/*";
      file.addEventListener("change", function () {
        if (file.files && file.files[0]) {
          uploadImage(field.id, file.files[0], img, clearBtn);
        }
      });
      var clearBtn = document.createElement("button");
      clearBtn.type = "button";
      clearBtn.textContent = "Убрать";
      clearBtn.addEventListener("click", function () {
        commit(field.id, null).then(function (ok) {
          if (ok) {
            img.removeAttribute("src");
            file.value = "";
          }
        });
      });
      el.appendChild(img);
      el.appendChild(file);
      el.appendChild(clearBtn);
    } else {
      var inp = document.createElement("input");
      inp.type = "text";
      inp.value = String(current);
      bindCommit(inp, field, function () { return inp.value; });
      el.appendChild(inp);
    }
    return el;
  }

  function bindCommit(control, field, read) {
    control.addEventListener("blur", function () {
      commit(field.id, read());
    });
    control.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && field.type !== "textarea") {
        ev.preventDefault();
        control.blur();
      }
    });
  }

  async function commit(fieldId, value) {
    var resp = await fetch("/api/field", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ field_id: fieldId, value: value }),
    });
    var data = await resp.json();
    if (!resp.ok) {
      setStatus(data.error || "Не удалось записать поле", true);
      if (resp.status === 409) {
        onKicked();
      }
      return false;
    }
    values[fieldId] = data.value;
    return true;
  }

  async function uploadImage(fieldId, file, imgEl, clearBtn) {
    var form = new FormData();
    form.append("field_id", fieldId);
    form.append("file", file);
    var resp = await fetch("/api/image", {
      method: "POST",
      headers: authHeaders(),
      body: form,
    });
    var data = await resp.json();
    if (!resp.ok) {
      setStatus(data.error || "Файл не является изображением", true);
      return;
    }
    values[fieldId] = data.image_id;
    imgEl.src = "/api/image/" + data.image_id + "?token=" + encodeURIComponent(token);
  }

  function applyRemoteValue(fieldId, value) {
    values[fieldId] = value;
    var fieldEl = tape.querySelector('.field[data-field-id="' + fieldId + '"]');
    if (!fieldEl) {
      return;
    }
    var control = fieldEl.querySelector("input, textarea, select");
    if (!control || document.activeElement === control) {
      return;
    }
    if (control.type === "checkbox") {
      control.checked = Boolean(value) && value !== "false";
    } else if (control.type === "file") {
      var img = fieldEl.querySelector("img");
      if (img) {
        if (value === null || value === undefined) {
          img.removeAttribute("src");
        } else {
          img.src = "/api/image/" + value + "?token=" + encodeURIComponent(token);
        }
      }
    } else {
      control.value = value === null || value === undefined ? "" : String(value);
    }
  }

  function applyZoom() {
    tape.style.transform = "scale(" + zoom + ")";
  }

  function touchDistance(a, b) {
    var dx = a.clientX - b.clientX;
    var dy = a.clientY - b.clientY;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function openWs() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(proto + "//" + location.host + "/ws?token=" + encodeURIComponent(token));
    ws.onmessage = function (ev) {
      var msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (e) {
        return;
      }
      if (msg.type === "kicked") {
        onKicked();
      } else if (msg.type === "stopped") {
        onStopped();
      } else if (msg.type === "layout") {
        loadSheet();
      } else if (msg.type === "value") {
        applyRemoteValue(msg.field_id, msg.value);
      }
    };
  }

  function returnToLanding(message) {
    setStatus(message, true);
    landing.hidden = false;
    sheetEl.hidden = true;
    token = "";
    if (ws) {
      ws.close();
      ws = null;
    }
    loadSeats();
    startSeatsPoll();
  }

  function onKicked() {
    returnToLanding("Вас вытеснили с листа");
  }

  function onStopped() {
    returnToLanding("Стол закрыт");
  }

  async function leave() {
    if (!token) {
      return;
    }
    try {
      await fetch("/api/leave", { method: "POST", headers: authHeaders() });
    } catch (e) {}
    returnToLanding("");
    setStatus("");
  }

  pinInput.addEventListener("input", function () {
    loadSeats();
    startSeatsPoll();
  });
  document.getElementById("leave").addEventListener("click", leave);
  document.getElementById("zoom-in").addEventListener("click", function () {
    zoom = Math.min(4, zoom + 0.1);
    applyZoom();
  });
  document.getElementById("zoom-out").addEventListener("click", function () {
    zoom = Math.max(0.25, zoom - 0.1);
    applyZoom();
  });
  viewport.addEventListener("wheel", function (ev) {
    if (!ev.ctrlKey) {
      return;
    }
    ev.preventDefault();
    zoom = Math.min(4, Math.max(0.25, zoom + (ev.deltaY < 0 ? 0.1 : -0.1)));
    applyZoom();
  }, { passive: false });
  viewport.addEventListener("touchstart", function (ev) {
    if (ev.touches.length === 2) {
      pinchStart = touchDistance(ev.touches[0], ev.touches[1]);
      pinchZoom = zoom;
    }
  }, { passive: true });
  viewport.addEventListener("touchmove", function (ev) {
    if (ev.touches.length === 2 && pinchStart) {
      ev.preventDefault();
      var d = touchDistance(ev.touches[0], ev.touches[1]);
      zoom = Math.min(4, Math.max(0.25, pinchZoom * (d / pinchStart)));
      applyZoom();
    }
  }, { passive: false });
  window.addEventListener("pagehide", function () {
    if (!token) {
      return;
    }
    navigator.sendBeacon("/api/leave?token=" + encodeURIComponent(token));
  });
})();
