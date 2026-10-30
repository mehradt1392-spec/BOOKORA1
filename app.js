const form = document.getElementById("translateForm");
const input = document.getElementById("pdfFile");
const dropzone = document.getElementById("dropzone");
const fileTitle = document.getElementById("fileTitle");
const fileSub = document.getElementById("fileSub");
const submitButton = document.getElementById("submitButton");
const progressWrap = document.getElementById("progressWrap");
const message = document.getElementById("message");
const results = document.getElementById("results");
const previewGrid = document.getElementById("previewGrid");
const downloadAgain = document.getElementById("downloadAgain");
let lastBlob = null;
let lastName = "BOOKORA-translation.zip";

function setFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    showMessage("فقط فایل PDF قابل بارگذاری است.", true);
    input.value = "";
    return;
  }
  fileTitle.textContent = file.name;
  fileSub.textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB · آمادهٔ ترجمه`;
  message.hidden = true;
}
input.addEventListener("change", () => setFile(input.files[0]));
["dragenter","dragover"].forEach(type => dropzone.addEventListener(type, e => {
  e.preventDefault(); dropzone.classList.add("dragover");
}));
["dragleave","drop"].forEach(type => dropzone.addEventListener(type, e => {
  e.preventDefault(); dropzone.classList.remove("dragover");
}));
dropzone.addEventListener("drop", e => {
  const file = e.dataTransfer.files[0];
  if (file) {
    const transfer = new DataTransfer(); transfer.items.add(file); input.files = transfer.files; setFile(file);
  }
});

function showMessage(text, error=false) {
  message.textContent = text; message.hidden = false;
  message.classList.toggle("error", error);
}
function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
downloadAgain.addEventListener("click", () => { if (lastBlob) downloadBlob(lastBlob, lastName); });

form.addEventListener("submit", async e => {
  e.preventDefault();
  const file = input.files[0];
  if (!file) return showMessage("ابتدا یک فایل PDF انتخاب کن.", true);
  if (file.size > 50 * 1024 * 1024) return showMessage("حجم فایل بیشتر از ۵۰ مگابایت است.", true);

  message.hidden = true; results.hidden = true; progressWrap.hidden = false;
  submitButton.disabled = true;
  document.getElementById("progressTitle").textContent = "در حال ترجمهٔ کتاب...";
  document.getElementById("progressText").textContent = "متن صفحات استخراج و سپس ترجمه می‌شود. بسته به تعداد صفحات، این کار زمان می‌برد.";

  const data = new FormData();
  data.append("file", file);
  data.append("target_language", document.getElementById("targetLanguage").value);

  try {
    const response = await fetch("/api/translate", {method:"POST", body:data});
    if (!response.ok) {
      let detail = "ترجمه انجام نشد.";
      try { const body = await response.json(); detail = body.detail || detail; } catch {}
      throw new Error(detail);
    }
    const blob = await response.blob();
    lastBlob = blob;
    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/i);
    lastName = match ? match[1] : "BOOKORA-translation.zip";
    downloadBlob(blob, lastName);
    progressWrap.hidden = true;
    results.hidden = false;
    showMessage("ترجمه با موفقیت آماده شد. فایل ZIP نیز به‌صورت خودکار دانلود شد.");
    await showPreviews(blob);
  } catch (err) {
    progressWrap.hidden = true;
    showMessage(err.message || "خطای ناشناخته رخ داد.", true);
  } finally {
    submitButton.disabled = false;
  }
});

async function showPreviews(blob) {
  previewGrid.innerHTML = "";
  if (!window.JSZip) {
    document.querySelector(".preview-note").textContent = "برای دیدن پیش‌نمایش، فایل ZIP دانلودشده را باز کن.";
    return;
  }
  const zip = await JSZip.loadAsync(blob);
  const names = Object.keys(zip.files).filter(n => n.endsWith(".png")).sort().slice(0, 6);
  for (const name of names) {
    const fileBlob = await zip.files[name].async("blob");
    const url = URL.createObjectURL(fileBlob);
    const card = document.createElement("div"); card.className = "preview-card";
    const img = document.createElement("img"); img.src = url; img.alt = name;
    const caption = document.createElement("span"); caption.textContent = name.split("/").pop();
    card.append(img, caption); previewGrid.append(card);
  }
}
