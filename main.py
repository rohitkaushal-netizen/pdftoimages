import io
import os
import re
import base64
import json
import uuid
import html as html_stdlib
import random
import shutil
import tempfile
import zipfile
import asyncio
import warnings
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import fitz  # PyMuPDF
import pdfplumber
import pytesseract
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageStat
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", category=UserWarning)

# Tesseract binary — homebrew installs here on Apple Silicon Macs
_TESS_CANDIDATES = [
    "/Users/rohitkaushal/homebrew/Cellar/tesseract/5.5.2/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
]
for _p in _TESS_CANDIDATES:
    if Path(_p).exists():
        pytesseract.pytesseract.tesseract_cmd = _p
        break

app = FastAPI(title="PDF Extractor + Housing.com Enrichment + Website Scraper")

# Allow Tampermonkey (browser extension) to call localhost API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── CMS queue (in-memory) ──────────────────────────────────────────────────────
_cms_queue: list[dict] = []
_cms_pos: int = 0

# In-memory stores (image bytes live on disk, not here)
sessions: dict = {}       # session_id → {images: [meta, ...]}
scrape_jobs: dict = {}    # session_id → job state dict

HTML_PATH = Path(__file__).parent / "index.html"

# ── Disk image store ───────────────────────────────────────────────────────────
# All image bytes are written to TEMP_DIR/<session_id>/<img_id>.<fmt>
# This keeps the Python process RAM near-zero regardless of how many images are loaded.
TEMP_DIR = Path(tempfile.gettempdir()) / "pdf_extractor_imgs"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
# Clean up any orphan dirs left from a previous server run
for _d in TEMP_DIR.iterdir():
    if _d.is_dir():
        shutil.rmtree(_d, ignore_errors=True)


def _img_dir(session_id: str) -> Path:
    d = TEMP_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_img(session_id: str, img_id: str, fmt: str, data: bytes) -> None:
    (_img_dir(session_id) / f"{img_id}.{fmt}").write_bytes(data)


def _img_file(session_id: str, img_id: str) -> Path | None:
    """Return the disk Path for an image, checking metadata first then common extensions."""
    meta = next(
        (m for m in sessions.get(session_id, {}).get("images", []) if m["id"] == img_id),
        None,
    )
    if meta:
        p = _img_dir(session_id) / f"{img_id}.{meta.get('format', 'jpeg')}"
        if p.exists():
            return p
    for ext in ("jpeg", "jpg", "png", "webp", "gif"):
        p = _img_dir(session_id) / f"{img_id}.{ext}"
        if p.exists():
            return p
    return None


def _read_img(session_id: str, img_id: str) -> bytes | None:
    p = _img_file(session_id, img_id)
    return p.read_bytes() if p else None


def _clear_session_dir(session_id: str) -> None:
    d = TEMP_DIR / session_id
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)

APPROVED_AMENITIES = (
    "24 X 7 Security, 24x7 CCTV Surveillance, 24X7 Water Supply, Acupressure Center, "
    "Acupressure Pathway, Adventure Club, Aerobics Room, Air Conditioned, Amphitheater, "
    "Amusement Area, Anti-termite Treatment, Archery Club, Assembly Area, ATM, "
    "Auto Service Station, Automated Car Wash, Ayurveda Centre, Badminton Court, "
    "Banquet Hall, Bar/ Chill-out Lounge, Barbecue Area, Basketball Court, Beach access, "
    "Beach Volley Ball Court, Billiards/ Snooker Table, Board Games, Boom Barriers, "
    "Bowling Alley, Bus Shelter, Business Center, Business Suites, Cafeteria, Car Lift, "
    "Car Parking, Car Wash Area, Card Room, Carrom, Central Cooling System, Changing Room, "
    "Chess Board, Children's play area, Cigar Lounge, Cineplex, Closed Car Parking, "
    "Club House, Club Rooftop, Community Buildings, Community Hall, Compound Wall, "
    "Concierge Service, Conference Room, Cricket arena, Cricket Pitch, "
    "Cycling & Jogging Track, Dart Board, Day Care Center, DG Availability, Discotheque, "
    "Dock, Doctor on call, Double Glazed Windows, Earthquake Resistant Structure, "
    "Electrical meter Room, Electrification, Energy management, "
    "Entrance Gate Security Cabin, Entrance Lobby, Escalators, EV Charging Point, "
    "Exotic Plantation, Facilities for Disabled, Feng Shui, Fire Alarm, "
    "Fire Escape Staircases, Fire Fighting System, "
    "Fire Protection And Fire Safety Requirements, Fire Retardant Structure, "
    "Fire Sprinklers, Fitness Center, Flower Garden, Food Court, Foosball, "
    "Football Field, Footpaths/ Pedestrian, Fountains, Full Power Backup, Futsal, "
    "Garbage Disposal, Gated Community, Gazebo, Golf Course, Grade A Building, "
    "Greenhouse Farming, Grocery Shop, Gymnasium, Health Facilities, Helipad, "
    "High Speed Elevators, High-tech Alarm System, Hockey Ground, Hospital, "
    "Indoor Games, Infinity Pool, Intercom, Internal Roads & Footpaths, Internet/ Wi-Fi, "
    "Jacuzzi, Jogging Track, Kid's Pool, Landscape Garden and Tree Planting, "
    "Landscaped Gardens, Laundromat, Lawn Tennis Court, Letter Box, Library, Lift(s), "
    "Light shows, Lockers, Maintenance Staff, Manicured Garden, Medical Facilities, "
    "Medical Store/ Pharmacy, Milk Booth, Mini Theatre, Motion Sensor, "
    "Multi - Level Parking, Multipurpose Hall, Multipurpose Room, Natural Pond, "
    "Nature Club, Observatories, Open Air Theatre, Open Car Parking, Open Gym, "
    "Open Parking, Opera House, Organic Farming, Partial Power Backup, Party Hall, "
    "Party Lawn, Paved Compound, Pergola, Pet Grooming, Petrol Pump, Pickleball Court, "
    "Piped Gas Connection, Place for Worship, Polo Ground, Projector Wall, Race Course, "
    "Rain Water Harvesting, Reading Lounge, Receiving Station, "
    "Reception/ Waiting Room, Recreation Facilities, Reflexology Park, "
    "Reserved Parking, Rest House for Drivers, Restaurant, RO Water System, Salon, "
    "Sauna Bath, School, Security Cabin, Security Guards, Semi Open Car Parking, "
    "Senior Citizen Sitout, Sensor operated doors and lifts, Server Room, Service Lift, "
    "Sewage Treatment Plant, Shooting range, Shopping Mall, Skating Rink, "
    "Smoke Detectors, Solar Lighting, Solar Power System, Solar Water Heating, "
    "Solid Waste Management And Disposal, Spa, Spa/ Sauna/ Steam, Sports Area, "
    "Sports Complex, Sports Facility, Squash Court, Staff Quarter, Steam Room, "
    "Storm Water Drains, Street Lighting, Sub-Station, Sun Bathing, Sun Deck, "
    "Swimming Pool, Table Tennis, Taxi/ Bus Terminal, Temple, Tennis Court, "
    "Terrace Garden, Theme Park, Two Wheeler Parking, Utility Shops, Vaastu Compliant, "
    "Valet Parking, Vastu Compliant, Vertical Garden, Video Door Security, "
    "Visitor Parking, Volleyball Court, Waiting Lounge, Wall Climbing, "
    "Water Conservation, Rain water Harvesting, Water Softener Plant, Water Sports, "
    "Water Storage, Water Supply, Yoga/ Meditation Area, Zebra Crossing"
)

# ── Web scraper constants ──────────────────────────────────────────────────────

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

IMG_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "avif", "bmp"}
SKIP_NAME_PATTERNS = [
    "icon", "favicon", "logo-sm", "thumb-xs", "sprite",
    "button", "avatar", "1x1", "pixel", "blank", "spacer",
]
CRAWL_PRIORITY_KW = [
    "gallery", "images", "photos", "media", "project",
    "amenities", "floorplan", "floor-plan", "renders",
]
# Ordered list of (category, keywords) — checked first-match wins (most specific first)
_CAT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Kitchen",      ["kitchen", "modular-kitchen", "modular kitchen"]),
    ("Bedroom",      ["bedroom", "bed-room", "master-bed", "master bedroom", "master bed"]),
    ("Bathroom",     ["bathroom", "toilet", "washroom", "bath-room", "powder-room", "powder room"]),
    ("Living Room",  ["living-room", "living room", "drawing-room", "drawing room", "sitting room"]),
    ("Model Flat",   ["model-flat", "model flat", "sample-flat", "sample flat",
                      "show-flat", "show flat", "furnished", "model apartment"]),
    ("Amenity",      ["amenity", "amenities", "swimming pool", "swimming-pool", "pool",
                      "gymnasium", "gym ", " gym", "clubhouse", "club-house", "garden",
                      "landscape", "playground", "play-area", "play area", "jogging",
                      "sports", "tennis", "badminton", "basketball", "yoga", "meditation",
                      "spa", "party-lawn", "party lawn", "amphitheater", "gazebo",
                      "fountain", "recreation", "kids-area", "kids area", "lobby",
                      # builder-site gallery labels (countygroup / similar)
                      "lagoon", "lotus pond", "nature bridge", "energy bar",
                      "skating", "sanctuary", "restro", "plaza", "tot lot",
                      "little champ", "flowing water", "central landscape",
                      "sports area", "culinary", "infinity"]),
    ("Elevation",    ["elevation", "facade", "front-view", "frontview", "front view",
                      "building-view", "tower-view", "exterior"]),
    ("3D Render",    ["render", "3d-view", "3dview", "3d view", "perspective",
                      "visuali", "aerial", "drone", "birdseye", "bird-eye", "bird's eye"]),
    ("Location Plan",["location-plan", "location plan", "location-map", "locationmap",
                      "connectivity", "vicinity", "area-map", "area map"]),
    ("Master Plan",  ["master-plan", "masterplan", "master plan", "site-plan",
                      "siteplan", "site plan", "project-plan", "projectplan", "project plan"]),
    ("Cluster Plan", ["cluster-plan", "clusterplan", "cluster plan", "block-plan",
                      "wing-plan", "wing plan", "cluster"]),
    ("Floor Plan",   ["floor-plan", "floorplan", "floor plan", "unit-plan", "unitplan",
                      "unit plan", "apartment-plan", "flat-plan", "typical-floor",
                      "1bhk", "2bhk", "3bhk", "4bhk", "5bhk", "bhk-plan", "layout", "/fp/", "-fp-"]),
]

# ── Pydantic models ────────────────────────────────────────────────────────────

class EnrichRequest(BaseModel):
    project_id: str

class ScrapeRequest(BaseModel):
    url: str
    deep_crawl: bool = True
    max_pages: int = 5
    image_type_filter: str = "all"   # all | photos | floor_plans | renders | diagrams
    html_override: str = ""           # if set, skip HTTP fetch and parse this HTML directly

# ── PDF helpers ────────────────────────────────────────────────────────────────

def _pixel_heuristic_classify(image_bytes: bytes) -> str:
    """
    Fallback classifier using pixel statistics.
    - Mostly white + low variance  → Floor Plan
    - High stddev                  → Photo
    - Low stddev                   → Diagram
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        thumb = img.resize((100, 100))
        pixels = list(thumb.getdata())
        total = len(pixels)
        white = sum(1 for r, g, b in pixels if r > 200 and g > 200 and b > 200)
        if white / total > 0.60:
            if ImageStat.Stat(img.convert("L")).stddev[0] < 60:
                return "Floor Plan"
        std = ImageStat.Stat(img.convert("L")).stddev[0]
        return "Photo" if std > 40 else "Diagram"
    except Exception:
        return "Photo"


def classify_image_category(image_bytes: bytes, context_text: str = "") -> str:
    """
    Synchronous classifier for PDF images.
    1. Keyword match on context_text (filename + page text).
    2. Pixel heuristics fallback.
    """
    ctx = context_text.lower()
    for category, keywords in _CAT_KEYWORDS:
        if any(kw in ctx for kw in keywords):
            return category
    return _pixel_heuristic_classify(image_bytes)


async def classify_image_with_vision(image_bytes: bytes, context_text: str = "") -> str:
    """
    Classifier for website-scraped images — no external API calls.
    1. Keyword check on URL / filename (instant).
    2. Pixel heuristics fallback.
    """
    ctx = context_text.lower()
    for category, keywords in _CAT_KEYWORDS:
        if any(kw in ctx for kw in keywords):
            return category
    return _pixel_heuristic_classify(image_bytes)


def ocr_pdf(pdf_bytes: bytes, scale: float = 2.0) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    mat = fitz.Matrix(scale, scale)
    parts: list[str] = []
    for page in doc:
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        text = pytesseract.image_to_string(img, lang="eng", config="--psm 3")
        if text.strip():
            parts.append(text.strip())
    doc.close()
    return "\n\n".join(parts)


def find_brochure_url(obj, depth: int = 0) -> str | None:
    if depth > 12:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "brochure" in k.lower() and "pdf" in k.lower():
                if isinstance(v, str) and v.startswith("http"):
                    return v
        for k, v in obj.items():
            if "brochure" in k.lower():
                if isinstance(v, str) and v.startswith("http") and ".pdf" in v.lower():
                    return v
        for v in obj.values():
            r = find_brochure_url(v, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = find_brochure_url(item, depth + 1)
            if r:
                return r
    return None


def find_rera(obj, depth: int = 0) -> str | None:
    if depth > 12:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "rera" in k.lower():
                if isinstance(v, str) and v:
                    return v
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, str) and item:
                            return item
            r = find_rera(v, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = find_rera(item, depth + 1)
            if r:
                return r
    return None


def _build_zip(items: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, data in items:
            zf.writestr(filename, data)
    return buf.getvalue()


def _extract_images_from_pdf(
    doc: fitz.Document, session_id: str, min_w: int = 0, min_h: int = 0
) -> list[dict]:
    """Extract images from a PDF, write bytes directly to disk, return metadata only."""
    images: list[dict] = []
    seen_xrefs: set[int] = set()
    idx = 0

    page_texts: list[str] = [page.get_text() for page in doc]

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_text = page_texts[page_num]

        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                extracted = doc.extract_image(xref)
            except Exception:
                continue
            img_bytes: bytes = extracted["image"]
            img_ext: str = extracted.get("ext", "png").lower()
            width: int = extracted.get("width", 0)
            height: int = extracted.get("height", 0)
            if width < min_w or height < min_h:
                continue
            if img_ext == "jpg":
                img_ext = "jpeg"
            img_id = str(idx)
            filename = f"image_{idx:04d}_page{page_num + 1}.{img_ext}"
            image_type = classify_image_category(img_bytes, context_text=filename + " " + page_text)
            images.append({
                "id": img_id, "filename": filename,
                "width": width, "height": height,
                "page": page_num + 1, "format": img_ext,
                "image_type": image_type, "size": len(img_bytes),
            })
            _write_img(session_id, img_id, img_ext, img_bytes)   # straight to disk
            idx += 1
    return images

# ── Web scraper helpers ────────────────────────────────────────────────────────

def parse_srcset(srcset_str: str) -> str | None:
    """Pick highest-resolution URL from a srcset string."""
    candidates: list[tuple[float, str]] = []
    for part in srcset_str.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if not tokens:
            continue
        url = tokens[0]
        weight: float = 0
        if len(tokens) >= 2:
            desc = tokens[1]
            try:
                if desc.endswith("w"):
                    weight = float(desc[:-1])
                elif desc.endswith("x"):
                    weight = float(desc[:-1]) * 1000
            except ValueError:
                pass
        candidates.append((weight, url))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def normalize_img_url(raw: str, base: str) -> str | None:
    raw = raw.strip()
    if not raw or raw.startswith("data:") or raw.startswith("javascript:"):
        return None
    raw = html_stdlib.unescape(raw)
    if raw.startswith("//"):
        raw = urlparse(base).scheme + ":" + raw
    if not raw.startswith("http"):
        raw = urljoin(base, raw)
    return raw if raw.startswith("http") else None


def looks_like_image_url(url: str) -> bool:
    path = url.split("?")[0].lower()
    ext = path.rsplit(".", 1)[-1] if "." in path else ""
    return ext in IMG_EXTENSIONS


def is_likely_icon(url: str) -> bool:
    name = url.split("/")[-1].split("?")[0].lower()
    return any(p in name for p in SKIP_NAME_PATTERNS)


def is_cloudflare_protected(resp: httpx.Response) -> bool:
    if resp.status_code not in (403, 429, 503):
        return False
    text = resp.text.lower()
    return (
        "cloudflare" in text
        or "cf-ray" in resp.headers
        or "__cf_bm" in resp.headers.get("set-cookie", "")
        or "just a moment" in text
    )


_BG_IMG_RE = re.compile(
    r'background(?:-image)?\s*:\s*url\(["\']?([^"\')\s]+)["\']?\)', re.I
)
_JS_IMG_RE = re.compile(
    r'https?://[^\s\'"<>]+\.(?:jpg|jpeg|png|webp|gif|avif)(?:\?[^\s\'"<>]*)?',
    re.I,
)
# Matches http/https AND protocol-relative (//), covers youtube-nocookie and youtu.be
_YT_RE = re.compile(
    r'(?:https?:)?//(?:www\.)?'
    r'(?:youtube(?:-nocookie)?\.com/(?:watch\?[^"\'\s]*?v=|embed/(?!videoseries)|shorts/|v/)'
    r'|youtu\.be/)'
    r'([\w-]{11})',
    re.I,
)
# Catches   videoId: "abc123"   or   video_id="abc123"   in JS/data attributes
_YT_ID_ATTR_RE = re.compile(
    r'(?:video[-_]?id|videoId|ytid|youtube[-_]?id)\s*[=:]\s*["\']?([\w-]{11})["\']?',
    re.I,
)
_PDF_URL_RE = re.compile(
    r'https?://[^\s\'"<>()]+\.pdf(?:\?[^\s\'"<>()]*)?',
    re.I,
)
_PRICE_VALUE_RE = re.compile(
    r'(?:₹|Rs\.?|INR)\s*[\d,]+(?:\.\d+)?\s*(?:Lakh|Lac|Cr|Crore|L)?'
    r'|[\d,]+(?:\.\d+)?\s*(?:Lakh|Lac|Crore|Cr)\b',
    re.I,
)
_PRICE_SECTION_RE = re.compile(
    r'\b(?:price|pricing|cost|bsp|basic\s+selling|starting\s+(?:from|price)|'
    r'configuration|config|rate\s+list|price\s+list)\b',
    re.I,
)
_STARTING_PRICE_RE = re.compile(
    r'(?:[Ss]tarting\s+(?:[Ff]rom\s+|[Aa]t\s+)?|[Bb]ase\s+[Pp]rice[:\s]+|[Pp]rice\s+[Ss]tarting\s+(?:[Ff]rom\s+)?)'
    r'(?:₹|Rs\.?|INR)?\s*[\d,]+(?:\.\d+)?\s*(?:Lakh|Lac|Cr(?:ore)?|L)?'
    r'|(?:₹|Rs\.?|INR)\s*[\d,]+(?:\.\d+)?\s*(?:Lakh|Lac|Cr(?:ore)?)\s*[Oo]nwards',
    re.I,
)
_PAYMENT_KW_RE = re.compile(
    r'\b(?:On\s+Booking|On\s+Agreement|On\s+Possession|On\s+Completion|'
    r'Construction[-\s]Linked|Down\s+Payment|At\s+the\s+time\s+of|'
    r'Stage[-\s]Wise|Payment\s+Plan|Possession\s+Stage|Installment|'
    r'Subvention|No\s+EMI)\b',
    re.I,
)
_PERCENT_RE = re.compile(r'\d+\s*%')


def extract_image_urls(soup: BeautifulSoup, html_str: str, page_url: str) -> list[str]:
    found: set[str] = set()

    # Respect <base href> — builder sites like countygroup.in use it so all
    # relative URLs resolve against the site root, not the current path.
    base_tag = soup.find("base", href=True)
    if base_tag:
        raw_base = base_tag["href"].strip()
        if raw_base.startswith("http"):
            page_url = raw_base
        elif raw_base:
            page_url = urljoin(page_url, raw_base)

    def add(raw: str) -> None:
        n = normalize_img_url(raw, page_url)
        if n and looks_like_image_url(n) and not is_likely_icon(n):
            found.add(n)

    # 1+2+10. <img> with every relevant attribute
    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-lazy-src", "data-original",
                     "data-background", "data-image", "data-full", "data-zoom-image"):
            val = img.get(attr, "")
            if val:
                add(val)
        # 3. srcset
        srcset = img.get("srcset", "")
        if srcset:
            best = parse_srcset(srcset)
            if best:
                add(best)

    # 4. <source srcset> / <source src> in <picture>
    for source in soup.find_all("source"):
        srcset = source.get("srcset", "")
        if srcset:
            best = parse_srcset(srcset)
            if best:
                add(best)
        src = source.get("src", "")
        if src:
            add(src)

    # 5+6. background-image in style attributes
    for tag in soup.find_all(style=True):
        for m in _BG_IMG_RE.finditer(tag["style"]):
            add(m.group(1))

    # background-image in <style> blocks
    for style_tag in soup.find_all("style"):
        for m in _BG_IMG_RE.finditer(style_tag.get_text()):
            add(m.group(1))

    # 7. OG / Twitter meta tags
    for prop in ("og:image", "og:image:secure_url"):
        for meta in soup.find_all("meta", property=prop):
            c = meta.get("content", "")
            if c:
                add(c)
    for meta in soup.find_all("meta", attrs={"name": "twitter:image"}):
        c = meta.get("content", "")
        if c:
            add(c)

    # 8. JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue

        def _walk_json(obj: object) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k.lower() in ("image", "imageurl", "photo", "thumbnail", "logo", "url"):
                        if isinstance(v, str):
                            add(v)
                        elif isinstance(v, list):
                            for item in v:
                                if isinstance(item, str):
                                    add(item)
                                elif isinstance(item, dict):
                                    add(item.get("url", ""))
                    else:
                        _walk_json(v)
            elif isinstance(obj, list):
                for item in obj:
                    _walk_json(item)

        _walk_json(data)

    # 9. Inline JS regex scan
    for script in soup.find_all("script"):
        for m in _JS_IMG_RE.finditer(script.string or ""):
            add(m.group(0))

    # 11. <link rel="preload" as="image">
    for link in soup.find_all("link", rel="preload"):
        if link.get("as") == "image":
            href = link.get("href", "")
            if href:
                add(href)

    # 12. Carousel / slider containers
    for slide in soup.find_all(class_=re.compile(
        r"swiper-slide|owl-item|slick-slide|carousel-item", re.I
    )):
        for img in slide.find_all("img"):
            for attr in ("src", "data-src", "data-lazy", "data-original"):
                val = img.get(attr, "")
                if val:
                    add(val)

    # 13. Fancybox / lightbox gallery anchors — builder sites often put the
    # full-res URL in data-src on the <a> tag, with the same (or smaller)
    # thumbnail in the nested <img>.  data-gallery / data-lightbox are
    # alternative patterns used by other gallery plugins.
    for a in soup.find_all("a"):
        if not any(a.has_attr(attr) for attr in ("data-fancybox", "data-lightbox", "data-gallery")):
            continue
        for attr in ("data-src", "data-full", "data-orig", "href"):
            val = a.get(attr, "")
            if val and not val.startswith(("#", "javascript:")):
                add(val)
                break

    # 14. Generic popup/lightbox data attributes on any element — e.g. Lodha's
    # data-popup-img="/sites/default/files/Gallery/main/..."
    _POPUP_ATTRS = ("data-popup-img", "data-popup-src", "data-full-img",
                    "data-large", "data-large-src", "data-high-res",
                    "data-zoom", "data-zoom-src", "data-lightbox-src")
    for tag in soup.find_all(True):
        for attr in _POPUP_ATTRS:
            val = tag.get(attr, "")
            if val:
                add(val)

    return list(found)


# ── Section-ID keyword → image category (for builder/developer websites) ───────
_SECTION_ID_TO_CATEGORY: dict[str, str] = {
    "amenities":      "Amenity",
    "amenity":        "Amenity",
    "gallery":        "Photo",
    "floor-plan":     "Floor Plan",
    "floorplan":      "Floor Plan",
    "master-plan":    "Master Plan",
    "masterplan":     "Master Plan",
    "site-plan":      "Master Plan",
    "location":       "Location Plan",
    "location-map":   "Location Plan",
    "specifications": "Photo",
    "elevation":      "Elevation",
    "exterior":       "Elevation",
    "overview":       "3D Render",
    "renders":        "3D Render",
    "clubhouse":      "Amenity",
    "club-house":     "Amenity",
}

# Label selectors tried in order when looking for a gallery image's caption
_GALLERY_LABEL_SELECTORS = [
    ".sopmiow5", "figcaption", ".caption", ".img-caption",
    "[class*=caption]", "[class*=label]", "[class*=title]",
    ".card-title", ".slide-title", ".thumb-title",
]


def extract_fancybox_labels(soup: BeautifulSoup, base_url: str) -> dict[str, str]:
    """
    For fancybox / lightbox gallery anchors, find each image's label from:
      1. A nearby caption element (.sopmiow5, figcaption, [class*=caption], …)
      2. The nearest ancestor section/div whose id contains a known category keyword.
    Returns {abs_image_url: label_text}.
    """
    labels: dict[str, str] = {}

    for a in soup.find_all("a"):
        if not any(a.has_attr(attr) for attr in ("data-fancybox", "data-lightbox", "data-gallery")):
            continue
        raw_url = a.get("data-src") or a.get("data-full") or a.get("data-orig") or a.get("href") or ""
        if not raw_url or raw_url.startswith(("#", "javascript:")):
            continue
        abs_url = normalize_img_url(raw_url, base_url)
        if not abs_url or not looks_like_image_url(abs_url):
            continue

        label = ""

        # 1. Search siblings/parent containers for a caption element
        container = a.parent
        for _ in range(6):
            if container is None:
                break
            for sel in _GALLERY_LABEL_SELECTORS:
                try:
                    el = container.select_one(sel)
                except Exception:
                    el = None
                if el:
                    text = el.get_text(strip=True)
                    if 2 < len(text) < 120:
                        label = text
                        break
            if label:
                break
            container = getattr(container, "parent", None)

        # 2. Fallback: nearest ancestor whose id maps to a known category
        if not label:
            for ancestor in a.parents:
                aid = (ancestor.get("id") or "").lower()
                if not aid:
                    continue
                for key, cat in _SECTION_ID_TO_CATEGORY.items():
                    if key in aid:
                        label = cat
                        break
                if label:
                    break

        if label:
            labels[abs_url] = label

    return labels


def extract_internal_links(
    soup: BeautifulSoup, current_url: str, base_domain: str
) -> list[str]:
    priority, normal = [], []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        abs_url = normalize_img_url(href, current_url)
        if not abs_url:
            continue
        parsed = urlparse(abs_url)
        if parsed.netloc != base_domain:
            continue
        if looks_like_image_url(abs_url) or abs_url.lower().endswith(".pdf"):
            continue
        lower = abs_url.lower()
        if any(kw in lower for kw in CRAWL_PRIORITY_KW):
            priority.append(abs_url)
        else:
            normal.append(abs_url)
    return priority + normal


async def classify_scraped_image(img_bytes: bytes, url: str, filename: str) -> str:
    """Async wrapper around the vision classifier using URL + filename as context."""
    return await classify_image_with_vision(img_bytes, context_text=url + " " + filename)


# ── Content extractor helpers ──────────────────────────────────────────────────

_DOC_KEYWORDS = {
    "brochure": "Brochure", "e-brochure": "Brochure", "ebrochure": "Brochure",
    "catalog": "Brochure", "catalogue": "Brochure",
    "price": "Price List", "pricelist": "Price List", "rate": "Price List",
    "cost": "Price List", "bsp": "Price List",
    "payment": "Payment Plan", "installment": "Payment Plan",
    "floor": "Floor Plans", "layout": "Floor Plans",
    "master": "Master Plan", "site plan": "Master Plan",
}


def _classify_doc(url: str, link_text: str) -> str:
    combined = url.lower() + " " + link_text.lower()
    for kw, t in _DOC_KEYWORDS.items():
        if kw in combined:
            return t
    return "Document"


def extract_documents(soup: BeautifulSoup, page_url: str, html_str: str) -> list[dict]:
    """Extract ALL PDF links (anchor tags + raw HTML scan) and classify by type."""
    docs: list[dict] = []
    seen: set[str] = set()

    def _add(url: str, title: str, doc_type: str) -> None:
        if url in seen:
            return
        seen.add(url)
        docs.append({"url": url, "title": (title.strip() or url.rsplit("/", 1)[-1])[:200], "type": doc_type})

    # 1. Anchor tags — include every PDF regardless of link text
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        abs_url = normalize_img_url(href, page_url)
        if not abs_url:
            continue

        link_text = a.get_text(separator=" ", strip=True)
        combined  = abs_url.lower() + " " + link_text.lower()
        is_pdf    = ".pdf" in abs_url.lower() or "pdf" in a.get("type", "").lower()
        has_doc_kw = any(kw in combined for kw in _DOC_KEYWORDS)

        if is_pdf:
            _add(abs_url, link_text or abs_url.rsplit("/", 1)[-1], _classify_doc(abs_url, link_text))
        elif has_doc_kw:
            # Non-PDF doc links (e.g., download buttons that don't show extension)
            _add(abs_url, link_text, _classify_doc(abs_url, link_text))

    # 2. Raw HTML scan — catches PDFs in JS vars, data-href, onclick, etc.
    for m in _PDF_URL_RE.finditer(html_str):
        abs_url = m.group(0)
        _add(abs_url, abs_url.rsplit("/", 1)[-1], _classify_doc(abs_url, ""))

    return docs


# ── Structured pricing helpers ─────────────────────────────────────────────────

_COL_TYPE_KW  = {"type", "config", "bhk", "unit", "apartment", "flat", "bedroom",
                 "room", "villa", "plot", "studio", "size"}
_COL_AREA_KW  = {"area", "sq", "sqft", "carpet", "built", "super", "sft", "size"}
_COL_PRICE_KW = {"price", "cost", "rate", "bsp", "value", "amount",
                 "₹", "rs", "inr", "lakh", "lac", "crore"}


def _identify_columns(headers: list[str]) -> tuple[int | None, int | None, int | None]:
    """Return (type_col, area_col, price_col) indices from header texts."""
    type_idx = area_idx = price_idx = None
    for i, h in enumerate(headers):
        hl = h.lower()
        if price_idx is None and any(kw in hl for kw in _COL_PRICE_KW):
            price_idx = i
        elif area_idx is None and any(kw in hl for kw in _COL_AREA_KW):
            area_idx = i
        elif type_idx is None and any(kw in hl for kw in _COL_TYPE_KW):
            type_idx = i
    return type_idx, area_idx, price_idx


def _parse_price_table(table) -> list[dict]:
    """Try to extract structured rows {type, area, price} from an HTML table."""
    rows = table.find_all("tr")
    if len(rows) < 2:
        return []

    # Find the best header row (first row that has recognisable keywords)
    header_row_idx = 0
    headers: list[str] = []
    for ri, row in enumerate(rows[:3]):
        cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
        if cells:
            _, _, pi = _identify_columns(cells)
            if pi is not None:
                headers = cells
                header_row_idx = ri
                break

    if not headers:
        return []

    type_idx, area_idx, price_idx = _identify_columns(headers)
    if price_idx is None:
        return []

    results: list[dict] = []
    for row in rows[header_row_idx + 1:]:
        cells = [c.get_text(separator=" ", strip=True) for c in row.find_all(["td", "th"])]
        if not cells or len(cells) < 2:
            continue
        entry: dict = {}
        if type_idx is not None and type_idx < len(cells):
            entry["type"] = cells[type_idx].strip()
        if area_idx is not None and area_idx < len(cells):
            entry["area"] = cells[area_idx].strip()
        if price_idx < len(cells):
            entry["price"] = cells[price_idx].strip()
        # Keep rows where the price cell actually contains a price value
        # (this naturally filters repeated header rows)
        if entry.get("price") and _PRICE_VALUE_RE.search(entry["price"]):
            if entry.get("type") or entry.get("area"):
                results.append(entry)

    return results


def extract_structured_pricing(soup: BeautifulSoup) -> dict:
    """
    Return:
      {
        "configs":       [{type, area, price}, ...],   # from parsed tables
        "starting_price": str | None,
        "raw_blocks":    [str, ...],                   # fallback text blocks
      }
    """
    configs: list[dict] = []
    seen_rows: set[str] = set()
    raw_blocks: list[str] = []
    seen_raw: set[str] = set()
    starting_price: str | None = None

    def _add_raw(text: str) -> None:
        clean = " ".join(text.split())[:900]
        key = clean[:120]
        if key and key not in seen_raw and len(clean) > 25:
            seen_raw.add(key)
            raw_blocks.append(clean)

    # 1. Parse tables for structured rows
    for table in soup.find_all("table"):
        rows = _parse_price_table(table)
        for row in rows:
            key = f"{row.get('type','')}|{row.get('area','')}|{row.get('price','')}"
            if key not in seen_rows:
                seen_rows.add(key)
                configs.append(row)
        if not rows:
            # Still keep as raw block if it looks like a pricing table
            text = table.get_text(separator=" | ", strip=True)
            if _PRICE_VALUE_RE.search(text) and _PRICE_SECTION_RE.search(text):
                _add_raw(text)

    # 2. Fallback — divs/sections with pricing signals
    if not configs:
        for tag in soup.find_all(["div", "section", "article", "ul", "li"]):
            if tag.find("table"):
                continue
            text = tag.get_text(separator=" ", strip=True)
            if len(text) < 25 or len(text) > 1500:
                continue
            if _PRICE_VALUE_RE.search(text) and _PRICE_SECTION_RE.search(text):
                _add_raw(text)

    # 3. Extract a standalone starting price string
    full_text = soup.get_text(separator=" ")
    m = _STARTING_PRICE_RE.search(full_text)
    if m:
        starting_price = " ".join(m.group(0).split())[:120]

    return {
        "configs": configs,
        "starting_price": starting_price,
        "raw_blocks": raw_blocks[:8],
    }


def extract_payment_plan_blocks(soup: BeautifulSoup) -> list[str]:
    """Extract text blocks describing payment plan stages."""
    blocks: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        clean = " ".join(text.split())[:900]
        key = clean[:120]
        if key and key not in seen and len(clean) > 20:
            seen.add(key)
            blocks.append(clean)

    for table in soup.find_all("table"):
        text = table.get_text(separator=" | ", strip=True)
        if _PAYMENT_KW_RE.search(text) and _PERCENT_RE.search(text):
            _add(text)

    for tag in soup.find_all(["div", "section", "ul", "ol", "p"]):
        if tag.find("table"):
            continue
        text = tag.get_text(separator=" ", strip=True)
        if len(text) < 25 or len(text) > 2000:
            continue
        if _PAYMENT_KW_RE.search(text) and _PERCENT_RE.search(text):
            _add(text)

    return blocks[:10]


def extract_youtube_links(soup: BeautifulSoup, html_str: str) -> list[dict]:
    """
    Find YouTube video IDs from every possible source on the page:
    iframes (src + data-src), anchor tags, lite-youtube / custom elements,
    data-* attributes, JSON-LD, inline JS variables, and raw HTML scan.
    """
    seen_ids: set[str] = set()
    links: list[dict] = []

    def _add(video_id: str, title: str = "") -> None:
        vid = video_id.strip()
        # YouTube video IDs are always exactly 11 characters
        if not vid or len(vid) != 11 or vid in seen_ids:
            return
        seen_ids.add(vid)
        links.append({
            "video_id": vid,
            "url":       f"https://www.youtube.com/watch?v={vid}",
            "embed_url": f"https://www.youtube.com/embed/{vid}",
            "thumbnail": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg",
            "title":     (title.strip() or vid)[:200],
        })

    # 1. <iframe src="..."> and <iframe data-src="..."> (lazy-loaded iframes)
    for iframe in soup.find_all("iframe"):
        for attr in ("src", "data-src", "data-lazy-src"):
            val = iframe.get(attr, "")
            if val:
                m = _YT_RE.search(val)
                if m:
                    _add(m.group(1), iframe.get("title", ""))

    # 2. <a href="..."> anchor links to YouTube
    for a in soup.find_all("a", href=True):
        m = _YT_RE.search(a["href"])
        if m:
            _add(m.group(1), a.get_text(separator=" ", strip=True))

    # 3. Custom / web-component elements:
    #    <lite-youtube videoid="...">, <youtube-video id="...">, etc.
    #    Also catches data-video-id, data-youtube-id on any element
    _YT_DATA_ATTRS = (
        "videoid", "data-videoid", "data-video-id",
        "data-youtube-id", "data-youtube", "data-vid", "data-ytid",
    )
    for tag in soup.find_all(True):
        for attr in _YT_DATA_ATTRS:
            val = tag.get(attr, "")
            if val and re.match(r'^[\w-]{11}$', val):
                title = tag.get("data-title", tag.get("title", ""))
                _add(val, title)

    # 3b. Scan ALL data-* attributes for any YouTube URL
    #     Catches data-popup-iframe, data-video-src, data-youtube-src, etc.
    #     e.g. <div data-popup-iframe="https://www.youtube.com/embed/D5bG0vWP3i8?...">
    for tag in soup.find_all(True):
        for attr, val in tag.attrs.items():
            if not attr.startswith("data-"):
                continue
            if isinstance(val, str) and ("youtube" in val or "youtu.be" in val):
                m = _YT_RE.search(val)
                if m:
                    title = tag.get("data-title", "") or tag.get("title", "")
                    _add(m.group(1), title)

    # 4. JSON-LD scripts — embedUrl, url, video fields
    for script in soup.find_all("script", type="application/ld+json"):
        text = script.string or ""
        for m in _YT_RE.finditer(text):
            _add(m.group(1))

    # 5. Raw HTML scan — catches JS vars, onclick, data-attrs with full URLs
    for m in _YT_RE.finditer(html_str):
        _add(m.group(1))

    # 6. videoId / video_id JS patterns (e.g. new YT.Player or ytplayer config)
    for m in _YT_ID_ATTR_RE.finditer(html_str):
        _add(m.group(1))

    return links


# ── Web scraper background task ────────────────────────────────────────────────

async def _download_one(
    client: httpx.AsyncClient,
    img_url: str,
    found_on: str,
    idx: int,
    semaphore: asyncio.Semaphore,
    job: dict,
    image_type_filter: str,
) -> dict | None:
    # ── Phase 1: Download (semaphore limits concurrent connections to target host)
    try:
        async with semaphore:
            # Send Referer so sites don't block hotlinking (e.g. lodhagroup.com)
            parsed_found = urlparse(found_on)
            referer = f"{parsed_found.scheme}://{parsed_found.netloc}/"
            r = await client.get(img_url, headers={"Referer": referer})
            if r.status_code == 403:
                # Retry with the exact page URL as Referer
                r = await client.get(img_url, headers={"Referer": found_on})
            ct = r.headers.get("content-type", "")
            # Accept image/* or octet-stream (some CDNs omit proper content-type)
            looks_like_img = ct.startswith("image/") or ct in (
                "application/octet-stream", "binary/octet-stream", ""
            )
            if not looks_like_img or len(r.content) < 2 * 1024:
                return None
            img = Image.open(io.BytesIO(r.content))
            w, h = img.size
            if w < 100 or h < 100:
                return None
            fmt = (img.format or "jpeg").lower()
            if fmt == "jpg":
                fmt = "jpeg"
            raw_name = img_url.split("/")[-1].split("?")[0] or f"img_{idx:04d}.{fmt}"
            raw_name = re.sub(r"[^\w.\-]", "_", raw_name)[:80]
            raw_content = r.content
    except Exception as e:
        job.setdefault("errors", []).append(f"{img_url}: {e}")
        return None

    # ── Phase 2: Classify (outside semaphore — Claude API calls don't block downloads)
    try:
        image_type = await classify_scraped_image(raw_content, img_url, raw_name)
        filter_map = {
            "photos":      "Photo",
            "floor_plans": "Floor Plan",
            "renders":     "3D Render",
            "diagrams":    "Diagram",
        }
        if image_type_filter != "all":
            if image_type != filter_map.get(image_type_filter, ""):
                return None
        img_id = str(uuid.uuid4())
        job["images_found"] = job.get("images_found", 0) + 1
        return {
            "meta": {
                "id": img_id, "url": img_url, "found_on_page": found_on,
                "width": w, "height": h, "format": fmt,
                "file_size_kb": round(len(raw_content) / 1024, 1),
                "image_type": image_type,
                "filename": f"{idx:04d}_{raw_name}",
            },
            "data": raw_content,
            "id": img_id,
        }
    except Exception as e:
        job.setdefault("errors", []).append(f"{img_url}: {e}")
        return None


async def _do_scrape(
    session_id: str,
    start_url: str,
    deep_crawl: bool,
    max_pages: int,
    image_type_filter: str,
    html_override: str = "",
) -> None:
    job = scrape_jobs[session_id]

    def log(msg: str) -> None:
        job.setdefault("log", []).append(msg)
        job["log"] = job["log"][-50:]
        print(f"[scrape:{session_id[:8]}] {msg}")

    try:
        parsed_base = urlparse(start_url)
        base_domain = parsed_base.netloc

        # ── Direct image URL ────────────────────────────────────────────────
        if looks_like_image_url(start_url):
            log("URL is a direct image — downloading it.")
            async with httpx.AsyncClient(
                timeout=30, verify=False, follow_redirects=True, headers=BROWSER_HEADERS
            ) as client:
                result = await _download_one(
                    client, start_url, start_url, 0,
                    asyncio.Semaphore(1), job, image_type_filter
                )
            images = [result["meta"]] if result else []
            if result:
                _write_img(session_id, result["id"], result["meta"].get("format", "jpeg"), result["data"])
            sessions[session_id] = {"images": images}
            job["images"] = images
            job["pages_crawled"] = 1
            job["status"] = "complete"
            log(f"Done. {len(images)} image(s) saved.")
            return

        # ── Direct PDF URL ──────────────────────────────────────────────────
        if start_url.lower().endswith(".pdf"):
            job["has_pdf_url"] = start_url
            job["status"] = "complete"
            sessions[session_id] = {"images": []}
            job["images"] = []
            log("URL is a PDF — switch to the Brochure Extractor tab.")
            return

        # ── Crawl pages ─────────────────────────────────────────────────────
        all_img_urls: dict[str, str] = {}   # img_url → found_on_page
        visited: set[str] = set()
        # html_override: skip HTTP entirely, parse pasted HTML directly
        queue: list[str] = [] if html_override else [start_url]
        pages_crawled = 0

        # Accumulated extra data
        all_documents: list[dict]       = []
        all_pricing_configs: list[dict] = []
        all_pricing_raw: list[str]      = []
        all_pricing_starting: str | None = None
        all_payment_plan: list[str]    = []
        all_youtube: list[dict]        = []
        seen_doc_urls: set[str]        = set()
        all_img_labels: dict[str, str]  = {}  # img_url → gallery label (for builder sites)
        seen_yt_ids: set[str]          = set()
        _seen_price_rows: set[str]     = set()

        async with httpx.AsyncClient(
            timeout=30, verify=False, follow_redirects=True, headers=BROWSER_HEADERS
        ) as client:
            while queue and pages_crawled < max_pages:
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                job["current_url"] = url
                log(f"Fetching page {pages_crawled + 1}/{max_pages}: {url}")

                try:
                    resp = await client.get(url)
                    # 403 retry with Referer
                    if resp.status_code == 403:
                        resp = await client.get(
                            url, headers={"Referer": f"https://{base_domain}/"}
                        )
                    if is_cloudflare_protected(resp):
                        log("⚠ Cloudflare protection detected — try a more specific URL.")
                        job.setdefault("errors", []).append(
                            f"Cloudflare protection on {url}"
                        )
                        pages_crawled += 1
                        job["pages_crawled"] = pages_crawled
                        continue
                    if resp.status_code != 200:
                        log(f"✗ HTTP {resp.status_code} on {url}")
                        pages_crawled += 1
                        job["pages_crawled"] = pages_crawled
                        continue

                    ct = resp.headers.get("content-type", "")
                    if "pdf" in ct:
                        job["has_pdf_url"] = url
                        log(f"Found PDF link: {url}")
                        pages_crawled += 1
                        job["pages_crawled"] = pages_crawled
                        continue
                    if ct.startswith("image/"):
                        all_img_urls.setdefault(url, url)
                        pages_crawled += 1
                        job["pages_crawled"] = pages_crawled
                        continue

                    soup = BeautifulSoup(resp.text, "lxml")
                    page_imgs = extract_image_urls(soup, resp.text, url)
                    new_count = sum(1 for u in page_imgs if u not in all_img_urls)
                    for u in page_imgs:
                        all_img_urls.setdefault(u, url)

                    # Fancybox/lightbox gallery labels for builder-site pages
                    # (uses <base href>-aware URL the same way extract_image_urls does)
                    page_labels = extract_fancybox_labels(soup, url)
                    all_img_labels.update(page_labels)
                    if page_labels:
                        log(f"  → {len(page_labels)} gallery labels extracted")

                    # Extract additional content
                    for doc in extract_documents(soup, url, resp.text):
                        if doc["url"] not in seen_doc_urls:
                            seen_doc_urls.add(doc["url"])
                            all_documents.append(doc)
                    page_pricing = extract_structured_pricing(soup)
                    for row in page_pricing["configs"]:
                        key = f"{row.get('type','')}|{row.get('area','')}|{row.get('price','')}"
                        if key not in _seen_price_rows:
                            _seen_price_rows.add(key)
                            all_pricing_configs.append(row)
                    for blk in page_pricing["raw_blocks"]:
                        if blk not in all_pricing_raw:
                            all_pricing_raw.append(blk)
                    if not all_pricing_starting and page_pricing["starting_price"]:
                        all_pricing_starting = page_pricing["starting_price"]
                    for blk in extract_payment_plan_blocks(soup):
                        if blk not in all_payment_plan:
                            all_payment_plan.append(blk)
                    for yt in extract_youtube_links(soup, resp.text):
                        if yt["video_id"] not in seen_yt_ids:
                            seen_yt_ids.add(yt["video_id"])
                            all_youtube.append(yt)

                    pages_crawled += 1
                    job["pages_crawled"] = pages_crawled
                    log(f"  → {new_count} new images | {len(all_documents)} docs | {len(all_youtube)} videos (total: {len(all_img_urls)} imgs)")

                    if deep_crawl and pages_crawled < max_pages:
                        links = extract_internal_links(soup, url, base_domain)
                        for lnk in links:
                            if lnk not in visited and lnk not in queue:
                                queue.append(lnk)

                except Exception as e:
                    log(f"✗ Error on {url}: {e}")
                    pages_crawled += 1
                    job["pages_crawled"] = pages_crawled

        # ── html_override: parse pasted HTML now that accumulators exist ───
        if html_override:
            log("Parsing pasted HTML (no HTTP request made)…")
            _soup = BeautifulSoup(html_override, "lxml")
            for u in extract_image_urls(_soup, html_override, start_url):
                all_img_urls.setdefault(u, start_url)
            all_img_labels.update(extract_fancybox_labels(_soup, start_url))
            for doc in extract_documents(_soup, start_url, html_override):
                if doc["url"] not in seen_doc_urls:
                    seen_doc_urls.add(doc["url"])
                    all_documents.append(doc)
            for blk in extract_payment_plan_blocks(_soup):
                if blk not in all_payment_plan:
                    all_payment_plan.append(blk)
            for yt in extract_youtube_links(_soup, html_override):
                if yt["video_id"] not in seen_yt_ids:
                    seen_yt_ids.add(yt["video_id"])
                    all_youtube.append(yt)
            pages_crawled = 1
            job["pages_crawled"] = 1
            log(f"  → {len(all_img_urls)} image URLs found in pasted HTML")

        if not all_img_urls:
            log("No image URLs found.")
            sessions[session_id] = {"images": []}
            job["images"] = []
            job["status"] = "complete"
            return

        # ── Download images concurrently (10 at a time) ─────────────────────
        # Semaphore only gates the HTTP download; Claude Vision runs outside it,
        # so higher concurrency here doesn't risk overwhelming the target server.
        log(f"Downloading {len(all_img_urls)} candidate images...")
        semaphore = asyncio.Semaphore(10)

        async with httpx.AsyncClient(
            timeout=15, verify=False, follow_redirects=True, headers=BROWSER_HEADERS
        ) as client:
            tasks = [
                _download_one(client, img_url, found_on, idx, semaphore, job, image_type_filter)
                for idx, (img_url, found_on) in enumerate(all_img_urls.items())
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        images: list[dict] = []
        for r in results:
            if r and not isinstance(r, Exception):
                meta = r["meta"]
                img_url = meta.get("url", "")
                if img_url in all_img_labels:
                    meta["image_type"] = all_img_labels[img_url]
                images.append(meta)
                _write_img(session_id, r["id"], meta.get("format", "jpeg"), r["data"])

        sessions[session_id] = {"images": images}
        job["images"] = images
        job["images_found"] = len(images)
        job["documents"] = all_documents
        job["pricing"] = {
            "configs": all_pricing_configs,
            "starting_price": all_pricing_starting,
            "raw_blocks": all_pricing_raw[:8],
        }
        job["payment_plan"] = all_payment_plan[:10]
        job["youtube_links"] = all_youtube
        job["status"] = "complete"
        log(f"✓ Done! {len(images)} images | {len(all_documents)} docs | {len(all_youtube)} videos from {pages_crawled} page(s).")

    except Exception as e:
        job["status"] = "error"
        job.setdefault("errors", []).append(str(e))
        log(f"✗ Fatal: {e}")
        sessions[session_id] = {"images": []}
        job["images"] = []


# ── Frontend ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    return HTML_PATH.read_text(encoding="utf-8")


# ── Upload endpoints ───────────────────────────────────────────────────────────

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...), session_id: str = Query(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
    pdf_bytes = await file.read()
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not open PDF: {e}")
    images = _extract_images_from_pdf(doc, session_id)
    doc.close()
    sessions[session_id] = {"images": images}
    return {"images": images, "total": len(images)}


@app.get("/image/{image_id}")
async def get_image(image_id: str, session_id: str = Query(...)):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    p = _img_file(session_id, image_id)
    if not p:
        raise HTTPException(status_code=404, detail="Image not found.")
    meta = next((m for m in session["images"] if m["id"] == image_id), None)
    fmt = meta["format"] if meta else "jpeg"
    return FileResponse(p, media_type=f"image/{fmt}")


@app.get("/download-all")
async def download_all(session_id: str = Query(...)):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    items = [
        (m["filename"], _read_img(session_id, m["id"]))
        for m in session["images"]
        if _img_file(session_id, m["id"])
    ]
    if not items:
        raise HTTPException(status_code=400, detail="No images to download.")
    return StreamingResponse(
        io.BytesIO(_build_zip(items)), media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=all_images.zip"},
    )


@app.get("/download-zip")
async def download_zip(session_id: str = Query(...), ids: str = Query(...)):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    id_set = set(ids.split(","))
    items = [
        (m["filename"], _read_img(session_id, m["id"]))
        for m in session["images"]
        if m["id"] in id_set and _img_file(session_id, m["id"])
    ]
    if not items:
        raise HTTPException(status_code=400, detail="No valid image IDs provided.")
    return StreamingResponse(
        io.BytesIO(_build_zip(items)), media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=filtered_images.zip"},
    )


class NamedImageItem(BaseModel):
    id: str
    filename: str   # client-supplied (possibly renamed)


class DownloadNamedRequest(BaseModel):
    session_id: str
    images: list[NamedImageItem]


@app.post("/download-zip-named")
async def download_zip_named(body: DownloadNamedRequest):
    """Download a zip of selected images with caller-supplied filenames (supports rename)."""
    session = sessions.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    items: list[tuple[str, bytes]] = []
    seen_names: dict[str, int] = {}
    for img in body.images:
        data = _read_img(body.session_id, img.id)
        if not data:
            continue
        name = img.filename.strip() or img.id
        # Deduplicate filenames by appending a counter
        if name in seen_names:
            seen_names[name] += 1
            base, _, ext = name.rpartition(".")
            name = f"{base}_{seen_names[name]}.{ext}" if ext else f"{name}_{seen_names[name]}"
        else:
            seen_names[name] = 0
        items.append((name, data))
    if not items:
        raise HTTPException(status_code=400, detail="No valid images found in session.")
    return StreamingResponse(
        io.BytesIO(_build_zip(items)), media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=selected_images.zip"},
    )


# ── CMS queue endpoints ────────────────────────────────────────────────────────

class CmsQueueItem(BaseModel):
    id: str
    session_id: str
    source: str           # CMS source dropdown text  e.g. "99 Acres", "Brochure"
    category: str         # primary type e.g. "Elevation"
    subtype: str = ""     # secondary type e.g. "Swimming Pool"
    filename: str
    image_reality: str = "Actual"   # "Actual" | "Artistic"
    title: str = ""       # defaults to category + subtype
    status_date: str = "" # construction status update date e.g. "November 2023"


class CmsPushRequest(BaseModel):
    items: list[CmsQueueItem]


@app.post("/cms-queue/push")
async def cms_queue_push(body: CmsPushRequest):
    global _cms_queue, _cms_pos
    _cms_queue = [item.dict() for item in body.items]
    _cms_pos = 0
    return {"queued": len(_cms_queue), "status": "ready"}


@app.get("/cms-queue/next")
async def cms_queue_next():
    if _cms_pos >= len(_cms_queue):
        return {"done": True, "remaining": 0, "total": len(_cms_queue)}
    item = _cms_queue[_cms_pos]
    return {
        "done": False,
        "index": _cms_pos,
        "total": len(_cms_queue),
        "remaining": len(_cms_queue) - _cms_pos,
        "item": item,
    }


@app.post("/cms-queue/done")
async def cms_queue_done():
    global _cms_pos
    _cms_pos = min(_cms_pos + 1, len(_cms_queue))
    return {
        "pos": _cms_pos,
        "remaining": max(0, len(_cms_queue) - _cms_pos),
        "all_done": _cms_pos >= len(_cms_queue),
    }


@app.post("/cms-queue/skip")
async def cms_queue_skip():
    """Skip current item without marking it done — advances same as /done."""
    return await cms_queue_done()


@app.get("/cms-queue/status")
async def cms_queue_status():
    return {
        "total": len(_cms_queue),
        "pos": _cms_pos,
        "remaining": max(0, len(_cms_queue) - _cms_pos),
        "all_done": _cms_pos >= len(_cms_queue),
        "items": _cms_queue,
    }


@app.post("/cms-queue/clear")
async def cms_queue_clear():
    global _cms_queue, _cms_pos
    _cms_queue = []
    _cms_pos = 0
    return {"cleared": True}


@app.post("/session/clear")
async def clear_session(body: dict):
    """Free RAM and disk for a session — called by the frontend on page unload."""
    sid = body.get("session_id", "")
    sessions.pop(sid, None)
    scrape_jobs.pop(sid, None)
    _clear_session_dir(sid)
    return {"ok": True}


@app.post("/debug-99acres-parse")
async def debug_99acres_parse(body: dict):
    """
    Dev endpoint: paste any 99acres HTML and see what the parser extracts.
    Returns next_data presence, tuples type map, and documents found.
    """
    html_str = body.get("html", "")
    if not html_str:
        raise HTTPException(400, "Provide 'html' field")

    soup = BeautifulSoup(html_str, "lxml")
    next_data = _parse_next_data(html_str)

    url_to_type: dict[str, str] = {}
    if next_data:
        url_to_type.update(_extract_tuples_type_map(next_data))

    _decoder = json.JSONDecoder()
    scripts_with_tuples = 0
    for script in soup.find_all("script"):
        content = script.string or ""
        if '"tuples"' not in content:
            continue
        scripts_with_tuples += 1
        try:
            data = json.loads(content)
            url_to_type.update(_extract_tuples_type_map(data))
            continue
        except Exception:
            pass
        for m in re.finditer(r'=\s*([\[\{])', content):
            pos = m.start(1)
            try:
                data, _ = _decoder.raw_decode(content, pos)
                if isinstance(data, (dict, list)):
                    url_to_type.update(_extract_tuples_type_map(data))
            except Exception:
                pass

    documents = _extract_a99_documents(next_data) if next_data else []

    # Sample: first 20 url→type pairs
    sample = {url[-80:]: t for url, t in list(url_to_type.items())[:20]}

    return {
        "next_data_found": bool(next_data),
        "next_data_size_chars": len(str(next_data)) if next_data else 0,
        "scripts_with_tuples_keyword": scripts_with_tuples,
        "url_type_total": len(url_to_type),
        "distinct_types": sorted(set(url_to_type.values())),
        "sample_url_type": sample,
        "documents": documents,
    }


# ── Brochure regex extraction (replaces Claude) ───────────────────────────────

_BHK_AREA_RE = re.compile(
    r'(\d)\s*BHK[^0-9]{0,40}?(\d[\d,]+)\s*(sq\.?\s*ft|sqft|sq\.?\s*m|sqmt)',
    re.I,
)
_POSSESS_RE = re.compile(
    r'(?:possession|ready\s+by|handover|delivery)[:\s]+([^\n,;.]{5,50})',
    re.I,
)
_UNITS_RE = re.compile(r'(\d[\d,]+)\s*(?:residential\s+)?units?', re.I)
_AREA_ACRES_RE = re.compile(r'(\d[\d.,]+)\s*acres?', re.I)
_SPEC_RE: dict[str, re.Pattern] = {
    k: re.compile(r'\b' + k + r'\b[:\s]+([^\n.;]{5,120})', re.I)
    for k in ("flooring", "kitchen", "doors?", "windows?", "toilets?",
              "walls?", "structure", "electrical")
}
_LOCATION_RE = re.compile(
    r'(?:\d+\s*(?:km|kms|minutes?|mins?)[^\n.]{5,100}|'
    r'(?:near|adjacent|opposite|close\s+to)[^\n.]{5,100})',
    re.I,
)


def _extract_brochure_regex(
    raw_text: str,
    project_name: str,
    builder_name: str,
    rera_id: str | None,
    configurations: list,
) -> dict:
    """
    Extract structured brochure data with regex only — no external API calls.
    Falls back to Housing.com API values (project_name, builder_name,
    configurations) when regex finds nothing.
    """
    text_lower = raw_text.lower()

    # RERA IDs
    rera_ids = list({m.group(1) for m in _RERA_RE.finditer(raw_text)}
                   | {m.group(1) for m in _RERA_EMBEDDED_RE.finditer(raw_text)})
    if not rera_ids and rera_id:
        rera_ids = [rera_id]

    # BHK configurations (only if API didn't supply them)
    if not configurations:
        seen_configs: set[str] = set()
        for m in _BHK_AREA_RE.finditer(raw_text):
            unit_type = f"{m.group(1)} BHK"
            area = m.group(2).replace(",", "")
            area_unit = "Sq.Ft" if "ft" in m.group(3).lower() else "Sq.Mt"
            key = f"{unit_type}|{area}"
            if key not in seen_configs:
                seen_configs.add(key)
                configurations.append({
                    "unit_type": unit_type,
                    "area": area,
                    "area_unit": area_unit,
                    "area_type": "Super Built-up",
                })

    # Amenities — match approved list against brochure text
    amenity_list = [a.strip() for a in APPROVED_AMENITIES.split(",") if a.strip()]
    amenities_found = [a for a in amenity_list if a.lower() in text_lower]

    # Specifications
    specs: dict = {"other": []}
    spec_key_map = {
        "flooring": "flooring", "kitchen": "kitchen", "doors?": "doors",
        "windows?": "windows", "toilets?": "toilets", "walls?": "walls",
        "structure": "structure", "electrical": "electrical",
    }
    for pattern_key, out_key in spec_key_map.items():
        m = _SPEC_RE[pattern_key].search(raw_text)
        if m:
            specs[out_key] = m.group(1).strip()

    # Location highlights
    highlights = []
    seen_h: set[str] = set()
    for m in _LOCATION_RE.finditer(raw_text):
        h = m.group(0).strip()
        if h not in seen_h:
            seen_h.add(h)
            highlights.append(h)

    # Possession date
    possession = None
    m = _POSSESS_RE.search(raw_text)
    if m:
        possession = m.group(1).strip()

    # Total units
    total_units = None
    m = _UNITS_RE.search(raw_text)
    if m:
        total_units = m.group(1).replace(",", "")

    # Total area
    total_area = None
    m = _AREA_ACRES_RE.search(raw_text)
    if m:
        total_area = f"{m.group(1)} acres"

    return {
        "project_name": project_name,
        "builder_name": builder_name,
        "rera_ids": rera_ids,
        "configurations": configurations,
        "amenities_found": amenities_found,
        "specifications": specs,
        "location_highlights": highlights[:10],
        "possession_date": possession,
        "total_units": total_units,
        "total_area": total_area,
    }


# ── Enrichment endpoints ───────────────────────────────────────────────────────

@app.post("/enrich")
async def enrich_project(body: EnrichRequest):
    project_id = body.project_id.strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")

    session_id = str(uuid.uuid4())
    api_url = (
        f"https://venus.housing.com/api/v7/new-projects/{project_id}/webapp"
        "?keys=id,name,status,inventory_configs"
    )
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(api_url, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        raw_json = r.json()
        api_data = raw_json.get("data", raw_json) if isinstance(raw_json.get("data"), dict) else raw_json
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=400, detail=f"Housing.com API error: HTTP {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch project: {e}")

    print(f"[enrich] project_id={project_id} keys={list(api_data.keys())[:20]}")

    project_name: str = api_data.get("name") or api_data.get("project_name") or "Unknown"
    status: str = api_data.get("status") or api_data.get("launch_status") or "Unknown"

    builder_name: str | None = None
    for key in ("developer", "builder", "developer_info", "builderInfo"):
        obj = api_data.get(key)
        if isinstance(obj, dict):
            builder_name = obj.get("name") or obj.get("display_name") or obj.get("developer_name")
            if builder_name:
                break

    rera_id = find_rera(api_data)
    brochure_url = find_brochure_url(api_data)

    configurations: list[dict] = []
    for cfg in api_data.get("inventory_configs", []):
        configurations.append({
            "bhk_type": cfg.get("bhk_type") or cfg.get("unit_type") or cfg.get("name"),
            "min_area": cfg.get("min_area") or cfg.get("area"),
            "max_area": cfg.get("max_area"),
            "area_type": cfg.get("area_type") or cfg.get("area_unit_type"),
        })

    images: list[dict] = []
    raw_text = ""
    brochure_error: str | None = None

    if brochure_url:
        try:
            async with httpx.AsyncClient(timeout=90, verify=False, follow_redirects=True) as client:
                pdf_resp = await client.get(brochure_url, headers={"User-Agent": "Mozilla/5.0"})
            pdf_bytes = pdf_resp.content
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            images = _extract_images_from_pdf(doc, session_id, min_w=100, min_h=100)
            doc.close()
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                parts = [p.extract_text() for p in pdf.pages if p.extract_text()]
                raw_text = "\n\n".join(parts)
            if not raw_text.strip():
                print("[enrich] no selectable text — running OCR")
                raw_text = ocr_pdf(pdf_bytes)
                print(f"[enrich] OCR extracted {len(raw_text)} chars")
        except Exception as e:
            brochure_error = str(e)
            print(f"[enrich] brochure error: {e}")

    extracted = _extract_brochure_regex(
        raw_text, project_name, builder_name, rera_id, configurations
    ) if raw_text else {
        "project_name": project_name, "builder_name": builder_name,
        "rera_ids": ([rera_id] if rera_id else []),
        "configurations": configurations, "amenities_found": [],
        "specifications": {}, "location_highlights": [],
        "possession_date": None, "total_units": None, "total_area": None,
    }

    sessions[session_id] = {"images": images}
    return {
        "session_id": session_id,
        "project_id": api_data.get("id", project_id),
        "project_name": extracted["project_name"],
        "builder_name": extracted["builder_name"],
        "status": status,
        "rera_ids": extracted["rera_ids"],
        "brochure_url": brochure_url,
        "brochure_error": brochure_error,
        "configurations": extracted["configurations"],
        "amenities_found": extracted["amenities_found"],
        "specifications": extracted["specifications"],
        "location_highlights": extracted["location_highlights"],
        "possession_date": extracted["possession_date"],
        "total_units": extracted["total_units"],
        "total_area": extracted["total_area"],
        "images": images,
        "api_raw": api_data,
    }


@app.get("/image/{session_id}/{image_id}")
async def get_enrich_image(session_id: str, image_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    p = _img_file(session_id, image_id)
    if not p:
        raise HTTPException(status_code=404, detail="Image not found.")
    meta = next((m for m in session["images"] if m["id"] == image_id), None)
    fmt = meta["format"] if meta else "jpeg"
    return FileResponse(p, media_type=f"image/{fmt}")


@app.get("/download-zip/{session_id}")
async def download_enrich_zip(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    items = [
        (m["filename"], _read_img(session_id, m["id"]))
        for m in session["images"]
        if _img_file(session_id, m["id"])
    ]
    if not items:
        raise HTTPException(status_code=400, detail="No images to download.")
    return StreamingResponse(
        io.BytesIO(_build_zip(items)), media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=brochure_images.zip"},
    )


# ── PDF Crop Tool endpoint ─────────────────────────────────────────────────────

@app.post("/upload-crop")
async def upload_crop(req: Request):
    data = await req.json()
    session_id = data.get("session_id") or str(uuid.uuid4())
    b64_data   = data.get("image_data", "")
    image_type = data.get("image_type", "Other")
    page       = int(data.get("page", 1))
    width      = int(data.get("width", 0))
    height     = int(data.get("height", 0))

    if not b64_data:
        raise HTTPException(status_code=400, detail="image_data is required")

    # Strip the data URL header (e.g. "data:image/jpeg;base64,")
    if "," in b64_data:
        b64_data = b64_data.split(",", 1)[1]
    img_bytes = base64.b64decode(b64_data)

    if session_id not in sessions:
        sessions[session_id] = {"images": []}

    img_id = f"crop_{uuid.uuid4().hex[:10]}"
    sessions[session_id]["images"].append({
        "id":         img_id,
        "filename":   f"crop_page{page}_{img_id}.jpg",
        "type":       image_type,
        "format":     "jpeg",
        "source":     "crop",
        "page":       page,
        "width":      width,
        "height":     height,
    })
    _write_img(session_id, img_id, "jpeg", img_bytes)   # bytes to disk, not RAM

    return {"session_id": session_id, "image_id": img_id}


# ── Website scraper endpoints ──────────────────────────────────────────────────

@app.post("/scrape-website")
async def scrape_website(body: ScrapeRequest, background_tasks: BackgroundTasks):
    if not body.url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    max_pages = max(1, min(body.max_pages, 20))
    session_id = str(uuid.uuid4())

    scrape_jobs[session_id] = {
        "status": "running",
        "pages_crawled": 0,
        "images_found": 0,
        "current_url": body.url,
        "log": [],
        "errors": [],
        "images": [],
        "documents": [],
        "pricing": {"configs": [], "starting_price": None, "raw_blocks": []},
        "payment_plan": [],
        "youtube_links": [],
        "has_pdf_url": None,
    }
    sessions[session_id] = {"images": []}

    background_tasks.add_task(
        _do_scrape, session_id, body.url,
        body.deep_crawl, max_pages, body.image_type_filter, body.html_override
    )
    return {"session_id": session_id, "status": "running"}


@app.get("/scrape-status/{session_id}")
async def scrape_status(session_id: str):
    job = scrape_jobs.get(session_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scrape job not found.")
    is_done = job["status"] == "complete"
    return {
        "status": job["status"],
        "pages_crawled": job.get("pages_crawled", 0),
        "images_found": job.get("images_found", 0),
        "current_url": job.get("current_url", ""),
        "log": job.get("log", [])[-10:],
        "images":       job.get("images", [])       if is_done else [],
        "documents":    job.get("documents", [])    if is_done else [],
        "pricing":      job.get("pricing", [])      if is_done else [],
        "payment_plan": job.get("payment_plan", []) if is_done else [],
        "youtube_links":job.get("youtube_links", [])if is_done else [],
        "errors": job.get("errors", []),
        "has_pdf_url": job.get("has_pdf_url"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  99ACRES SCRAPER
# ═══════════════════════════════════════════════════════════════════════════════

ACRES99_USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

# Matching Sec-Ch-Ua strings for each UA above
_ACRES99_CH_UA: list[str] = [
    '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    '"Chromium";v="123", "Microsoft Edge";v="123", "Not-A.Brand";v="8"',
    '',  # Safari doesn't send Sec-Ch-Ua
]

_NPXID_RE      = re.compile(r'npxid-([A-Za-z0-9]+)', re.I)
_NEXT_DATA_RE  = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.S
)
_INIT_STATE_RE = re.compile(
    r'window\.__(?:INITIAL_STATE|STATE|REDUX_STATE)__\s*=\s*(\{.{100,}?\});', re.S
)
# RERA preceded by keyword: "RERA: XXXX", "RERA# XXXX", "RERA-XXXX"
_RERA_RE = re.compile(r'\bRERA[:\s#-]*([A-Z0-9/\-]{8,35})\b', re.I)
# State-prefixed RERA IDs — only known 2-letter Indian state/UT codes before RERA
# e.g. UPRERAPRJ123456, HRERA-PKL-..., MAHARERA/..., DLRERA2017X000123
_RERA_EMBEDDED_RE = re.compile(
    r'\b((?:UP|HR|MH|KA|TN|TS|GJ|RJ|MP|KL|AP|WB|OD|PB|CG|UK|DL|JH|AS|HP|GA|JK|AN|PY|CH)'
    r'RERA[A-Z0-9/\-]{5,30})\b',
    re.I,
)

# Ordered image category keywords — checked first-match wins
_A99_CAT_KW: list[tuple[str, list[str]]] = [
    ("Floor Plan",            ["floorplan", "floor_plan", "floor-plan", "unit_plan",
                               "/fp/", "-fp-", "fp_", "bhk-plan", "unit-plan", "layout"]),
    ("Render / Elevation",    ["render", "elevation", "exterior", "aerial", "facade",
                               "front-view", "frontview", "birdseye", "bird-eye"]),
    ("Construction Progress", ["construction", "progress", "update_", "on-site", "site-photo"]),
    ("Amenity Photo",         ["amenity", "gym-", "-gym", "swimming", "pool", "clubhouse",
                               "garden", "park", "playground", "sports", "fitness"]),
    ("Interior Photo",        ["interior", "bedroom", "kitchen", "living-room", "bathroom",
                               "drawing-room", "model-flat", "furnished"]),
    ("Location Map",          ["location-map", "locationmap", "connectivity", "distance",
                               "nearby", "area-map", "vicinity"]),
]

# ── 99acres tuples-type → internal classification ─────────────────────────────
# 99acres embeds {"tuples":[{"name":"<Type>", ...images...}]} in __NEXT_DATA__
# and inline scripts.  These are the canonical type names we've seen in the wild.
_A99_TUPLES_TYPE_TO_CLASS: dict[str, str] = {
    # Photos / Elevation
    "photos":                "Photos",
    "photo":                 "Photos",
    "exterior":              "Photos",
    "exterior photos":       "Photos",
    "elevation":             "Elevation",
    "elevations":            "Elevation",
    # Floor / Unit plans
    "floor plan":            "Floor Plan",
    "floor plans":           "Floor Plan",
    "floorplan":             "Floor Plan",
    "unit plan":             "Floor Plan",
    "unit plans":            "Floor Plan",
    # Master / Cluster / Site Plan
    "master plan":           "Master Plan",
    "masterplan":            "Master Plan",
    "cluster plan":          "Cluster Plan",
    "site plan":             "Site Plan",
    "site map":              "Site Plan",
    # Location
    "location map":          "Location Map",
    "location plan":         "Location Map",
    "location":              "Location Map",
    "connectivity":          "Location Map",
    # Amenities
    "amenities":             "Amenities",
    "amenity":               "Amenities",
    "facilities":            "Amenities",
    # Construction
    "construction status":   "Construction Status",
    "construction progress": "Construction Status",
    "construction update":   "Construction Status",
    "construction":          "Construction Status",
    # Aerial / Top view
    "aerial view":           "Aerial View",
    "aerial":                "Aerial View",
    "aerial photos":         "Aerial View",
    "top view":              "Aerial View",
    "drone view":            "Aerial View",
    # Interior
    "interior":              "Interior",
    "interiors":             "Interior",
    "interior photos":       "Interior",
    "model flat":            "Interior",
    # 3D Renders
    "3d render":             "3D Render",
    "3d renders":            "3D Render",
    "3d view":               "3D Render",
    "renders":               "3D Render",
    "render":                "3D Render",
}


def _a99_tuples_classify(raw_type: str) -> str:
    """Map a raw 99acres tuples type name to our classification label.
    Falls back to Title-cased raw name if not in the lookup."""
    return _A99_TUPLES_TYPE_TO_CLASS.get(raw_type.lower().strip(), raw_type.strip())


def _extract_tuples_type_map(
    obj: Any,
    url_to_date: "dict[str, str] | None" = None,
) -> dict[str, str]:
    """
    Walk JSON for 99acres gallery structures:

      Array of:  {"tuples": [{"name": "<type>", "variants": {"ORIGINAL": "<url>", ...}}],
                  "date": "November 2023", "type": "OUTDOORS"}

    The "name" field on each individual tuple item is the image type.
    If url_to_date is provided, also fills it with {url: date_string} for
    construction-status images — the date lives at the parent node of "tuples".

    Returns {url: raw_type_name}.
    """
    url_to_type: dict[str, str] = {}

    def _register(url: str, type_name: str, date: str) -> None:
        if not url or not isinstance(url, str):
            return
        url_to_type.setdefault(url, type_name)
        ck = _canonical_a99_key(url)
        if ck:
            url_to_type.setdefault(ck, type_name)
        if url_to_date is not None and date:
            url_to_date.setdefault(url, date)
            if ck:
                url_to_date.setdefault(ck, date)

    def _get_date(d: dict) -> str:
        """Return a date string from a dict's top-level keys, or ''."""
        for k, v in d.items():
            if k.lower() in _CONSTR_DATE_KEYS and isinstance(v, str) and v.strip():
                return v.strip()
        # Also try separate month + year
        month = d.get("month") or d.get("statusMonth") or ""
        year  = d.get("year")  or d.get("statusYear")  or ""
        if month and year:
            return f"{month} {year}"
        return ""

    def _process_tuple(tup: dict, type_name: str, parent_date: str) -> None:
        """Map every variant URL of a single tuple item to its type (and date)."""
        # Date can also live inside the tuple item itself
        date = _get_date(tup) or parent_date
        variants = tup.get("variants")
        if isinstance(variants, dict):
            # Register ORIGINAL first so it wins for the canonical key
            _register(variants.get("ORIGINAL", ""), type_name, date)
            for url in variants.values():
                _register(url, type_name, date)
        else:
            # Fallback: any string value that looks like an image URL
            for v in tup.values():
                if isinstance(v, str):
                    _register(v, type_name, date)

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            tuples_val = node.get("tuples")
            if isinstance(tuples_val, list):
                # Date at the parent level (same dict that has "tuples")
                parent_date = _get_date(node) if url_to_date is not None else ""
                for tup in tuples_val:
                    if isinstance(tup, dict):
                        name = (tup.get("name") or "").strip()
                        if name:
                            _process_tuple(tup, name, parent_date)
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(obj)
    return url_to_type


# ── Document keys the 99acres JSON may carry ──────────────────────────────────
_A99_DOCUMENT_KEYS: dict[str, str] = {
    "brochureDocument": "Brochure",
    "priceListDocument": "Payment Plan",
    "floorPlanDocument": "Floor Plan",
    "masterPlanDocument": "Master Plan",
}


def _extract_a99_documents(obj: Any) -> list[dict]:
    """
    Walk JSON for document structures like:
      "brochureDocument": {"name": "Brochure", "variants": {"ORIGINAL": "<url>.pdf"}}
      "priceListDocument": {"name": "Payment Plan", "variants": {"ORIGINAL": "<url>.pdf"}}

    Only returns entries whose URL ends in .pdf — never images.
    Returns a list of {"name": <label>, "url": <original_url>} dicts.
    """
    docs: list[dict] = []
    seen: set[str] = set()

    def _try_doc(label: str, node: Any) -> None:
        if not isinstance(node, dict):
            return
        name = node.get("name") or label
        variants = node.get("variants") or {}
        url = ""
        if isinstance(variants, dict):
            # Always prefer ORIGINAL; fall back to first value
            url = (variants.get("ORIGINAL") or variants.get("original")
                   or next(iter(variants.values()), ""))
        if not url:
            url = node.get("url") or node.get("link") or ""
        # Only accept PDF URLs
        if url and url.lower().endswith(".pdf") and url not in seen:
            seen.add(url)
            docs.append({"name": name, "url": url})

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key in _A99_DOCUMENT_KEYS:
                    _try_doc(_A99_DOCUMENT_KEYS[key], val)
            for val in node.values():
                _walk(val)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(obj)
    return docs


# ── Date fields used by 99acres for construction status updates ────────────────
_CONSTR_DATE_KEYS: frozenset[str] = frozenset({
    "date", "statusdate", "statuson", "updatedon",
    "photographydate", "statusmonth", "createddate",
})


def _extract_a99_construction_dates(obj: Any) -> dict[str, str]:
    """
    Walk JSON for date-grouped construction status sections.

    99acres wraps each construction-update group in a dict like:
      {"date": "November 2023", "tuples": [...images...]}
    or
      {"statusDate": "15 Nov, 2023", "images": {"tuples": [...]}}
    or separate month/year keys.

    For every such group we register all image URLs (raw + canonical) →
    the date string.  Returns {url: date_string}.
    """
    url_to_date: dict[str, str] = {}

    def _reg(url: str, date: str) -> None:
        if url and isinstance(url, str):
            url_to_date.setdefault(url, date)
            ck = _canonical_a99_key(url)
            if ck:
                url_to_date.setdefault(ck, date)

    def _collect_image_urls(node: Any, out: list) -> None:
        """Collect every image URL found in variants dicts."""
        if isinstance(node, dict):
            variants = node.get("variants")
            if isinstance(variants, dict):
                for v in variants.values():
                    if isinstance(v, str) and v:
                        out.append(v)
            for v in node.values():
                _collect_image_urls(v, out)
        elif isinstance(node, list):
            for item in node:
                _collect_image_urls(item, out)

    def _date_from_dict(d: dict) -> str:
        """Return the first date-like string value found in d's keys."""
        for k, v in d.items():
            if k.lower() in _CONSTR_DATE_KEYS:
                if isinstance(v, str) and v.strip():
                    return v.strip()
                if isinstance(v, (int, float)):
                    return str(int(v))
        # Fallback: separate month + year keys
        month = d.get("month") or d.get("statusMonth") or ""
        year  = d.get("year")  or d.get("statusYear")  or ""
        if month and year:
            return f"{month} {year}"
        return ""

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            date = _date_from_dict(node)
            if date:
                # This node is a date-labelled group — map all its image URLs
                urls: list = []
                _collect_image_urls(node, urls)
                for url in urls:
                    _reg(url, date)
            # Always keep recursing (inner nodes may have their own dates)
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(obj)
    return url_to_date


# In-memory store for 99acres jobs
acres99_jobs: dict = {}


class ScrapeNinetyNineAcresRequest(BaseModel):
    url: str
    html_source: str | None = None   # manual HTML paste fallback


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_npxid(url: str) -> str | None:
    m = _NPXID_RE.search(url)
    return m.group(1) if m else None


def _parse_next_data(html_str: str) -> dict:
    """Extract __NEXT_DATA__ or window.__INITIAL_STATE__ from page HTML."""
    m = _NEXT_DATA_RE.search(html_str)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    m = _INIT_STATE_RE.search(html_str)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return {}


def _collect_from_json(
    obj: object,
    img_urls: list[str],
    vid_ids: set[str],
    depth: int = 0,
) -> None:
    """Recursively walk JSON and collect image URLs + YouTube video IDs."""
    if depth > 15:
        return
    if isinstance(obj, str) and len(obj) > 10:
        if re.search(r'\.(?:jpg|jpeg|png|webp|avif)(?:\?|$)', obj, re.I):
            img_urls.append(obj)
        m = _YT_RE.search(obj)
        if m:
            vid_ids.add(m.group(1))
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_from_json(v, img_urls, vid_ids, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _collect_from_json(item, img_urls, vid_ids, depth + 1)


def _extract_rera_ids(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    # Pattern 1: preceded by "RERA" keyword (e.g. "RERA: XXXX", "RERA# XXXX")
    for m in _RERA_RE.finditer(text):
        rid = m.group(1).strip().rstrip(".,;\"'")
        if rid and rid not in seen and 8 <= len(rid) <= 35:
            seen.add(rid)
            result.append(rid)
    # Pattern 2: state-prefixed RERA IDs (e.g. UPRERAPRJ123456, HRERA-PKL-...)
    for m in _RERA_EMBEDDED_RE.finditer(text):
        rid = m.group(1).strip()
        if rid and rid not in seen and 10 <= len(rid) <= 40:
            seen.add(rid)
            result.append(rid)
    return result


# 99acres CDN image size suffix patterns:
#   _O / _optOrig = original quality
#   _large / _med / _sm = standard CDN sizes
#   _small/_medium/_thumb/etc. = legacy names
_A99_SIZE_SUFFIX_RE = re.compile(
    r'_(O|optOrig|large|med|sm|small|medium|thumb|xs|sq|thumbnail|mini|preview)'
    r'(\.(jpe?g|png|webp|avif|gif))$',
    re.I,
)
_A99_SIZE_RANK: dict[str, int] = {
    'o': 0, 'optorig': 1, 'large': 2, 'med': 3, 'sm': 4,
    'small': 4, 'medium': 3, 'thumb': 5, 'xs': 5, 'sq': 5,
    'thumbnail': 5, 'mini': 5, 'preview': 5, 'mobile': 6,
}

_A99_MOBILE_RE = re.compile(r'[/_-]mobile[/_.]', re.I)


def _a99_size_rank(url: str) -> int:
    """Return quality rank for a 99acres CDN image URL (lower = better quality)."""
    m = _A99_SIZE_SUFFIX_RE.search(urlparse(url).path)
    if m:
        return _A99_SIZE_RANK.get(m.group(1).lower(), 5)
    return 1  # no recognised suffix → treat as near-original


def _canonical_a99_key(url: str) -> str:
    """
    Strip the size suffix from a 99acres CDN URL to get a canonical group key.
    URLs that differ only by size suffix (e.g. _large vs _sm vs _O) map to the
    same key so that per-group best-quality selection can deduplicate them.
    """
    try:
        parsed = urlparse(url)
        if parsed.netloc not in ('newprojects.99acres.com', 'imagecdn.99acres.com'):
            return url.split('?')[0]
        # Strip size suffix, keeping only the extension
        path = _A99_SIZE_SUFFIX_RE.sub(r'\2', parsed.path)
        return parsed._replace(path=path, query='').geturl()
    except Exception:
        return url.split('?')[0]


def _get_project_cdn_path(img_urls: list[str]) -> str | None:
    """
    Derive the CDN project path prefix (e.g. 'tulip_infratech/tulip_crimson')
    from a list of 99acres CDN image URLs.  Uses JSON-LD images as input since
    they are the most reliable source for the current project.
    """
    for url in img_urls:
        m = re.search(
            r'(?:newprojects|imagecdn)\.99acres\.com/projects/([^/?#]+/[^/?#]+)/',
            url,
        )
        if m:
            return m.group(1)
    return None


def _is_project_image(url: str, project_cdn_path: str | None) -> bool:
    """
    Return True only if `url` is an image that belongs to this project.
    Rejects YouTube thumbnails, 99acres UI assets, and images from other
    projects on the same page (e.g. "Similar Projects" section).
    """
    # YouTube thumbnails (used for video previews, not project photos)
    if 'img.youtube.com' in url or 'ytimg.com' in url:
        return False
    # Mobile-optimised variants (low-res, not useful alongside desktop sizes)
    if _A99_MOBILE_RE.search(url):
        return False
    # 99acres branding / universal UI assets
    if re.search(r'(?:static|cdn)\.99acres\.com/universal', url, re.I):
        return False
    if 'newprojects.99acres.com/media/' in url:
        return False
    # If we know the project CDN path, enforce it for 99acres CDN domains
    if project_cdn_path:
        if re.search(r'(?:newprojects|imagecdn)\.99acres\.com', url):
            return f'/projects/{project_cdn_path}/' in url
    return True


def _find_json_values(obj: object, keys: set, depth: int = 0) -> dict:
    """
    Walk nested JSON and return first value found for each target key.
    Key matching is case-insensitive.
    """
    if depth > 20:
        return {}
    results: dict = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            for tk in keys:
                if kl == tk and tk not in results and v not in (None, "", [], {}):
                    results[tk] = v
            if len(results) < len(keys):
                sub = _find_json_values(v, keys - set(results), depth + 1)
                results.update(sub)
    elif isinstance(obj, list):
        for item in obj:
            if len(results) >= len(keys):
                break
            sub = _find_json_values(item, keys - set(results), depth + 1)
            results.update(sub)
    return results


def _clean(val: object) -> str | None:
    """Return stripped string or None for blank/null-like values."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("null", "none", "undefined", "n/a", "-") else None


def _format_inr(amount: object) -> str | None:
    """Convert a raw INR integer/float to human-readable Lac/Cr string."""
    try:
        v = float(str(amount).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v >= 1e7:        # ≥ 1 Crore
        s = f"{v / 1e7:.2f}".rstrip("0").rstrip(".")
        return f"₹{s} Cr"
    if v >= 1e5:        # ≥ 1 Lakh
        s = f"{v / 1e5:.2f}".rstrip("0").rstrip(".")
        return f"₹{s} Lac"
    return f"₹{int(v):,}"


_DATE_RE = re.compile(
    r'\b(Q[1-4][\s\-]\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,\-]\s*\d{4}|\d{4})\b',
    re.I,
)
_UNITS_RE  = re.compile(r'\b(\d[\d,]*)\s*(?:units?|apartments?|flats?|villas?|plots?)\b', re.I)
_TOWERS_RE = re.compile(r'\b(\d+)\s*(?:towers?|blocks?)\b', re.I)
_FLOORS_RE = re.compile(r'\b(?:G\+\s*)?(\d+)\s*(?:storey|stor(?:e)?y|floors?)\b', re.I)
_AREA_ACRES_RE = re.compile(r'\b([\d.]+)\s*acres?\b', re.I)


def _parse_a99_config(c: dict) -> dict | None:
    """
    Parse one config item from various 99acres __NEXT_DATA__ structures.
    Field names vary wildly across 99acres API versions.
    """
    # Unit type / BHK
    unit_raw = (
        c.get("bedrooms") or c.get("bhk") or c.get("unitType") or c.get("unit_type")
        or c.get("bhkType") or c.get("bhk_type") or c.get("configType")
        or c.get("apartmentType") or c.get("type") or c.get("bedroomCount") or ""
    )
    unit = _clean(str(unit_raw)) if unit_raw else None
    if unit and unit.isdigit():
        unit = f"{unit} BHK"
    elif unit and re.match(r'^\d+$', unit.replace(" ", "")):
        unit = f"{unit} BHK"

    # Area — prefer carpet, then super built-up, then generic
    carpet   = _clean(str(c.get("carpetArea") or c.get("carpet_area") or c.get("carpetAreaSqft") or ""))
    sba      = _clean(str(c.get("superBuiltupArea") or c.get("super_builtup_area") or c.get("superBuiltupAreaSqft") or ""))
    builtup  = _clean(str(c.get("builtupArea") or c.get("builtup_area") or ""))
    area_gen = _clean(str(c.get("area") or c.get("minArea") or c.get("maxArea") or ""))

    if carpet:
        area, area_type = carpet, "CA"
    elif sba:
        area, area_type = sba, "SBA"
    elif builtup:
        area, area_type = builtup, "BA"
    else:
        area = area_gen
        area_type = _clean(str(c.get("areaType") or c.get("area_type") or "?")) or "?"

    # Price
    price_raw = (
        c.get("minPrice") or c.get("min_price") or c.get("price")
        or c.get("priceRange") or c.get("basePrice") or c.get("startingPrice") or ""
    )
    price: str | None = None
    if price_raw:
        price = _format_inr(price_raw)
        if not price:
            price = _clean(str(price_raw))

    if not unit and not area:
        return None

    return {
        "unit_type": unit or "?",
        "area": area or "?",
        "area_type": area_type,
        "price": price,
    }


def _extract_a99_project_dom(
    soup: BeautifulSoup,
    next_data: dict,
    raw_text: str,
    page_url: str,
    rera_ids: list[str],
) -> dict:
    """
    Extract all project overview data from DOM + __NEXT_DATA__ + regex.
    No Claude — pure structural extraction.
    """
    proj: dict = {
        "project_name": None,
        "developer_name": None,
        "location": {},
        "rera_ids": [{"number": r, "state": None, "tower_phase": None} for r in rera_ids],
        "project_details": {
            "total_units": None, "total_towers": None, "total_floors": None,
            "total_area_acres": None, "possession_date": None, "launch_date": None,
            "project_status": None, "open_area_percent": None,
            "price_min": None, "price_max": None,
        },
        "about_project": None,
        "about_developer": None,
    }

    # ── 0. JSON-LD schema.org tags in <head> (always present in static HTML) ──
    rera_seen: set[str] = {r["number"] for r in proj["rera_ids"]}

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            jld = json.loads(script.string or "")
            if not isinstance(jld, dict):
                continue
            st = jld.get("@type", "")

            if st == "Product":
                if not proj["project_name"]:
                    proj["project_name"] = _clean(jld.get("name"))
                # Description from Product is a marketing blurb — use as about_project
                if not proj["about_project"]:
                    desc = _clean(jld.get("description"))
                    if desc and len(desc) > 30:
                        proj["about_project"] = desc[:600].rsplit(" ", 1)[0] + "…" if len(desc) > 600 else desc
                brand = jld.get("brand") or {}
                if isinstance(brand, dict):
                    if not proj["developer_name"]:
                        proj["developer_name"] = _clean(brand.get("name"))
                    if not proj["about_developer"]:
                        bdesc = _clean(brand.get("description", ""))
                        proj["about_developer"] = bdesc[:400].rsplit(" ", 1)[0] + "…" if bdesc and len(bdesc) > 400 else bdesc
                # Price range from offers
                offers = jld.get("offers") or {}
                if isinstance(offers, dict):
                    pd = proj["project_details"]
                    low  = offers.get("lowPrice")
                    high = offers.get("highPrice")
                    if low and not pd.get("price_min"):
                        pd["price_min"] = _format_inr(low)
                    if high and not pd.get("price_max"):
                        pd["price_max"] = _format_inr(high)

                # additionalProperty / identifier — 99acres often stores RERA here
                for prop_key in ("additionalProperty", "identifier"):
                    for prop in (jld.get(prop_key) or []):
                        if not isinstance(prop, dict):
                            continue
                        pname = (prop.get("name") or prop.get("propertyID") or "").lower()
                        pval  = _clean(str(prop.get("value", "")))
                        if not pval:
                            continue
                        if "rera" in pname:
                            for r in _extract_rera_ids(pval) or [pval]:
                                if r and r not in rera_seen and len(r) >= 6:
                                    rera_seen.add(r)
                                    proj["rera_ids"].append({"number": r, "state": None, "tower_phase": None})
                        elif any(k in pname for k in ("unit", "total", "status", "possession")):
                            pd = proj["project_details"]
                            if "unit" in pname and not pd.get("total_units"):
                                pd["total_units"] = pval
                            elif "tower" in pname and not pd.get("total_towers"):
                                pd["total_towers"] = pval
                            elif "possession" in pname and not pd.get("possession_date"):
                                pd["possession_date"] = pval
                            elif "status" in pname and not pd.get("project_status"):
                                pd["project_status"] = pval

            elif st == "Residence":
                addr = jld.get("address") or {}
                if isinstance(addr, dict):
                    loc = proj["location"]
                    if not loc.get("sector"):
                        loc["sector"] = _clean(addr.get("addressLocality"))
                    if not loc.get("state"):
                        loc["state"] = _clean(addr.get("addressRegion"))
                    if not loc.get("full_address"):
                        loc["full_address"] = _clean(addr.get("streetAddress"))
                    if not loc.get("city"):
                        loc["city"] = _clean(addr.get("addressRegion"))

            elif st == "BreadcrumbList":
                # Extract locality/city from breadcrumb
                items = jld.get("itemListElement") or []
                for item in items:
                    name = _clean((item.get("item") or {}).get("name", "") or item.get("name", ""))
                    if name and "noida" in name.lower():
                        proj["location"].setdefault("city", name)
                    if name and "sector" in name.lower():
                        proj["location"].setdefault("sector", name)

        except Exception:
            pass

    # ── 1. Walk __NEXT_DATA__ for known keys ──────────────────────────────────
    nd: dict = {}   # populated inside the block below, referenced later for specs
    if next_data:
        nd = _find_json_values(next_data, {
            "projectname", "name", "developername", "buildername", "buildergroupname",
            "localityname", "cityname", "sectorname", "statename", "address", "fulladdress",
            "totalunits", "totalfloors", "totaltowers", "projectarea", "totalarea",
            "possessiondate", "expectedpossession", "launchdate",
            "projectstatus", "constructionstatus", "status",
            "description", "projectdescription", "about", "overview",
            "developerdescription", "builderdescription",
            # RERA — expanded variants
            "reraid", "reranumber", "reraregistration", "reraregistrationno",
            "reraregno", "reraids", "reradetails", "reraregistrations",
            "projectreraid", "reraapprovalno", "rno",
            # Prices
            "minprice", "maxprice", "pricerange", "startingprice", "baseprice",
            "pricemin", "pricemax", "lowestprice",
        })

        # Project name — prefer "projectname" over generic "name"
        if not proj["project_name"]:
            proj["project_name"] = _clean(nd.get("projectname") or nd.get("name"))
        if not proj["developer_name"]:
            proj["developer_name"] = _clean(
                nd.get("developername") or nd.get("buildername") or nd.get("buildergroupname")
            )

        # Location
        loc = proj["location"]
        if not loc.get("sector"):
            loc["sector"] = _clean(nd.get("localityname") or nd.get("sectorname"))
        if not loc.get("city"):
            loc["city"]   = _clean(nd.get("cityname"))
        if not loc.get("state"):
            loc["state"]  = _clean(nd.get("statename"))
        if not loc.get("full_address"):
            addr = _clean(nd.get("fulladdress") or nd.get("address"))
            if addr:
                loc["full_address"] = addr

        # Project details
        pd = proj["project_details"]
        if not pd["total_units"]:
            pd["total_units"]      = _clean(nd.get("totalunits"))
        if not pd["total_towers"]:
            pd["total_towers"]     = _clean(nd.get("totaltowers"))
        if not pd["total_floors"]:
            pd["total_floors"]     = _clean(nd.get("totalfloors"))
        if not pd["total_area_acres"]:
            pd["total_area_acres"] = _clean(nd.get("projectarea") or nd.get("totalarea"))
        if not pd["possession_date"]:
            pd["possession_date"]  = _clean(nd.get("possessiondate") or nd.get("expectedpossession"))
        if not pd["launch_date"]:
            pd["launch_date"]      = _clean(nd.get("launchdate"))
        if not pd["project_status"]:
            pd["project_status"]   = _clean(
                nd.get("projectstatus") or nd.get("constructionstatus") or nd.get("status")
            )

        # About
        if not proj["about_project"]:
            proj["about_project"]  = _clean(
                nd.get("projectdescription") or nd.get("description") or
                nd.get("about") or nd.get("overview")
            )
        if not proj["about_developer"]:
            proj["about_developer"] = _clean(
                nd.get("developerdescription") or nd.get("builderdescription")
            )

        # RERA from __NEXT_DATA__
        rera_raw = (
            nd.get("reraid") or nd.get("reranumber") or nd.get("reraregistration")
            or nd.get("reraregistrationno") or nd.get("reraregno")
            or nd.get("reraids") or nd.get("reradetails") or nd.get("reraregistrations")
            or nd.get("rno")
        )
        if rera_raw:
            items = rera_raw if isinstance(rera_raw, list) else [rera_raw]
            for item in items:
                if isinstance(item, dict):
                    # Try common field names inside RERA detail objects
                    num_raw = (item.get("number") or item.get("reraId") or item.get("reraNumber")
                               or item.get("regNo") or item.get("registrationNo") or item.get("id") or "")
                    num = _clean(str(num_raw))
                elif isinstance(item, str):
                    num = _clean(item)
                else:
                    num = _clean(str(item))
                if num and num not in rera_seen and len(num) >= 6:
                    # Also run embedded-RERA extraction in case the value contains extra text
                    for r in _extract_rera_ids(num) or [num]:
                        if r and r not in rera_seen and len(r) >= 6:
                            rera_seen.add(r)
                            proj["rera_ids"].append({"number": r, "state": None, "tower_phase": None})

        # Price from __NEXT_DATA__ (fill if JSON-LD didn't give us prices)
        pd = proj["project_details"]
        if not pd.get("price_min"):
            raw_min = nd.get("minprice") or nd.get("pricemin") or nd.get("lowestprice") or nd.get("startingprice")
            if raw_min:
                pd["price_min"] = _format_inr(raw_min) or _clean(str(raw_min))
        if not pd.get("price_max"):
            raw_max = nd.get("maxprice") or nd.get("pricemax")
            if raw_max:
                pd["price_max"] = _format_inr(raw_max) or _clean(str(raw_max))

    # ── 2. DOM selectors (fill gaps) ─────────────────────────────────────────
    def _first_text(*selectors: str) -> str | None:
        for sel in selectors:
            try:
                el = soup.select_one(sel)
                if el:
                    t = _clean(el.get_text(" ", strip=True))
                    if t:
                        return t
            except Exception:
                pass
        return None

    if not proj["project_name"]:
        proj["project_name"] = _first_text(
            "h1",
            "[class*='projectName']", "[class*='ProjectName']",
            "[class*='project-name']", "[class*='project_name']",
            "[class*='propName']",
        )

    if not proj["developer_name"]:
        proj["developer_name"] = _first_text(
            "[class*='developerName']", "[class*='DeveloperName']",
            "[class*='builderName']",  "[class*='BuilderName']",
            "[class*='developer-name']", "[class*='builder-name']",
            "[class*='builderGroupName']",
        )

    if not proj["location"].get("full_address"):
        addr = _first_text(
            "[class*='localityName']", "[class*='LocalityName']",
            "[class*='address']",      "[class*='Address']",
            "[class*='location']",     "[class*='Location']",
            "[class*='projectLocation']",
        )
        if addr:
            proj["location"]["full_address"] = addr

    pd = proj["project_details"]

    if not pd["project_status"]:
        pd["project_status"] = _first_text(
            "[class*='projectStatus']", "[class*='ProjectStatus']",
            "[class*='constructionStatus']", "[class*='status']",
        )

    if not pd["possession_date"]:
        pd["possession_date"] = _first_text(
            "[class*='possessionDate']", "[class*='PossessionDate']",
            "[class*='possession']", "[class*='Possession']",
        )

    if not pd["total_units"]:
        pd["total_units"] = _first_text(
            "[class*='totalUnits']", "[class*='TotalUnits']",
            "[class*='unitCount']", "[class*='noOfUnits']",
        )

    if not pd["total_towers"]:
        pd["total_towers"] = _first_text(
            "[class*='totalTowers']", "[class*='TotalTowers']",
            "[class*='towerCount']",
        )

    if not pd["total_area_acres"]:
        pd["total_area_acres"] = _first_text(
            "[class*='totalArea']", "[class*='projectArea']",
            "[class*='TotalArea']",
        )

    if not proj["about_project"]:
        proj["about_project"] = _first_text(
            "[class*='projectDescription']", "[class*='ProjectDescription']",
            "[class*='about-project']",      "[class*='projectAbout']",
            "[class*='description']",        "[class*='overview']",
        )
        # Truncate very long descriptions
        if proj["about_project"] and len(proj["about_project"]) > 500:
            proj["about_project"] = proj["about_project"][:500].rsplit(" ", 1)[0] + "…"

    if not proj["about_developer"]:
        proj["about_developer"] = _first_text(
            "[class*='developerDescription']", "[class*='builderDescription']",
            "[class*='developerAbout']",       "[class*='builderAbout']",
        )

    # ── 3. Regex fallbacks on raw text ────────────────────────────────────────
    if not pd["total_units"]:
        m = _UNITS_RE.search(raw_text)
        if m:
            pd["total_units"] = m.group(1).replace(",", "")

    if not pd["total_towers"]:
        m = _TOWERS_RE.search(raw_text)
        if m:
            pd["total_towers"] = m.group(1)

    if not pd["total_floors"]:
        m = _FLOORS_RE.search(raw_text)
        if m:
            pd["total_floors"] = m.group(1)

    if not pd["total_area_acres"]:
        m = _AREA_ACRES_RE.search(raw_text)
        if m:
            pd["total_area_acres"] = m.group(1) + " acres"

    if not pd["possession_date"]:
        m = _DATE_RE.search(raw_text)
        if m:
            pd["possession_date"] = m.group(1)

    # ── 4. RERA from DOM (rendered React content) ────────────────────────────
    def _add_rera_from_text(text: str) -> None:
        for r in _extract_rera_ids(text):
            if r and r not in rera_seen and len(r) >= 8:
                rera_seen.add(r)
                proj["rera_ids"].append({"number": r, "state": None, "tower_phase": None})

    for el in soup.select(
        "[class*='rera'], [class*='Rera'], [class*='RERA'], "
        "[class*='reraId'], [class*='reraNumber'], [class*='reraReg']"
    ):
        _add_rera_from_text(el.get_text(" ", strip=True))

    # RERA from first 5000 chars of visible page text only —
    # limits false-positives from "similar projects" sections further down.
    _add_rera_from_text(raw_text[:5000])

    # ── 5. Build readable full_address if missing ────────────────────────────
    loc = proj["location"]
    if not loc.get("full_address"):
        parts = [loc.get("sector"), loc.get("city"), loc.get("state")]
        addr = ", ".join(p for p in parts if p)
        if addr:
            loc["full_address"] = addr

    return proj


def _extract_a99_floor_plan_configs(
    soup: BeautifulSoup, page_url: str
) -> tuple[list[dict], list[str]]:
    """
    Parse floor plan cards rendered by 99acres JS (FloorPlanCardV2).
    Returns (configs, fp_image_urls).
    Mirrors the bookmarklet's .FloorPlanCardV2__xidFpCard logic.
    """
    configs: list[dict] = []
    fp_image_urls: list[str] = []
    seen_keys: set[str] = set()

    for card in soup.select(".FloorPlanCardV2__xidFpCard"):
        # Area value
        area_el = card.select_one(".FloorPlanCardV2__areaDisplay")
        area = ""
        if area_el:
            first_child = next(
                (c for c in area_el.children if hasattr(c, "get_text")), None
            )
            area = (first_child.get_text(strip=True) if first_child
                    else area_el.get_text(strip=True))

        # BHK + area type  — format: "Super Built-up Area | 2 BHK"
        type_el = card.select_one(".FloorPlanCardV2__areaType")
        bhk = ""
        area_type = ""
        if type_el:
            parts = type_el.get_text(" ", strip=True).split("|")
            if len(parts) >= 2:
                raw_type = parts[0].strip()
                area_type = (
                    "SBA" if "super" in raw_type.lower() else
                    "BA" if "built-up" in raw_type.lower() else
                    "CA" if "carpet" in raw_type.lower() else
                    raw_type
                )
                bhk = parts[1].strip()
            elif len(parts) == 1:
                bhk = parts[0].strip()

        # Floor plan image
        wrapper = card.select_one(".FloorPlanCardV2__floorPlanImageWrapper")
        has_fp = False
        fp_img_url: str | None = None
        if wrapper:
            img = wrapper.select_one("img[src]")
            if img and img.get("src", ""):
                src = img["src"]
                if "floorPlanNoImage" not in src and "no-image" not in src.lower():
                    has_fp = True
                    fp_img_url = normalize_img_url(src, page_url)
                    if fp_img_url:
                        fp_image_urls.append(fp_img_url)

        # Price range
        price_el = card.select_one(
            ".FloorPlanCardV2__priceDisplay,.FloorPlanCardV2__price"
        )
        price = price_el.get_text(strip=True) if price_el else ""

        key = f"{bhk}|{area}|{area_type}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        configs.append({
            "unit_type": bhk or "?",
            "area": area or "?",
            "area_type": area_type or "?",
            "has_floor_plan_image": has_fp,
            "fp_image_url": fp_img_url,
            "price": price or None,
        })

    return configs, fp_image_urls


def _extract_a99_amenities_dom(soup: BeautifulSoup) -> list[str]:
    """
    Parse amenities rendered by 99acres JS (UniquesFacilities).
    Mirrors the bookmarklet's selector logic.
    """
    seen: set[str] = set()
    amenities: list[str] = []

    def _add(text: str) -> None:
        t = text.strip()
        if t and t not in seen and len(t) > 2:
            seen.add(t)
            amenities.append(t)

    # Card style (icon + label)
    for el in soup.select(
        ".UniquesFacilities__xidFacilitiesCard > div > div:last-child"
    ):
        _add(el.get_text(strip=True))

    # List style
    for el in soup.select(".UniquesFacilities__xidFacilitiesList .body_med"):
        _add(el.get_text(strip=True))

    # Generic fallback selectors
    for sel in (
        "[class*='FacilitiesCard'] [class*='label']",
        "[class*='FacilitiesCard'] [class*='text']",
        "[class*='AmenitiesCard'] span",
        "[class*='amenity'] span",
    ):
        try:
            for el in soup.select(sel):
                _add(el.get_text(strip=True))
        except Exception:
            pass

    return amenities


def _classify_a99_image(
    url: str, alt: str = "", img_bytes: bytes | None = None
) -> tuple[str, str | None]:
    """
    Classify a 99acres image into category + extract BHK label.
    Returns (classification, bhk_label | None).
    """
    ctx = (url + " " + alt).lower()

    # BHK label from URL/alt
    bm = re.search(r'(\d)\s*bhk', ctx, re.I)
    bhk = f"{bm.group(1)} BHK" if bm else None

    # Keyword classification
    for cat, kws in _A99_CAT_KW:
        if any(kw in ctx for kw in kws):
            return cat, bhk

    # BHK in context without explicit floor-plan keyword → likely floor plan
    if bhk:
        return "Floor Plan", bhk

    # Pixel heuristics
    if img_bytes:
        try:
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            thumb = img.resize((100, 100))
            pixels = list(thumb.getdata())
            total = len(pixels)
            white = sum(1 for r, g, b in pixels if r > 200 and g > 200 and b > 200)
            if white / total > 0.55 and ImageStat.Stat(img.convert("L")).stddev[0] < 35:
                return "Floor Plan", bhk
            std = ImageStat.Stat(img.convert("L")).stddev[0]
            return ("Photo", bhk) if std > 45 else ("Other", bhk)
        except Exception:
            pass

    return "Photo", bhk


def _extract_a99_dom_images(
    soup: BeautifulSoup, html_str: str, page_url: str
) -> list[dict]:
    """
    Extract ALL image entries {url, alt} from 99acres DOM.
    Covers every category container, data attribute, preload hint,
    and inline script on the page.
    """
    found: dict[str, str] = {}   # normalised-url → alt

    def _add(url: str, alt: str = "") -> None:
        n = normalize_img_url(url, page_url)
        if not n or is_likely_icon(n) or not looks_like_image_url(n):
            return
        if n not in found:
            found[n] = alt

    # ── 1. Every <img> tag (all attributes) ──────────────────────────────────
    for img in soup.find_all("img"):
        alt_text = img.get("alt", "")
        for attr in ("src", "data-src", "data-original", "data-lazy",
                     "data-image", "data-zoom-image", "data-full",
                     "data-large", "data-high-res", "data-img"):
            val = img.get(attr, "")
            if val:
                _add(val, alt_text)
        srcset = img.get("srcset", "")
        if srcset:
            best = parse_srcset(srcset)
            if best:
                _add(best, alt_text)

    # ── 2. Background-image in inline style attrs ─────────────────────────────
    for tag in soup.find_all(style=True):
        for m in _BG_IMG_RE.finditer(tag["style"]):
            _add(m.group(1))

    # ── 3. 99acres category-specific containers (Photos / Floor Plans /
    #        Site Plan / Master Plan / Aerial / Construction / Amenities etc.)
    for sel in (
        # Generic gallery / photo sections
        ".project_gallery img", ".gallery_image img",
        ".slider_images img", "[data-testid='gallery'] img",
        "div[class*='gallery'] img", "div[class*='photo'] img",
        "div[class*='Photo'] img",
        # Floor plan cards
        ".FloorPlanCardV2__xidFpCard img",
        "div[class*='FloorPlan'] img", "div[class*='floorPlan'] img",
        "div[class*='floor-plan'] img", "div[class*='floor_plan'] img",
        # Site / Master Plan
        "div[class*='SitePlan'] img", "div[class*='sitePlan'] img",
        "div[class*='MasterPlan'] img", "div[class*='masterPlan'] img",
        "div[class*='master-plan'] img", "div[class*='site-plan'] img",
        # Aerial / Elevation / Render
        "div[class*='aerial'] img", "div[class*='Aerial'] img",
        "div[class*='elevation'] img", "div[class*='Elevation'] img",
        "div[class*='render'] img", "div[class*='Render'] img",
        # Construction Progress
        "div[class*='construction'] img", "div[class*='Construction'] img",
        "div[class*='progress'] img",
        # Amenities
        "div[class*='amenity'] img", "div[class*='Amenity'] img",
        "div[class*='facilities'] img",
        # Generic sliders / carousels
        "div[class*='slider'] img", "div[class*='carousel'] img",
        "div[class*='Slider'] img", "div[class*='Carousel'] img",
        "div[class*='swiper'] img",
        # Any container with project/media class
        "div[class*='project'] img", "div[class*='media'] img",
        "div[class*='Media'] img",
    ):
        try:
            for img in soup.select(sel):
                src = (img.get("src") or img.get("data-src") or
                       img.get("data-original") or img.get("data-lazy") or "")
                if src:
                    _add(src, img.get("alt", ""))
        except Exception:
            pass

    # ── 4. ALL data-* attributes on any element that contain image URLs ────────
    for tag in soup.find_all(True):
        for attr, val in tag.attrs.items():
            if not attr.startswith("data-"):
                continue
            if not isinstance(val, str):
                continue
            if re.search(r'\.(?:jpe?g|png|webp|avif)(?:\?|$)', val, re.I):
                _add(val, tag.get("alt", ""))

    # ── 5. <link rel="preload" as="image"> ───────────────────────────────────
    for link in soup.find_all(
        "link",
        rel=lambda r: r and "preload" in (r if isinstance(r, str) else " ".join(r)),
    ):
        if link.get("as") == "image":
            href = link.get("href", "").strip()
            if href:
                _add(href, "preload-hero")

    # ── 6. Inline <script> scan ───────────────────────────────────────────────
    for script in soup.find_all("script"):
        content = script.string or ""
        for m in _JS_IMG_RE.finditer(content):
            _add(m.group(0))

    return [{"url": u, "alt": a} for u, a in found.items()]


# Matches "Status as on Oct, 2024", "Status as on: November 2023", etc.
_STATUS_AS_ON_RE = re.compile(
    r'(?:status\s+as\s+on|as\s+on)[:\s]+([A-Za-z]+[\s,]+\d{4}|\d{1,2}[\/\-]\d{4}|\d{4})',
    re.I,
)

# CSS class fragments that 99acres uses for construction-status date labels
_CONSTR_DATE_CLASS_PATTERNS = (
    "statusDate", "StatusDate", "status-date", "statusdate",
    "constructionDate", "ConstructionDate", "construction-date",
    "updateDate", "UpdateDate", "update-date",
    "imgdate", "ImgDate", "img-date",
)


def _extract_a99_construction_dates_dom(
    soup: BeautifulSoup,
    page_url: str,
    url_to_date: dict[str, str],
) -> int:
    """
    Walk the 99acres DOM to find construction-status date headers
    ("Status as on Oct, 2024") and map all image URLs in the same
    container to that date string.  Fills url_to_date in-place.
    Returns the number of new URL→date mappings added.
    """
    before = len(url_to_date)
    seen_imgs: set[str] = set()

    def _register(raw_url: str, date_text: str) -> None:
        n = normalize_img_url(raw_url, page_url)
        if not n or not looks_like_image_url(n) or is_likely_icon(n):
            return
        if n not in seen_imgs:
            seen_imgs.add(n)
            url_to_date.setdefault(n, date_text)
            ck = _canonical_a99_key(n)
            if ck:
                url_to_date.setdefault(ck, date_text)

    def _imgs_in(container) -> list:
        imgs = []
        for img in container.find_all("img"):
            for attr in ("src", "data-src", "data-original", "data-lazy"):
                raw = img.get(attr, "")
                if raw:
                    imgs.append(raw)
                    break
        return imgs

    def _apply_date_to_container(container, date_text: str) -> None:
        """Walk up from container until we find a parent that has ≥1 images."""
        node = container
        for _ in range(8):
            if node is None:
                break
            urls = _imgs_in(node)
            if urls:
                for u in urls:
                    _register(u, date_text)
                return
            node = getattr(node, "parent", None)

    # ── Strategy A: find elements whose class contains a date-class pattern ────
    for el in soup.find_all(True):
        cls = " ".join(el.get("class") or [])
        if not any(p in cls for p in _CONSTR_DATE_CLASS_PATTERNS):
            continue
        date_text = el.get_text(strip=True)[:80]
        if not date_text:
            continue
        _apply_date_to_container(el, date_text)

    # ── Strategy B: find text nodes matching "Status as on <date>" ─────────────
    for text_node in soup.find_all(string=_STATUS_AS_ON_RE):
        m = _STATUS_AS_ON_RE.search(text_node)
        if not m:
            continue
        date_text = m.group(1).strip()
        if not date_text:
            continue
        parent = getattr(text_node, "parent", None)
        if parent:
            _apply_date_to_container(parent, date_text)

    return len(url_to_date) - before


async def _download_a99_image(
    client: httpx.AsyncClient,
    img_url: str,
    alt: str,
    idx: int,
    semaphore: asyncio.Semaphore,
    url_to_type: dict[str, str] | None = None,
    url_to_date: dict[str, str] | None = None,
) -> dict | None:
    async with semaphore:
        try:
            await asyncio.sleep(random.uniform(0.05, 0.3))
            r = await client.get(img_url, timeout=20)
            ct = r.headers.get("content-type", "")
            if not ct.startswith("image/") or len(r.content) < 5 * 1024:
                return None
            try:
                img = Image.open(io.BytesIO(r.content))
                w, h = img.size
            except Exception:
                return None
            if w < 100 or h < 100:
                return None
            fmt = (img.format or "jpeg").lower()
            if fmt == "jpg":
                fmt = "jpeg"
            raw_name = img_url.split("/")[-1].split("?")[0] or f"img_{idx:04d}.{fmt}"
            raw_name = re.sub(r"[^\w.\-]", "_", raw_name)[:80]

            # Prefer the type extracted from the page's tuples structure (most accurate)
            # over the URL/pixel heuristic fallback.
            a99_type: str | None = None
            if url_to_type:
                a99_type = (url_to_type.get(img_url)
                            or url_to_type.get(_canonical_a99_key(img_url)))

            if a99_type:
                classification = _a99_tuples_classify(a99_type)
                # Still extract BHK label from alt/URL for floor plans
                bm = re.search(r'(\d)\s*bhk', (img_url + " " + alt).lower())
                bhk_label: str | None = f"{bm.group(1)} BHK" if bm else None
            else:
                classification, bhk_label = _classify_a99_image(img_url, alt, r.content)

            # Look up construction-status date for this image
            status_date: str | None = None
            if url_to_date:
                status_date = (url_to_date.get(img_url)
                               or url_to_date.get(_canonical_a99_key(img_url)))

            img_id = str(uuid.uuid4())
            return {
                "meta": {
                    "id": img_id,
                    "url": img_url,
                    "classification": classification,
                    "a99_type": a99_type,          # raw 99acres type label (may be None)
                    "bhk_label": bhk_label,
                    "status_date": status_date,    # construction update date (may be None)
                    "width": w, "height": h, "format": fmt,
                    "file_size_kb": round(len(r.content) / 1024, 1),
                    "alt_text": alt or None,
                    "filename": f"{idx:04d}_{raw_name}",
                },
                "data": r.content,
                "id": img_id,
            }
        except Exception:
            return None


# ── Background task ────────────────────────────────────────────────────────────

async def _do_scrape_99acres(
    session_id: str, url: str, html_source: str | None
) -> None:
    job = acres99_jobs[session_id]

    def log(msg: str) -> None:
        job.setdefault("log", []).append(msg)
        job["log"] = job["log"][-80:]
        print(f"[99acres:{session_id[:8]}] {msg}")

    try:
        npxid = _get_npxid(url) or "manual"
        job["npxid"] = npxid
        log(f"NPXID: {npxid}")

        all_img_entries: list[tuple[str, str]] = []   # (url, alt)
        all_vid_ids: set[str] = set()
        jld_imgs: list[str] = []   # populated in Step 3; used by Step 6 for CDN path detection
        extraction_method = "html_scrape"
        raw_text = ""
        documents: list[dict] = []   # brochure/payment plan PDFs
        html_str = html_source or ""
        url_to_type: dict[str, str] = {}   # image URL → 99acres type label (from tuples)
        url_to_date: dict[str, str] = {}   # construction status: image URL → date string

        # ── Step 1: Try 99acres internal APIs ─────────────────────────────────
        log("Step 1: Trying internal APIs…")
        api_headers = {
            "User-Agent": ACRES99_USER_AGENTS[0],
            "Accept": "application/json",
            "Referer": "https://www.99acres.com/",
            "X-Requested-With": "XMLHttpRequest",
            "Cookie": "device_id=web; session_id=abc123",
        }
        api_data: dict = {}
        async with httpx.AsyncClient(
            timeout=15, verify=False, follow_redirects=True
        ) as client:
            for endpoint in ("detail", "gallery", "amenities", "floorplans"):
                ep_url = f"https://www.99acres.com/api/v2/project/{npxid}/{endpoint}"
                try:
                    r = await client.get(ep_url, headers=api_headers)
                    if r.status_code == 200:
                        try:
                            data = r.json()
                            log(f"  API /{endpoint}: OK")
                            print(f"[99acres API /{endpoint}] {json.dumps(data)[:500]}")
                            if endpoint == "detail":
                                api_data.update(data if isinstance(data, dict) else {})
                                extraction_method = "api"
                            # Collect image/video URLs from all API responses
                            imgs: list[str] = []
                            vids: set[str] = set()
                            _collect_from_json(data, imgs, vids)
                            for iu in imgs:
                                all_img_entries.append((iu, ""))
                            all_vid_ids.update(vids)
                        except Exception as je:
                            log(f"  API /{endpoint}: JSON error — {je}")
                    else:
                        log(f"  API /{endpoint}: HTTP {r.status_code}")
                except Exception as e:
                    log(f"  API /{endpoint}: {e}")
                    job.setdefault("errors", []).append(f"API /{endpoint}: {e}")

        # ── Step 2: Fetch page HTML ────────────────────────────────────────────
        if not html_str:
            log("Step 2: Fetching page HTML…")
            # Attempt with 3 different UA profiles
            profiles = list(range(len(ACRES99_USER_AGENTS)))
            random.shuffle(profiles)

            for attempt, ua_idx in enumerate(profiles[:3]):
                ua  = ACRES99_USER_AGENTS[ua_idx]
                cua = _ACRES99_CH_UA[ua_idx]
                is_chrome = "Chrome" in ua and "Edg" not in ua
                is_edge   = "Edg" in ua

                hdrs: dict[str, str] = {
                    "User-Agent": ua,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                    "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                    "Cache-Control": "max-age=0",
                    "DNT": "1",
                }
                if cua:
                    hdrs["Sec-Ch-Ua"] = cua
                    hdrs["Sec-Ch-Ua-Mobile"] = "?0"
                    hdrs["Sec-Ch-Ua-Platform"] = '"Windows"' if "Windows" in ua else '"macOS"'

                if attempt == 1:
                    hdrs["Referer"] = "https://www.google.com/search?q=99acres+project"
                    hdrs["Sec-Fetch-Site"] = "cross-site"
                elif attempt == 2:
                    hdrs["Referer"] = "https://www.99acres.com/"
                    hdrs["Sec-Fetch-Site"] = "same-origin"

                if attempt > 0:
                    delay = random.uniform(2.0, 4.5)
                    log(f"  Waiting {delay:.1f}s before attempt {attempt + 1}…")
                    await asyncio.sleep(delay)

                try:
                    async with httpx.AsyncClient(
                        timeout=35, verify=False, follow_redirects=True,
                        headers=hdrs, http2=True,
                    ) as client:
                        resp = await client.get(url)

                    log(f"  Attempt {attempt + 1}: HTTP {resp.status_code}")

                    if resp.status_code in (403, 429, 503):
                        job.setdefault("errors", []).append(
                            f"HTTP {resp.status_code} on attempt {attempt + 1}"
                        )
                        continue

                    body_lower = resp.text[:2000].lower()
                    if ("cf-browser-verification" in body_lower
                            or "checking your browser" in body_lower
                            or "just a moment" in body_lower
                            or "enable javascript" in body_lower):
                        log("  Bot/Cloudflare challenge detected")
                        job["cloudflare_blocked"] = True
                        job.setdefault("errors", []).append(
                            "Bot protection active — paste page HTML manually"
                        )
                        break

                    if resp.status_code == 200:
                        html_str = resp.text
                        log(f"  Got HTML: {len(html_str):,} bytes")
                        break
                    else:
                        log(f"  Unexpected status {resp.status_code}")

                except Exception as e:
                    log(f"  Fetch error: {e}")
                    job.setdefault("errors", []).append(str(e))

            if not html_str:
                if not job.get("cloudflare_blocked"):
                    job["cloudflare_blocked"] = True
                    job.setdefault("errors", []).append(
                        "All fetch attempts blocked — open the page in your browser and paste the HTML"
                    )
                # Surface as error so the frontend shows the paste banner immediately
                job["status"] = "error"
                sessions[session_id] = {"images": []}
                job["images"] = []
                log("Aborting — no HTML available. Use manual paste.")
                return
        else:
            log(f"Step 2: Using pasted HTML ({len(html_str):,} bytes)")

        # ── Step 3: Parse HTML ─────────────────────────────────────────────────
        soup: BeautifulSoup | None = None
        next_data: dict = {}

        if html_str:
            log("Step 3: Parsing HTML…")
            soup = BeautifulSoup(html_str, "lxml")

            # __NEXT_DATA__ / window.__INITIAL_STATE__
            next_data = _parse_next_data(html_str)
            if next_data:
                log(f"  __NEXT_DATA__ found ({len(str(next_data))} chars)")
                if extraction_method not in ("api",):
                    extraction_method = "nextjs_state"
                nd_imgs: list[str] = []
                nd_vids: set[str] = set()
                _collect_from_json(next_data, nd_imgs, nd_vids)
                for iu in nd_imgs:
                    all_img_entries.append((iu, ""))
                all_vid_ids.update(nd_vids)
                log(f"  → {len(nd_imgs)} img URLs, {len(nd_vids)} video IDs")
            else:
                log("  __NEXT_DATA__ not found")

            # ── Build tuples type map + extract documents + construction dates ──
            # Walk __NEXT_DATA__ + any inline script that contains "tuples" or
            # document keys to build a url→type mapping, collect PDFs, and
            # capture per-update dates for construction status images.
            url_to_type: dict[str, str] = {}
            url_to_date: dict[str, str] = {}   # construction status: url → date string
            doc_seen_urls: set[str] = set()
            documents: list[dict] = []

            def _merge_docs(new_docs: list[dict]) -> None:
                for d in new_docs:
                    if d["url"] not in doc_seen_urls:
                        doc_seen_urls.add(d["url"])
                        documents.append(d)

            # Start with __NEXT_DATA__ for tuples, documents, and construction dates
            if next_data:
                url_to_type.update(_extract_tuples_type_map(next_data, url_to_date))
                log(f"  __NEXT_DATA__ tuples scan: {len(url_to_type)} URLs mapped, "
                    f"{len(url_to_date)} with dates")
                _merge_docs(_extract_a99_documents(next_data))

            _decoder = json.JSONDecoder()
            for script in soup.find_all("script"):
                content = script.string or ""
                has_tuples = '"tuples"' in content
                has_docs = any(k in content for k in _A99_DOCUMENT_KEYS)
                if not has_tuples and not has_docs:
                    continue
                # Strategy 1: whole script is pure JSON
                try:
                    data = json.loads(content)
                    if has_tuples:
                        before_t = len(url_to_type)
                        before_d = len(url_to_date)
                        url_to_type.update(_extract_tuples_type_map(data, url_to_date))
                        if len(url_to_type) > before_t:
                            log(f"  Inline JSON script: +{len(url_to_type)-before_t} URLs, "
                                f"+{len(url_to_date)-before_d} dates")
                    if has_docs:
                        _merge_docs(_extract_a99_documents(data))
                    continue
                except Exception:
                    pass
                # Strategy 2: use JSONDecoder.raw_decode at every `= [` or `= {`
                # position — finds JSON arrays (the actual structure) and objects.
                for m in re.finditer(r'=\s*([\[\{])', content):
                    pos = m.start(1)
                    try:
                        data, _ = _decoder.raw_decode(content, pos)
                        if isinstance(data, (dict, list)):
                            if has_tuples:
                                before = len(url_to_type)
                                url_to_type.update(_extract_tuples_type_map(data, url_to_date))
                                if len(url_to_type) > before:
                                    log(f"  Inline script (pos {pos}): +{len(url_to_type)-before} URLs")
                            if has_docs:
                                _merge_docs(_extract_a99_documents(data))
                    except Exception:
                        pass

            log(f"  Tuples type map total: {len(url_to_type)} URL→type entries, "
                f"types={list(set(url_to_type.values()))}")
            if url_to_date:
                log(f"  Construction dates: {len(url_to_date)} URLs with date labels")
            if documents:
                log(f"  Documents found: {[d['name'] for d in documents]}")
            job["documents"] = documents

            # JSON-LD (jld_imgs is declared outer-scope so Step 6 can use it
            # for CDN path detection even if this block is skipped)
            jld_vids: set[str] = set()
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    jld = json.loads(script.string or "")
                    _collect_from_json(jld, jld_imgs, jld_vids)
                except Exception:
                    pass
            for iu in jld_imgs:
                all_img_entries.append((iu, ""))
            all_vid_ids.update(jld_vids)
            log(f"  JSON-LD: {len(jld_imgs)} imgs, {len(jld_vids)} videos")

            # DOM images
            dom_imgs = _extract_a99_dom_images(soup, html_str, url)
            for e in dom_imgs:
                all_img_entries.append((e["url"], e.get("alt", "")))
            log(f"  DOM images: {len(dom_imgs)}")

            # Construction-status dates from DOM ("Status as on Oct, 2024")
            n_dom_dates = _extract_a99_construction_dates_dom(soup, url, url_to_date)
            if n_dom_dates:
                log(f"  Construction dates (DOM): +{n_dom_dates} URLs → date")

            # Videos from DOM
            for yt in extract_youtube_links(soup, html_str):
                all_vid_ids.add(yt["video_id"])
            # Also catch video IDs stored as plain strings in __NEXT_DATA__
            # (e.g. {"videoId": "abc123XYZ11"}) that _YT_RE won't match
            if next_data:
                for m in _YT_ID_ATTR_RE.finditer(json.dumps(next_data)):
                    vid = m.group(1).strip()
                    if len(vid) == 11:
                        all_vid_ids.add(vid)
            log(f"  Total video IDs: {len(all_vid_ids)}")

            # Page text for regex (strip scripts/styles first)
            for tag in soup.find_all(["script", "style", "noscript"]):
                tag.decompose()
            raw_text = soup.get_text(separator=" ", strip=True)
            log(f"  Page text: {len(raw_text)} chars")

        # ── Step 4: RERA regex scan (first 5000 chars of visible text only) ───
        # Limit to top of page to avoid picking up RERA IDs from "similar
        # projects" or "other listings" sections further down.
        rera_from_regex = _extract_rera_ids(raw_text[:5000])
        if rera_from_regex:
            log(f"Step 4: RERA IDs from regex: {rera_from_regex}")

        # ── Step 5: DOM-only project extraction (no Claude) ────────────────────
        log("Step 5: Extracting project data from DOM…")
        dom_result = _extract_a99_project_dom(
            soup or BeautifulSoup("", "lxml"),
            next_data,
            raw_text,
            url,
            rera_from_regex,
        )
        log(f"  project_name={dom_result.get('project_name')!r} | "
            f"developer={dom_result.get('developer_name')!r} | "
            f"RERA={len(dom_result.get('rera_ids', []))} | "
            f"possession={dom_result.get('project_details', {}).get('possession_date')!r}")

        # ── Step 6: Filter to this project + deduplicate size variants ──────────
        # Strategy:
        #  1. Derive the project's CDN path from JSON-LD images (most reliable).
        #  2. Filter out YouTube thumbnails, UI assets, and images whose CDN
        #     path doesn't match this project (eliminates "Similar Projects" etc.).
        #  3. Group by canonical key (strip size suffix) and keep only the
        #     highest-quality variant per group.
        # A second content-hash dedup after download catches any remaining dupes.
        project_cdn_path = _get_project_cdn_path(jld_imgs)
        log(f"Step 6: project CDN path = {project_cdn_path!r}")

        canonical_best: dict[str, tuple[str, str, int]] = {}
        skipped_other = 0
        for iu, alt in all_img_entries:
            iu = iu.strip()
            if not iu:
                continue
            if not _is_project_image(iu, project_cdn_path):
                skipped_other += 1
                continue
            key = _canonical_a99_key(iu)
            rank = _a99_size_rank(iu)
            existing = canonical_best.get(key)
            if existing is None or rank < existing[2]:
                canonical_best[key] = (iu, alt, rank)

        unique = [(url, alt) for url, alt, _ in canonical_best.values()]
        log(f"Step 6: {len(unique)} unique images after filtering "
            f"(skipped {skipped_other} other-project / UI URLs)…")
        job["total_images"] = len(unique)

        dl_headers = {
            "User-Agent": ACRES99_USER_AGENTS[0],
            "Referer": "https://www.99acres.com/",
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        }
        semaphore = asyncio.Semaphore(5)
        async with httpx.AsyncClient(
            timeout=20, verify=False, follow_redirects=True, headers=dl_headers
        ) as client:
            tasks = [
                _download_a99_image(client, iu, alt, idx, semaphore, url_to_type, url_to_date)
                for idx, (iu, alt) in enumerate(unique)
            ]
            dl_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Dedup by content hash — different URLs can serve identical bytes
        seen_hashes: set[str] = set()
        images_meta: list[dict] = []
        for r in dl_results:
            if r and not isinstance(r, Exception):
                h = hashlib.md5(r["data"]).hexdigest()
                if h in seen_hashes:
                    continue
                seen_hashes.add(h)
                images_meta.append(r["meta"])
                _write_img(session_id, r["id"], r["meta"].get("format", "jpeg"), r["data"])

        log(f"  Downloaded {len(images_meta)} unique images (by content hash)")

        # ── Step 7: Build video list ───────────────────────────────────────────
        videos_list = [
            {
                "type": "youtube",
                "url": f"https://www.youtube.com/watch?v={vid}",
                "embed_id": vid,
                "thumbnail": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg",
            }
            for vid in all_vid_ids
            if vid and len(vid) == 11
        ]

        # ── Finalise ───────────────────────────────────────────────────────────
        sessions[session_id] = {"images": images_meta}
        job["status"] = "complete"
        job["project"] = dom_result
        job["images"] = images_meta
        job["videos"] = videos_list
        job["documents"] = documents
        job["extraction_method"] = extraction_method
        log(f"Done! {len(images_meta)} images | {len(videos_list)} videos | "
            f"{len(documents)} docs | method={extraction_method}")

    except Exception as e:
        job["status"] = "error"
        job.setdefault("errors", []).append(str(e))
        log(f"Fatal: {e}")
        sessions[session_id] = {"images": []}
        job["images"] = []


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/scrape-99acres")
async def start_scrape_99acres(
    body: ScrapeNinetyNineAcresRequest,
    background_tasks: BackgroundTasks,
):
    url = body.url.strip()
    if not body.html_source:
        if "99acres.com" not in url:
            raise HTTPException(400, "URL must be a 99acres.com URL")
        if "npxid" not in url.lower():
            raise HTTPException(
                400,
                "URL must contain 'npxid' (e.g. …project-name-npxid-R12345)",
            )

    npxid = _get_npxid(url) or "manual"
    session_id = npxid  # stable key per project

    acres99_jobs[session_id] = {
        "status": "running",
        "log": [], "errors": [],
        "images": [], "videos": [], "documents": [], "project": {},
        "extraction_method": "html_scrape",
        "npxid": npxid,
        "cloudflare_blocked": False,
        "total_images": 0,
    }
    sessions[session_id] = {"images": []}

    background_tasks.add_task(_do_scrape_99acres, session_id, url, body.html_source)
    return {"session_id": session_id, "npxid": npxid, "status": "running"}


@app.get("/acres99-status/{session_id}")
async def acres99_status(session_id: str):
    job = acres99_jobs.get(session_id)
    if not job:
        raise HTTPException(404, "Job not found")
    is_done = job["status"] == "complete"
    return {
        "status": job["status"],
        "log": job.get("log", [])[-15:],
        "errors": job.get("errors", []),
        "cloudflare_blocked": job.get("cloudflare_blocked", False),
        "npxid": job.get("npxid", ""),
        "images":            job.get("images", [])    if is_done else [],
        "videos":            job.get("videos", [])    if is_done else [],
        "documents":         job.get("documents", []) if is_done else [],
        "project":           job.get("project", {})   if is_done else {},
        "extraction_method": job.get("extraction_method", ""),
        "images_found":      len(job.get("images", [])),
        "total_images":      job.get("total_images", 0),
    }
