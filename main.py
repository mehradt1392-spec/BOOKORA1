import io
import os
import uuid
import zipfile
import base64
import binascii
import hmac
import asyncio
import html
from pathlib import Path

import fitz
import httpx
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="BOOKORA", version="1.1.0", description="Private PDF translation engine")

# Private-site gate: every route except the minimal health check requires HTTP Basic Auth.
# Credentials must be supplied through server environment variables; never hard-code them.
BOOKORA_USERNAME = os.getenv("BOOKORA_USERNAME", "")
BOOKORA_PASSWORD = os.getenv("BOOKORA_PASSWORD", "")

@app.middleware("http")
async def private_site_auth(request: Request, call_next):
    if request.url.path == "/health":
        response = await call_next(request)
    else:
        if not BOOKORA_USERNAME or not BOOKORA_PASSWORD:
            return JSONResponse(
                status_code=503,
                content={"detail": "ورود خصوصی تنظیم نشده است. مدیر سایت باید BOOKORA_USERNAME و BOOKORA_PASSWORD را در محیط سرور تنظیم کند."},
                headers={"Cache-Control": "no-store"},
            )

        auth = request.headers.get("authorization", "")
        valid = False
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:], validate=True).decode("utf-8")
                supplied_user, separator, supplied_password = decoded.partition(":")
                valid = bool(separator) and hmac.compare_digest(supplied_user, BOOKORA_USERNAME) and hmac.compare_digest(supplied_password, BOOKORA_PASSWORD)
            except (binascii.Error, UnicodeDecodeError, ValueError):
                valid = False

        if not valid:
            return JSONResponse(
                status_code=401,
                content={"detail": "برای ورود به BOOKORA نام کاربری و رمز عبور لازم است."},
                headers={"WWW-Authenticate": 'Basic realm="BOOKORA Private", charset="UTF-8"', "Cache-Control": "no-store"},
            )
        response = await call_next(request)

    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

API_KEY = os.getenv("GOOGLE_TRANSLATE_API_KEY", "")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "300"))
PAGE_W, PAGE_H, MARGIN = 1500, 2100, 105

LANGUAGES = [
    {"code": "fa", "name": "فارسی"},
    {"code": "en", "name": "English"},
    {"code": "de", "name": "Deutsch"},
    {"code": "fr", "name": "Français"},
    {"code": "es", "name": "Español"},
    {"code": "it", "name": "Italiano"},
    {"code": "tr", "name": "Türkçe"},
    {"code": "ar", "name": "العربية"},
    {"code": "ru", "name": "Русский"},
    {"code": "pt", "name": "Português"},
    {"code": "zh-CN", "name": "中文"},
    {"code": "ja", "name": "日本語"},
    {"code": "ko", "name": "한국어"},
    {"code": "hi", "name": "हिन्दी"},
    {"code": "nl", "name": "Nederlands"},
    {"code": "pl", "name": "Polski"},
    {"code": "uk", "name": "Українська"},
    {"code": "sv", "name": "Svenska"},
]

@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "BOOKORA",
        "translation_configured": bool(API_KEY),
        "max_upload_mb": MAX_UPLOAD_MB,
        "max_pages": MAX_PAGES
    }

@app.get("/api/languages")
def languages():
    return LANGUAGES

def split_text(text: str, limit: int = 4300):
    """Split text into API-safe chunks without cutting words where possible."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    while len(text) > limit:
        # Prefer paragraph, sentence, then whitespace boundaries.
        candidates = [
            text.rfind("\n", 0, limit),
            text.rfind(". ", 0, limit),
            text.rfind("! ", 0, limit),
            text.rfind("? ", 0, limit),
            text.rfind(" ", 0, limit),
        ]
        cut = max(candidates)
        if cut < limit // 2:
            cut = limit
        yield text[:cut].strip()
        text = text[cut:].strip()
    if text:
        yield text


async def translate(text: str, target: str) -> str:
    """Translate using Google Cloud Translation Basic (v2) with retry/error handling."""
    if not API_KEY:
        raise RuntimeError("کلید Google Cloud Translation روی سرور تنظیم نشده است.")

    output = []
    timeout = httpx.Timeout(90.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for part in split_text(text):
            last_error = None
            for attempt in range(3):
                try:
                    response = await client.post(
                        "https://translation.googleapis.com/language/translate/v2",
                        params={"key": API_KEY},
                        json={"q": part, "target": target, "format": "text"},
                    )
                    if response.status_code in (429, 500, 502, 503, 504):
                        last_error = f"خطای موقت سرویس ترجمه (HTTP {response.status_code})"
                        if attempt < 2:
                            await asyncio.sleep(1.5 * (attempt + 1))
                            continue
                    if response.is_error:
                        try:
                            api_message = response.json().get("error", {}).get("message", "")
                        except Exception:
                            api_message = ""
                        if response.status_code in (400, 401, 403):
                            raise RuntimeError(
                                "Google Translation درخواست را نپذیرفت. فعال بودن Cloud Translation API، "
                                "درستی کلید و فعال بودن Billing را بررسی کنید. " + api_message[:300]
                            )
                        raise RuntimeError(last_error or f"سرویس ترجمه خطای HTTP {response.status_code} برگرداند.")

                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise RuntimeError("پاسخ Google Translation قابل خواندن نیست.") from exc
                    translations = payload.get("data", {}).get("translations", [])
                    if not translations or not isinstance(translations[0].get("translatedText"), str):
                        raise RuntimeError("پاسخ سرویس ترجمه ساختار معتبری ندارد.")
                    # Google v2 returns HTML-escaped entities even for format=text.
                    output.append(html.unescape(translations[0]["translatedText"]))
                    break
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    last_error = "ارتباط با سرویس ترجمه برقرار نشد یا زمان پاسخ‌گویی تمام شد."
                    if attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    raise RuntimeError(last_error) from exc
            else:
                raise RuntimeError(last_error or "ترجمه انجام نشد.")
    return "\n".join(output)

def extract_text(page) -> str:
    text = page.get_text("text").strip()
    if len(text) >= 20:
        return text
    try:
        import pytesseract
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        from PIL import Image
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        lang = os.getenv("OCR_LANG", "eng")
        return pytesseract.image_to_string(image, lang=lang).strip()
    except Exception:
        return text

def get_font(size: int, target: str):
    candidates = []
    custom = os.getenv("BOOKORA_FONT")
    if custom:
        candidates.append(custom)
    if target in ("fa", "ar"):
        candidates += [
            "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    candidates += [
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()

def prepare_rtl(text: str, target: str):
    if target not in ("fa", "ar"):
        return text, False
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return "\n".join(get_display(arabic_reshaper.reshape(x)) for x in text.splitlines()), True
    except Exception:
        return text, True

def render_translated_page(text: str, number: int, total: int, target: str) -> Image.Image:
    image = Image.new("RGB", (PAGE_W, PAGE_H), "#fbfaf7")
    draw = ImageDraw.Draw(image)
    title_font = get_font(43, target)
    body_font = get_font(29, target)
    meta_font = get_font(20, target)
    draw.text((MARGIN, 55), "BOOKORA", font=title_font, fill="#17233d")
    draw.text((MARGIN, 118), f"TRANSLATED EDITION  /  {target.upper()}", font=meta_font, fill="#a18450")
    draw.line((MARGIN, 170, PAGE_W-MARGIN, 170), fill="#d8cfbd", width=2)

    prepared, rtl = prepare_rtl(text, target)
    y = 220
    line_height = 43
    max_width = PAGE_W - 2 * MARGIN
    for paragraph in prepared.splitlines():
        words = paragraph.split()
        if not words:
            y += 20
            continue
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if draw.textbbox((0, 0), candidate, font=body_font)[2] <= max_width:
                line = candidate
            else:
                if line:
                    x = PAGE_W - MARGIN if rtl else MARGIN
                    draw.text((x, y), line, font=body_font, fill="#252a34", anchor="ra" if rtl else None)
                    y += line_height
                line = word
            if y > PAGE_H - 160:
                break
        if line and y <= PAGE_H - 160:
            x = PAGE_W - MARGIN if rtl else MARGIN
            draw.text((x, y), line, font=body_font, fill="#252a34", anchor="ra" if rtl else None)
            y += line_height
        y += 14
        if y > PAGE_H - 160:
            break

    draw.line((MARGIN, PAGE_H-105, PAGE_W-MARGIN, PAGE_H-105), fill="#d8cfbd", width=2)
    draw.text((MARGIN, PAGE_H-75), f"BOOKORA  •  {number} / {total}", font=meta_font, fill="#8a806e")
    return image

@app.post("/api/translate")
async def translate_pdf(
    file: UploadFile = File(...),
    target_language: str = Form(...)
):
    if not API_KEY:
        raise HTTPException(503, "موتور ترجمه هنوز پیکربندی نشده است. مدیر سایت باید کلید API را روی سرور قرار دهد.")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "لطفاً یک فایل PDF انتخاب کنید.")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"حجم فایل نباید بیشتر از {MAX_UPLOAD_MB} مگابایت باشد.")
    if not raw.startswith(b"%PDF"):
        raise HTTPException(400, "فایل انتخاب‌شده PDF معتبر نیست.")
    if target_language not in {x["code"] for x in LANGUAGES}:
        raise HTTPException(400, "زبان مقصد پشتیبانی نمی‌شود.")

    try:
        document = fitz.open(stream=raw, filetype="pdf")
    except Exception:
        raise HTTPException(400, "باز کردن فایل PDF ممکن نشد.")
    if len(document) > MAX_PAGES:
        document.close()
        raise HTTPException(413, f"این نسخه حداکثر {MAX_PAGES} صفحه را در هر درخواست می‌پذیرد.")

    job_id = uuid.uuid4().hex[:10]
    archive_buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for page_index, page in enumerate(document, start=1):
                source = extract_text(page)
                if not source:
                    translated = "متنی برای ترجمه در این صفحه شناسایی نشد."
                else:
                    translated = await translate(source, target_language)
                rendered = render_translated_page(translated, page_index, len(document), target_language)
                image_buffer = io.BytesIO()
                rendered.save(image_buffer, format="PNG", optimize=True)
                archive.writestr(f"pages/page-{page_index:04d}.png", image_buffer.getvalue())
        archive_buffer.seek(0)
    except RuntimeError as error:
        raise HTTPException(502, str(error))
    finally:
        document.close()

    return StreamingResponse(
        archive_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="BOOKORA-{job_id}.zip"'}
    )
