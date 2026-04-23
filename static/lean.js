const addButton = document.querySelector("[data-add-line]");
const tbody = document.querySelector("[data-lines]");

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
    tbody.appendChild(row);
  });
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
  });
  return true;
}

document.querySelectorAll("[data-bulk-apply]").forEach((button) => {
  button.addEventListener("click", () => {
    applyBulkField(button.dataset.bulkApply);
  });
});

const applyAllButton = document.querySelector("[data-bulk-apply-all]");
if (applyAllButton) {
  applyAllButton.addEventListener("click", () => {
    ["line_tax_category", "line_tax_code", "line_tax_rate"].forEach(applyBulkField);
  });
}

document.querySelectorAll("[data-edit-field]").forEach((button) => {
  button.addEventListener("click", () => {
    const wrapper = button.closest(".editable-field");
    const input = wrapper ? wrapper.querySelector("[data-lockable]") : null;
    if (!input) {
      return;
    }
    input.removeAttribute("readonly");
    wrapper.classList.add("is-editing");
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
  });
});
