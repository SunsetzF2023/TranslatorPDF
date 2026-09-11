import * as pdfjs from "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.7.76/build/pdf.min.mjs";

pdfjs.GlobalWorkerOptions.workerSrc =
  "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.7.76/build/pdf.worker.min.mjs";

const el = (id) => document.getElementById(id);
const ui = {
  file: el("file"),
  filename: el("filename"),
  firstPage: el("firstPage"),
  lastPage: el("lastPage"),
  provider: el("provider"),
  target: el("target"),
  translate: el("translate"),
  stop: el("stop"),
  print: el("print"),
  download: el("download"),
  progress: el("progress"),
  status: el("status"),
  output: el("output"),
};

let paragraphs = [];
let translations = [];
let stopped = false;
let docName = "document";

/* ------------------------------------------------------------------ PDF */

const SENTENCE_END = /[.!?:;"”)]\s*$/;
const BULLET = /^\s*([•●▪\-*·]|\(?\d+[.)]|[a-z]\))\s+/;

function itemsToLines(items) {
  const lines = [];
  for (const item of items) {
    if (!item.str.trim()) continue;
    const y = Math.round(item.transform[5] * 10) / 10;
    const x = item.transform[4];
    const last = lines[lines.length - 1];
    if (last && Math.abs(last.y - y) < 2.5) {
      const gap = x - (last.right ?? x);
      last.text += (gap > 1.2 && !last.text.endsWith(" ") ? " " : "") + item.str;
      last.right = x + (item.width || 0);
      last.left = Math.min(last.left, x);
    } else {
      lines.push({ y, left: x, right: x + (item.width || 0), text: item.str, height: item.height || 10 });
    }
  }
  return lines.filter((line) => line.text.trim());
}

function linesToParagraphs(lines, pageNumber) {
  const result = [];
  const widths = lines.map((l) => l.right - l.left);
  const maxWidth = Math.max(...widths, 1);
  let current = "";
  let previous = null;

  const flush = () => {
    const text = current.replace(/\s{2,}/g, " ").trim();
    if (text.length > 1 && /[a-zA-Z\u4e00-\u9fff]/.test(text)) {
      result.push({ page: pageNumber, text });
    }
    current = "";
  };

  for (const line of lines) {
    const text = line.text.trim();
    const gap = previous ? previous.y - line.y : 0;
    const breakHere =
      !current ||
      gap > line.height * 1.8 ||
      BULLET.test(text) ||
      (SENTENCE_END.test(current) && previous && previous.right - previous.left < maxWidth * 0.85) ||
      (previous && Math.abs(line.left - previous.left) > 12 && SENTENCE_END.test(current));
    if (breakHere) {
      flush();
      current = text;
    } else if (current.endsWith("-") && !current.endsWith("--")) {
      current = current.slice(0, -1) + text;
    } else {
      current += " " + text;
    }
    previous = line;
  }
  flush();
  return result;
}

async function loadPdf(file) {
  docName = file.name.replace(/\.pdf$/i, "");
  ui.filename.textContent = file.name;
  ui.status.textContent = "正在解析 PDF…";
  const data = new Uint8Array(await file.arrayBuffer());
  const doc = await pdfjs.getDocument({ data }).promise;
  const collected = [];
  for (let n = 1; n <= doc.numPages; n += 1) {
    const page = await doc.getPage(n);
    const content = await page.getTextContent();
    collected.push(...linesToParagraphs(itemsToLines(content.items), n));
  }
  paragraphs = collected;
  translations = new Array(paragraphs.length).fill("");
  ui.firstPage.value = 1;
  ui.lastPage.value = doc.numPages;
  ui.firstPage.max = doc.numPages;
  ui.lastPage.max = doc.numPages;
  ui.translate.disabled = paragraphs.length === 0;
  ui.print.disabled = true;
  ui.download.disabled = true;
  render();
  ui.status.textContent = paragraphs.length
    ? `${doc.numPages} 页，${paragraphs.length} 个段落。点“开始翻译”。`
    : "这个 PDF 没有文字层（扫描件），需要先 OCR。";
}

/* ----------------------------------------------------------- translation */

const CACHE_PREFIX = "pdfbt2:";

function cacheGet(target, text) {
  try {
    return localStorage.getItem(CACHE_PREFIX + target + ":" + text);
  } catch {
    return null;
  }
}

function cachePut(target, text, value) {
  try {
    localStorage.setItem(CACHE_PREFIX + target + ":" + text, value);
  } catch {
    /* quota exceeded — caching is best effort */
  }
}

function splitChunks(text, limit) {
  if (text.length <= limit) return [text];
  const chunks = [];
  let current = "";
  for (let piece of text.split(/(?<=[.!?;:])\s+/)) {
    while (piece.length > limit) {
      const cut = piece.lastIndexOf(" ", limit) > 0 ? piece.lastIndexOf(" ", limit) : limit;
      chunks.push(piece.slice(0, cut).trim());
      piece = piece.slice(cut).trim();
    }
    if (!current) current = piece;
    else if (current.length + piece.length + 1 <= limit) current += " " + piece;
    else {
      chunks.push(current);
      current = piece;
    }
  }
  if (current) chunks.push(current);
  return chunks.filter(Boolean);
}

function cleanup(text) {
  const stripped = text.replace(/<\/?g\b[^>]*>/g, "");
  const doc = new DOMParser().parseFromString(stripped, "text/html");
  return (doc.body.textContent ?? stripped).trim();
}

const providers = {
  async mymemory(text, target) {
    const url =
      "https://api.mymemory.translated.net/get?q=" +
      encodeURIComponent(text) +
      "&langpair=en|" +
      target;
    const response = await fetch(url);
    if (!response.ok) throw new Error("MyMemory HTTP " + response.status);
    const payload = await response.json();
    if (String(payload.responseStatus) !== "200") {
      throw new Error("MyMemory: " + payload.responseDetails);
    }
    return cleanup(payload.responseData.translatedText);
  },
  async google(text, target) {
    // `translate_a/t` (the Chrome dictionary client) is the only Google endpoint
    // that sends `Access-Control-Allow-Origin: *`, so it is usable from a page.
    const url =
      "https://translate.googleapis.com/translate_a/t?client=dict-chrome-ex&sl=en&tl=" +
      target +
      "&q=" +
      encodeURIComponent(text);
    const response = await fetch(url);
    if (!response.ok) throw new Error("Google HTTP " + response.status);
    const payload = await response.json();
    const flat = Array.isArray(payload) ? payload.flat(Infinity) : [payload];
    return cleanup(flat.filter((part) => typeof part === "string").join(""));
  },
};

const CHUNK_LIMIT = { mymemory: 480, google: 1500 };
const RETRIES = 3;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function callProvider(name, text, target) {
  let lastError;
  for (let attempt = 0; attempt < RETRIES; attempt += 1) {
    if (stopped) throw new Error("已停止");
    try {
      return await providers[name](text, target);
    } catch (error) {
      lastError = error;
      await sleep(600 * 2 ** attempt + Math.random() * 400);
    }
  }
  throw lastError;
}

async function translateParagraph(text, target, preferred) {
  const cached = cacheGet(target, text);
  if (cached) return cached;
  const order = [preferred, ...Object.keys(providers).filter((n) => n !== preferred)];
  const errors = [];
  for (const name of order) {
    try {
      const parts = [];
      for (const chunk of splitChunks(text, CHUNK_LIMIT[name])) {
        parts.push(await callProvider(name, chunk, target));
      }
      const result = parts.join(" ").trim();
      if (result) {
        cachePut(target, text, result);
        return result;
      }
    } catch (error) {
      errors.push(name + ": " + error.message);
    }
  }
  throw new Error(errors.join("；") || "翻译失败");
}

async function runTranslation() {
  const indices = activeIndices();
  if (!indices.length) return;
  const target = ui.target.value;
  const preferred = ui.provider.value;
  stopped = false;
  ui.translate.disabled = true;
  ui.stop.disabled = false;
  ui.progress.max = indices.length;
  ui.progress.value = 0;

  let done = 0;
  const queue = indices.slice();
  const worker = async () => {
    while (queue.length && !stopped) {
      const index = queue.shift();
      const node = document.querySelector(`[data-dst="${index}"]`);
      try {
        const text = await translateParagraph(paragraphs[index].text, target, preferred);
        translations[index] = text;
        if (node) {
          node.textContent = text;
          node.className = "dst";
        }
      } catch (error) {
        if (node) {
          node.textContent = "[翻译失败] " + error.message;
          node.className = "dst error";
        }
      }
      done += 1;
      ui.progress.value = done;
      ui.status.textContent = `翻译中 ${done}/${indices.length} …`;
    }
  };

  await Promise.all([worker(), worker()]);
  ui.translate.disabled = false;
  ui.stop.disabled = true;
  const ok = indices.filter((i) => translations[i]).length;
  ui.print.disabled = ok === 0;
  ui.download.disabled = ok === 0;
  ui.status.textContent = stopped
    ? `已停止：${ok}/${indices.length} 段已翻译。`
    : `完成：${ok}/${indices.length} 段已翻译。`;
}

/* ---------------------------------------------------------------- render */

function activeIndices() {
  const first = Number(ui.firstPage.value) || 1;
  const last = Number(ui.lastPage.value) || Infinity;
  return paragraphs.map((_, i) => i).filter((i) => paragraphs[i].page >= first && paragraphs[i].page <= last);
}

function render() {
  ui.output.textContent = "";
  let lastPage = null;
  for (const index of activeIndices()) {
    const para = paragraphs[index];
    if (para.page !== lastPage) {
      const label = document.createElement("div");
      label.className = "page-label";
      label.textContent = `第 ${para.page} 页 / Page ${para.page}`;
      ui.output.append(label);
      lastPage = para.page;
    }
    const row = document.createElement("div");
    row.className = "row";
    const src = document.createElement("div");
    src.className = "src";
    src.textContent = para.text;
    const dst = document.createElement("div");
    dst.className = translations[index] ? "dst" : "dst pending";
    dst.dataset.dst = String(index);
    dst.textContent = translations[index] || "…";
    row.append(src, dst);
    ui.output.append(row);
  }
}

const EXPORT_CSS = `body{font-family:-apple-system,"Segoe UI","Microsoft YaHei","Noto Sans CJK SC",sans-serif;max-width:1200px;margin:0 auto;padding:24px;line-height:1.7;color:#1c1e21}
h1{font-size:20px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:24px;padding:10px 0;border-bottom:1px solid #eceef1}
.src{white-space:pre-wrap}
.dst{color:#0b4f9e;white-space:pre-wrap}
.dst.pending,.dst.error{color:#999}
.page-label{margin:24px 0 8px;color:#999;font-size:12px;border-bottom:1px solid #eceef1;padding-bottom:4px}
@media print{.row{break-inside:avoid;border-bottom:none}}
@media (max-width:720px){.row{grid-template-columns:1fr;gap:6px}}`;

function downloadHtml() {
  const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>${docName} 中英对照</title>
<style>${EXPORT_CSS}</style><h1>${docName}</h1>${ui.output.innerHTML}</html>`;
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${docName}_bilingual.html`;
  link.click();
  URL.revokeObjectURL(link.href);
}

/* ---------------------------------------------------------------- events */

ui.file.addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  if (file) loadPdf(file).catch((error) => (ui.status.textContent = "读取失败：" + error.message));
});
ui.translate.addEventListener("click", () => runTranslation());
ui.stop.addEventListener("click", () => {
  stopped = true;
  ui.status.textContent = "正在停止…";
});
ui.print.addEventListener("click", () => window.print());
ui.download.addEventListener("click", downloadHtml);
for (const input of [ui.firstPage, ui.lastPage]) {
  input.addEventListener("change", () => paragraphs.length && render());
}

document.addEventListener("dragover", (event) => {
  event.preventDefault();
  document.body.classList.add("dragging");
});
document.addEventListener("dragleave", (event) => {
  if (event.relatedTarget === null) document.body.classList.remove("dragging");
});
document.addEventListener("drop", (event) => {
  event.preventDefault();
  document.body.classList.remove("dragging");
  const file = event.dataTransfer?.files?.[0];
  if (file && file.type === "application/pdf") {
    loadPdf(file).catch((error) => (ui.status.textContent = "读取失败：" + error.message));
  }
});
