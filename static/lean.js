const addButton = document.querySelector("[data-add-line]");
const tbody = document.querySelector("[data-lines]");

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function updateSelectedFileStatus(input) {
  const toolbar = input.closest(".composer-toolbar") || input.closest("form");
  const status = toolbar ? toolbar.querySelector("[data-file-status]") : null;
  if (!status) {
    return;
  }
  const files = Array.from(input.files || []);
  status.classList.toggle("has-files", files.length > 0);
  if (!files.length) {
    status.textContent = "尚未选择材料。";
    return;
  }
  const names = files.slice(0, 4).map((file) => file.name);
  const extra = files.length > names.length ? `，另有 ${files.length - names.length} 个` : "";
  status.innerHTML = `已选择 ${files.length} 个材料，点击“生成开票草稿”后上传：<span class="file-chip-list">${names
    .map((name) => `<span class="file-chip" title="${escapeHtml(name)}">${escapeHtml(name)}</span>`)
    .join("")}</span>${extra}`;
}

document.querySelectorAll("[data-file-input]").forEach((input) => {
  input.addEventListener("change", () => updateSelectedFileStatus(input));
});

const createDraftForm = document.querySelector("[data-create-draft-form]");
if (createDraftForm) {
  createDraftForm.addEventListener("submit", () => {
    const button = createDraftForm.querySelector("[data-submit-button]");
    const status = createDraftForm.querySelector("[data-submit-status]");
    const stageNode = createDraftForm.querySelector("[data-submit-stage]");
    const detailNode = createDraftForm.querySelector("[data-submit-detail]");
    const elapsedNode = createDraftForm.querySelector("[data-submit-elapsed]");
    const fileInput = createDraftForm.querySelector("[data-file-input]");
    const batchMode = createDraftForm.querySelector('input[name="batch_mode"]');
    const rawText = createDraftForm.querySelector('textarea[name="raw_text"]')?.value || "";
    const files = Array.from(fileInput?.files || []);
    const fileNames = files.map((file) => file.name || "");
    const hasExcel = fileNames.some((name) => /\.(xlsx?|csv|tsv)$/i.test(name));
    const hasPdf = fileNames.some((name) => /\.pdf$/i.test(name));
    const hasWord = fileNames.some((name) => /\.(docx?|md|txt)$/i.test(name));
    const imageFiles = files.filter((file) => /\.(png|jpe?g|webp|bmp|gif)$/i.test(file.name || ""));
    const hasArchive = fileNames.some((name) => /\.(zip|7z)$/i.test(name));
    const willUseVision = imageFiles.length > 0 && (!batchMode?.checked || imageFiles.length <= 5);
    const startedAt = Date.now();
    const stages = buildSubmitStages({ hasExcel, hasPdf, hasWord, imageCount: imageFiles.length, hasArchive, rawText, batchMode: Boolean(batchMode?.checked), willUseVision });

    if (button) {
      button.disabled = true;
      button.textContent = "正在生成草稿…";
    }
    if (status) {
      status.hidden = false;
      status.classList.add("is-live");
      status.classList.toggle("uses-llm", willUseVision);
    }

    const render = () => {
      const elapsed = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      const current = stages.slice().reverse().find((stage) => elapsed >= stage.at) || stages[0];
      if (stageNode) stageNode.textContent = current.title;
      if (detailNode) detailNode.textContent = current.detail;
      if (elapsedNode) elapsedNode.textContent = `${elapsed} 秒`;
      if (button) button.textContent = current.button || "正在生成草稿…";
    };
    render();
    window.setInterval(render, 1000);
  });
}

function buildSubmitStages({ hasExcel, hasPdf, hasWord, imageCount, hasArchive, rawText, batchMode, willUseVision }) {
  const stages = [
    { at: 0, title: "接收客户材料", detail: "正在保存上传文件和你粘贴的补充说明。", button: "接收材料中…" },
    { at: 1, title: "本地规则快速识别", detail: "先用本地规则找销售主体、购买方、金额和票种。", button: "本地识别中…" },
  ];
  if (hasArchive) stages.push({ at: 2, title: "展开压缩包线索", detail: "正在识别压缩包内的 Excel / PDF / Word 材料。", button: "读取压缩包…" });
  if (hasExcel) stages.push({ at: 3, title: batchMode ? "批量识别 Excel 明细" : "识别 Excel 明细", detail: "正在定位项目、规格、数量、单价、金额和税率列。", button: "解析 Excel…" });
  if (hasPdf || hasWord) stages.push({ at: hasExcel ? 5 : 3, title: "读取 PDF / Word", detail: "正在提取开票信息、样票字段和购买方资料。", button: "读取文件…" });
  if (rawText.trim()) stages.push({ at: 4, title: "合并补充说明", detail: "正在判断本次金额、税点、备注是否覆盖样票旧信息。", button: "合并文字…" });
  if (imageCount > 0) {
    stages.push({ at: 5, title: "图片 OCR 预处理", detail: `检测到 ${imageCount} 张图片，先识别关键截图，剩余保留附件。`, button: "识别图片…" });
  }
  if (willUseVision) {
    stages.push({ at: 8, title: "LLM 识别图片中", detail: "正在让视觉模型读取截图里的买方、金额、订单号和备注。", button: "LLM 识别中…" });
  }
  stages.push(
    { at: willUseVision ? 14 : 7, title: "匹配客户历史档案", detail: "正在按销售主体查历史购买方、常用项目和税率候选。", button: "匹配档案…" },
    { at: willUseVision ? 18 : 10, title: "生成可复核草稿", detail: "正在把识别结果放入草稿页，并标记需要你重点核对的位置。", button: "生成草稿…" },
    { at: willUseVision ? 25 : 16, title: "仍在处理，请稍等", detail: "材料较多时会多花几秒；系统会尽量先给出可复核草稿。", button: "即将完成…" }
  );
  return stages.sort((a, b) => a.at - b.at);
}

function setActionMode(mode) {
  const panel = document.querySelector("[data-action-panel]");
  if (!panel) {
    return;
  }
  const invoiceButton = panel.querySelector("[data-invoice-action]");
  const saveButton = panel.querySelector("[data-save-action]");
  if (!invoiceButton || !saveButton) {
    return;
  }
  const saveIsPrimary = mode === "save";
  saveButton.classList.toggle("primary", saveIsPrimary);
  saveButton.classList.toggle("secondary", !saveIsPrimary);
  invoiceButton.classList.toggle("primary", !saveIsPrimary);
  invoiceButton.classList.toggle("secondary", saveIsPrimary);
  panel.dataset.currentAction = mode;
}

function markDraftNeedsRebuild() {
  setActionMode("save");
}

const draftLiveStatus = document.querySelector("[data-draft-live-status]");
if (draftLiveStatus) {
  const titleNode = draftLiveStatus.querySelector("[data-draft-live-title]");
  const detailNode = draftLiveStatus.querySelector("[data-draft-live-detail]");
  const elapsedNode = draftLiveStatus.querySelector("[data-draft-live-elapsed]");
  const hasActiveWork = draftLiveStatus.dataset.hasActiveWork === "1";
  if (!hasActiveWork) {
    if (elapsedNode) elapsedNode.textContent = "已就绪";
    if (titleNode) titleNode.textContent = titleNode.textContent || "草稿已就绪，请按高亮提示复核";
  } else {
    const startedAt = Date.now();
    const activeMessages = [
      "可以先核对已填出的购买方、金额和明细。",
      "如果有图片或样票，请重点看黄色高亮字段。",
      "未命中赋码的行建议先用“一键智能赋码”。",
      "后台识别失败也不会影响你手工复核和保存。",
    ];
    let messageIndex = 0;
    const tick = () => {
      const elapsed = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      if (elapsedNode) elapsedNode.textContent = `复核已打开 ${elapsed} 秒`;
      if (detailNode && elapsed > 0 && elapsed % 4 === 0) {
        messageIndex = (messageIndex + 1) % activeMessages.length;
        detailNode.textContent = activeMessages[messageIndex];
      }
    };
    tick();
    window.setInterval(tick, 1000);
  }
}

const draftForm = document.querySelector("[data-draft-form]");
if (draftForm) {
  setActionMode(draftForm.dataset.initialAction || "invoice");
  draftForm.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement)) {
      return;
    }
    if (target.name === "failure_file" || target.name === "cdp_endpoint") {
      return;
    }
    markDraftNeedsRebuild();
  });
  draftForm.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement)) {
      return;
    }
    if (target.name === "failure_file" || target.name === "cdp_endpoint") {
      return;
    }
    markDraftNeedsRebuild();
  });
}

if (addButton && tbody) {
  addButton.addEventListener("click", () => {
    const template = tbody.querySelector("tr");
    const row = template ? template.cloneNode(true) : document.createElement("tr");
    const lineBoard = tbody.closest("[data-edit-scope='line-board']");
    const isEditing = lineBoard ? lineBoard.classList.contains("is-editing") : false;
    row.querySelectorAll("input").forEach((input) => {
      input.value = input.name === "line_tax_rate" ? "3%" : "";
      if (input.dataset.lockable !== undefined && !isEditing) {
        input.setAttribute("readonly", "readonly");
      } else {
        input.removeAttribute("readonly");
      }
    });
    row.querySelectorAll("[data-coding-note]").forEach((note) => {
      note.textContent = "待人工复核";
      note.classList.remove("pending-change");
    });
    tbody.appendChild(row);
    markDraftNeedsRebuild();
  });
}

function markCodingPending(input) {
  const row = input.closest("tr");
  const note = row ? row.querySelector("[data-coding-note]") : null;
  if (!note) {
    return;
  }
  note.textContent = "保存后记录人工修正";
  note.classList.add("pending-change");
  markDraftNeedsRebuild();
}

function applyBulkField(fieldName) {
  if (!tbody) {
    return false;
  }
  const source = document.querySelector(`[data-bulk-source="${fieldName}"]`);
  const value = source ? source.value.trim() : "";
  if (!value) {
    return false;
  }
  tbody.querySelectorAll(`input[name="${fieldName}"]`).forEach((input) => {
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    markCodingPending(input);
  });
  return true;
}

document.querySelectorAll("[data-bulk-apply]").forEach((button) => {
  button.addEventListener("click", () => {
    applyBulkField(button.dataset.bulkApply);
    markDraftNeedsRebuild();
  });
});

const applyAllButton = document.querySelector("[data-bulk-apply-all]");
if (applyAllButton) {
  applyAllButton.addEventListener("click", () => {
    ["line_tax_category", "line_tax_code", "line_tax_rate"].forEach(applyBulkField);
    markDraftNeedsRebuild();
  });
}

const batchRecommendationButton = document.querySelector("[data-apply-batch-recommendation]");
if (batchRecommendationButton) {
  batchRecommendationButton.addEventListener("click", () => {
    const fieldMap = {};
    document.querySelectorAll("[data-batch-recommendation-field]").forEach((input) => {
      fieldMap[input.dataset.batchRecommendationField] = input.value.trim();
    });
    Object.entries(fieldMap).forEach(([name, value]) => {
      if (!value) {
        return;
      }
      document.querySelectorAll(`input[name="${name}"], input[name$="_${name}"]`).forEach((input) => {
        input.value = value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
    });
    const appliedInput = document.querySelector("[data-batch-recommendation-applied]");
    if (appliedInput) {
      appliedInput.value = "1";
    }
    const status = document.querySelector("[data-batch-recommendation-status]");
    if (status) {
      status.textContent = "已导入到 Sheet 2，请保存本批修改并重新校验。";
    }
  });
}

document.querySelectorAll("[data-batch-smart-submit]").forEach((button) => {
  button.addEventListener("click", () => {
    const form = button.closest("form");
    const live = document.querySelector("[data-batch-smart-live]");
    const title = live?.querySelector("[data-batch-smart-title]");
    const detail = live?.querySelector("[data-batch-smart-detail]");
    const elapsedNode = live?.querySelector("[data-batch-smart-elapsed]");
    const startedAt = Date.now();
    if (live) {
      live.hidden = false;
      live.classList.add("is-live");
    }
    if (title) title.textContent = button.value === "all" ? "正在智能复核本批全部明细…" : "正在智能赋码本批未命中明细…";
    const render = () => {
      const elapsed = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      if (elapsedNode) elapsedNode.textContent = `${elapsed} 秒`;
      if (detail) {
        if (elapsed < 4) detail.textContent = "正在保存本页修改，并收集本批所有子草稿明细。";
        else if (elapsed < 10) detail.textContent = "正在按工程材料规则、官方候选和客户规则包处理可确定明细。";
        else detail.textContent = "材料较多或需要 LLM 候选时会多花几秒；完成后会回到本批复核页。";
      }
      button.textContent = `${button.value === "all" ? "智能复核中" : "智能赋码中"}…${elapsed} 秒`;
    };
    render();
    window.setInterval(render, 1000);
    form?.querySelectorAll("button").forEach((candidate) => {
      if (candidate !== button) candidate.disabled = true;
    });
  });
});

const taxonomyPicker = document.querySelector("[data-taxonomy-picker]");
if (taxonomyPicker) {
  const queryInput = taxonomyPicker.querySelector("[data-taxonomy-query]");
  const resultsBox = taxonomyPicker.querySelector("[data-taxonomy-results]");
  const categoryInput = document.querySelector('[data-bulk-source="line_tax_category"]');
  const codeInput = document.querySelector('[data-bulk-source="line_tax_code"]');
  let taxonomyTimer = null;
  let codeLookupTimer = null;

  function hideTaxonomyResults() {
    if (resultsBox) {
      resultsBox.hidden = true;
      resultsBox.innerHTML = "";
    }
  }

  function renderTaxonomyMessage(message) {
    if (!resultsBox) {
      return;
    }
    resultsBox.innerHTML = `<div class="taxonomy-option is-message"><small>${escapeHtml(message)}</small></div>`;
    resultsBox.hidden = false;
  }

  function applyTaxonomyItem(item) {
    if (categoryInput) {
      categoryInput.value = item.category_short_name || item.official_name || "";
      categoryInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (codeInput) {
      codeInput.value = item.official_code || "";
      codeInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (queryInput) {
      queryInput.value = item.official_name || item.category_short_name || "";
    }
  }

  function renderTaxonomyResults(items) {
    if (!resultsBox) {
      return;
    }
    resultsBox.innerHTML = "";
    if (!items.length) {
      renderTaxonomyMessage("没有匹配结果，换个关键词试试；如果知道编码，可直接填入下方税收编码框。");
      return;
    }
    items.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "taxonomy-option";
      button.innerHTML = `
        <strong>细分品类：${escapeHtml(item.official_name || item.category_short_name)}</strong>
        <small>大类：${escapeHtml(item.category_short_name || "未识别")}｜税收编码：${escapeHtml(item.official_code || "")}${item.is_summary ? "｜<em>汇总类，建议继续选更具体项</em>" : ""}</small>
      `;
      button.addEventListener("click", () => {
        applyTaxonomyItem(item);
        hideTaxonomyResults();
      });
      resultsBox.appendChild(button);
    });
    resultsBox.hidden = false;
  }

  async function fetchTaxonomy(query) {
    const response = await fetch(`/api/taxonomy/search?q=${encodeURIComponent(query)}`);
    if (!response.ok) {
      throw new Error("taxonomy search unavailable");
    }
    const payload = await response.json();
    return payload.results || [];
  }

  async function searchTaxonomy(query) {
    const keyword = query.trim();
    if (keyword.length < 2) {
      hideTaxonomyResults();
      return;
    }
    renderTaxonomyMessage("正在查找官方税收编码……");
    try {
      renderTaxonomyResults(await fetchTaxonomy(keyword));
    } catch (error) {
      renderTaxonomyMessage("搜索服务未启用，请重启工作台后再试。");
    }
  }

  async function completeCategoryFromCode(value) {
    const code = value.trim();
    if (!/^\d{12,20}$/.test(code)) {
      return;
    }
    try {
      const items = await fetchTaxonomy(code);
      const exact = items.find((item) => item.official_code === code) || items[0];
      if (exact && categoryInput) {
        categoryInput.value = exact.category_short_name || exact.official_name || "";
        categoryInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
    } catch (error) {
      // 反向补全失败不阻断手工填写。
    }
  }

  if (queryInput) {
    queryInput.addEventListener("input", () => {
      clearTimeout(taxonomyTimer);
      taxonomyTimer = setTimeout(() => searchTaxonomy(queryInput.value), 220);
    });
    queryInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        clearTimeout(taxonomyTimer);
        searchTaxonomy(queryInput.value);
      }
    });
  }
  if (codeInput) {
    codeInput.addEventListener("input", () => {
      clearTimeout(codeLookupTimer);
      codeLookupTimer = setTimeout(() => completeCategoryFromCode(codeInput.value), 260);
    });
    codeInput.addEventListener("blur", () => completeCategoryFromCode(codeInput.value));
  }
}

document.querySelectorAll("[data-apply-line-repair]").forEach((button) => {
  button.addEventListener("click", () => {
    const row = button.closest("tr");
    const fieldName = button.dataset.repairField;
    const value = button.dataset.repairValue || "";
    const input = row && fieldName ? row.querySelector(`input[name="${fieldName}"]`) : null;
    if (!input || !value) {
      return;
    }
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    if (input.dataset.lockable !== undefined) {
      input.removeAttribute("readonly");
    }
    markCodingPending(input);
    markDraftNeedsRebuild();
    button.textContent = `已应用：${value}`;
  });
});

document.querySelectorAll("[data-edit-field]").forEach((button) => {
  button.addEventListener("click", () => {
    const wrapper = button.closest(".editable-field");
    const input = wrapper ? wrapper.querySelector("[data-lockable]") : null;
    if (!input) {
      return;
    }
    input.removeAttribute("readonly");
    wrapper.classList.add("is-editing");
    markDraftNeedsRebuild();
    input.focus();
    if (input.select) {
      input.select();
    }
  });
});

document.querySelectorAll("[data-edit-section]").forEach((button) => {
  button.addEventListener("click", () => {
    const target = button.dataset.editSection;
    const scope = document.querySelector(`[data-edit-scope="${target}"]`);
    if (!scope) {
      return;
    }
    const enable = !scope.classList.contains("is-editing");
    scope.classList.toggle("is-editing", enable);
    scope.querySelectorAll("[data-lockable]").forEach((input) => {
      if (enable) {
        input.removeAttribute("readonly");
      } else {
        input.setAttribute("readonly", "readonly");
      }
    });
    if (enable) {
      markDraftNeedsRebuild();
      const first = scope.querySelector("[data-lockable]");
      if (first) {
        first.focus();
        if (first.select) {
          first.select();
        }
      }
    }
    if (button.textContent.trim() === "编辑明细") {
      button.textContent = enable ? "完成编辑" : "编辑明细";
    }
  });
});

document.querySelectorAll("[data-toggle-choice]").forEach((button) => {
  button.addEventListener("click", () => {
    const wrapper = button.closest(".field-choice");
    if (!wrapper) {
      return;
    }
    wrapper.classList.toggle("is-editing");
    markDraftNeedsRebuild();
    const select = wrapper.querySelector("select");
    if (select) {
      select.focus();
    }
  });
});

document.querySelectorAll(".field-choice select").forEach((select) => {
  select.addEventListener("change", () => {
    const wrapper = select.closest(".field-choice");
    const display = wrapper ? wrapper.querySelector("[data-choice-display]") : null;
    if (display) {
      display.textContent = select.options[select.selectedIndex]?.text || select.value;
    }
    markDraftNeedsRebuild();
  });
});

if (tbody) {
  tbody.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) {
      return;
    }
    if (["line_tax_category", "line_tax_code", "line_tax_rate"].includes(target.name)) {
      markCodingPending(target);
    }
  });
}

const sellerProfileBox = document.querySelector("[data-seller-profile-status]");
const sellerCompanyInput = document.querySelector('input[name="company_name"]');
let sellerProfileTimer = null;

function setSellerProfileStatus(message, kind = "") {
  if (!sellerProfileBox) {
    return;
  }
  sellerProfileBox.classList.remove("ok", "alert", "notice");
  if (kind) {
    sellerProfileBox.classList.add(kind);
  }
  sellerProfileBox.innerHTML = `<p>${escapeHtml(message)}</p>`;
}

async function refreshSellerProfileStatus() {
  if (!sellerProfileBox || !sellerCompanyInput) {
    return;
  }
  const seller = sellerCompanyInput.value.trim();
  if (!seller) {
    setSellerProfileStatus("材料销售方档案：填写销售方后，系统会按此主体匹配云端常用项目；不依赖当前税局登录主体。", "notice");
    return;
  }
  try {
    const response = await fetch(`/api/profiles/seller?q=${encodeURIComponent(seller)}`);
    const data = await response.json();
    const profile = data.profile || {};
    const summary = data.summary || {};
    if (profile.matched) {
      setSellerProfileStatus(`材料销售方档案：已匹配 ${profile.seller_name || seller}，生成草稿会使用 ${profile.project_profile_count || 0} 个常用项目 / ${profile.buyer_count || 0} 个购买方。当前税局登录主体只在上传前做安全核对。`, "ok");
    } else if (summary.exists) {
      setSellerProfileStatus(`材料销售方档案：云端缓存已加载 ${summary.seller_count || 0} 个销售主体，但未匹配“${seller}”。请检查销售方全称，或先导入该主体历史档案。`, "notice");
    } else {
      setSellerProfileStatus("材料销售方档案：本机暂无云端缓存；工作台会在后台尝试拉取。", "notice");
    }
  } catch (error) {
    setSellerProfileStatus("材料销售方档案：查询失败，但不阻断生成草稿。", "notice");
  }
}

if (sellerCompanyInput && sellerProfileBox) {
  sellerProfileBox.classList.add("notice");
  sellerCompanyInput.addEventListener("input", () => {
    clearTimeout(sellerProfileTimer);
    sellerProfileTimer = setTimeout(refreshSellerProfileStatus, 250);
  });
  sellerCompanyInput.addEventListener("blur", refreshSellerProfileStatus);
  if (sellerCompanyInput.value.trim()) {
    refreshSellerProfileStatus();
  }
}

const taxConsole = document.querySelector("[data-tax-console]");
if (taxConsole) {
  const statusBox = taxConsole.querySelector("[data-tax-status]");
  const companyInput = document.querySelector('input[name="company_name"]');

  function setTaxStatus(message, kind = "") {
    if (!statusBox) {
      return;
    }
    statusBox.classList.remove("ok", "alert", "notice");
    if (kind) {
      statusBox.classList.add(kind);
    }
    statusBox.innerHTML = `<p>${escapeHtml(message)}</p>`;
  }

  function renderTaxStatus(data) {
    if (!data || data.status !== "ok") {
      setTaxStatus(`识别失败：${data && data.error ? data.error : "未连接到 CDP Edge"}`, "alert");
      return;
    }
    const subject = data.subject || "未识别到主体";
    const page = data.best_page || {};
    const profile = data.profile || {};
    if (companyInput && subject && subject !== "未识别到主体" && !companyInput.value.trim()) {
      companyInput.value = (profile.seller_name || subject.split("/")[0] || "").trim();
      companyInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
    const profileText = profile.matched
      ? `已匹配档案：${profile.seller_name || "当前主体"}，${profile.project_profile_count || 0} 个常用项目 / ${profile.buyer_count || 0} 个购买方。`
      : "云端缓存中暂未匹配到该主体档案。";
    setTaxStatus(`当前税局主体：${subject}。${profileText} 当前页面：${page.title || "无标题"}`, profile.matched ? "ok" : "notice");
  }

  async function identifyTaxSubject() {
    setTaxStatus("正在识别 CDP Edge 中的税局主体，并匹配客户档案…", "notice");
    try {
      const response = await fetch("/tax/status");
      const data = await response.json();
      renderTaxStatus(data);
    } catch (error) {
      setTaxStatus(`识别失败：${error}`, "alert");
    }
  }

  document.querySelectorAll("[data-tax-identify]").forEach((button) => {
    button.addEventListener("click", identifyTaxSubject);
  });

  document.querySelectorAll("[data-tax-open]").forEach((button) => {
    button.addEventListener("click", async () => {
      setTaxStatus("正在通过 CDP Edge 打开税局网站…", "notice");
      const body = new URLSearchParams();
      body.set("province", button.dataset.province || "liaoning");
      try {
        const response = await fetch("/tax/open", { method: "POST", body });
        const data = await response.json();
        if (data.status === "ok") {
          setTaxStatus(`已在 CDP Edge 打开税局网站：${data.title || data.url || "请在浏览器中继续登录"}。登录后点击“识别当前税局主体 / 加载档案”。`, "ok");
        } else {
          setTaxStatus(`打开失败：${data.error || "请确认 CDP Edge 已启动"}`, "alert");
        }
      } catch (error) {
        setTaxStatus(`打开失败：${error}`, "alert");
      }
    });
  });
}
