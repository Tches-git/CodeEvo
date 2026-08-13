const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const titles = {
  overview: "运行总览",
  review: "发起审查",
  tasks: "任务中心",
  annotations: "标注工作台",
  skills: "Skill 注册中心",
  evolution: "演进实验室",
};

const stateLabels = {
  PENDING: "等待中",
  PLANNING: "规划中",
  EXECUTING: "执行中",
  REVIEWING: "汇总中",
  SUCCESS: "已完成",
  FAILED: "失败",
  CANCELLED: "已取消",
};

const annotationStatusLabels = {
  ready: "待标注",
  in_review: "标注中",
  needs_adjudication: "待仲裁",
  approved: "已通过",
  exported: "已导出",
};

let selectedTask = null;
let selectedTaskData = null;
let accessToken = localStorage.getItem("codeevo_token") || "";
let currentRole = localStorage.getItem("codeevo_role") || (accessToken ? "" : "admin");
let selectedAnnotationCase = null;
let toastTimer = null;
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = value ?? "";
  return node.innerHTML;
}

function escapeAttr(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function formatTime(value) {
  if (!value) return "时间未知";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : new Intl.DateTimeFormat("zh-CN", {
        month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      }).format(date);
}

function formatJson(value) {
  return JSON.stringify(value, null, 2);
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("json") ? await response.json() : await response.text();

  if (response.status === 401) {
    $("#login-overlay").classList.remove("hidden");
    $("#logout").classList.add("hidden");
  }
  if (!response.ok) {
    const plainText = typeof data === "string" && !/<[a-z][\s\S]*>/i.test(data) ? data.trim() : "";
    const message = typeof data === "object"
      ? data.error || data.detail
      : plainText || `请求失败 (${response.status})`;
    throw new Error(message || response.statusText || "请求失败");
  }
  return data;
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("show"), 2600);
}

function setButtonBusy(button, busy, busyText) {
  if (!button) return;
  button.setAttribute("aria-busy", String(busy));
  if (busy) {
    button.dataset.label = button.innerHTML;
    button.disabled = true;
    button.textContent = busyText;
  } else {
    button.disabled = false;
    if (button.dataset.label) button.innerHTML = button.dataset.label;
  }
}

function applyRoleVisibility() {
  $$(".manager-only").forEach((element) => {
    element.classList.toggle("role-hidden", currentRole !== "admin");
  });
}

function show(view, updateHash = true) {
  if (!titles[view]) {
    view = "overview";
    history.replaceState(null, "", "#overview");
  }
  $$(".view").forEach((element) => element.classList.remove("active"));
  $$(".nav-item").forEach((element) => {
    const active = element.dataset.view === view;
    element.classList.toggle("active", active);
    element.setAttribute("aria-current", active ? "page" : "false");
  });
  $(`#view-${view}`).classList.add("active");
  $("#page-title").textContent = titles[view];
  document.title = `${titles[view]} · CodeEvo`;
  if (updateHash) history.replaceState(null, "", `#${view}`);

  if (view === "tasks") loadTasks();
  if (view === "annotations") loadAnnotationCases();
  if (view === "skills") loadSkills();
  if (view === "evolution") loadFailures();
  window.scrollTo({ top: 0, behavior: reduceMotion.matches ? "auto" : "smooth" });
}

$$(".nav-item").forEach((button) => button.addEventListener("click", () => show(button.dataset.view)));
$$("[data-jump]").forEach((button) => button.addEventListener("click", () => show(button.dataset.jump)));
window.addEventListener("hashchange", () => show(location.hash.slice(1), false));

function taskRows(tasks) {
  if (!tasks?.length) {
    return '<div class="empty-state"><span><b>还没有审查任务</b>提交一个 Diff 开始首次审查</span></div>';
  }
  return tasks.map((task) => {
    const state = String(task.state || "PENDING").toUpperCase();
    const repository = escapeHtml(task.repository || "未命名仓库");
    const pr = task.pull_request ? `PR #${escapeHtml(task.pull_request)}` : "手动审查";
    return `
      <button class="task-row" data-task="${escapeHtml(task.id)}" type="button">
        <span class="task-main">
          <span class="task-glyph">PR</span>
          <span class="task-copy">
            <span class="task-name">${repository}</span>
            <span class="task-meta"><span>${pr}</span><span>${escapeHtml(formatTime(task.created_at))}</span></span>
          </span>
        </span>
        <span class="status state-${state.toLowerCase()}">${stateLabels[state] || escapeHtml(state)}</span>
      </button>`;
  }).join("");
}

function bindTasks(root) {
  $$("[data-task]", root).forEach((row) => row.addEventListener("click", () => openTask(row.dataset.task)));
}

function statCard(label, value, note, style, icon) {
  return `<article class="stat ${style}">
    <div class="stat-head"><span>${label}</span><i>${icon}</i></div>
    <b>${value}</b><small>${note}</small>
  </article>`;
}

function renderLlmRuntime(llm = {}) {
  const enabled = Boolean(llm.enabled);
  const failed = Boolean(llm.error);
  const provider = String(llm.provider || "local");
  const model = String(llm.model || "");
  const detail = failed
    ? "暂时无法读取模型配置"
    : enabled
      ? `${provider} / ${model || "默认模型"}，参与上下文审查与风险判断`
      : "未配置模型，当前由确定性本地规则 Agent 兜底";
  const state = failed ? "读取失败" : enabled ? "已启用" : "待配置";
  const runtime = failed
    ? "运行时状态未知"
    : enabled
      ? `${provider} / ${model || "模型已配置"}`
      : "Local rules fallback";

  const step = $("#llm-agent-step");
  step.classList.remove("is-pending");
  step.classList.toggle("is-active", enabled);
  step.classList.toggle("is-disabled", !enabled && !failed);
  step.classList.toggle("is-error", failed);
  $("#llm-agent-detail").textContent = detail;
  $("#llm-agent-state").textContent = state;

  const status = $("#llm-runtime-status");
  status.className = `runtime-status ${failed ? "is-error" : enabled ? "is-active" : "is-disabled"}`;
  status.textContent = state;
  const capability = $("#llm-capability");
  capability.classList.toggle("is-active", enabled);
  capability.classList.toggle("is-disabled", !enabled && !failed);
  capability.classList.toggle("is-error", failed);
  $("#llm-capability-detail").textContent = detail;
  $("#llm-runtime-model").textContent = runtime;
}

async function loadDashboard() {
  try {
    const data = await api("/api/dashboard");
    renderLlmRuntime(data.llm);
    $("#system-status").textContent = `${data.queue} · ${data.orchestrator}`;
    const stats = data.stats || {};
    const rate = Math.round(Number(stats.success_rate || 0) * 100);
    $("#stats").innerHTML = [
      statCard("总任务", stats.tasks_total ?? 0, "累计审查任务", "", "ALL"),
      statCard("已完成", stats.tasks_success ?? 0, "通过质量门禁", "success", "OK"),
      statCard("失败", stats.tasks_failed ?? 0, "需要进一步处理", "failed", "ERR"),
      statCard("成功率", `${rate}%`, "全部任务成功率", "rate", "RATE"),
      statCard("待处理案例", stats.unresolved_failure_cases ?? 0, "未解决反馈", "feedback", "OPEN"),
      statCard("活跃 Skills", stats.active_skill_versions ?? 0, "当前生效版本", "skills", "SK"),
    ].join("");
    $("#recent-tasks").innerHTML = taskRows((data.tasks || []).slice(0, 5));
    bindTasks($("#recent-tasks"));
  } catch (error) {
    renderLlmRuntime({ error: true });
    $("#system-status").textContent = "服务连接异常";
    $("#stats").innerHTML = '<div class="empty-state"><span><b>暂时无法读取数据</b>请检查服务状态后重试</span></div>';
    $("#recent-tasks").innerHTML = '<div class="empty-state"><span>数据加载失败</span></div>';
    toast(error.message);
  }
}

async function loadTasks() {
  const root = $("#all-tasks");
  root.innerHTML = '<div class="list-loading"></div><div class="list-loading"></div>';
  try {
    const data = await api("/api/tasks");
    root.innerHTML = taskRows(data.tasks || []);
    bindTasks(root);
  } catch (error) {
    root.innerHTML = '<div class="empty-state"><span>任务加载失败</span></div>';
    toast(error.message);
  }
}

async function openTask(id) {
  show("tasks");
  $("#task-report").textContent = "正在加载任务报告…";
  $("#feedback-panel").classList.add("hidden");
  try {
    const task = await api(`/v1/tasks/${encodeURIComponent(id)}`);
    selectedTask = id;
    selectedTaskData = task;
    $("#task-report").textContent = formatJson(task);
    $("#create-fix").classList.toggle("hidden", !(task.report && task.pull_request));
    const feedbackReady = task.state === "SUCCESS" && task.report;
    $("#feedback-panel").classList.toggle("hidden", !feedbackReady);
    if (feedbackReady) {
      populateFeedbackFindings(task.report.findings || []);
      await loadTaskFeedback(id);
    }
  } catch (error) {
    $("#task-report").textContent = error.message;
    selectedTaskData = null;
  }
}

const feedbackLabels = {
  false_positive: "误报",
  missed_issue: "漏报",
  bad_fix: "坏修复",
  accepted: "已接受",
};

function populateFeedbackFindings(findings) {
  const select = $("#feedback-finding");
  select.innerHTML = '<option value="">不关联已有结论</option>' + findings.map((finding, index) => {
    const identity = `${finding.rule_id || "未命名规则"} · ${finding.path || "未知文件"}:${finding.line || "?"}`;
    return `<option value="${index}">${escapeHtml(identity)}</option>`;
  }).join("");
  $("#feedback-result").textContent = "";
}

function renderTaskFeedback(cases) {
  const root = $("#task-feedback-history");
  if (!cases.length) {
    root.innerHTML = '<p class="feedback-empty">尚无反馈。提交后，它会在这里保留并进入后续评测。</p>';
    return;
  }
  root.innerHTML = `<p class="list-section-label">本任务反馈</p>${cases.map((item) => {
    const payload = item.payload || {};
    const finding = payload.finding || {};
    const reference = finding.rule_id
      ? `${finding.rule_id}${finding.path ? ` · ${finding.path}:${finding.line || "?"}` : ""}`
      : "未关联审查结论";
    return `<div class="feedback-case">
      <span class="feedback-case-type">${escapeHtml(feedbackLabels[item.category] || item.category)}</span>
      <span class="feedback-case-copy"><b>${escapeHtml(reference)}</b><small>${escapeHtml(payload.note || "未填写说明")}</small></span>
      <span class="status ${item.resolved ? "state-success" : "state-pending"}">${item.resolved ? "已解决" : "待评测"}</span>
    </div>`;
  }).join("")}`;
}

async function loadTaskFeedback(taskId) {
  const root = $("#task-feedback-history");
  root.innerHTML = '<p class="feedback-empty">正在读取本任务反馈…</p>';
  try {
    const data = await api(`/v1/tasks/${encodeURIComponent(taskId)}/feedback`);
    if (selectedTask === taskId) renderTaskFeedback(data.cases || []);
  } catch (error) {
    root.innerHTML = `<p class="feedback-empty">无法读取反馈历史：${escapeHtml(error.message)}</p>`;
  }
}

async function loadSkills() {
  const root = $("#skill-list");
  root.innerHTML = '<div class="skill-card loading"></div><div class="skill-card loading"></div>';
  try {
    const data = await api("/api/skills");
    renderLlmRuntime(data.llm);
    const skills = (data.skills || []).filter((skill) => skill.name !== "llm-review");
    root.innerHTML = skills.length ? skills.map((skill) => `
      <article class="skill-card">
        <span class="skill-label">${skill.sandboxed ? "SANDBOXED SKILL" : "ACTIVE SKILL"}</span>
        <h3>${escapeHtml(skill.name)}</h3>
        <p>${escapeHtml(skill.description || "暂无能力描述")}</p>
        <span class="skill-meta">v${escapeHtml(skill.version)} · ${escapeHtml(skill.source)}</span>
      </article>`).join("") : '<div class="empty-state"><span><b>尚未加载 Skill</b>扫描目录以加载可用能力</span></div>';
  } catch (error) {
    renderLlmRuntime({ error: true });
    root.innerHTML = '<div class="empty-state"><span>Skills 加载失败</span></div>';
    toast(error.message);
  }
}

async function loadFailures() {
  try {
    const [failuresData, status, runsData] = await Promise.all([
      api("/api/failures"),
      api("/v1/evolution/status"),
      api("/v1/evolution/runs?limit=5"),
    ]);
    $("#evolution-status").textContent = formatJson(status);
    const cases = failuresData.cases || [];
    const runs = runsData.runs || [];
    const failureHtml = cases.length
      ? cases.slice(0, 8).map((item) => `
          <div class="task-row">
            <span class="task-main"><span class="task-glyph">FC</span><span class="task-copy">
              <span class="task-name">${escapeHtml(feedbackLabels[item.category] || item.category)}</span>
              <span class="task-meta"><span>${escapeHtml(item.task_id)}</span><span>${escapeHtml((item.payload || {}).note || "无说明")}</span></span>
            </span></span>
            <span class="status ${item.resolved ? "state-success" : "state-pending"}">${item.resolved ? "已解决" : "待处理"}</span>
          </div>`).join("")
      : '<div class="empty-state"><span><b>暂无失败反馈</b>系统当前没有未处理案例</span></div>';
    const historyHtml = runs.length
      ? `<p class="list-section-label">最近评测</p>${runs.map((run) => `
          <div class="task-row">
            <span class="task-main"><span class="task-glyph">V${escapeHtml(run.candidate_version)}</span><span class="task-copy">
              <span class="task-name">${escapeHtml(run.decision)}</span>
              <span class="task-meta">${Number(run.candidate_score).toFixed(3)} vs ${Number(run.baseline_score).toFixed(3)}</span>
            </span></span>
          </div>`).join("")}`
      : "";
    $("#failure-list").innerHTML = failureHtml + historyHtml;
  } catch (error) {
    $("#evolution-status").textContent = "暂时无法读取评测状态。";
    $("#failure-list").innerHTML = '<div class="empty-state"><span>反馈加载失败</span></div>';
    toast(error.message);
  }
}

function annotationCaseRows(cases) {
  if (!cases.length) {
    return '<div class="empty-state"><span><b>当前筛选下没有案例</b>调整筛选条件，或导入新的公开 PR。</span></div>';
  }
  return cases.map((item) => {
    const status = String(item.status || "ready");
    const active = item.id === selectedAnnotationCase ? " is-selected" : "";
    return `<button class="annotation-case-row${active}" type="button" data-annotation-case="${escapeAttr(item.id)}">
      <span class="annotation-case-main">
        <span class="annotation-case-title">${escapeHtml(item.repository)} <b>#${escapeHtml(item.pull_request)}</b></span>
        <span class="annotation-case-meta"><span>${escapeHtml(item.split)}</span><span>${item.review_progress || 0}/${item.required_reviewers || 2} 份标注</span><span>${escapeHtml(formatTime(item.created_at))}</span></span>
      </span>
      <span class="status annotation-state-${escapeHtml(status)}">${escapeHtml(annotationStatusLabels[status] || status)}</span>
    </button>`;
  }).join("");
}

function bindAnnotationCases() {
  $$('[data-annotation-case]', $("#annotation-cases")).forEach((row) => {
    row.addEventListener("click", () => openAnnotationCase(row.dataset.annotationCase));
  });
}

async function loadAnnotationCases() {
  const root = $("#annotation-cases");
  root.innerHTML = '<div class="list-loading"></div><div class="list-loading"></div>';
  const status = $("#annotation-status-filter").value;
  const split = $("#annotation-split-filter").value;
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (split) query.set("split", split);
  try {
    const data = await api(`/v1/annotations/cases?${query}`);
    const cases = data.cases || [];
    root.innerHTML = annotationCaseRows(cases);
    $("#annotation-count").textContent = `${cases.length} 个案例`;
    bindAnnotationCases();
  } catch (error) {
    root.innerHTML = `<div class="empty-state error-state"><span><b>标注队列加载失败</b>${escapeHtml(error.message)}</span></div>`;
    $("#annotation-count").textContent = "读取失败";
  }
}

function findingRow(scope, finding = {}) {
  return `<div class="finding-row">
    <div class="finding-grid">
      <label>文件路径<input data-field="path" value="${escapeAttr(finding.path || "")}" placeholder="app/api.py" required></label>
      <label>起始行<input data-field="start_line" type="number" min="1" value="${escapeAttr(finding.start_line || "")}" required></label>
      <label>结束行<input data-field="end_line" type="number" min="1" value="${escapeAttr(finding.end_line || "")}" required></label>
      <label>CWE<input data-field="cwe" value="${escapeAttr(finding.cwe || "")}" placeholder="CWE-79" required></label>
      <label>严重级别<select data-field="severity"><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></label>
    </div>
    <label>依据说明<textarea data-field="explanation" rows="2" placeholder="说明风险如何由新增代码引入。">${escapeHtml(finding.explanation || "")}</textarea></label>
    <label>Finding 证据 URL <span class="optional">可选</span><input data-field="evidence_url" type="url" value="${escapeAttr(finding.evidence_url || "")}" placeholder="https://github.com/owner/repository/pull/42/files"></label>
    <button class="link-button danger-link" type="button" data-remove-finding="${scope}">移除此项</button>
  </div>`;
}

function bindFindingRows(scope) {
  $$(`[data-remove-finding="${scope}"]`).forEach((button) => {
    button.addEventListener("click", () => button.closest(".finding-row").remove());
  });
}

function addFinding(scope, finding = {}) {
  const list = $(`[data-finding-list="${scope}"]`);
  list.insertAdjacentHTML("beforeend", findingRow(scope, finding));
  const row = list.lastElementChild;
  if (finding.severity) $('[data-field="severity"]', row).value = finding.severity;
  bindFindingRows(scope);
  $('[data-field="path"]', row).focus();
}

function resetFindingEditor(scope, findings = []) {
  const list = $(`[data-finding-list="${scope}"]`);
  list.innerHTML = "";
  (findings.length ? findings : [{}]).forEach((finding) => addFinding(scope, finding));
}

function setFindingEditorVisibility(form) {
  const clean = $('[name="verdict"]', form).value === "clean";
  $(".finding-editor", form).classList.toggle("hidden", clean);
}

function collectFindings(form) {
  if ($('[name="verdict"]', form).value === "clean") return [];
  return $$(".finding-row", form).map((row) => ({
    path: String($('[data-field="path"]', row).value).trim(),
    start_line: Number($('[data-field="start_line"]', row).value),
    end_line: Number($('[data-field="end_line"]', row).value),
    cwe: String($('[data-field="cwe"]', row).value).trim(),
    severity: $('[data-field="severity"]', row).value,
    explanation: String($('[data-field="explanation"]', row).value).trim(),
    evidence_url: String($('[data-field="evidence_url"]', row).value).trim(),
  }));
}

function renderAnnotationSubmissions(data) {
  const submissions = data.submissions || [];
  const root = $("#annotation-submissions");
  if (!submissions.length) {
    root.innerHTML = '<div class="empty-state"><span>双人盲审完成后显示对比结果。</span></div>';
    return;
  }
  root.innerHTML = submissions.map((item, index) => `<article class="submission-result">
    <div class="submission-result-head"><b>评审 ${index + 1}: ${escapeHtml(item.annotator)}</b><span>${item.verdict === "risk" ? "发现风险" : "未发现风险"}</span></div>
    <p>${escapeHtml(item.methodology)}</p>
    <pre>${escapeHtml(formatJson(item.findings || []))}</pre>
  </article>`).join("");
}

function renderAnnotationCase(data) {
  selectedAnnotationCase = data.id;
  $("#annotation-detail-empty").classList.add("hidden");
  $("#annotation-detail").classList.remove("hidden");
  $("#annotation-case-title").textContent = `${data.repository} #${data.pull_request}`;
  $("#annotation-case-meta").textContent = `${data.split.toUpperCase()} / Diff SHA-256 ${data.diff_sha256}`;
  const status = $("#annotation-case-status");
  status.className = `status annotation-state-${data.status}`;
  status.textContent = annotationStatusLabels[data.status] || data.status;
  const source = data.source || {};
  $("#annotation-proof").innerHTML = `<span><b>来源</b><a href="${escapeAttr(source.public_url || "#")}" target="_blank" rel="noreferrer">GitHub PR</a></span>
    <span><b>Base</b><code>${escapeHtml(String(source.base_sha || "").slice(0, 12))}</code></span>
    <span><b>Head</b><code>${escapeHtml(String(source.head_sha || "").slice(0, 12))}</code></span>
    <span><b>License</b><code>${escapeHtml((source.license || {}).spdx_id || "未知")}</code></span>`;
  $("#annotation-diff").textContent = data.diff || "";

  const submissionForm = $("#annotation-submission-form");
  const accepting = ["ready", "in_review"].includes(data.status) && !data.my_submission;
  submissionForm.classList.toggle("hidden", !accepting);
  if (accepting) {
    submissionForm.reset();
    resetFindingEditor("submission");
    setFindingEditorVisibility(submissionForm);
  }

  const complete = ["needs_adjudication", "approved", "exported"].includes(data.status);
  $("#annotation-resolution").classList.toggle("hidden", !complete);
  if (complete) {
    const resolution = $("#annotation-resolution-status");
    resolution.textContent = data.status === "needs_adjudication" ? "标签冲突" : "标签已确定";
    resolution.className = `status annotation-state-${data.status}`;
    renderAnnotationSubmissions(data);
  }
  const canAdjudicate = data.status === "needs_adjudication" && currentRole === "admin";
  $("#annotation-adjudication-form").classList.toggle("hidden", !canAdjudicate);
  if (canAdjudicate) {
    $("#annotation-adjudication-form").reset();
    resetFindingEditor("adjudication");
    setFindingEditorVisibility($("#annotation-adjudication-form"));
  }
}

async function openAnnotationCase(caseId) {
  selectedAnnotationCase = caseId;
  $("#annotation-detail-empty").classList.add("hidden");
  $("#annotation-detail").classList.remove("hidden");
  $("#annotation-case-title").textContent = "正在加载案例";
  $("#annotation-case-meta").textContent = "正在验证访问范围";
  $("#annotation-diff").textContent = "正在读取 Diff...";
  try {
    const data = await api(`/v1/annotations/cases/${encodeURIComponent(caseId)}`);
    renderAnnotationCase(data);
    await loadAnnotationCases();
  } catch (error) {
    $("#annotation-case-title").textContent = "案例加载失败";
    $("#annotation-case-meta").textContent = error.message;
    $("#annotation-diff").textContent = "请确认账号具有标注权限。";
  }
}

$("#toggle-annotation-import").addEventListener("click", () => {
  const form = $("#annotation-import-form");
  const visible = form.classList.toggle("hidden") === false;
  $("#toggle-annotation-import").textContent = visible ? "收起导入表单" : "导入公开 PR";
  if (visible) $('input[name="repository"]', form).focus();
});

$("#annotation-import-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  const values = new FormData(form);
  setButtonBusy(button, true, "正在验证...");
  try {
    const data = await api("/v1/annotations/cases/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repository: String(values.get("repository") || "").trim(),
        pull_request: Number(values.get("pull_request")),
        license_spdx: String(values.get("license_spdx") || "").trim(),
        license_evidence_url: String(values.get("license_evidence_url") || "").trim(),
      }),
    });
    form.reset();
    form.classList.add("hidden");
    $("#toggle-annotation-import").textContent = "导入公开 PR";
    toast(`已导入 ${data.repository} #${data.pull_request}`);
    await loadAnnotationCases();
    await openAnnotationCase(data.id);
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$$('[data-add-finding]').forEach((button) => {
  button.addEventListener("click", () => addFinding(button.dataset.addFinding));
});

$$('.annotation-verdict').forEach((select) => {
  select.addEventListener("change", () => setFindingEditorVisibility(select.form));
});

$("#annotation-submission-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedAnnotationCase) return;
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  const values = new FormData(form);
  setButtonBusy(button, true, "正在提交...");
  try {
    const data = await api(`/v1/annotations/cases/${encodeURIComponent(selectedAnnotationCase)}/submissions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        verdict: values.get("verdict"),
        findings: collectFindings(form),
        methodology: String(values.get("methodology") || "").trim(),
        evidence_urls: String(values.get("evidence_urls") || "").split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
      }),
    });
    toast(data.case_status === "approved" ? "双人标签一致，案例已通过" : data.case_status === "needs_adjudication" ? "标签存在冲突，案例已转入仲裁" : "独立标注已提交");
    await openAnnotationCase(selectedAnnotationCase);
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#annotation-adjudication-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedAnnotationCase) return;
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  const values = new FormData(form);
  setButtonBusy(button, true, "正在仲裁...");
  try {
    await api(`/v1/annotations/cases/${encodeURIComponent(selectedAnnotationCase)}/adjudications`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        verdict: values.get("verdict"),
        findings: collectFindings(form),
        rationale: String(values.get("rationale") || "").trim(),
      }),
    });
    toast("最终仲裁已提交，案例已通过");
    await openAnnotationCase(selectedAnnotationCase);
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#annotation-export-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  const values = new FormData(form);
  const output = $("#annotation-export-result");
  setButtonBusy(button, true, "正在执行门禁...");
  output.textContent = "正在校验来源、分区隔离和重复 Diff...";
  try {
    const data = await api("/v1/annotations/exports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: String(values.get("name") || "").trim(),
        version: String(values.get("version") || "").trim(),
        splits: values.getAll("splits"),
        case_ids: [],
      }),
    });
    output.innerHTML = `<b>导出完成</b><span>${escapeHtml(data.manifest.cases)} 个案例，SHA-256 ${escapeHtml(data.manifest.dataset_sha256)}</span><button class="link-button" type="button" id="download-annotation-export">下载 JSONL</button>`;
    $("#download-annotation-export").addEventListener("click", async () => {
      try {
        const headers = accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
        const response = await fetch(data.download_url, { headers });
        if (!response.ok) throw new Error("下载失败");
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `${values.get("name")}-${values.get("version")}.jsonl`;
        anchor.click();
        URL.revokeObjectURL(url);
      } catch (error) {
        toast(error.message);
      }
    });
    toast("Harness 数据集已生成");
    await loadAnnotationCases();
  } catch (error) {
    output.textContent = `导出失败：${error.message}`;
  } finally {
    setButtonBusy(button, false);
  }
});

$("#annotation-status-filter").addEventListener("change", loadAnnotationCases);
$("#annotation-split-filter").addEventListener("change", loadAnnotationCases);
$("#refresh-annotations").addEventListener("click", loadAnnotationCases);

$("#review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  const values = new FormData(form);
  const body = { repository: values.get("repository"), diff: values.get("diff") };
  if (values.get("pull_request")) body.pull_request = Number(values.get("pull_request"));
  const asyncQuery = values.get("async") ? "?async=true" : "";
  const output = $("#review-result");
  output.classList.remove("empty");
  output.textContent = "正在提交审查任务…";
  setButtonBusy(button, true, "正在提交…");
  try {
    const data = await api(`/v1/reviews${asyncQuery}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    output.textContent = formatJson(data);
    toast("审查任务已成功提交");
    loadDashboard();
  } catch (error) {
    output.textContent = error.message;
  } finally {
    setButtonBusy(button, false);
  }
});

$("#create-fix").addEventListener("click", async () => {
  if (!selectedTask) return;
  const button = $("#create-fix");
  setButtonBusy(button, true, "正在创建…");
  try {
    const data = await api(`/v1/tasks/${encodeURIComponent(selectedTask)}/fix`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    $("#task-report").textContent = formatJson(data);
    toast("修复分支已创建");
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#feedback-category").addEventListener("change", (event) => {
  const missed = event.target.value === "missed_issue";
  $("#feedback-missed-fields").classList.toggle("hidden", !missed);
  $("#feedback-hint").textContent = missed
    ? "补充规则和位置可让候选评测学习更精确的检查点。"
    : "提交后可在本任务和演进实验室查看状态。";
});

$("#feedback-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedTask || !selectedTaskData?.report) return;
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  const values = new FormData(form);
  const category = String(values.get("category"));
  const selectedIndex = values.get("finding_index");
  const findings = selectedTaskData.report.findings || [];
  const finding = selectedIndex === "" ? {} : { ...(findings[Number(selectedIndex)] || {}) };
  if (category === "missed_issue") {
    const ruleId = String(values.get("rule_id") || "").trim();
    const path = String(values.get("path") || "").trim();
    const line = Number(values.get("line"));
    if (ruleId) finding.rule_id = ruleId;
    if (path) finding.path = path;
    if (Number.isInteger(line) && line > 0) finding.line = line;
  }
  const output = $("#feedback-result");
  output.textContent = "正在保存反馈…";
  setButtonBusy(button, true, "正在提交…");
  try {
    const data = await api(`/v1/tasks/${encodeURIComponent(selectedTask)}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        category,
        finding: Object.keys(finding).length ? finding : null,
        note: String(values.get("note") || "").trim(),
      }),
    });
    output.textContent = `${feedbackLabels[data.category] || data.category}已记录；可在演进实验室等待候选评测。`;
    form.reset();
    $("#feedback-missed-fields").classList.add("hidden");
    $("#feedback-hint").textContent = "提交后可在本任务和演进实验室查看状态。";
    await Promise.all([loadTaskFeedback(selectedTask), loadDashboard()]);
    toast("反馈已记录");
  } catch (error) {
    output.textContent = `提交失败：${error.message}`;
  } finally {
    setButtonBusy(button, false);
  }
});

$("#reload-skills").addEventListener("click", async () => {
  const button = $("#reload-skills");
  setButtonBusy(button, true, "正在扫描…");
  try {
    await api("/v1/skills/reload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    await loadSkills();
    toast("Skills 已重新加载");
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#evolution-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  const values = new FormData(form);
  setButtonBusy(button, true, "正在评测…");
  try {
    const data = await api("/v1/evolution/propose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skill_name: values.get("skill_name"), prompt: values.get("prompt") }),
    });
    $("#evolution-result").classList.remove("empty");
    $("#evolution-result").textContent = formatJson(data);
    toast("新旧版本回放评测已完成");
    loadFailures();
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#auto-evolve").addEventListener("click", async () => {
  const button = $("#auto-evolve");
  setButtonBusy(button, true, "正在生成…");
  try {
    const data = await api("/v1/evolution/auto", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skill_name: "llm-review" }),
    });
    $("#evolution-result").classList.remove("empty");
    $("#evolution-result").textContent = formatJson(data);
    toast("反馈候选评测已完成");
    loadFailures();
  } catch (error) {
    toast(error.message);
  } finally {
    setButtonBusy(button, false);
  }
});

$("#refresh").addEventListener("click", async () => {
  const view = location.hash.slice(1) || "overview";
  if (view === "overview") await loadDashboard();
  else if (view === "tasks") await loadTasks();
  else if (view === "annotations") await loadAnnotationCases();
  else if (view === "skills") await loadSkills();
  else if (view === "evolution") await loadFailures();
  else await loadDashboard();
  toast("数据已刷新");
});

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $('button[type="submit"]', form);
  const values = new FormData(form);
  setButtonBusy(button, true, "正在登录…");
  try {
    const data = await api("/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: values.get("username"),
        password: values.get("password"),
        tenant_id: values.get("tenant_id"),
      }),
    });
    accessToken = data.access_token;
    currentRole = data.role;
    localStorage.setItem("codeevo_token", accessToken);
    localStorage.setItem("codeevo_role", currentRole);
    applyRoleVisibility();
    $("#login-overlay").classList.add("hidden");
    $("#logout").classList.remove("hidden");
    $("#login-error").textContent = "";
    await loadDashboard();
  } catch (error) {
    $("#login-error").textContent = error.message;
  } finally {
    setButtonBusy(button, false);
  }
});

$("#logout").addEventListener("click", () => {
  accessToken = "";
  currentRole = "";
  localStorage.removeItem("codeevo_token");
  localStorage.removeItem("codeevo_role");
  applyRoleVisibility();
  $("#login-overlay").classList.remove("hidden");
  $("#logout").classList.add("hidden");
});

const diffInput = $('textarea[name="diff"]', $("#review-form"));
const diffStats = $("#diff-stats");
function updateDiffStats() {
  const value = diffInput.value;
  const lines = value ? value.split(/\r?\n/).length : 0;
  diffStats.textContent = `${lines} 行，${value.length} 字符`;
}
diffInput.addEventListener("input", updateDiffStats);
updateDiffStats();

if (accessToken) $("#logout").classList.remove("hidden");
applyRoleVisibility();
resetFindingEditor("submission");
resetFindingEditor("adjudication");
show(location.hash.slice(1) || "overview", false);
loadDashboard();
