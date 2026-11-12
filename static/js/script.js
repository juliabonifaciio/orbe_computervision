const STATUS = {
  pending: "Aguardando validação",
  additional_review: "Análise adicional",
  confirmed: "Confirmada",
  corrected: "Corrigida",
  rejected: "Rejeitada",
  not_required: "Não requer validação",
};
const RESULT = {
  possible: "Possível ocorrência",
  inconclusive: "Inconclusivo",
  none: "Sem ocorrência",
};
const CATEGORY = {
  vehicle: "Veículo",
  vulnerable: "Pedestre/ciclista",
  accident: "Classe de acidente",
  other: "Outro",
};
const EVIDENCE = {
  modelo_de_acidentes: "Modelo com classes de acidente",
  heuristica_modelo_generico: "Indício geométrico (modelo genérico)",
  sem_evidencia: "Sem evidência",
};
const STEPS = ["acionada", "a_caminho", "no_local", "concluida"];
const STEP_LABELS = {
  acionada: "Equipe acionada",
  a_caminho: "A caminho",
  no_local: "No local",
  concluida: "Concluído",
};
const LOADING_STEPS = [
  "Validando o arquivo",
  "Pré-processando a imagem",
  "Rodando o modelo de visão",
  "Aplicando as regras",
  "Montando o resumo para o APH",
];

function $(sel, root) {
  return (root || document).querySelector(sel);
}

function $$(sel, root) {
  return Array.from((root || document).querySelectorAll(sel));
}

function esc(v) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
    return map[c];
  });
}

function icon(name, cls) {
  return '<svg class="ic ' + (cls || "") + '"><use href="#i-' + name + '"/></svg>';
}

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch (e) {
    return iso;
  }
}

function pct(v) {
  if (v == null) return "—";
  return Math.round(v * 100) + "%";
}

function getSaved(key) {
  try {
    return localStorage.getItem(key) || "";
  } catch (e) {
    return "";
  }
}

function save(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (e) {}
}

function toast(msg, type) {
  const el = document.createElement("div");
  el.className = "toast " + (type || "success");
  el.innerHTML = icon(type === "error" ? "alert" : "ok") + "<span>" + esc(msg) + "</span>";
  $("#toasts").appendChild(el);
  setTimeout(function () {
    el.classList.add("out");
    setTimeout(function () {
      el.remove();
    }, 400);
  }, type === "error" ? 6500 : 3800);
}

async function api(url, opts) {
  let res;
  let data = null;
  try {
    res = await fetch(url, opts);
  } catch (e) {
    throw new Error("Não consegui falar com o servidor do ORBE.");
  }
  try {
    data = await res.json();
  } catch (e) {}
  if (!res.ok || !data || data.ok === false) {
    const msg = data && data.error ? data.error.message : "Erro " + res.status;
    throw new Error(msg);
  }
  return data;
}

function orbitSvg(cls) {
  const path = "M15,100 a85,36 0 1,0 170,0 a85,36 0 1,0 -170,0";
  return (
    '<svg class="orbit ' + (cls || "") + '" viewBox="0 0 200 200">' +
    '<g transform="rotate(-34 100 100)"><ellipse class="o1" cx="100" cy="100" rx="85" ry="36"/>' +
    '<circle r="7" fill="#3ee0b8"><animateMotion dur="7s" repeatCount="indefinite" path="' + path + '"/></circle>' +
    '<circle r="7" fill="#2ab4ff"><animateMotion dur="7s" begin="-3.5s" repeatCount="indefinite" path="' + path + '"/></circle></g>' +
    '<g transform="rotate(-18 100 100)"><ellipse class="o2" cx="100" cy="100" rx="85" ry="36"/>' +
    '<circle r="6" fill="#2ab4ff"><animateMotion dur="10s" repeatCount="indefinite" path="' + path + '"/></circle></g>' +
    '<circle class="core" cx="100" cy="100" r="9" fill="#dcc9ff"/></svg>'
  );
}

function startOrbits() {
  $$("[data-orbit]").forEach(function (el) {
    const kind = el.dataset.orbit;
    el.innerHTML = orbitSvg(kind === "sm" ? "sm" : "");
  });
}

function countUp() {
  $$("[data-count]").forEach(function (el) {
    const target = parseInt(el.dataset.count, 10) || 0;
    const start = performance.now();
    function tick(now) {
      const t = Math.min((now - start) / 1100, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = Math.round(target * eased);
      if (t < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  });
}

async function refreshHealth() {
  const box = $("#health");
  try {
    const h = await api("/api/health");
    box.dataset.state = h.state;
    $("span", box).textContent = h.label;
    const b = $("#reviewBadge");
    b.textContent = h.pending_review;
    b.hidden = !h.pending_review;
  } catch (e) {
    box.dataset.state = "error";
    $("span", box).textContent = "Servidor indisponível";
  }
}

function fallbackTriage(a) {
  let p = "sem_acionamento";
  if (a.result === "possible") p = "media";
  if (a.result === "inconclusive") p = "verificar";
  const levels = { alta: 3, media: 2, verificar: 1, sem_acionamento: 0 };
  const labels = { media: "Prioridade média", verificar: "Verificar na imagem", sem_acionamento: "Sem acionamento" };
  return {
    priority: p,
    priority_label: labels[p],
    level: levels[p],
    indicators: { vehicles: 0, people: 0, two_wheelers: 0, heavy: 0, fire: false, rollover: false },
    why: [],
    resources: [],
    checklist: [],
    disclaimer: "",
  };
}

function qcard(a, i, withAction) {
  const t = a.triage || fallbackTriage(a);
  const ind = t.indicators;
  let chips = "";
  if (ind.vehicles) chips += '<span class="chip">' + ind.vehicles + " veículo(s)</span>";
  if (ind.people) chips += '<span class="chip">' + ind.people + " pessoa(s)</span>";
  if (ind.two_wheelers) chips += '<span class="chip">' + ind.two_wheelers + " moto/bike</span>";
  if (ind.heavy) chips += '<span class="chip">pesado</span>';
  if (ind.fire) chips += '<span class="chip">fogo</span>';
  if (a.dispatch_status) chips += '<span class="chip">' + esc(STEP_LABELS[a.dispatch_status]) + "</span>";
  const go = withAction ? '<span class="go btn primary">' + (a.dispatch_status ? "Acompanhar" : "Revisar") + "</span>" : "";
  return (
    '<article class="qcard rise ' + t.priority + '" style="--i:' + i + '" data-href="/analysis/' + esc(a.id) + '">' +
    '<img src="/media/uploads/' + esc(a.stored_name) + '" alt="">' +
    "<div><h3>" + esc(a.image_name) + "</h3>" +
    '<span class="badge p-' + t.priority + '"><i class="dot"></i>' + esc(t.priority_label) + "</span> " +
    "<small>" + fmtDate(a.created_at) + (a.source ? " · " + esc(a.source) : "") + "</small>" +
    '<div class="chips">' + chips + "</div></div>" + go + "</article>"
  );
}

function bindCards(root) {
  $$(".qcard", root).forEach(function (c) {
    c.addEventListener("click", function () {
      location.href = c.dataset.href;
    });
  });
}

function emptyBox(text) {
  return '<div class="empty"><div class="okring">' + icon("check") + "</div><p>" + text + "</p></div>";
}

async function initDashboard() {
  countUp();
  try {
    const q = await api("/api/history?review=1&limit=5");
    const box = $("#queueBox");
    box.innerHTML = q.items.length
      ? q.items.map(function (a, i) { return qcard(a, i, true); }).join("")
      : emptyBox("Nenhuma ocorrência esperando decisão.");
    bindCards(box);
    const all = await api("/api/history?limit=200");
    const active = all.items.filter(function (a) {
      return ["acionada", "a_caminho", "no_local"].indexOf(a.dispatch_status) >= 0;
    });
    const box2 = $("#activeBox");
    box2.innerHTML = active.length
      ? active.map(function (a, i) { return qcard(a, i, false); }).join("")
      : emptyBox("Nenhuma equipe em atendimento agora.");
    bindCards(box2);
  } catch (e) {
    toast(e.message, "error");
  }
}

async function initQueue() {
  const box = $("#queueBox");
  try {
    const q = await api("/api/history?review=1&limit=100");
    box.innerHTML = q.items.length
      ? q.items.map(function (a, i) { return qcard(a, i, true); }).join("")
      : '<div class="panel">' + emptyBox("Fila vazia. Nenhuma ocorrência esperando decisão.") + "</div>";
    bindCards(box);
  } catch (e) {
    toast(e.message, "error");
  }
}

function indicatorTiles(t) {
  const ind = t.indicators;
  const items = [
    ["car", "Veículos", ind.vehicles, false],
    ["user", "Pessoas", ind.people, ind.people > 0],
    ["rotate", "Motos / bicicletas", ind.two_wheelers, ind.two_wheelers > 0],
    ["truck", "Veículos pesados", ind.heavy, ind.heavy > 0],
  ];
  let html = items
    .map(function (it) {
      return (
        '<div class="tile' + (it[3] ? " hot" : "") + '"><span>' + it[1] + '</span><strong data-count="' + it[2] + '">0</strong></div>'
      );
    })
    .join("");
  html += '<div class="tile' + (ind.fire ? " hot" : "") + '"><span>Fogo</span><strong>' + (ind.fire ? "Sim" : "Não") + "</strong></div>";
  html += '<div class="tile' + (ind.rollover ? " hot" : "") + '"><span>Capotamento</span><strong>' + (ind.rollover ? "Sim" : "Não") + "</strong></div>";
  return html;
}

function boxesSvg(a) {
  const W = a.image_width;
  const H = a.image_height;
  const fs = Math.max(13, Math.round(W / 55));
  let out = '<svg class="boxes" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none">';
  a.detections.forEach(function (d, i) {
    const x = d.bbox[0];
    const y = d.bbox[1];
    const w = d.bbox[2] - d.bbox[0];
    const h = d.bbox[3] - d.bbox[1];
    const kind = d.is_evidence ? "ev" : d.class_name === "person" ? "person" : "";
    const label = d.class_name + " " + pct(d.confidence);
    const lw = label.length * fs * 0.62 + 10;
    const ly = y - fs - 6 > 0 ? y - fs - 6 : y;
    out +=
      '<g style="--i:' + i + '"><rect id="box-' + i + '" class="box ' + kind + '" style="--i:' + i + '" x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="4"/>' +
      '<rect class="tagbg ' + kind + '" style="--i:' + i + '" x="' + x + '" y="' + ly + '" width="' + lw + '" height="' + (fs + 6) + '" rx="4"/>' +
      '<text class="tag" style="--i:' + i + '" x="' + (x + 5) + '" y="' + (ly + fs) + '" font-size="' + fs + '">' + esc(label) + "</text></g>";
  });
  return out + "</svg>";
}

function renderResult(root, a) {
  const t = a.triage || fallbackTriage(a);
  const generic = a.model_mode === "generic";
  const sum = a.llm_summary || {};
  let notice = "";
  if (generic && a.result !== "none") {
    notice =
      '<div class="caution rise">' + icon("info") +
      "<div><strong>Modelo genérico em uso.</strong> Ele enxerga veículos e pessoas, mas não foi treinado para reconhecer acidentes. Este alerta é só um indício e precisa da sua confirmação.</div></div>";
  }

  const rows = a.detections.length
    ? a.detections.map(function (d, i) {
        return (
          '<tr data-box="' + i + '"><td><strong>' + esc(d.class_name) + "</strong>" + (d.is_evidence ? '<span class="ev-tag">evidência</span>' : "") + "</td>" +
          "<td>" + esc(CATEGORY[d.category] || d.category) + "</td>" +
          '<td><div class="bar-cell"><div class="meter"><i data-w="' + Math.round(d.confidence * 100) + '"></i></div><span class="num">' + pct(d.confidence) + "</span></div></td></tr>"
        );
      }).join("")
    : '<tr><td colspan="3" class="muted">Nenhum objeto detectado.</td></tr>';

  const reasons = a.reasons.map(function (r, i) {
    return '<li style="--i:' + i + '"><span><b>' + esc(r.rule) + "</b>" + esc(r.text) + "</span></li>";
  }).join("");
  const why = t.why.map(function (w, i) {
    return '<li style="--i:' + i + '">' + icon("alert") + "<span>" + esc(w) + "</span></li>";
  }).join("");
  const res = t.resources.map(function (r, i) {
    return '<li style="--i:' + i + '">' + icon("check") + "<span>" + esc(r) + "</span></li>";
  }).join("");
  const checks = t.checklist.map(function (c) {
    return '<label class="check"><input type="checkbox"><span>' + esc(c) + "</span></label>";
  }).join("");

  root.innerHTML =
    '<section class="alert-panel rise ' + t.priority + '" role="alert">' +
    '<div class="ring"><svg viewBox="0 0 100 100"><circle class="bgc" cx="50" cy="50" r="42"/><circle class="fg" cx="50" cy="50" r="42"/></svg><b>' + t.level + "/3</b></div>" +
    "<div><h2>" + esc(t.priority_label) + "</h2><p>" + esc(RESULT[a.result]) + ": " + esc(a.situation_type) + "</p></div>" +
    '<div class="alert-side"><span class="notify">' + icon("bell") + (a.notify ? "Avisar a equipe APH" : a.requires_review ? "Conferir a imagem" : "Sem aviso") + "</span>" +
    '<small class="muted">Confiança das evidências: <strong>' + pct(a.confidence) + "</strong></small></div></section>" +
    notice +
    '<div class="grid-2">' +
    '<section class="panel rise" style="--i:1"><div class="tabs">' +
    '<button class="tab on" data-view="boxes">Câmera + detecções</button><button class="tab" data-view="processed">Imagem processada</button><button class="tab" data-view="original">Original</button></div>' +
    '<div class="viewer" id="viewer"><img id="vimg" src="/media/uploads/' + esc(a.stored_name) + '" alt="Imagem da câmera">' + boxesSvg(a) + "</div>" +
    '<div class="vcap"><span>' + a.image_width + "×" + a.image_height + " px · " + a.detection_count + " detecção(ões)</span><span>" + esc(a.source || "origem não informada") + "</span></div></section>" +
    '<section class="panel rise" style="--i:2"><h2>Cena em números</h2><div class="tiles" style="margin-top:12px">' + indicatorTiles(t) + "</div></section></div>" +
    '<div class="grid-eq">' +
    '<section class="panel rise" style="--i:3"><h2>Recursos sugeridos</h2><ul class="list" style="margin-top:12px">' + (res || '<li style="--i:0"><span class="muted">Sem sugestão para este resultado.</span></li>') + "</ul>" +
    '<p class="disc">' + esc(t.disclaimer) + "</p></section>" +
    '<section class="panel rise" style="--i:4"><h2>Checklist do atendimento</h2>' +
    (checks ? '<div class="progressbar"><i id="checkBar"></i></div><div class="list" id="checkList">' + checks + "</div>" : '<p class="muted">O checklist aparece quando há possível ocorrência.</p>') + "</section></div>" +
    '<div class="grid-eq">' +
    '<section class="panel rise" style="--i:5"><h2>Detecções</h2><div class="table-wrap"><table class="table"><thead><tr><th>Classe</th><th>Categoria</th><th>Confiança</th></tr></thead><tbody>' + rows + "</tbody></table></div></section>" +
    '<section class="panel rise" style="--i:6"><h2>Por que esta prioridade?</h2><ul class="list" style="margin:12px 0">' + why + "</ul>" +
    '<h2 style="margin-top:16px">Regras acionadas</h2><ul class="list" style="margin-top:12px">' + reasons + "</ul></section></div>" +
    '<section class="panel rise" style="--i:7"><h2>Resumo para o operador</h2><p class="summary" style="margin-top:10px">' + esc(sum.text || "") + "</p>" +
    '<span class="summary-src">' + (sum.source === "llm" ? "Texto gerado por LLM" : "Texto padrão do sistema, sem LLM") + " · a IA não confirma ocorrências.</span>" +
    '<div class="metrics"><div class="metric">Inferência<strong>' + Math.round(a.inference_ms) + " ms</strong></div>" +
    '<div class="metric">Tempo total<strong>' + Math.round(a.total_ms) + " ms</strong></div>" +
    '<div class="metric">Modelo<strong>' + esc(a.model_name) + "</strong></div>" +
    '<div class="metric">Evidência<strong>' + esc(EVIDENCE[a.evidence_level] || a.evidence_level) + "</strong></div>" +
    '<div class="metric">ID<strong class="mono">' + esc(a.id) + "</strong></div></div></section>" +
    '<div id="validation"></div>';

  setTimeout(function () {
    const fg = $(".ring .fg", root);
    if (fg) fg.style.strokeDashoffset = t.level === 0 ? 250 : 264 - (264 * t.level) / 3;
    $$(".meter i", root).forEach(function (m) {
      m.style.width = m.dataset.w + "%";
    });
  }, 80);
  countUp();
  bindViewer(root, a);
  bindChecklist(root);
  renderValidation($("#validation", root), a);
}

function bindViewer(root, a) {
  const img = $("#vimg", root);
  $$(".tab", root).forEach(function (tab) {
    tab.addEventListener("click", function () {
      $$(".tab", root).forEach(function (x) {
        x.classList.remove("on");
      });
      tab.classList.add("on");
      const v = tab.dataset.view;
      if (v === "processed") img.src = "/media/processed/" + a.processed_name;
      else img.src = "/media/uploads/" + a.stored_name;
      const svg = $("svg.boxes", root);
      svg.hidden = v !== "boxes";
      if (v === "boxes") svg.replaceWith(svg.cloneNode(true));
    });
  });
  $$("tr[data-box]", root).forEach(function (tr) {
    tr.addEventListener("mouseenter", function () {
      tr.classList.add("hl");
      const b = $("#box-" + tr.dataset.box, root);
      if (b) b.classList.add("hl");
    });
    tr.addEventListener("mouseleave", function () {
      tr.classList.remove("hl");
      const b = $("#box-" + tr.dataset.box, root);
      if (b) b.classList.remove("hl");
    });
  });
}

function bindChecklist(root) {
  const list = $("#checkList", root);
  if (!list) return;
  const bar = $("#checkBar", root);
  function update() {
    const boxes = $$("input", list);
    const done = boxes.filter(function (b) { return b.checked; }).length;
    bar.style.width = (done / boxes.length) * 100 + "%";
    $$(".check", list).forEach(function (c) {
      c.classList.toggle("done", $("input", c).checked);
    });
  }
  list.addEventListener("change", update);
}

function dispatchHtml(a) {
  const events = {};
  a.dispatch.forEach(function (e) {
    events[e.status] = e;
  });
  const current = a.dispatch_status;
  const idx = STEPS.indexOf(current);
  let html = '<div class="stepper">';
  STEPS.forEach(function (s, i) {
    let cls = "";
    if (i < idx || (i === idx && s === "concluida")) cls = "done";
    else if (i === idx) cls = "current";
    const when = events[s] ? fmtDate(events[s].created_at) : "";
    html += '<div class="step ' + cls + '"><i>' + (cls === "done" ? "✓" : i + 1) + "</i>" + STEP_LABELS[s] + "<small>" + when + "</small></div>";
  });
  html += "</div>";
  if (idx < STEPS.length - 1) {
    const next = STEPS[idx + 1];
    html += '<button class="btn success" id="nextStep" data-next="' + next + '">' + icon("check") + " Registrar: " + STEP_LABELS[next] + "</button>";
  } else {
    html += '<p class="muted">Atendimento concluído.</p>';
  }
  return html;
}

function decisionLog(a) {
  if (!a.decisions.length) return "";
  return (
    '<ul class="timeline">' +
    a.decisions.map(function (d) {
      return (
        "<li><strong>" + esc(STATUS[d.decision] || d.decision) + "</strong>" + (d.corrected_type ? " · tipo: " + esc(d.corrected_type) : "") +
        " · " + esc(d.operator || "responsável não informado") + " · " + fmtDate(d.decided_at) +
        (d.notes ? '<br><span class="muted">' + esc(d.notes) + "</span>" : "") + "</li>"
      );
    }).join("") + "</ul>"
  );
}

function renderValidation(box, a) {
  const st = a.validation_status;
  if (st === "not_required") {
    box.innerHTML = '<section class="panel rise"><h2>Validação humana</h2><p class="muted">Este resultado não precisa de decisão. Ele fica no histórico para consulta.</p></section>';
    return;
  }
  if (st === "confirmed" || st === "corrected") {
    const def = a.definitive;
    box.innerHTML =
      '<section class="panel rise"><h2>Atendimento APH</h2>' +
      '<p style="margin:8px 0 0"><span class="badge st-' + st + '">' + STATUS[st] + "</span> Registrada como <strong>ocorrência definitiva</strong> (" + esc(def.final_type) + ") por <strong>" + esc(def.operator) + "</strong> em " + fmtDate(def.confirmed_at) + ".</p>" +
      dispatchHtml(a) + decisionLog(a) +
      '<p class="disc">O resultado automático não muda. A decisão e o andamento ficam guardados separados, para auditoria.</p></section>';
    const btn = $("#nextStep", box);
    if (btn) {
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        try {
          const out = await api("/api/analyses/" + a.id + "/dispatch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: btn.dataset.next, operator: getSaved("orbe_operator") }),
          });
          renderValidation(box, Object.assign({}, a, out.analysis));
          toast(STEP_LABELS[btn.dataset.next] + ": registrado.");
          refreshHealth();
        } catch (e) {
          toast(e.message, "error");
          btn.disabled = false;
        }
      });
    }
    return;
  }
  if (st === "rejected") {
    box.innerHTML =
      '<section class="panel rise"><h2>Validação humana</h2><p style="margin:8px 0 0"><span class="badge st-rejected">Rejeitada</span> Não foi registrada como ocorrência definitiva. A decisão fica guardada para auditoria.</p>' +
      decisionLog(a) + "</section>";
    return;
  }

  const types = (window.ORBE_TYPES || []).map(function (t) {
    return "<option>" + esc(t) + "</option>";
  }).join("");
  box.innerHTML =
    '<section class="panel rise validate"><h2>Decisão do operador</h2>' +
    '<p class="muted" style="margin:6px 0 18px">' + (st === "additional_review" ? "Análise adicional pedida. " : "") + "Confira a imagem. Confirmar registra a ocorrência e abre o acompanhamento da equipe APH. Rejeitar não registra nada.</p>" +
    '<div class="grid">' +
    '<div class="field"><label for="vOperator">Responsável <small>(obrigatório para confirmar)</small></label><input type="text" id="vOperator" maxlength="80" placeholder="Seu nome" value="' + esc(getSaved("orbe_operator")) + '"></div>' +
    '<div class="field"><label for="vType">Tipo da ocorrência <small>(escolha para corrigir)</small></label><select id="vType"><option value="">Manter: ' + esc(a.situation_type) + "</option>" + types + "</select></div>" +
    '<div class="field full"><label for="vNotes">Observações <small>(opcional)</small></label><textarea id="vNotes" maxlength="1000" placeholder="O que você viu na imagem?"></textarea></div></div>' +
    '<div class="btns"><button class="btn success" data-d="confirmed">' + icon("check") + " Confirmar e acionar APH</button>" +
    '<button class="btn danger" data-d="rejected">' + icon("xcircle") + " Rejeitar</button>" +
    '<button class="btn" data-d="additional_review">' + icon("clock") + " Pedir análise adicional</button></div>" + decisionLog(a) + "</section>";

  $$("[data-d]", box).forEach(function (btn) {
    btn.addEventListener("click", async function () {
      const operator = $("#vOperator", box).value.trim();
      const decision = btn.dataset.d;
      if (decision === "confirmed" && !operator) {
        toast("Informe o responsável para confirmar.", "error");
        $("#vOperator", box).focus();
        return;
      }
      const body = {
        decision: decision,
        operator: operator,
        notes: $("#vNotes", box).value,
        corrected_type: decision === "rejected" ? "" : $("#vType", box).value,
      };
      $$("button", box).forEach(function (b) {
        b.disabled = true;
      });
      try {
        const out = await api("/api/analyses/" + a.id + "/decision", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (operator) save("orbe_operator", operator);
        renderValidation(box, Object.assign({}, a, out.analysis));
        const s = out.analysis.validation_status;
        const msgs = {
          confirmed: "Ocorrência confirmada. Acionamento do APH registrado.",
          corrected: "Ocorrência corrigida e confirmada. Acionamento do APH registrado.",
          rejected: "Suspeita rejeitada. Nada foi registrado como definitivo.",
          additional_review: "Análise adicional pedida. O caso continua na fila.",
        };
        toast(msgs[s]);
        refreshHealth();
      } catch (e) {
        toast(e.message, "error");
        $$("button", box).forEach(function (b) {
          b.disabled = false;
        });
      }
    });
  });
}

function initAnalysis() {
  const form = $("#analysisForm");
  const input = $("#fileInput");
  const zone = $("#dropzone");
  const prev = $("#preview");
  const empty = $("#dzEmpty");
  const meta = $("#fileMeta");
  const btn = $("#analyzeBtn");
  const result = $("#result");
  const scan = $("#scan");
  const stepsEl = $("#steps");
  let timer = null;

  function setFile(file) {
    if (!file) return reset();
    if (!/\.(jpe?g|png)$/i.test(file.name)) {
      toast("Formato não aceito. Envie JPG, JPEG ou PNG.", "error");
      return reset();
    }
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    prev.src = URL.createObjectURL(file);
    prev.hidden = false;
    empty.hidden = true;
    meta.hidden = false;
    meta.innerHTML = "<strong>" + esc(file.name) + "</strong><br>" + (file.size / 1024 / 1024).toFixed(2) + " MB";
    btn.disabled = false;
  }

  function reset() {
    input.value = "";
    prev.hidden = true;
    prev.removeAttribute("src");
    empty.hidden = false;
    meta.hidden = true;
    btn.disabled = true;
    result.hidden = true;
    result.innerHTML = "";
    $("#sourceInput").value = "";
  }

  function startLoading() {
    scan.hidden = false;
    stepsEl.innerHTML = LOADING_STEPS.map(function (s) {
      return "<li><i></i>" + s + "</li>";
    }).join("");
    let i = 0;
    const items = $$("li", stepsEl);
    items[0].classList.add("on");
    timer = setInterval(function () {
      if (i < items.length - 1) {
        items[i].classList.remove("on");
        items[i].classList.add("done");
        i++;
        items[i].classList.add("on");
      }
    }, 800);
  }

  function stopLoading() {
    clearInterval(timer);
    $$("li", stepsEl).forEach(function (li) {
      li.className = "done";
    });
    return new Promise(function (resolve) {
      setTimeout(function () {
        scan.hidden = true;
        resolve();
      }, 500);
    });
  }

  input.addEventListener("change", function () {
    setFile(input.files[0]);
  });
  $("#clearBtn").addEventListener("click", reset);
  ["dragenter", "dragover"].forEach(function (ev) {
    zone.addEventListener(ev, function (e) {
      e.preventDefault();
      zone.classList.add("drag");
    });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    zone.addEventListener(ev, function (e) {
      e.preventDefault();
      zone.classList.remove("drag");
    });
  });
  zone.addEventListener("drop", function (e) {
    setFile(e.dataTransfer.files[0]);
  });
  zone.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      input.click();
    }
  });

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    if (!input.files[0]) return;
    btn.disabled = true;
    result.hidden = true;
    startLoading();
    try {
      const out = await api("/api/analyze", { method: "POST", body: new FormData(form) });
      await stopLoading();
      renderResult(result, out.analysis);
      result.hidden = false;
      result.scrollIntoView({ behavior: "smooth", block: "start" });
      if (out.analysis.notify) toast("Possível ocorrência. Confira a imagem e decida se aciona o APH.");
      else toast("Análise concluída.");
      refreshHealth();
    } catch (err) {
      clearInterval(timer);
      scan.hidden = true;
      toast(err.message, "error");
      refreshHealth();
    }
    btn.disabled = false;
  });
}

async function initDetail() {
  const root = $("#result");
  try {
    const out = await api("/api/analyses/" + root.dataset.analysisId);
    renderResult(root, out.analysis);
  } catch (e) {
    root.innerHTML = '<div class="panel empty"><p>' + esc(e.message) + "</p></div>";
  }
}

function initHistory() {
  const f = $("#filters");
  const body = $("#historyBody");
  let timer;

  async function load() {
    const p = new URLSearchParams(new FormData(f));
    Array.from(p.keys()).forEach(function (k) {
      if (!p.get(k)) p.delete(k);
    });
    try {
      const out = await api("/api/history?" + p);
      body.innerHTML = out.items.map(function (a, i) {
        const t = a.triage || fallbackTriage(a);
        return (
          '<tr class="clickable" style="--i:' + i + '" data-href="/analysis/' + esc(a.id) + '">' +
          "<td><strong>" + esc(a.image_name) + '</strong><small class="muted block">' + esc(a.source || a.id) + "</small></td>" +
          "<td>" + fmtDate(a.created_at) + "</td>" +
          '<td><span class="badge p-' + t.priority + '"><i class="dot"></i>' + esc(t.priority_label) + "</span></td>" +
          "<td>" + (a.classes.length ? esc(a.classes.join(", ")) : '<span class="muted">—</span>') + "</td>" +
          '<td class="num">' + pct(a.confidence) + "</td>" +
          '<td><span class="badge st-' + a.validation_status + '">' + esc(STATUS[a.validation_status]) + "</span>" +
          (a.operator ? '<small class="muted block">' + esc(a.operator) + "</small>" : "") + "</td>" +
          "<td>" + (a.dispatch_status ? esc(STEP_LABELS[a.dispatch_status]) : '<span class="muted">—</span>') + "</td>" +
          '<td class="right"><a class="link" href="/analysis/' + esc(a.id) + '">Detalhes</a></td></tr>'
        );
      }).join("");
      const emp = $("#historyEmpty");
      emp.hidden = out.count > 0;
      $("#historyTable").hidden = out.count === 0;
      $("p", emp).textContent = "Nenhuma análise encontrada com esses filtros.";
      $("#historyCount").textContent = out.count ? out.count + " análise(s)" : "";
    } catch (e) {
      toast(e.message, "error");
    }
  }

  body.addEventListener("click", function (e) {
    const tr = e.target.closest("tr[data-href]");
    if (tr && !e.target.closest("a")) location.href = tr.dataset.href;
  });
  f.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(load, 250);
  });
  f.addEventListener("submit", function (e) {
    e.preventDefault();
  });
  $("#fclear").addEventListener("click", function () {
    f.reset();
    load();
  });
  load();
}

startOrbits();
refreshHealth();
setInterval(refreshHealth, 15000);
const page = document.body.dataset.page;
if (page === "dashboard") initDashboard();
if (page === "queue") initQueue();
if (page === "analysis") initAnalysis();
if (page === "detail") initDetail();
if (page === "history") initHistory();
