// Comparison table for the Compare tab, mounted with st.components.v2.
//
// Python sends the rows as data. Pins and column widths are purely visual, so
// they stay in the browser (module memory + localStorage) and never cost a
// rerun; only the per-row actions (add to list, hide) are sent back to Python
// as trigger values.

const STORAGE_KEY = "nn-table-layout-v1";
const ACTION_WIDTH = 46;
const ACTION_WIDTH_EDITABLE = 72;
const MIN_WIDTH = 60;
const DEFAULT_WIDTH = { text: 140, product: 260, num: 124, long: 340, grade: 92, link: 160 };

// Survives re-mounts on rerun (the module is imported once per page).
let layout = loadLayout();
const scrollPos = new Map();
const expandedRows = new Map();

function loadLayout() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY));
    if (saved && typeof saved === "object") {
      return { pinned: saved.pinned || null, widths: saved.widths || {} };
    }
  } catch (e) {
    // Storage blocked or corrupt: fall back to defaults.
  }
  return { pinned: null, widths: {} };
}

function saveLayout() {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
  } catch (e) {
    // Not persisted, still works for this page view.
  }
}

const PIN_SVG =
  '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">' +
  '<path d="M15 3l6 6-2.5 1-3.5 3.5.5 4.5-2 2-4-4-5 5-1-1 5-5-4-4 2-2 4.5.5L14.5 5.5z" ' +
  'fill="currentColor"/></svg>';

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function widthOf(col) {
  return layout.widths[col.name] || DEFAULT_WIDTH[col.kind] || DEFAULT_WIDTH.text;
}

function renderCell(col, value) {
  const td = el("td", "nn-" + col.kind);
  if (value === null || value === undefined || value === "") {
    td.appendChild(el("span", "nn-muted", "—"));
    return td;
  }
  if (value === "No data") {
    td.appendChild(el("span", "nn-muted", value));
    return td;
  }
  if (col.kind === "grade") {
    if (value === "Unrated") {
      td.appendChild(el("span", "nn-muted", value));
    } else {
      td.appendChild(el("span", "nn-pill nn-grade-" + value, value));
    }
    return td;
  }
  if (col.kind === "link") {
    const a = el("a", "nn-link", "Open Food Facts ↗");
    a.href = value;
    a.target = "_blank";
    a.rel = "noopener";
    td.appendChild(a);
    return td;
  }
  const span = el("span", "nn-text", String(value));
  td.title = String(value);
  td.appendChild(span);
  return td;
}

export default function (component) {
  const { data, parentElement, setTriggerValue, key } = component;
  const columns = data.columns;
  const rows = data.rows;
  const editable = Boolean(data.editable);
  const actionWidth = editable ? ACTION_WIDTH_EDITABLE : ACTION_WIDTH;

  const knownNames = new Set(columns.map((c) => c.name));
  if (!layout.pinned) layout.pinned = data.default_pinned.slice();
  const expanded = expandedRows.get(key) || new Set();
  expandedRows.set(key, expanded);

  // Streamlit calls this again with new data on every rerun; replace the
  // previous table rather than stacking a second one under it.
  parentElement.querySelectorAll(".nn-root").forEach((old) => old.remove());
  const root = el("div", "nn-root");
  parentElement.appendChild(root);

  const wrap = el("div", "nn-wrap");
  const table = el("table", "nn-table");
  const colgroup = el("colgroup");
  const thead = el("thead");
  const tbody = el("tbody");
  table.append(colgroup, thead, tbody);
  wrap.appendChild(table);
  root.appendChild(wrap);

  function orderedColumns() {
    const pinned = layout.pinned.filter((n) => knownNames.has(n));
    const pinnedCols = columns.filter((c) => pinned.includes(c.name));
    const rest = columns.filter((c) => !pinned.includes(c.name));
    return { cols: pinnedCols.concat(rest), pinnedCount: pinnedCols.length };
  }

  function render() {
    const { cols, pinnedCount } = orderedColumns();
    colgroup.replaceChildren();
    thead.replaceChildren();
    tbody.replaceChildren();

    // Sticky offsets: the action column, then each pinned column's width.
    const offsets = [];
    let left = actionWidth;
    cols.forEach((col, i) => {
      offsets.push(i < pinnedCount ? left : null);
      if (i < pinnedCount) left += widthOf(col);
    });

    const actionCol = el("col");
    actionCol.style.width = actionWidth + "px";
    colgroup.appendChild(actionCol);
    let total = actionWidth;
    cols.forEach((col) => {
      const c = el("col");
      c.style.width = widthOf(col) + "px";
      total += widthOf(col);
      colgroup.appendChild(c);
    });
    table.style.width = total + "px";

    const headRow = el("tr");
    const actionTh = el("th", "nn-action nn-sticky");
    actionTh.style.left = "0px";
    actionTh.title = "Add to your shopping list";
    actionTh.textContent = "List";
    headRow.appendChild(actionTh);

    cols.forEach((col, i) => {
      const th = el("th", "nn-" + col.kind);
      const isPinned = i < pinnedCount;
      if (isPinned) {
        th.classList.add("nn-sticky");
        th.style.left = offsets[i] + "px";
        if (i === pinnedCount - 1) th.classList.add("nn-last-pin");
      }
      const inner = el("div", "nn-th");
      const label = el("span", "nn-th-label", col.name);
      label.title = col.name;
      const pin = el("button", "nn-pin" + (isPinned ? " is-on" : ""));
      pin.type = "button";
      pin.innerHTML = PIN_SVG;
      pin.title = isPinned ? "Unpin column" : "Keep visible while scrolling sideways";
      pin.setAttribute("aria-label", pin.title + ": " + col.name);
      pin.addEventListener("click", () => {
        if (isPinned) {
          layout.pinned = layout.pinned.filter((n) => n !== col.name);
        } else {
          layout.pinned = layout.pinned.concat([col.name]);
        }
        saveLayout();
        render();
      });
      inner.append(label, pin);
      th.appendChild(inner);

      const grip = el("div", "nn-resize");
      grip.title = "Drag to resize";
      grip.addEventListener("pointerdown", (e) => startResize(e, col, i + 1));
      grip.addEventListener("dblclick", () => {
        delete layout.widths[col.name];
        saveLayout();
        render();
      });
      th.appendChild(grip);
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);

    rows.forEach((row) => {
      const tr = el("tr");
      if (row.cheapest) tr.classList.add("is-cheapest");
      if (row.healthiest) tr.classList.add("is-healthiest");
      if (expanded.has(row.id)) tr.classList.add("is-expanded");

      const actionTd = el("td", "nn-action nn-sticky");
      actionTd.style.left = "0px";
      const add = el("button", "nn-add" + (row.in_cart ? " is-on" : ""), row.in_cart ? "✓" : "+");
      add.type = "button";
      add.title = row.in_cart ? "On your list (click to remove)" : "Add to shopping list";
      add.setAttribute("aria-label", add.title);
      add.addEventListener("click", (e) => {
        e.stopPropagation();
        add.disabled = true;
        setTriggerValue("toggle_cart", row.id);
      });
      actionTd.appendChild(add);
      if (editable) {
        const hide = el("button", "nn-hide", "×");
        hide.type = "button";
        hide.title = "Hide from this category (it doesn't belong here)";
        hide.setAttribute("aria-label", hide.title);
        hide.addEventListener("click", (e) => {
          e.stopPropagation();
          hide.disabled = true;
          setTriggerValue("hide", row.id);
        });
        actionTd.appendChild(hide);
      }
      tr.appendChild(actionTd);

      cols.forEach((col, i) => {
        const td = renderCell(col, row.cells[col.name]);
        if (i < pinnedCount) {
          td.classList.add("nn-sticky");
          td.style.left = offsets[i] + "px";
          if (i === pinnedCount - 1) td.classList.add("nn-last-pin");
        }
        if (col.name === data.product_column) {
          const badges = el("span", "nn-badges");
          if (row.cheapest) badges.appendChild(el("span", "nn-badge nn-badge-cheap", "Cheapest"));
          if (row.healthiest) badges.appendChild(el("span", "nn-badge nn-badge-healthy", "Healthiest"));
          if (badges.childNodes.length) td.prepend(badges);
        }
        tr.appendChild(td);
      });

      // Clicking a row reveals the full text of every cut-off cell in it.
      tr.addEventListener("click", (e) => {
        if (e.target.closest("a, button")) return;
        if (window.getSelection && String(window.getSelection()).length) return;
        if (expanded.has(row.id)) expanded.delete(row.id);
        else expanded.add(row.id);
        tr.classList.toggle("is-expanded");
      });
      tbody.appendChild(tr);
    });
  }

  function startResize(e, col, colIndex) {
    e.preventDefault();
    e.stopPropagation();
    const startX = e.clientX;
    const startWidth = widthOf(col);
    const colEl = colgroup.children[colIndex];
    const baseTotal = parseFloat(table.style.width) - startWidth;
    root.classList.add("is-resizing");
    const onMove = (ev) => {
      const w = Math.max(MIN_WIDTH, Math.round(startWidth + ev.clientX - startX));
      layout.widths[col.name] = w;
      colEl.style.width = w + "px";
      table.style.width = baseTotal + w + "px";
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      root.classList.remove("is-resizing");
      saveLayout();
      // Pinned offsets depend on widths, so lay the table out again.
      render();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  render();

  const saved = scrollPos.get(key);
  if (saved) {
    wrap.scrollLeft = saved.left;
    wrap.scrollTop = saved.top;
  }
  const onScroll = () => scrollPos.set(key, { left: wrap.scrollLeft, top: wrap.scrollTop });
  wrap.addEventListener("scroll", onScroll, { passive: true });

  return () => {
    wrap.removeEventListener("scroll", onScroll);
    root.remove();
  };
}
