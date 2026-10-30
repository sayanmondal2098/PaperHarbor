const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c],
  );
const HEADERS = { "X-PaperHarbor": "1", "Content-Type": "application/json" };
let library = null,
  selection = new Set(),
  loadedConfig = null,
  upload = null;
let revision = 0,
  loading = false,
  running = false,
  starting = false;
let pdfOverrides = {},
  retryAvailable = false,
  lastResults = "";
let autoLinkedRetries = new Set();

async function request(path, cfg) {
  const response = await fetch(
    path,
    cfg === undefined
      ? {}
      : {
          method: "POST",
          headers: HEADERS,
          body: JSON.stringify(cfg),
        },
  );
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error || "The request could not be completed.");
  return data;
}

function updateControls() {
  $("source_fields").disabled = running || starting;
  $("connect").disabled = loading || running || starting;
  $("connect").textContent = loading
    ? "Loading references…"
    : "Load references ↗";
  $("go").disabled =
    loading || running || starting || !library || !selection.size;
  $("go").textContent =
    running || starting
      ? "Downloading…"
      : selection.size
        ? "Download " +
          selection.size +
          " selected reference" +
          (selection.size === 1 ? "" : "s") +
          " ↓"
        : "Find & download PDFs ↓";
  for (const id of [
    "select_all",
    "unselect_all",
    "select_shown",
    "select_visible",
    "upload_shortcut",
  ]) {
    $(id).disabled = running || starting || loading;
  }
  $("select_visible").disabled ||= !shownReferences().length;
  $("retry_failed").hidden = !retryAvailable;
  $("retry_failed").disabled = running || starting;
  document.querySelectorAll("#librows input").forEach((el) => {
    el.disabled = running || starting;
  });
}

function invalidateLibrary() {
  revision++;
  loading = false;
  library = null;
  loadedConfig = null;
  selection.clear();
  pdfOverrides = {};
  autoLinkedRetries.clear();
  $("lib").hidden = true;
  $("empty_library").hidden = false;
  $("library_count").textContent = "0";
  $("source_badge").textContent = "No source connected";
  $("libmsg").textContent = "";
  $("msg").textContent = "";
  updateControls();
}

function sourceChanged() {
  invalidateLibrary();
  const value = $("src").value;
  for (const source of ["sqlite", "upload", "export", "api", "single"]) {
    const panel = $("f_" + source);
    if (panel) panel.hidden = value !== source;
  }
}

function sourceConfig() {
  switch ($("src").value) {
    case "single":
      if (!$("paper_identifier").value.trim())
        throw new Error("Paste a paper DOI or article URL first.");
      return {
        paper_identifier: $("paper_identifier").value.trim(),
        paper_title: $("paper_title").value.trim(),
        email: $("email").value.trim(),
      };
    case "upload":
      if (!upload)
        throw new Error(
          "Choose a bibliography or PaperHarbor CSV report first.",
        );
      return {
        upload_name: upload.name,
        upload_content: upload.content,
        retry_not_found: $("retry_not_found").checked,
      };
    case "export":
      if (!$("export_file").value.trim())
        throw new Error("Enter an export file path.");
      return { export_file: $("export_file").value.trim() };
    case "api":
      if (!$("api_key").value.trim())
        throw new Error("Enter your Zotero API key.");
      if (!$("user_id").value.trim() && !$("group_id").value.trim())
        throw new Error("Enter a user ID or group ID.");
      if ($("user_id").value.trim() && $("group_id").value.trim())
        throw new Error("Use either a user ID or a group ID.");
      return {
        api_key: $("api_key").value.trim(),
        user_id: $("user_id").value.trim(),
        group_id: $("group_id").value.trim(),
      };
    default:
      return { zotero_path: $("zotero_path").value.trim() };
  }
}

async function loadLibrary() {
  if (loading || running || starting) return;
  invalidateLibrary();
  const currentRevision = revision;
  loading = true;
  $("libmsg").classList.remove("error");
  $("libmsg").textContent = "Reading your references…";
  updateControls();
  try {
    const cfg = sourceConfig();
    const data = await request("/api/library", cfg);
    if (revision !== currentRevision) return;
    library = data;
    loadedConfig = cfg;
    selection = new Set();
    $("q").value = "";
    $("coll").replaceChildren(new Option("All collections", ""));
    for (const collection of data.collections)
      $("coll").add(
        new Option(
          collection.name + " (" + collection.count + ")",
          collection.name,
        ),
      );
    $("lib").hidden = false;
    $("empty_library").hidden = true;
    $("library_count").textContent = data.items.length;
    $("source_badge").textContent =
      upload && $("src").value === "upload"
        ? upload.name
        : $("src").selectedOptions[0].textContent;
    $("libmsg").textContent =
      data.items.length + " references ready. Choose the papers you want.";
    renderLibrary();
  } catch (error) {
    if (revision === currentRevision) {
      $("libmsg").textContent = error.message;
      $("libmsg").classList.add("error");
    }
  } finally {
    if (revision === currentRevision) loading = false;
    updateControls();
  }
}

async function readUpload(file) {
  if (!file || running || starting) return;
  $("src").value = "upload";
  sourceChanged();
  upload = null;
  const currentRevision = revision;
  try {
    if (!/\.(bib|bibtex|json|csv)$/i.test(file.name))
      throw new Error(
        "Choose a .bib, .bibtex, .json, or PaperHarbor .csv file.",
      );
    if (file.size > 5 * 1024 * 1024)
      throw new Error("Choose a file smaller than 5 MB.");
    if (!file.size) throw new Error("The selected file is empty.");
    const content = await file.text();
    if (revision !== currentRevision) return;
    upload = { name: file.name, content };
    $("upload_info").textContent =
      file.name + " · " + Math.max(1, Math.round(file.size / 1024)) + " KB";
    await loadLibrary();
  } catch (error) {
    $("upload_info").textContent = error.message;
    $("libmsg").textContent = error.message;
    $("libmsg").classList.add("error");
  } finally {
    $("bib_file").value = "";
    updateControls();
  }
}

function shownReferences() {
  if (!library) return [];
  const query = $("q").value.trim().toLowerCase(),
    collection = $("coll").value;
  return library.items.filter(
    (item) =>
      (!collection || item.collections.includes(collection)) &&
      (!$("onlymiss").checked || !item.has_pdf) &&
      (!query ||
        (item.title + " " + item.authors + " " + item.doi)
          .toLowerCase()
          .includes(query)),
  );
}

function updateSelection() {
  const shown = shownReferences();
  const selectedShown = shown.filter((item) => selection.has(item.key)).length;
  $("selcount").textContent =
    selection.size + " selected · " + shown.length + " shown";
  $("select_visible").checked =
    shown.length > 0 && selectedShown === shown.length;
  $("select_visible").indeterminate =
    selectedShown > 0 && selectedShown < shown.length;
  $("select_visible").disabled = !shown.length || running || starting;
  updateControls();
}

function renderLibrary() {
  const items = shownReferences();
  $("librows").innerHTML = items.length
    ? items
        .map(
          (item) =>
            '<tr class="' +
            (selection.has(item.key) ? "selected" : "") +
            '">' +
            '<td class="checkbox-cell"><input type="checkbox" data-key="' +
            esc(item.key) +
            '" aria-label="Select ' +
            esc(item.title || "Untitled reference") +
            '" ' +
            (selection.has(item.key) ? "checked" : "") +
            "></td>" +
            '<td><div class="paper-title">' +
            esc(item.title || "Untitled reference") +
            '</div><div class="paper-meta">' +
            esc(item.authors || "Unknown author") +
            (item.doi ? " · DOI: " + esc(item.doi) : "") +
            '</div><details class="alternate"><summary>Use another PDF link</summary><input type="url" data-override-key="' +
            esc(item.key) +
            '" aria-label="Alternate PDF URL" placeholder="https://repository.edu/paper.pdf" value="' +
            esc(pdfOverrides[item.key] || "") +
            '"></details></td>' +
            '<td class="year-cell">' +
            esc(item.year) +
            '</td><td><span class="badge ' +
            (item.has_pdf ? "has-pdf" : "") +
            '">' +
            (item.has_pdf ? "Attached" : "Missing") +
            "</span></td></tr>",
        )
        .join("")
    : '<tr><td colspan="4" class="no-matches">No references match these filters.</td></tr>';
  updateSelection();
}

function selectAll() {
  if (!library || running || starting) return;
  selection = new Set(library.items.map((item) => item.key));
  renderLibrary();
}
function unselectAll() {
  if (!running && !starting) {
    selection.clear();
    renderLibrary();
  }
}
function selectShown(on) {
  if (running || starting) return;
  for (const item of shownReferences())
    on ? selection.add(item.key) : selection.delete(item.key);
  renderLibrary();
}

async function startDownload() {
  $("msg").textContent = "";
  if (!library || !selection.size) {
    $("msg").textContent = "Load references and select at least one paper.";
    return;
  }
  if (!$("dest_folder").value.trim()) {
    $("msg").textContent = "Choose a destination folder first.";
    $("dest_folder").focus();
    return;
  }
  const limit = $("limit").value;
  if (limit && (!Number.isInteger(Number(limit)) || Number(limit) < 1)) {
    $("msg").textContent =
      "The reference limit must be a positive whole number.";
    return;
  }
  if (!$("email").checkValidity()) {
    $("msg").textContent = "Enter a valid contact email or leave it blank.";
    return;
  }
  const cfg = {
    ...loadedConfig,
    item_keys: [...selection],
    dest_folder: $("dest_folder").value.trim(),
    email: $("email").value.trim(),
    limit,
    template: $("template").value.trim(),
    include_zotero_has_pdf: $("include_zotero_has_pdf").checked,
    force_redownload: $("force_redownload").checked,
    pdf_overrides: pdfOverrides,
    auto_retry_once:
      Boolean(loadedConfig.paper_identifier) &&
      ($("auto_retry_once")?.checked ?? true),
  };
  starting = true;
  updateControls();
  try {
    await request("/api/start", cfg);
    running = true;
    $("job_badge").textContent = "Searching & downloading";
  } catch (error) {
    $("msg").textContent = error.message;
  } finally {
    starting = false;
    updateControls();
  }
}

const STATUS_LABELS = {
  DOWNLOADED: "Downloaded",
  SKIPPED_ALREADY_IN_ZOTERO: "Already attached",
  SKIPPED_ALREADY_IN_DEST: "Already saved",
  PAYWALLED_OR_OA_NOT_FOUND: "No open copy found",
  DOWNLOAD_FAILED: "Download failed",
  OA_BLOCKED_MANUAL: "Open manually",
  ERROR: "Error",
  WEB_RESOURCE: "Documentation / dataset",
  WITHDRAWN: "Withdrawn",
};
async function poll() {
  try {
    const state = await request("/api/status");
    running = state.running;
    retryAvailable =
      state.done &&
      state.results.some((r) =>
        ["DOWNLOAD_FAILED", "OA_BLOCKED_MANUAL", "ERROR"].includes(r.status),
      );
    const completed = state.results.length;
    $("bar").max = state.total || 1;
    $("bar").value = completed;
    const percent =
      state.done && !state.error
        ? 100
        : state.total
          ? Math.round((completed / state.total) * 100)
          : 0;
    $("percentage").textContent = percent + "%";
    $("cur").textContent = state.running
      ? state.total
        ? state.current + " / " + state.total + " · " + state.title
        : "Reading references and looking for PDFs…"
      : state.done
        ? state.error
          ? "The job stopped. See details below."
          : "Finished processing your references."
        : "Choose your references to get started.";
    $("job_badge").textContent = state.running
      ? "Searching & downloading"
      : state.done
        ? state.error
          ? "Needs attention"
          : "Completed"
        : "Ready when you are";
    const summary = state.summary;
    const skipped =
      (summary.SKIPPED_ALREADY_IN_ZOTERO || 0) +
      (summary.SKIPPED_ALREADY_IN_DEST || 0);
    const review =
      (summary.PAYWALLED_OR_OA_NOT_FOUND || 0) +
      (summary.DOWNLOAD_FAILED || 0) +
      (summary.OA_BLOCKED_MANUAL || 0) +
      (summary.ERROR || 0) +
      (summary.WITHDRAWN || 0);
    const statItems = [
      [summary.DOWNLOADED || 0, "Downloaded"],
      [skipped, "Skipped"],
      [review, "Need review"],
    ];
    if (summary.WEB_RESOURCE)
      statItems.push([summary.WEB_RESOURCE, "Web resources"]);
    $("stats").innerHTML = statItems
      .map(
        ([n, label]) =>
          "<div><strong>" + n + "</strong><span>" + label + "</span></div>",
      )
      .join("");
    $("job_error").textContent = state.error;
    $("rep").hidden = !state.report;
    $("rep").textContent = state.report
      ? "CSV report saved to: " + state.report
      : "";
    $("results_wrap").hidden = !state.results.length;
    for (const result of state.results) {
      const token = result.key + "|" + result.auto_retry_url;
      if (
        result.auto_retry_count &&
        result.auto_retry_url &&
        library?.items.some((item) => item.key === result.key) &&
        !autoLinkedRetries.has(token)
      ) {
        if (!pdfOverrides[result.key]) {
          pdfOverrides[result.key] = result.auto_retry_url;
          document.querySelectorAll("[data-override-key]").forEach((input) => {
            if (input.dataset.overrideKey === result.key) {
              input.value = result.auto_retry_url;
              const details = input.closest("details");
              if (details) details.open = true;
            }
          });
        }
        autoLinkedRetries.add(token);
      }
    }
    const resultSignature = JSON.stringify(state.results);
    if (resultSignature !== lastResults) {
      $("rows").innerHTML = state.results
        .slice()
        .reverse()
        .map(
          (result) =>
            '<tr><td><span class="badge ' +
            esc(result.status) +
            '">' +
            esc(STATUS_LABELS[result.status] || result.status) +
            "</span></td>" +
            '<td><div class="paper-title">' +
            esc(result.title) +
            '</div><div class="paper-meta">' +
            esc(result.author) +
            " · " +
            esc(result.year) +
            "</div></td>" +
            '<td><div class="paper-title">' +
            esc(result.file || result.provider || "—") +
            "</div>" +
            (result.file && result.provider
              ? '<div class="paper-meta">' + esc(result.provider) + "</div>"
              : "") +
            (/^https?:\/\//i.test(result.url)
              ? '<a href="' +
                esc(result.url) +
                '" target="_blank" rel="noopener" class="paper-meta">Open source ↗</a>'
              : "") +
            '<div class="paper-meta">' +
            esc(result.action || "") +
            "</div>" +
            (result.auto_retry_count
              ? '<div class="paper-meta">Automatic linked retry: 1/1</div>'
              : "") +
            (result.suggested_filename
              ? '<div class="paper-meta">Save as: ' +
                esc(result.suggested_filename) +
                "</div>"
              : "") +
            (result.links || [])
              .filter((link) => /^https?:\/\//i.test(link.url))
              .map(
                (link) =>
                  '<a class="recovery-link" target="_blank" rel="noopener" href="' +
                  esc(link.url) +
                  '">' +
                  esc(link.label) +
                  "</a>",
              )
              .join(" ") +
            '<details class="attempt-details"><summary>Attempt details (' +
            (result.attempts || []).length +
            ")</summary><p>" +
            esc(result.notes || "") +
            "</p>" +
            (result.attempts || [])
              .map(
                (attempt) =>
                  '<div class="attempt"><strong>' +
                  esc(attempt.provider) +
                  "</strong><p>" +
                  esc(attempt.error || attempt.outcome) +
                  "</p><span>" +
                  esc(attempt.url) +
                  "</span></div>",
              )
              .join("") +
            "</details></td></tr>",
        )
        .join("");
      lastResults = resultSignature;
    }
    const log = $("log"),
      nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.textContent = state.logs.join("\n") || "No activity yet.";
    if (nearBottom) log.scrollTop = log.scrollHeight;
    updateControls();
  } catch (error) {
    $("job_badge").textContent = "Reconnecting…";
  } finally {
    setTimeout(poll, 1000);
  }
}

$("src").addEventListener("change", sourceChanged);
for (const id of [
  "zotero_path",
  "export_file",
  "api_key",
  "user_id",
  "group_id",
  "paper_identifier",
  "paper_title",
])
  $(id)?.addEventListener("input", invalidateLibrary);
$("connect").addEventListener("click", loadLibrary);
$("bib_file").addEventListener("change", (event) =>
  readUpload(event.target.files[0]),
);
$("retry_not_found").addEventListener("change", loadLibrary);
$("librows").addEventListener("input", (event) => {
  const key = event.target.dataset.overrideKey;
  if (!key) return;
  const value = event.target.value.trim();
  if (value) pdfOverrides[key] = value;
  else delete pdfOverrides[key];
});
$("retry_failed").addEventListener("click", async () => {
  starting = true;
  updateControls();
  try {
    await request("/api/retry", { pdf_overrides: pdfOverrides });
    running = true;
  } catch (error) {
    $("job_error").textContent = error.message;
  } finally {
    starting = false;
    updateControls();
  }
});
$("upload_shortcut").addEventListener("click", () => {
  $("src").value = "upload";
  sourceChanged();
  $("bib_file").click();
});
const dropzone = $("dropzone");
for (const event of ["dragenter", "dragover"])
  dropzone.addEventListener(event, (e) => {
    e.preventDefault();
    dropzone.classList.add("dragging");
  });
for (const event of ["dragleave", "drop"])
  dropzone.addEventListener(event, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragging");
  });
dropzone.addEventListener("drop", (event) =>
  readUpload(event.dataTransfer.files[0]),
);
$("q").addEventListener("input", renderLibrary);
$("coll").addEventListener("change", renderLibrary);
$("onlymiss").addEventListener("change", renderLibrary);
$("select_all").addEventListener("click", selectAll);
$("unselect_all").addEventListener("click", unselectAll);
$("select_shown").addEventListener("click", () => selectShown(true));
$("select_visible").addEventListener("change", (event) =>
  selectShown(event.target.checked),
);
$("librows").addEventListener("change", (event) => {
  const key = event.target.dataset.key;
  if (!key || running || starting) return;
  event.target.checked ? selection.add(key) : selection.delete(key);
  event.target.closest("tr").classList.toggle("selected", event.target.checked);
  updateSelection();
});
$("browse").addEventListener("click", async () => {
  $("browse").disabled = true;
  try {
    const data = await request("/api/pick-folder", {
      initial: $("dest_folder").value,
    });
    if (data.path) $("dest_folder").value = data.path;
  } catch (error) {
    $("msg").textContent = error.message;
  } finally {
    $("browse").disabled = false;
  }
});
$("go").addEventListener("click", startDownload);
request("/api/defaults")
  .then((data) => {
    $("zotero_path").placeholder =
      data.zotero_path || "Auto-detect zotero.sqlite";
  })
  .catch(() => {});
async function checkServerRuntime() {
  try {
    const response = await fetch("/api/runtime", { cache: "no-store" });
    let needsRestart = response.status === 404;
    if (response.ok) needsRestart = (await response.json()).restart_required;
    if (!response.ok && response.status !== 404) return;
    let notice = $("server_update_notice");
    if (needsRestart) {
      if (!notice) {
        notice = document.createElement("div");
        notice.id = "server_update_notice";
        notice.className = "server-update-notice";
        notice.setAttribute("role", "status");
        document.querySelector("main").prepend(notice);
      }
      notice.textContent =
        "PaperHarbor has been updated. Restart the Python web server with python web.py, then refresh this page to use the latest download fixes.";
    } else if (notice) {
      notice.remove();
    }
  } catch {
    // Connection errors are already shown by the regular job status poll.
  } finally {
    setTimeout(checkServerRuntime, 30000);
  }
}
updateControls();
poll();
checkServerRuntime();
