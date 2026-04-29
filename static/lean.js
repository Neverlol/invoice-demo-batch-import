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
    if (button) {
      button.disabled = true;
      button.textContent = "正在生成草稿…";
    }
    if (status) {
      status.hidden = false;
    }
  });
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
        <strong>${escapeHtml(item.official_name || item.category_short_name)}</strong>
        <small>${escapeHtml(item.category_short_name || "")}｜${escapeHtml(item.official_code || "")}${item.is_summary ? "｜<em>汇总类，建议继续选更具体项</em>" : ""}</small>
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
