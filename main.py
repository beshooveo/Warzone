from fastapi import FastAPI, Body, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pathlib import Path
import os
from typing import Dict, List, Optional, Any
from datetime import datetime
from io import StringIO
import asyncio
import hashlib
import json
import requests
import pandas as pd
import drive_store

try:
    from pywebpush import webpush, WebPushException
except Exception:
    webpush = None
    class WebPushException(Exception):
        response = None

app = FastAPI(title="War Zone Control")
from registration_routes import router as registration_router
import registration_routes as registration_data_module
app.include_router(registration_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/api/admin/backup-daily")
def daily_drive_backup(request: Request):
    secret = os.getenv("CRON_SECRET", "").strip()
    supplied = request.headers.get("x-cron-secret") or request.query_params.get("secret") or request.headers.get("authorization", "").replace("Bearer ", "")
    # Vercel Cron may call without custom headers; allow if no CRON_SECRET is configured, but setting it is recommended.
    if secret and supplied != secret:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not drive_store.enabled():
        raise HTTPException(status_code=400, detail="Google Drive storage is not configured.")
    snapshot = {
        "created_at": datetime.now().isoformat(),
        "warzone_main": load_data(),
        "registrations": registration_data_module.load_data(),
        "whatsapp_groups": registration_data_module.load_whatsapp_groups(),
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_id = drive_store.save_backup(f"warzone_backup_{stamp}.json", snapshot)
    if not backup_id:
        raise HTTPException(status_code=500, detail="Failed to create Google Drive backup.")
    return {"status": "success", "message": "Backup created", "backup_id": backup_id, "created_at": snapshot["created_at"]}


@app.get("/api/admin/backup-hourly")
def hourly_drive_backup_alias(request: Request):
    return daily_drive_backup(request)


@app.post("/api/admin/backup-now")
def manual_drive_backup(request: Request):
    supplied = request.headers.get("x-admin-password") or request.query_params.get("p") or request.query_params.get("password")
    admin_password = os.getenv("REGISTRATION_ADMIN_PASSWORD", "BeshooWarZone")
    if supplied != admin_password:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not drive_store.enabled():
        raise HTTPException(status_code=400, detail="Google Drive storage is not configured.")
    snapshot = {
        "created_at": datetime.now().isoformat(),
        "type": "manual",
        "warzone_main": load_data(),
        "registrations": registration_data_module.load_data(),
        "whatsapp_groups": registration_data_module.load_whatsapp_groups(),
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_id = drive_store.save_backup(f"warzone_manual_backup_{stamp}.json", snapshot)
    if not backup_id:
        raise HTTPException(status_code=500, detail="Failed to create Google Drive backup.")
    return {"status": "success", "message": "تم عمل Backup على Google Drive ✅", "backup_id": backup_id, "created_at": snapshot["created_at"]}


# =========================
# ثابت الألعاب والملفات
# =========================
SPORTS = ["Football", "Dodgeball", "Volleyball", "Ultimate Ball"]
SPORT_LABELS = {
    "Football": "Football ⚽",
    "Dodgeball": "Dodgeball 🤾🏻",
    "Volleyball": "Volleyball 🏐",
    "Ultimate Ball": "Ultimate Ball 🥏",
}
VERSION_LABELS = {"1": "المجموعات", "2": "المجموعات 2"}
DAY_LABELS = {"Day1": "اليوم الأول", "Day2": "اليوم الثاني"}

DEFAULT_VISIBILITY = {
    "teams": False,
    "groups": True,
    "groups2": False,
    "finals": False,
    "matches_day1": False,
    "matches_day2": True,
    "results_day1": False,
    "results_day2": False,
}

DATA_FILE = Path(os.getenv("WARZONE_DATA_FILE", "/tmp/warzone_data.json"))

DEFAULT_MATCHES_URLS = {
    "Day1": "https://docs.google.com/spreadsheets/d/e/2PACX-1vTPGvQX6sgITTWxbUXDqQzLSmQqU6TBxmZJDt0DS9pKOMNnoK7490Bn1TvNQrFlGdJZIH0Z9YPGTYb6/pub?gid=186915705&single=true&output=csv",
    "Day2": "https://docs.google.com/spreadsheets/d/e/2PACX-1vRqzlySvoK19S0Maw_xLSlUMmGcOPx6eNqiwKJKCtrHwkDxKuO95ZJKbvyNcXns8TxRe1oYnhZRtlNs/pub?gid=1547895490&single=true&output=csv",
}

# الجداول القديمة بتاعة المجموعات/الترتيب من Google Sheets.
# دي هتكون المصدر الأساسي للمجموعات، والجروبات اليدوية هتفضل fallback لو الشيت فاضي/مش متاح.
DEFAULT_SHEET_URLS = {
    "Football": "https://docs.google.com/spreadsheets/d/e/2PACX-1vTPGvQX6sgITTWxbUXDqQzLSmQqU6TBxmZJDt0DS9pKOMNnoK7490Bn1TvNQrFlGdJZIH0Z9YPGTYb6/pub?gid=621025358&single=true&output=csv",
    "Dodgeball": "https://docs.google.com/spreadsheets/d/e/2PACX-1vTPGvQX6sgITTWxbUXDqQzLSmQqU6TBxmZJDt0DS9pKOMNnoK7490Bn1TvNQrFlGdJZIH0Z9YPGTYb6/pub?gid=863642824&single=true&output=csv",
    "Volleyball": "https://docs.google.com/spreadsheets/d/e/2PACX-1vTPGvQX6sgITTWxbUXDqQzLSmQqU6TBxmZJDt0DS9pKOMNnoK7490Bn1TvNQrFlGdJZIH0Z9YPGTYb6/pub?gid=1033302345&single=true&output=csv",
    "Ultimate Ball": "https://docs.google.com/spreadsheets/d/e/2PACX-1vTPGvQX6sgITTWxbUXDqQzLSmQqU6TBxmZJDt0DS9pKOMNnoK7490Bn1TvNQrFlGdJZIH0Z9YPGTYb6/pub?gid=2017169226&single=true&output=csv",
    "Football2": "https://docs.google.com/spreadsheets/d/e/2PACX-1vTPGvQX6sgITTWxbUXDqQzLSmQqU6TBxmZJDt0DS9pKOMNnoK7490Bn1TvNQrFlGdJZIH0Z9YPGTYb6/pub?gid=907297379&single=true&output=csv",
    "Dodgeball2": "https://docs.google.com/spreadsheets/d/e/2PACX-1vTPGvQX6sgITTWxbUXDqQzLSmQqU6TBxmZJDt0DS9pKOMNnoK7490Bn1TvNQrFlGdJZIH0Z9YPGTYb6/pub?gid=402610111&single=true&output=csv",
    "Volleyball2": "https://docs.google.com/spreadsheets/d/e/2PACX-1vTPGvQX6sgITTWxbUXDqQzLSmQqU6TBxmZJDt0DS9pKOMNnoK7490Bn1TvNQrFlGdJZIH0Z9YPGTYb6/pub?gid=42182221&single=true&output=csv",
    "Ultimate Ball2": "https://docs.google.com/spreadsheets/d/e/2PACX-1vTPGvQX6sgITTWxbUXDqQzLSmQqU6TBxmZJDt0DS9pKOMNnoK7490Bn1TvNQrFlGdJZIH0Z9YPGTYb6/pub?gid=1116838793&single=true&output=csv"
}

# شيت النتايج: الأدمن بيكتب عليه، والموقع بيقرأ منه دوريًا.
# حط لينك CSV منشور (output=csv) للقراءة، ولو عايز كتابة من الأدمن:
# - شارك الشيت Edit مع Service Account
# - و/أو حط spreadsheet id / لينك الشيت العادي في RESULTS_SHEET_ID أو اللينك نفسه
DEFAULT_RESULTS_URLS = {
    "Day1": "",
    "Day2": "",
}
DEFAULT_RESULTS_SHEET_NAMES = {
    "Day1": "Results Day1",
    "Day2": "Results Day2",
}
RESULTS_SHEET_ID_ENV = os.getenv("RESULTS_SHEET_ID", "").strip()
RESULTS_SYNC_INTERVAL_SEC = int(os.getenv("RESULTS_SYNC_INTERVAL_SEC", "60") or "60")

# Runtime keys remain the same, but URLs can be changed from /sheets and stored in warzone_data.json.
MATCHES_URLS = DEFAULT_MATCHES_URLS
SHEET_URLS = DEFAULT_SHEET_URLS

all_matches_data: Dict[str, List[Dict[str, Any]]] = {k: [] for k in DEFAULT_MATCHES_URLS}
all_standings_sheet_data: Dict[str, List[Dict[str, Any]]] = {k: [] for k in DEFAULT_SHEET_URLS}
all_results_sheet_data: Dict[str, List[Dict[str, Any]]] = {k: [] for k in DEFAULT_RESULTS_URLS}
_results_sheet_sync_lock = asyncio.Lock()

# =========================
# Push Notifications
# =========================
VAPID_PUBLIC_KEY = "BNzit0AtKjV98NKB0QTVt8wpzvpEmxpmCq6PGIbxafoJUwjy7oODmFKoMSjNykAu6vp2ZHXhD4xeLunAD5AkIdo"
VAPID_PRIVATE_KEY = "EovBlK04jq_suYT2t2ULH-gmM_d6smFSoTihYi9roPs"
VAPID_CLAIMS = {"sub": "mailto:admin@warzone.com"}
subscribers = set()

# =========================
# Admin Login
# =========================
ADMIN_PASSWORD = "BeshooWarZone"
ADMIN_COOKIE_NAME = "warzone_admin_auth"
ADMIN_TOKEN = hashlib.sha256(f"warzone-admin:{ADMIN_PASSWORD}".encode("utf-8")).hexdigest()


class LoginPayload(BaseModel):
    password: str


def require_admin(request: Request) -> None:
    if request.cookies.get(ADMIN_COOKIE_NAME) != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="محتاج تسجل دخول للأدمن")


class NotificationPayload(BaseModel):
    title: str
    body: str


class GroupPayload(BaseModel):
    sport: str
    version: str
    group: str
    teams: List[str]


class ResultPayload(BaseModel):
    schedule_key: str
    day_name: str
    sport: str
    version: str
    group: str
    team1: str
    team2: str
    score1: int = Field(..., ge=0)
    score2: int = Field(..., ge=0)
    match_time: str = ""
    match_text: str = ""
    notify: bool = False


class FinalMatch(BaseModel):
    team1: str = ""
    team2: str = ""
    score1: str = "-"
    score2: str = "-"


class FinalsPayload(BaseModel):
    sport: str
    semi1: FinalMatch
    semi2: FinalMatch
    final: FinalMatch


class VisibilityPayload(BaseModel):
    visibility: Dict[str, bool]


class TeamNameOverridePayload(BaseModel):
    old_name: str
    new_name: str


class GroupOverridePayload(BaseModel):
    sport: str
    version: str
    action: str  # add_team / hide_team / move_team / hide_group
    group: str = ""
    team: str = ""
    from_group: str = ""
    to_group: str = ""


class SheetLinksPayload(BaseModel):
    standings: Dict[str, str] = {}
    matches: Dict[str, str] = {}
    results: Dict[str, str] = {}
    results_sheet_names: Dict[str, str] = {}
    results_spreadsheet_id: str = ""


class DrawSetupPayload(BaseModel):
    sport: str
    version: str
    title: str = ""
    placeholders: List[str]
    teams: List[str]


class DrawControlPayload(BaseModel):
    sport: str
    version: str
    action: str  # set_active / start / reveal_next / shuffle_remaining / reset


# =========================
# Data helpers
# =========================
def default_sheet_links() -> Dict[str, Any]:
    return {
        "standings": DEFAULT_SHEET_URLS.copy(),
        "matches": DEFAULT_MATCHES_URLS.copy(),
        "results": DEFAULT_RESULTS_URLS.copy(),
        "results_sheet_names": DEFAULT_RESULTS_SHEET_NAMES.copy(),
        "results_spreadsheet_id": RESULTS_SHEET_ID_ENV,
    }


def ensure_sheet_links(data: Dict[str, Any]) -> Dict[str, Any]:
    links = data.setdefault("sheet_links", default_sheet_links())
    links.setdefault("standings", {})
    links.setdefault("matches", {})
    links.setdefault("results", {})
    links.setdefault("results_sheet_names", {})
    for key, url in DEFAULT_SHEET_URLS.items():
        links["standings"].setdefault(key, url)
    for key, url in DEFAULT_MATCHES_URLS.items():
        links["matches"].setdefault(key, url)
    for key, url in DEFAULT_RESULTS_URLS.items():
        links["results"].setdefault(key, url)
    for key, name in DEFAULT_RESULTS_SHEET_NAMES.items():
        links["results_sheet_names"].setdefault(key, name)
    # Keep only known keys so accidental inputs do not break the app.
    links["standings"] = {k: str(links["standings"].get(k, DEFAULT_SHEET_URLS[k])).strip() or DEFAULT_SHEET_URLS[k] for k in DEFAULT_SHEET_URLS}
    links["matches"] = {k: str(links["matches"].get(k, DEFAULT_MATCHES_URLS[k])).strip() or DEFAULT_MATCHES_URLS[k] for k in DEFAULT_MATCHES_URLS}
    # Results CSV links may be empty until admin configures them.
    links["results"] = {k: str(links["results"].get(k, DEFAULT_RESULTS_URLS.get(k, "")) or "").strip() for k in DEFAULT_RESULTS_URLS}
    links["results_sheet_names"] = {
        k: str(links["results_sheet_names"].get(k, DEFAULT_RESULTS_SHEET_NAMES.get(k, k)) or DEFAULT_RESULTS_SHEET_NAMES.get(k, k)).strip()
        or DEFAULT_RESULTS_SHEET_NAMES.get(k, k)
        for k in DEFAULT_RESULTS_URLS
    }
    sid = str(links.get("results_spreadsheet_id") or RESULTS_SHEET_ID_ENV or "").strip()
    links["results_spreadsheet_id"] = sid
    data["sheet_links"] = links
    return links


def get_current_sheet_links() -> Dict[str, Any]:
    return ensure_sheet_links(load_data())


def get_current_standings_urls() -> Dict[str, str]:
    return get_current_sheet_links()["standings"]


def get_current_matches_urls() -> Dict[str, str]:
    return get_current_sheet_links()["matches"]


def get_current_results_urls() -> Dict[str, str]:
    return get_current_sheet_links()["results"]


def get_current_results_sheet_names() -> Dict[str, str]:
    return get_current_sheet_links()["results_sheet_names"]


def get_results_spreadsheet_id(links: Optional[Dict[str, Any]] = None) -> str:
    links = links or get_current_sheet_links()
    sid = str(links.get("results_spreadsheet_id") or RESULTS_SHEET_ID_ENV or "").strip()
    if sid:
        extracted = drive_store.extract_spreadsheet_id(sid) or sid
        return extracted
    # Fallback: try extract from any results CSV/edit URL
    for url in (links.get("results") or {}).values():
        extracted = drive_store.extract_spreadsheet_id(str(url or ""))
        if extracted:
            return extracted
    return ""


def validate_sheet_url(url: str, allow_empty: bool = False) -> str:
    clean = str(url or "").strip()
    if not clean:
        if allow_empty:
            return ""
        raise HTTPException(status_code=400, detail="لينك الشيت لا يمكن يكون فاضي")
    if not clean.startswith(("http://", "https://")):
        # allow bare spreadsheet ids for results write config
        if drive_store.extract_spreadsheet_id(clean):
            return clean
        raise HTTPException(status_code=400, detail="لينك الشيت لازم يبدأ بـ http أو https")
    return clean


def default_finals_for_sport(sport: str) -> Dict[str, Dict[str, str]]:
    return {
        "sport": sport,
        "semi1": {"team1": "X1", "team2": "Y2", "score1": "-", "score2": "-"},
        "semi2": {"team1": "X2", "team2": "Y1", "score1": "-", "score2": "-"},
        "final": {"team1": "الفائز 1", "team2": "الفائز 2", "score1": "-", "score2": "-"},
    }


def default_group_overrides() -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    return {sport: {"1": [], "2": []} for sport in SPORTS}


def default_draw_data() -> Dict[str, Any]:
    return {
        "active_key": "",
        "draws": {},
    }


def ensure_draw_data(data: Dict[str, Any]) -> Dict[str, Any]:
    draw = data.setdefault("draw", default_draw_data())
    if not isinstance(draw, dict):
        draw = default_draw_data()
        data["draw"] = draw
    draw.setdefault("active_key", "")
    draw.setdefault("draws", {})
    if not isinstance(draw.get("draws"), dict):
        draw["draws"] = {}
    return draw


def make_draw_key(sport: str, version: str) -> str:
    return f"{sport}|{version}"


def blank_draw(sport: str, version: str) -> Dict[str, Any]:
    return {
        "key": make_draw_key(sport, version),
        "sport": sport,
        "sport_label": SPORT_LABELS.get(sport, sport),
        "version": version,
        "version_label": VERSION_LABELS.get(version, version),
        "title": "قرعة War Zone",
        "placeholders": [],
        "teams": [],
        "assignments": {},
        "revealed": [],
        "status": "empty",
        "last_event": None,
        "applied_aliases": {},
        "updated_at": "",
    }


def get_draw_record(data: Dict[str, Any], sport: str, version: str) -> Dict[str, Any]:
    draw_data = ensure_draw_data(data)
    key = make_draw_key(sport, version)
    record = draw_data["draws"].setdefault(key, blank_draw(sport, version))
    record.setdefault("key", key)
    record.setdefault("sport", sport)
    record.setdefault("sport_label", SPORT_LABELS.get(sport, sport))
    record.setdefault("version", version)
    record.setdefault("version_label", VERSION_LABELS.get(version, version))
    record.setdefault("title", "قرعة War Zone")
    record.setdefault("placeholders", [])
    record.setdefault("teams", [])
    record.setdefault("assignments", {})
    record.setdefault("revealed", [])
    record.setdefault("status", "empty")
    record.setdefault("last_event", None)
    record.setdefault("applied_aliases", {})
    record.setdefault("updated_at", "")
    return record


def blank_data() -> Dict[str, Any]:
    return {
        "groups": {sport: {"1": {}, "2": {}} for sport in SPORTS},
        "results": {},
        "finals": {sport: default_finals_for_sport(sport) for sport in SPORTS},
        "visibility": DEFAULT_VISIBILITY.copy(),
        "team_name_overrides": {},
        "group_overrides": default_group_overrides(),
        "sheet_links": default_sheet_links(),
        "draw": default_draw_data(),
    }


def load_data() -> Dict[str, Any]:
    remote_data = drive_store.load_json("warzone_main")
    if isinstance(remote_data, dict):
        data = remote_data
    elif not DATA_FILE.exists():
        data = blank_data()
        save_data(data)
        return data
    else:
        try:
            with DATA_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = blank_data()

    # migrations / safety
    data.setdefault("groups", {})
    data.setdefault("results", {})
    data.setdefault("finals", {})
    data.setdefault("visibility", {})
    data.setdefault("team_name_overrides", {})
    data.setdefault("group_overrides", {})
    ensure_sheet_links(data)
    ensure_draw_data(data)
    for sport in SPORTS:
        data["groups"].setdefault(sport, {})
        data["groups"][sport].setdefault("1", {})
        data["groups"][sport].setdefault("2", {})
        data["finals"].setdefault(sport, default_finals_for_sport(sport))
        data["group_overrides"].setdefault(sport, {})
        data["group_overrides"][sport].setdefault("1", [])
        data["group_overrides"][sport].setdefault("2", [])
    for key, default_value in DEFAULT_VISIBILITY.items():
        data["visibility"].setdefault(key, default_value)
    return data


def save_data(data: Dict[str, Any]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        drive_store.save_json("warzone_main", data)
    except Exception:
        pass


def normalize_text(value: Any) -> str:
    text = " ".join(str(value or "").strip().split()).casefold()
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    return text.translate(trans)


def clean_team_name(name: Any) -> str:
    return str(name or "").strip()


def team_key_variants(name: Any) -> List[str]:
    base = normalize_text(name)
    variants = {base}
    for prefix in ["فريق ", "team ", "team-", "team_", "#"]:
        if base.startswith(prefix):
            variants.add(base[len(prefix):].strip())
    if base:
        variants.add(f"فريق {base}")
        variants.add(f"team {base}")
    return [v for v in variants if v]


def get_team_overrides(data: Dict[str, Any]) -> Dict[str, str]:
    raw = data.get("team_name_overrides", {}) or {}
    if isinstance(raw, list):
        raw = {str(x.get("old_name", "")): str(x.get("new_name", "")) for x in raw if isinstance(x, dict)}
    return {clean_team_name(k): clean_team_name(v) for k, v in raw.items() if clean_team_name(k) and clean_team_name(v)}


def apply_team_override(data: Dict[str, Any], name: Any) -> str:
    clean = clean_team_name(name)
    overrides = get_team_overrides(data)
    lookup: Dict[str, str] = {}
    for old_name, new_name in overrides.items():
        for key in team_key_variants(old_name):
            lookup[key] = new_name
    for key in team_key_variants(clean):
        if key in lookup:
            return lookup[key]
    return clean


def normalize_sport_and_version(sport_name: str) -> tuple[str, str]:
    sport_name = sport_name.strip()
    if sport_name.endswith("2"):
        maybe_sport = sport_name[:-1]
        if maybe_sport in SPORTS:
            return maybe_sport, "2"
    if sport_name in SPORTS:
        return sport_name, "1"
    raise HTTPException(status_code=404, detail="Sport not found")


def get_schedule_sport_column(sport: str) -> str:
    clean = str(sport or "").replace("2", "").strip()
    if clean in ["Ultimate", "Ultimate Ball"]:
        return "Ultimate Ball"
    return clean


def simplify_column_name(value: Any) -> str:
    text = normalize_text(value)
    keep = []
    for ch in text:
        if ch.isalnum() or ("\u0600" <= ch <= "\u06ff"):
            keep.append(ch)
    return "".join(keep)


def get_schedule_match_value(row: Dict[str, Any], sport: str) -> Any:
    # Strictly read the selected sport column only. This also handles headers with emojis/spaces.
    preferred = get_schedule_sport_column(sport)
    if preferred in row:
        return row.get(preferred, "")

    aliases = {
        "Football": ["Football", "Football ⚽", "كرة القدم"],
        "Dodgeball": ["Dodgeball", "Dodgeball 🤾🏻", "دودج بول", "دودجبول"],
        "Volleyball": ["Volleyball", "Volleyball 🏐", "كرة طائرة", "الطائرة"],
        "Ultimate Ball": ["Ultimate Ball", "Ultimate", "Ultimate 🥏", "التيميت", "التيميت بول"],
    }
    wanted = {simplify_column_name(x) for x in aliases.get(preferred, [preferred])}
    for key, value in row.items():
        if simplify_column_name(key) in wanted:
            return value
    return ""


def make_schedule_key(day_name: str, sport: str, row_index: int, match_time: str, match_text: str) -> str:
    raw = f"{day_name}|{sport}|{row_index}|{match_time}|{match_text}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def parse_match_text(match_text: Any) -> tuple[str, str]:
    text = " ".join(str(match_text or "").replace("\n", " ").split()).strip()
    if not text or text == "-":
        return "", ""

    separators = [
        " ضد ", " VS ", " vs ", " Vs ", " v ", " V ",
        " × ", " x ", " X ", " - ", " – ", " — ", " / ", " | ", ":",
    ]
    for sep in separators:
        if sep in text:
            parts = [p.strip() for p in text.split(sep, 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                return parts[0], parts[1]

    # fallback للماتشات المكتوبة بدون مسافات: TeamA-TeamB أو 3-4
    for sep in ["-", "–", "—", "×", "x", "X", "/", "|"]:
        if sep in text:
            parts = [p.strip() for p in text.split(sep, 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                return parts[0], parts[1]

    return "", ""


def fetch_matches_once(day_name: str, url: Optional[str] = None) -> List[Dict[str, Any]]:
    urls = get_current_matches_urls()
    if day_name not in urls:
        raise HTTPException(status_code=404, detail="اليوم غير موجود")
    response = requests.get(url or urls[day_name], timeout=20)
    response.raise_for_status()
    response.encoding = "utf-8"
    df = pd.read_csv(StringIO(response.text))
    df.columns = df.columns.str.strip()
    df = df.fillna("")
    rows = df.to_dict(orient="records")
    all_matches_data[day_name] = rows
    return rows


def get_schedule_rows(day_name: str) -> List[Dict[str, Any]]:
    if day_name not in DEFAULT_MATCHES_URLS:
        raise HTTPException(status_code=404, detail="اليوم غير موجود")
    if not all_matches_data.get(day_name):
        try:
            return fetch_matches_once(day_name)
        except Exception as e:
            print(f"❌ Error loading matches {day_name}: {e}")
            return []
    return all_matches_data.get(day_name, [])


def get_team_name_from_row(row: Dict[str, Any]) -> str:
    for key, value in row.items():
        key_norm = normalize_text(key)
        if key_norm in {"الفريق", "اسم الفريق", "team", "team name"} and clean_team_name(value):
            return clean_team_name(value)
    values = list(row.values())
    if len(values) > 9 and clean_team_name(values[9]):
        return clean_team_name(values[9])
    ignored = {"المجموعة", "group", "لعب", "فوز", "تعادل", "خسارة", "نقاط", "النقاط", "له", "عليه", "فرق"}
    for key, value in row.items():
        if normalize_text(key) in ignored:
            continue
        val = clean_team_name(value)
        if val and val != "-":
            return val
    return ""


def fetch_standings_once(sheet_key: str, url: Optional[str] = None) -> List[Dict[str, Any]]:
    urls = get_current_standings_urls()
    if sheet_key not in urls:
        raise HTTPException(status_code=404, detail="جدول المجموعات غير موجود")
    response = requests.get(url or urls[sheet_key], timeout=20)
    response.raise_for_status()
    response.encoding = "utf-8"
    df = pd.read_csv(StringIO(response.text))
    df.columns = df.columns.str.strip()
    df = df.fillna("")
    rows = df.to_dict(orient="records")
    all_standings_sheet_data[sheet_key] = rows
    return rows


def get_sheet_rows_for_groups(sport: str, version: str) -> List[Dict[str, Any]]:
    sheet_key = sport + ("2" if version == "2" else "")
    if sheet_key not in DEFAULT_SHEET_URLS:
        return []
    if not all_standings_sheet_data.get(sheet_key):
        try:
            return fetch_standings_once(sheet_key)
        except Exception as e:
            print(f"❌ Error loading standings sheet {sheet_key}: {e}")
            return []
    return all_standings_sheet_data.get(sheet_key, [])


def groups_from_sheet(data: Dict[str, Any], sport: str, version: str) -> Dict[str, List[str]]:
    rows = get_sheet_rows_for_groups(sport, version)
    groups: Dict[str, List[str]] = {}
    seen: Dict[str, set] = {}
    for row in rows:
        group_name = clean_team_name(row.get("المجموعة", row.get("Group", "A"))) or "A"
        team = apply_team_override(data, get_team_name_from_row(row))
        if not team:
            continue
        groups.setdefault(group_name, [])
        seen.setdefault(group_name, set())
        key = normalize_text(team)
        if key not in seen[group_name]:
            groups[group_name].append(team)
            seen[group_name].add(key)
    return groups


def sheet_number_value(row: Dict[str, Any], *keys: str, default: int = 0) -> int:
    for wanted in keys:
        wanted_norm = normalize_text(wanted)
        for key, value in row.items():
            if normalize_text(key) != wanted_norm:
                continue
            text = str(value).strip()
            if not text or text == "-":
                return default
            try:
                return int(float(text.replace(",", "")))
            except Exception:
                return default
    return default


def standings_from_sheet(data: Dict[str, Any], sport: str, version: str) -> Dict[str, List[Dict[str, Any]]]:
    """Build standings rows from the connected Google Sheet, not just team names."""
    rows = get_sheet_rows_for_groups(sport, version)
    standings: Dict[str, List[Dict[str, Any]]] = {}
    seen: Dict[str, set] = {}

    for row in rows:
        group_name = clean_team_name(row.get("المجموعة", row.get("Group", "A"))) or "A"
        team = apply_team_override(data, get_team_name_from_row(row))
        if not team:
            continue

        key = normalize_text(team)
        standings.setdefault(group_name, [])
        seen.setdefault(group_name, set())
        if key in seen[group_name]:
            continue
        seen[group_name].add(key)

        played = sheet_number_value(row, "لعب", "played", "p")
        wins = sheet_number_value(row, "فوز", "won", "win", "wins", "w")
        draws = sheet_number_value(row, "تعادل", "draw", "draws", "d")
        losses = sheet_number_value(row, "خسارة", "lost", "loss", "losses", "l")
        goals_for = sheet_number_value(row, "له", "أهداف له", "اهداف له", "goals for", "gf")
        goals_against = sheet_number_value(row, "عليه", "أهداف عليه", "اهداف عليه", "goals against", "ga")
        goal_diff = sheet_number_value(row, "فرق", "فارق", "goal difference", "gd", default=goals_for - goals_against)
        points = sheet_number_value(row, "نقاط", "النقاط", "points", "pts")

        standings[group_name].append({
            "الفريق": team,
            "لعب": played,
            "فوز": wins,
            "تعادل": draws,
            "خسارة": losses,
            "له": goals_for,
            "عليه": goals_against,
            "فرق": goal_diff,
            "نقاط": points,
        })

    for group_name, group_rows in standings.items():
        group_rows.sort(key=lambda r: (-r["نقاط"], -r["فرق"], -r["له"], r["عليه"], r["الفريق"]))
    return standings


def get_manual_groups(data: Dict[str, Any], sport: str, version: str) -> Dict[str, List[str]]:
    groups = data.get("groups", {}).get(sport, {}).get(version, {}) or {}
    clean_groups: Dict[str, List[str]] = {}
    for group_name, teams in groups.items():
        cleaned = []
        seen = set()
        for team in teams or []:
            name = apply_team_override(data, team)
            key = normalize_text(name)
            if name and key not in seen:
                cleaned.append(name)
                seen.add(key)
        if cleaned:
            clean_groups[group_name] = cleaned
    return clean_groups


def get_group_overrides(data: Dict[str, Any], sport: str, version: str) -> List[Dict[str, Any]]:
    return data.setdefault("group_overrides", {}).setdefault(sport, {}).setdefault(version, [])


def make_group_override_id(record: Dict[str, Any]) -> str:
    # Deterministic id so the same override is not duplicated if you click twice.
    raw = "|".join(str(record.get(k, "")) for k in ["sport", "version", "action", "group", "team", "from_group", "to_group"])
    return hashlib.sha1(normalize_text(raw).encode("utf-8")).hexdigest()[:20]


def add_team_once(groups: Dict[str, List[str]], group_name: str, team: str) -> None:
    group_name = clean_team_name(group_name)
    team = clean_team_name(team)
    if not group_name or not team:
        return
    groups.setdefault(group_name, [])
    existing = {normalize_text(t) for t in groups[group_name]}
    if normalize_text(team) not in existing:
        groups[group_name].append(team)


def remove_team_from_groups(groups: Dict[str, List[str]], team: str, group_name: str = "") -> None:
    team_norm = normalize_text(team)
    group_norm = normalize_text(group_name)
    if not team_norm:
        return
    for g in list(groups.keys()):
        if group_norm and normalize_text(g) != group_norm:
            continue
        groups[g] = [t for t in groups[g] if normalize_text(t) != team_norm]


def remove_group(groups: Dict[str, List[str]], group_name: str) -> None:
    group_norm = normalize_text(group_name)
    for g in list(groups.keys()):
        if normalize_text(g) == group_norm:
            del groups[g]


def apply_group_overrides(data: Dict[str, Any], sport: str, version: str, base_groups: Dict[str, List[str]]) -> Dict[str, List[str]]:
    # Copy first so sheet data stays untouched.
    groups: Dict[str, List[str]] = {clean_team_name(g): list(teams or []) for g, teams in (base_groups or {}).items()}
    overrides = get_group_overrides(data, sport, version)

    # 1) Move teams. This removes the team from any group first to avoid duplicates.
    for rec in overrides:
        if rec.get("action") != "move_team":
            continue
        team = apply_team_override(data, rec.get("team", ""))
        to_group = clean_team_name(rec.get("to_group", ""))
        if team and to_group:
            remove_team_from_groups(groups, team)
            add_team_once(groups, to_group, team)

    # 2) Add admin-only teams on top of the sheet/manual data.
    for rec in overrides:
        if rec.get("action") != "add_team":
            continue
        add_team_once(groups, rec.get("group", ""), apply_team_override(data, rec.get("team", "")))

    # 3) Hide teams from a specific group.
    for rec in overrides:
        if rec.get("action") != "hide_team":
            continue
        remove_team_from_groups(groups, apply_team_override(data, rec.get("team", "")), rec.get("group", ""))

    # 4) Hide/delete full groups.
    for rec in overrides:
        if rec.get("action") != "hide_group":
            continue
        remove_group(groups, rec.get("group", ""))

    # Clean empty groups and duplicates.
    clean_groups: Dict[str, List[str]] = {}
    for group_name, teams in groups.items():
        cleaned = []
        seen = set()
        for team in teams:
            team = clean_team_name(team)
            key = normalize_text(team)
            if team and key not in seen:
                cleaned.append(team)
                seen.add(key)
        if cleaned:
            clean_groups[group_name] = cleaned
    return clean_groups


def get_effective_groups(data: Dict[str, Any], sport: str, version: str) -> Dict[str, List[str]]:
    sheet_groups = groups_from_sheet(data, sport, version)
    base_groups = sheet_groups if sheet_groups else get_manual_groups(data, sport, version)
    return apply_group_overrides(data, sport, version, base_groups)


def get_all_effective_groups(data: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
    return {sport: {version: get_effective_groups(data, sport, version) for version in ["1", "2"]} for sport in SPORTS}


def build_groups_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for sport in SPORTS:
        for version in ["1", "2"]:
            sheet_groups = groups_from_sheet(data, sport, version)
            source = "sheet" if sheet_groups else "manual"
            groups = get_effective_groups(data, sport, version)
            has_overrides = bool(get_group_overrides(data, sport, version))
            if source == "sheet" and has_overrides:
                source_label = "من الشيت + تعديلات الأدمن"
            elif source == "sheet":
                source_label = "من الشيت"
            elif has_overrides:
                source_label = "يدوي/بديل + تعديلات الأدمن"
            else:
                source_label = "يدوي/بديل"
            for group_name, teams in groups.items():
                items.append({
                    "sport": sport,
                    "sport_label": SPORT_LABELS.get(sport, sport),
                    "version": version,
                    "version_label": VERSION_LABELS.get(version, version),
                    "group": group_name,
                    "teams": teams,
                    "source": source,
                    "source_label": source_label,
                })
    return items


def build_raw_team_name_options(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return original team names from sheets/match schedules before aliases are applied.
    Used by admin alias dropdown so the admin does not have to type the original sheet name manually.
    """
    items: Dict[str, Dict[str, Any]] = {}

    def add_name(name: Any, source: str) -> None:
        clean = clean_team_name(name)
        if not clean or clean == "-":
            return
        key = normalize_text(clean)
        if key not in items:
            items[key] = {"name": clean, "sources": []}
        if source and source not in items[key]["sources"]:
            items[key]["sources"].append(source)

    # Original names from standings/group sheets, before apply_team_override().
    for sport in SPORTS:
        for version in ["1", "2"]:
            for row in get_sheet_rows_for_groups(sport, version):
                group_name = clean_team_name(row.get("المجموعة", row.get("Group", "A"))) or "A"
                add_name(
                    get_team_name_from_row(row),
                    f"{SPORT_LABELS.get(sport, sport)} / {VERSION_LABELS.get(version, version)} / مجموعة {group_name}",
                )

    # Original names from match schedule sheets, before aliases are applied.
    for day_name in ["Day1", "Day2"]:
        for row in get_schedule_rows(day_name):
            for sport in SPORTS:
                column = get_schedule_sport_column(sport)
                raw_match_text = clean_team_name(row.get(column, ""))
                if not raw_match_text or raw_match_text == "-":
                    continue
                team1, team2 = parse_match_text(raw_match_text)
                source = f"{DAY_LABELS.get(day_name, day_name)} / {SPORT_LABELS.get(sport, sport)}"
                if team1 and team2:
                    add_name(team1, source)
                    add_name(team2, source)
                else:
                    # Fallback for unusual cells that contain a single placeholder/team value.
                    add_name(raw_match_text, source)

    # Include existing old names so saved overrides can still be edited/deleted even if the sheet changed.
    for old_name in (data.get("team_name_overrides", {}) or {}).keys():
        add_name(old_name, "استبدال محفوظ")

    out = []
    for item in items.values():
        sources = item.get("sources", [])
        out.append({
            "name": item["name"],
            "sources": sources,
            "label": item["name"] + (" — " + "، ".join(sources[:2]) if sources else ""),
        })
    out.sort(key=lambda x: normalize_text(x["name"]))
    return out


def build_group_overrides_list(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    labels = {
        "add_team": "إضافة فريق فوق الشيت",
        "hide_team": "إخفاء/حذف فريق من العرض",
        "move_team": "نقل فريق لمجموعة أخرى",
        "hide_group": "إخفاء/حذف مجموعة كاملة",
    }
    items: List[Dict[str, Any]] = []
    for sport in SPORTS:
        for version in ["1", "2"]:
            for rec in get_group_overrides(data, sport, version):
                item = dict(rec)
                item.setdefault("id", make_group_override_id(item))
                item["sport"] = sport
                item["version"] = version
                item["sport_label"] = SPORT_LABELS.get(sport, sport)
                item["version_label"] = VERSION_LABELS.get(version, version)
                item["action_label"] = labels.get(item.get("action", ""), item.get("action", ""))
                items.append(item)
    return items


def build_draw_placeholder_options(data: Dict[str, Any], sport: str, version: str) -> List[Dict[str, Any]]:
    """Placeholders are the raw names/numbers that currently exist in the sheet before aliases.
    The draw maps those placeholders to real team names, and that mapping is saved as team_name_overrides.
    """
    if sport not in SPORTS or version not in ["1", "2"]:
        raise HTTPException(status_code=400, detail="اللعبة أو التاب غير صحيح")

    items: Dict[str, Dict[str, Any]] = {}

    def add(name: Any, source: str, group: str = "") -> None:
        clean = clean_team_name(name)
        if not clean or clean == "-":
            return
        key = normalize_text(clean)
        if key not in items:
            items[key] = {"name": clean, "sources": [], "groups": []}
        if source and source not in items[key]["sources"]:
            items[key]["sources"].append(source)
        if group and group not in items[key]["groups"]:
            items[key]["groups"].append(group)

    for row in get_sheet_rows_for_groups(sport, version):
        group_name = clean_team_name(row.get("المجموعة", row.get("Group", "A"))) or "A"
        add(get_team_name_from_row(row), f"{VERSION_LABELS.get(version)} / مجموعة {group_name}", group_name)

    # Fallback: if the group sheet is empty, use effective/manual groups as placeholders.
    if not items:
        for group_name, teams in get_effective_groups(data, sport, version).items():
            for team in teams:
                add(team, f"حل بديل / مجموعة {group_name}", group_name)

    # Also include raw names that appear in schedule cells for the selected sport.
    for day_name in ["Day1", "Day2"]:
        for row in get_schedule_rows(day_name):
            column = get_schedule_sport_column(sport)
            raw_match_text = clean_team_name(row.get(column, ""))
            if not raw_match_text or raw_match_text == "-":
                continue
            t1, t2 = parse_match_text(raw_match_text)
            source = f"جدول ماتشات {DAY_LABELS.get(day_name, day_name)}"
            if t1 and t2:
                add(t1, source)
                add(t2, source)
            else:
                add(raw_match_text, source)

    out = []
    for item in items.values():
        label_bits = []
        if item.get("groups"):
            label_bits.append("مجموعة " + ", ".join(item["groups"][:2]))
        if item.get("sources"):
            label_bits.append(" / ".join(item["sources"][:2]))
        out.append({
            "name": item["name"],
            "groups": item.get("groups", []),
            "sources": item.get("sources", []),
            "label": item["name"] + (" — " + "، ".join(label_bits) if label_bits else ""),
        })
    out.sort(key=lambda x: normalize_text(x["name"]))
    return out


def remove_draw_aliases(data: Dict[str, Any], draw: Dict[str, Any]) -> None:
    overrides = data.setdefault("team_name_overrides", {})
    applied = draw.get("applied_aliases", {}) or {}
    for placeholder, team in list(applied.items()):
        for key in list(overrides.keys()):
            if normalize_text(key) == normalize_text(placeholder) and normalize_text(overrides.get(key, "")) == normalize_text(team):
                del overrides[key]
    draw["applied_aliases"] = {}


def apply_draw_assignment_alias(data: Dict[str, Any], draw: Dict[str, Any], placeholder: str, team: str) -> None:
    placeholder = clean_team_name(placeholder)
    team = clean_team_name(team)
    if not placeholder or not team:
        return
    data.setdefault("team_name_overrides", {})[placeholder] = team
    draw.setdefault("applied_aliases", {})[placeholder] = team


def draw_public_state(data: Dict[str, Any]) -> Dict[str, Any]:
    draw_data = ensure_draw_data(data)
    active_key = draw_data.get("active_key", "")
    active = draw_data.get("draws", {}).get(active_key) if active_key else None
    if not active:
        return {"active_key": "", "draw": None, "message": "لسه مفيش قرعة متفعلة"}
    record = dict(active)
    record["total"] = len(record.get("placeholders", []))
    record["revealed_count"] = len(record.get("revealed", []))
    return {"active_key": active_key, "draw": record}


def validate_draw_identity(sport: str, version: str) -> tuple[str, str]:
    sport = clean_team_name(sport)
    version = clean_team_name(version)
    if sport not in SPORTS:
        raise HTTPException(status_code=400, detail="اللعبة غير صحيحة")
    if version not in ["1", "2"]:
        raise HTTPException(status_code=400, detail="التاب غير صحيح")
    return sport, version


def find_group_for_match(data: Dict[str, Any], sport: str, team1: str, team2: str) -> Dict[str, str]:
    team1 = apply_team_override(data, team1)
    team2 = apply_team_override(data, team2)
    t1 = normalize_text(team1)
    t2 = normalize_text(team2)
    if not t1 or not t2:
        return {"version": "", "group": ""}
    for version in ["1", "2"]:
        groups = get_effective_groups(data, sport, version)
        for group_name, teams in groups.items():
            team_norms = {normalize_text(t) for t in teams}
            if t1 in team_norms and t2 in team_norms:
                return {"version": version, "group": group_name}
    return {"version": "", "group": ""}


def apply_overrides_to_match_text(data: Dict[str, Any], match_text: Any) -> str:
    team1, team2 = parse_match_text(match_text)
    if team1 and team2:
        return f"{apply_team_override(data, team1)} ضد {apply_team_override(data, team2)}"
    return apply_team_override(data, match_text)


def apply_overrides_to_match_rows(data: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    processed = []
    sport_columns = ["Football", "Dodgeball", "Volleyball", "Ultimate Ball"]
    for row in rows:
        new_row = dict(row)
        for col in sport_columns:
            if col in new_row:
                val = clean_team_name(new_row.get(col, ""))
                if val and val != "-":
                    new_row[col] = apply_overrides_to_match_text(data, val)
        processed.append(new_row)
    return processed


def build_available_schedule_matches(day_name: str, sport: str) -> List[Dict[str, Any]]:
    if sport not in SPORTS:
        raise HTTPException(status_code=400, detail="اللعبة غير صحيحة")
    data = load_data()
    raw_rows = get_schedule_rows(day_name)
    column = get_schedule_sport_column(sport)
    available: List[Dict[str, Any]] = []

    for index, row in enumerate(raw_rows):
        raw_match_text = str(get_schedule_match_value(row, sport) or "").strip()
        if not raw_match_text or raw_match_text == "-":
            continue
        match_time = str(row.get("التوقيت", row.get("time", row.get("Time", ""))) or "").strip()
        schedule_key = make_schedule_key(day_name, sport, index, match_time, raw_match_text)
        if schedule_key in data.get("results", {}):
            continue

        raw_team1, raw_team2 = parse_match_text(raw_match_text)
        team1 = apply_team_override(data, raw_team1)
        team2 = apply_team_override(data, raw_team2)
        match_text = apply_overrides_to_match_text(data, raw_match_text)
        group_info = find_group_for_match(data, sport, team1, team2)
        label_parts = []
        if match_time:
            label_parts.append(match_time)
        label_parts.append(match_text)
        if group_info.get("group"):
            label_parts.append(f"{VERSION_LABELS.get(group_info['version'], '')} / المجموعة {group_info['group']}")

        available.append({
            "id": schedule_key,
            "schedule_key": schedule_key,
            "day_name": day_name,
            "day_label": DAY_LABELS.get(day_name, day_name),
            "sport": sport,
            "sport_label": SPORT_LABELS.get(sport, sport),
            "row_index": index,
            "time": match_time,
            "match_time": match_time,
            "match_text": match_text,
            "raw_match_text": raw_match_text,
            "team1": team1,
            "team2": team2,
            "version": group_info.get("version", ""),
            "group": group_info.get("group", ""),
            "can_parse": bool(team1 and team2),
            "label": " | ".join(label_parts),
        })
    return available


def canonical_team_name(data: Dict[str, Any], sport: str, version: str, group: str, input_name: str) -> str:
    teams = get_effective_groups(data, sport, version).get(group, [])
    wanted = normalize_text(apply_team_override(data, input_name))
    for team in teams:
        if normalize_text(team) == wanted:
            return clean_team_name(team)
    return apply_team_override(data, input_name)


def ensure_result_valid(data: Dict[str, Any], payload: ResultPayload) -> None:
    if payload.sport not in SPORTS:
        raise HTTPException(status_code=400, detail="اللعبة غير صحيحة")
    if payload.version not in ["1", "2"]:
        raise HTTPException(status_code=400, detail="اختار المجموعات أو المجموعات 2")
    if payload.day_name not in ["Day1", "Day2"]:
        raise HTTPException(status_code=400, detail="اليوم غير صحيح")
    team1 = apply_team_override(data, payload.team1)
    team2 = apply_team_override(data, payload.team2)
    if normalize_text(team1) == normalize_text(team2):
        raise HTTPException(status_code=400, detail="لا يمكن اختيار نفس الفريق مرتين")

    groups = get_effective_groups(data, payload.sport, payload.version)
    teams = groups.get(payload.group)
    if teams is None:
        raise HTTPException(status_code=404, detail="المجموعة غير موجودة. تأكد إن الفريقين موجودين في نفس مجموعة الشيت أو في مجموعة يدوية بديلة")

    team_norms = {normalize_text(t) for t in teams}
    if normalize_text(team1) not in team_norms or normalize_text(team2) not in team_norms:
        raise HTTPException(status_code=404, detail="الفريقين لازم يكونوا موجودين في نفس المجموعة المختارة بعد استبدال الأسماء")


def calculate_standings(data: Dict[str, Any], sport: str, version: str) -> Dict[str, List[Dict[str, Any]]]:
    groups = get_effective_groups(data, sport, version)
    results = data.get("results", {})
    sheet_standings = standings_from_sheet(data, sport, version)
    standings: Dict[str, List[Dict[str, Any]]] = {}

    for group_name in sorted(groups.keys()):
        teams = [clean_team_name(t) for t in groups[group_name] if clean_team_name(t)]
        table: Dict[str, Dict[str, Any]] = {}
        sheet_rows_by_name = {normalize_text(r.get("الفريق", "")): r for r in sheet_standings.get(group_name, [])}
        for team in teams:
            sheet_row = sheet_rows_by_name.get(normalize_text(team))
            if sheet_row:
                table[team] = dict(sheet_row)
                table[team]["الفريق"] = team
            else:
                table[team] = {
                    "الفريق": team,
                    "لعب": 0,
                    "فوز": 0,
                    "تعادل": 0,
                    "خسارة": 0,
                    "له": 0,
                    "عليه": 0,
                    "فرق": 0,
                    "نقاط": 0,
                }

        for result in results.values():
            if result.get("sport") != sport or result.get("version") != version or result.get("group") != group_name:
                continue
            t1 = canonical_team_name(data, sport, version, group_name, result.get("team1", ""))
            t2 = canonical_team_name(data, sport, version, group_name, result.get("team2", ""))
            if t1 not in table or t2 not in table:
                continue
            s1, s2 = int(result.get("score1", 0)), int(result.get("score2", 0))

            table[t1]["لعب"] += 1
            table[t2]["لعب"] += 1
            table[t1]["له"] += s1
            table[t1]["عليه"] += s2
            table[t2]["له"] += s2
            table[t2]["عليه"] += s1

            if s1 > s2:
                table[t1]["فوز"] += 1
                table[t2]["خسارة"] += 1
                table[t1]["نقاط"] += 3
            elif s2 > s1:
                table[t2]["فوز"] += 1
                table[t1]["خسارة"] += 1
                table[t2]["نقاط"] += 3
            else:
                table[t1]["تعادل"] += 1
                table[t2]["تعادل"] += 1
                table[t1]["نقاط"] += 1
                table[t2]["نقاط"] += 1

        rows = []
        for row in table.values():
            row["فرق"] = row["له"] - row["عليه"]
            rows.append(row)
        rows.sort(key=lambda r: (-r["نقاط"], -r["فرق"], -r["له"], r["عليه"], r["الفريق"]))
        standings[group_name] = rows

    return standings



RESULTS_SHEET_HEADERS = [
    "id",
    "schedule_key",
    "day_name",
    "day_label",
    "sport",
    "sport_label",
    "version",
    "version_label",
    "group",
    "team1",
    "team2",
    "score1",
    "score2",
    "match_time",
    "match_text",
    "played_at",
]


def _row_get_ci(row: Dict[str, Any], *names: str) -> Any:
    if not isinstance(row, dict):
        return ""
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for name in names:
        key = str(name).strip().lower()
        if key in lowered and lowered[key] not in (None, ""):
            return lowered[key]
    return ""


def normalize_result_record(raw: Dict[str, Any], fallback_day: str = "") -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    day_name = str(_row_get_ci(raw, "day_name", "day", "اليوم") or fallback_day or "").strip()
    if day_name in ("1", "يوم 1", "اليوم الأول", "اليوم الاول"):
        day_name = "Day1"
    elif day_name in ("2", "يوم 2", "اليوم الثاني"):
        day_name = "Day2"
    if day_name not in DEFAULT_RESULTS_URLS and day_name not in DAY_LABELS:
        # try labels
        for k, label in DAY_LABELS.items():
            if day_name == label:
                day_name = k
                break
    if day_name not in DAY_LABELS:
        return None

    sport = str(_row_get_ci(raw, "sport", "اللعبة") or "").strip()
    # map labels back to keys
    if sport not in SPORTS:
        for k, label in SPORT_LABELS.items():
            if sport == label or sport.lower() == k.lower():
                sport = k
                break
    if sport not in SPORTS:
        return None

    version = str(_row_get_ci(raw, "version", "النسخة") or "1").strip() or "1"
    if version not in ("1", "2"):
        version = "1"

    team1 = clean_team_name(_row_get_ci(raw, "team1", "team_1", "الفريق 1", "الفريق١"))
    team2 = clean_team_name(_row_get_ci(raw, "team2", "team_2", "الفريق 2", "الفريق٢"))
    if not team1 or not team2:
        return None

    try:
        score1 = int(float(str(_row_get_ci(raw, "score1", "score_1", "نتيجة 1", "اهداف 1") or 0).strip() or 0))
        score2 = int(float(str(_row_get_ci(raw, "score2", "score_2", "نتيجة 2", "اهداف 2") or 0).strip() or 0))
    except Exception:
        return None
    if score1 < 0 or score2 < 0:
        return None

    group = str(_row_get_ci(raw, "group", "المجموعة") or "").strip()
    match_time = str(_row_get_ci(raw, "match_time", "time", "التوقيت") or "").strip()
    match_text = str(_row_get_ci(raw, "match_text", "الماتش") or "").strip() or f"{team1} vs {team2}"
    played_at = str(_row_get_ci(raw, "played_at", "updated_at") or "").strip() or (datetime.utcnow().isoformat() + "Z")

    rid = str(_row_get_ci(raw, "id", "schedule_key", "result_id") or "").strip()
    if not rid:
        raw_key = f"{day_name}|{sport}|{version}|{group}|{team1}|{team2}|{match_time}|{match_text}"
        rid = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:20]

    return {
        "id": rid,
        "schedule_key": rid,
        "day_name": day_name,
        "day_label": DAY_LABELS.get(day_name, day_name),
        "sport": sport,
        "sport_label": SPORT_LABELS.get(sport, sport),
        "version": version,
        "version_label": VERSION_LABELS.get(version, version),
        "group": group,
        "team1": team1,
        "team2": team2,
        "score1": score1,
        "score2": score2,
        "match_time": match_time,
        "match_text": match_text,
        "played_at": played_at,
    }


def result_to_sheet_row(result: Dict[str, Any]) -> List[Any]:
    return [result.get(h, "") for h in RESULTS_SHEET_HEADERS]


def build_results_sheet_values(data: Dict[str, Any], day_name: str) -> List[List[Any]]:
    rows = [dict(r) for r in data.get("results", {}).values() if r.get("day_name") == day_name]
    rows.sort(key=lambda r: (str(r.get("sport", "")), str(r.get("match_time", "")), str(r.get("group", "")), str(r.get("id", ""))))
    values = [RESULTS_SHEET_HEADERS[:]]
    for r in rows:
        values.append(result_to_sheet_row(r))
    return values


def fetch_results_rows_via_api(day_name: str) -> Optional[List[Dict[str, Any]]]:
    """Read results tab via Sheets API when service account is configured."""
    if not drive_store.sheets_enabled():
        return None
    links = get_current_sheet_links()
    spreadsheet_id = get_results_spreadsheet_id(links)
    if not spreadsheet_id:
        return None
    preferred_name = str((links.get("results_sheet_names") or {}).get(day_name) or DEFAULT_RESULTS_SHEET_NAMES.get(day_name) or day_name).strip()
    results_url = str((links.get("results") or {}).get(day_name) or "").strip()
    gid = drive_store.extract_gid(results_url)
    try:
        title = drive_store.resolve_sheet_title(spreadsheet_id, preferred_name=preferred_name, gid=gid)
        if not title:
            return None
        svc = drive_store._sheets_service()
        if not svc:
            return None
        safe_title = str(title).replace("'", "''")
        res = svc.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{safe_title}'",
        ).execute()
        values = res.get("values") or []
        if not values:
            return []
        headers = [str(h).strip() for h in values[0]]
        rows = []
        for raw in values[1:]:
            row = {}
            for idx, header in enumerate(headers):
                if not header:
                    continue
                row[header] = raw[idx] if idx < len(raw) else ""
            item = normalize_result_record(row, fallback_day=day_name)
            if item:
                rows.append(item)
        return rows
    except Exception as e:
        print(f"⚠️ results API read failed for {day_name}: {e}")
        return None


def fetch_results_once(day_name: str, url: Optional[str] = None) -> List[Dict[str, Any]]:
    urls = get_current_results_urls()
    target = (url if url is not None else urls.get(day_name, "")).strip()
    if day_name not in DEFAULT_RESULTS_URLS:
        raise ValueError(f"Unknown results day: {day_name}")

    # Prefer live Sheets API read (no publish delay) when available.
    api_rows = fetch_results_rows_via_api(day_name)
    if api_rows is not None:
        all_results_sheet_data[day_name] = api_rows
        return api_rows

    if not target:
        all_results_sheet_data[day_name] = []
        return []
    response = requests.get(target, timeout=20)
    response.raise_for_status()
    response.encoding = "utf-8"
    df = pd.read_csv(StringIO(response.text))
    df.columns = df.columns.str.strip()
    rows = df.fillna("").to_dict(orient="records")
    normalized = []
    for row in rows:
        item = normalize_result_record(row, fallback_day=day_name)
        if item:
            normalized.append(item)
    all_results_sheet_data[day_name] = normalized
    return normalized


def push_results_day_to_google_sheet(data: Dict[str, Any], day_name: str) -> Dict[str, Any]:
    """Write local results for a day into Google Sheets (requires service account edit access)."""
    if day_name not in DEFAULT_RESULTS_URLS:
        return {"ok": False, "skipped": True, "reason": "unknown_day"}
    if not drive_store.sheets_enabled():
        return {"ok": False, "skipped": True, "reason": "sheets_api_disabled"}

    links = ensure_sheet_links(data)
    spreadsheet_id = get_results_spreadsheet_id(links)
    if not spreadsheet_id:
        return {"ok": False, "skipped": True, "reason": "missing_spreadsheet_id"}

    sheet_names = links.get("results_sheet_names") or {}
    preferred_name = str(sheet_names.get(day_name) or DEFAULT_RESULTS_SHEET_NAMES.get(day_name) or day_name).strip()
    results_url = str((links.get("results") or {}).get(day_name) or "").strip()
    gid = drive_store.extract_gid(results_url)

    try:
        title = drive_store.resolve_sheet_title(spreadsheet_id, preferred_name=preferred_name, gid=gid)
        if not title:
            return {"ok": False, "skipped": False, "reason": "sheet_tab_not_found"}
        values = build_results_sheet_values(data, day_name)
        ok = drive_store.write_values(spreadsheet_id, title, values, clear_first=True)
        if not ok:
            return {"ok": False, "skipped": False, "reason": "write_failed"}
        return {
            "ok": True,
            "skipped": False,
            "spreadsheet_id": spreadsheet_id,
            "sheet_title": title,
            "rows": max(0, len(values) - 1),
        }
    except Exception as e:
        print(f"❌ push results {day_name}: {e}")
        return {"ok": False, "skipped": False, "reason": str(e)}


def push_all_results_to_google_sheets(data: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for day in DEFAULT_RESULTS_URLS:
        out[day] = push_results_day_to_google_sheet(data, day)
    return out


def merge_results_from_sheet_rows(data: Dict[str, Any], day_name: str, rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Replace results of a day with sheet rows. Local-only days stay if sheet empty and URL empty is handled by caller."""
    results = data.setdefault("results", {})
    before = len(results)
    # remove current day results then insert sheet rows
    to_delete = [rid for rid, r in results.items() if r.get("day_name") == day_name]
    for rid in to_delete:
        del results[rid]

    added = 0
    for row in rows:
        item = normalize_result_record(row, fallback_day=day_name)
        if not item:
            continue
        rid = item["id"]
        results[rid] = item
        added += 1
    data["results"] = results
    return {"removed": len(to_delete), "added": added, "before": before, "after": len(results)}


def sync_results_from_sheets(save: bool = True) -> Dict[str, Any]:
    """Pull results sheets into local warzone_data results (API first, CSV fallback)."""
    data = load_data()
    ensure_sheet_links(data)
    summary = {"days": {}, "changed": False}
    urls = get_current_results_urls()
    has_api = bool(drive_store.sheets_enabled() and get_results_spreadsheet_id())
    any_configured = has_api or any(str(u or "").strip() for u in urls.values())
    if not any_configured:
        summary["message"] = "no_results_urls_configured"
        return summary

    changed = False
    for day, url in urls.items():
        url = str(url or "").strip()
        if not url and not has_api:
            summary["days"][day] = {"skipped": True, "reason": "empty_url"}
            continue
        try:
            rows = fetch_results_once(day, url)
            # Compare fingerprint
            local_day = [r for r in data.get("results", {}).values() if r.get("day_name") == day]
            def fp(items):
                cleaned = []
                for r in items:
                    cleaned.append((
                        str(r.get("id", "")),
                        str(r.get("team1", "")),
                        str(r.get("team2", "")),
                        str(r.get("score1", "")),
                        str(r.get("score2", "")),
                        str(r.get("sport", "")),
                        str(r.get("version", "")),
                        str(r.get("group", "")),
                        str(r.get("match_time", "")),
                    ))
                return tuple(sorted(cleaned))
            if fp(local_day) != fp(rows):
                stats = merge_results_from_sheet_rows(data, day, rows)
                changed = True
                summary["days"][day] = {"ok": True, "changed": True, **stats, "sheet_rows": len(rows)}
            else:
                summary["days"][day] = {"ok": True, "changed": False, "sheet_rows": len(rows)}
        except Exception as e:
            print(f"❌ Error syncing results {day}: {e}")
            summary["days"][day] = {"ok": False, "error": str(e)}

    summary["changed"] = changed
    if changed and save:
        save_data(data)
    return summary


def get_day_results_list(data: Dict[str, Any], day_name: str, sport: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = [dict(r) for r in data.get("results", {}).values() if r.get("day_name") == day_name]
    if sport:
        if sport not in SPORTS:
            raise HTTPException(status_code=400, detail="اللعبة غير صحيحة")
        rows = [r for r in rows if r.get("sport") == sport]
    for r in rows:
        r["team1"] = apply_team_override(data, r.get("team1", ""))
        r["team2"] = apply_team_override(data, r.get("team2", ""))
        r["match_text"] = apply_overrides_to_match_text(data, r.get("match_text", ""))
    rows.sort(key=lambda r: (str(r.get("sport", "")), str(r.get("match_time", "")), str(r.get("group", ""))))
    return rows


def send_push_to_all(title: str, body: str) -> int:
    if webpush is None:
        print("pywebpush is not installed; notification skipped.")
        return 0
    message_data = json.dumps({"title": title, "body": body}, ensure_ascii=False)
    inactive_subs = []
    for sub_str in list(subscribers):
        sub_data = json.loads(sub_str)
        try:
            webpush(
                subscription_info=sub_data,
                data=message_data,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
        except WebPushException as ex:
            if getattr(ex, "response", None) and ex.response.status_code in [404, 410]:
                inactive_subs.append(sub_str)
        except Exception as ex:
            print(f"Push error: {ex}")
    for sub in inactive_subs:
        subscribers.discard(sub)
    return len(subscribers)


async def sync_google_sheets_loop():
    cycle = 0
    while True:
        cycle += 1
        standing_urls = get_current_standings_urls()
        match_urls = get_current_matches_urls()
        # Results sync every cycle (default ~60s). Standings/matches every other cycle if interval is 60.
        try:
            async with _results_sheet_sync_lock:
                summary = await asyncio.to_thread(sync_results_from_sheets, True)
            if summary.get("changed"):
                print(f"✅ Synced results from Google Sheets: {summary}")
            else:
                print(f"ℹ️ Results sheet check done: {summary.get('message') or 'no changes'}")
        except Exception as e:
            print(f"❌ Error syncing results sheets: {e}")

        # Keep standings/matches refresh around 2 minutes even if results interval is faster.
        if cycle % max(1, int(round(120 / max(RESULTS_SYNC_INTERVAL_SEC, 30)))) == 0 or cycle == 1:
            for key, url in standing_urls.items():
                try:
                    rows = await asyncio.to_thread(fetch_standings_once, key, url)
                    print(f"✅ Updated sheet groups/standings: {key} ({len(rows)} rows)")
                except Exception as e:
                    print(f"❌ Error syncing standings {key}: {e}")
            for day, url in match_urls.items():
                try:
                    rows = await asyncio.to_thread(fetch_matches_once, day, url)
                    print(f"✅ Updated sheet matches: {day} ({len(rows)} rows)")
                except Exception as e:
                    print(f"❌ Error syncing {day}: {e}")
        await asyncio.sleep(max(30, RESULTS_SYNC_INTERVAL_SEC))



# =========================
# Manual Backup / Restore
# =========================
def build_backup_snapshot() -> Dict[str, Any]:
    return {
        "backup_type": "warzone_full_backup",
        "schema_version": 1,
        "created_at": datetime.now().isoformat(),
        "warzone_main": load_data(),
        "registrations": registration_data_module.load_data(),
        "whatsapp_groups": registration_data_module.load_whatsapp_groups(),
    }


@app.get("/api/admin/backup-download")
def download_backup(request: Request):
    require_admin(request)
    snapshot = build_backup_snapshot()
    filename = f"warzone_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    content = json.dumps(snapshot, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/admin/backup-upload")
def upload_backup(request: Request, payload: Dict[str, Any] = Body(...)):
    require_admin(request)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="ملف الباك اب غير صحيح.")
    if payload.get("backup_type") != "warzone_full_backup":
        raise HTTPException(status_code=400, detail="ده مش ملف باك اب War Zone صحيح.")
    warzone_main = payload.get("warzone_main")
    registrations = payload.get("registrations")
    whatsapp_groups = payload.get("whatsapp_groups")
    if not isinstance(warzone_main, dict) or not isinstance(registrations, dict) or not isinstance(whatsapp_groups, dict):
        raise HTTPException(status_code=400, detail="ملف الباك اب ناقص بيانات.")
    if not isinstance(registrations.get("teams"), list):
        raise HTTPException(status_code=400, detail="بيانات الفرق في الباك اب غير صحيحة.")
    if not isinstance(whatsapp_groups.get("groups"), list):
        raise HTTPException(status_code=400, detail="بيانات جروبات الواتساب في الباك اب غير صحيحة.")

    save_data(warzone_main)
    registration_data_module.save_data(registrations)
    registration_data_module.save_whatsapp_groups(whatsapp_groups)
    return {
        "ok": True,
        "message": "تم استرجاع الباك اب بنجاح.",
        "teams_count": len(registrations.get("teams", [])),
        "created_at": payload.get("created_at"),
    }


# =========================
# Static pages
# =========================
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(sync_google_sheets_loop())


@app.get("/")
async def serve_home():
    return FileResponse("index.html")


@app.get("/admin")
async def serve_admin():
    return FileResponse("admin.html")


@app.get("/backup")
async def serve_backup():
    return FileResponse("backup.html")


@app.get("/photos")
async def serve_photos():
    return FileResponse("photos.html")


@app.get("/sheets")
async def serve_sheets():
    return FileResponse("sheets.html")


@app.get("/draw")
async def serve_draw():
    return FileResponse("draw.html")


@app.get("/draw-settings")
async def serve_draw_settings():
    return FileResponse("draw_settings.html")



@app.get("/sw.js")
async def serve_sw():
    return FileResponse("sw.js", media_type="application/javascript")


# =========================
# Admin login routes
# =========================
@app.post("/admin/login")
async def admin_login(payload: LoginPayload, response: Response):
    if payload.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="كلمة السر غير صحيحة")
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=ADMIN_TOKEN,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 12,
    )
    return {"status": "success", "message": "تم تسجيل الدخول"}


@app.post("/admin/logout")
async def admin_logout(response: Response):
    response.delete_cookie(ADMIN_COOKIE_NAME)
    return {"status": "success", "message": "تم تسجيل الخروج"}


# =========================
# Notification routes
# =========================
@app.post("/subscribe")
async def subscribe(subscription: dict = Body(...)):
    subscribers.add(json.dumps(subscription, sort_keys=True))
    return {"status": "success", "total": len(subscribers)}


@app.post("/send-notification")
async def send_notification(payload: NotificationPayload, request: Request):
    require_admin(request)
    sent_to = send_push_to_all(payload.title, payload.body)
    return {"status": "success", "sent_to": sent_to}


# =========================
# Public data routes
# =========================
@app.get("/standings/{sport_name}")
def get_standings(sport_name: str):
    data = load_data()
    sport, version = normalize_sport_and_version(sport_name)
    return calculate_standings(data, sport, version)


@app.get("/matches/{day_name}")
def get_matches(day_name: str):
    data = load_data()
    return apply_overrides_to_match_rows(data, get_schedule_rows(day_name))


@app.get("/day-results/{day_name}")
def get_day_results(day_name: str, sport: Optional[str] = Query(None)):
    if day_name not in ["Day1", "Day2"]:
        raise HTTPException(status_code=404, detail="اليوم غير موجود")
    return get_day_results_list(load_data(), day_name, sport)


@app.get("/finals/{sport_name}")
def get_finals(sport_name: str):
    sport, _ = normalize_sport_and_version(sport_name)
    data = load_data()
    return data.get("finals", {}).get(sport, default_finals_for_sport(sport))


@app.get("/site-settings")
def get_site_settings():
    data = load_data()
    return {"visibility": data.get("visibility", DEFAULT_VISIBILITY.copy())}


@app.get("/draw-state")
def get_draw_state():
    return draw_public_state(load_data())


# =========================
# Admin data routes
# =========================
@app.get("/admin-data")
def get_admin_data(request: Request):
    require_admin(request)
    data = load_data()
    return {
        "sports": SPORTS,
        "sport_labels": SPORT_LABELS,
        "version_labels": VERSION_LABELS,
        "day_labels": DAY_LABELS,
        "groups": get_all_effective_groups(data),
        "groups_list": build_groups_list(data),
        "manual_groups": data.get("groups", {}),
        "raw_team_name_options": build_raw_team_name_options(data),
        "team_name_overrides": get_team_overrides(data),
        "group_overrides": data.get("group_overrides", {}),
        "group_overrides_list": build_group_overrides_list(data),
        "results": get_day_results_list(data, "Day1") + get_day_results_list(data, "Day2"),
        "finals": data.get("finals", {}),
        "visibility": data.get("visibility", DEFAULT_VISIBILITY.copy()),
        "sheet_links": ensure_sheet_links(data),
        "draw": ensure_draw_data(data),
    }


@app.get("/admin/draw-data")
def get_admin_draw_data(request: Request, sport: str = Query("Football"), version: str = Query("1")):
    require_admin(request)
    sport, version = validate_draw_identity(sport, version)
    data = load_data()
    draw = get_draw_record(data, sport, version)
    return {
        "sports": SPORTS,
        "sport_labels": SPORT_LABELS,
        "version_labels": VERSION_LABELS,
        "active_key": ensure_draw_data(data).get("active_key", ""),
        "draw": draw,
        "all_draws": ensure_draw_data(data).get("draws", {}),
        "placeholders": build_draw_placeholder_options(data, sport, version),
        "team_name_overrides": get_team_overrides(data),
    }


@app.get("/admin/draw-placeholders")
def get_admin_draw_placeholders(request: Request, sport: str = Query("Football"), version: str = Query("1")):
    require_admin(request)
    sport, version = validate_draw_identity(sport, version)
    return build_draw_placeholder_options(load_data(), sport, version)


@app.post("/admin/draw/setup")
def save_draw_setup(payload: DrawSetupPayload, request: Request):
    require_admin(request)
    sport, version = validate_draw_identity(payload.sport, payload.version)

    placeholders: List[str] = []
    seen_placeholders = set()
    for item in payload.placeholders:
        clean = clean_team_name(item)
        key = normalize_text(clean)
        if clean and key not in seen_placeholders:
            placeholders.append(clean)
            seen_placeholders.add(key)

    teams: List[str] = []
    seen_teams = set()
    for item in payload.teams:
        clean = clean_team_name(item)
        key = normalize_text(clean)
        if clean and key not in seen_teams:
            teams.append(clean)
            seen_teams.add(key)

    if not placeholders:
        raise HTTPException(status_code=400, detail="اختار الأرقام/الخانات اللي هتدخل القرعة")
    if not teams:
        raise HTTPException(status_code=400, detail="اكتب الفرق اللي هتدخل القرعة")
    if len(placeholders) != len(teams):
        raise HTTPException(status_code=400, detail=f"عدد الفرق لازم يساوي عدد الخانات. الخانات: {len(placeholders)}، الفرق: {len(teams)}")

    data = load_data()
    draw = get_draw_record(data, sport, version)
    remove_draw_aliases(data, draw)
    draw.update({
        "key": make_draw_key(sport, version),
        "sport": sport,
        "sport_label": SPORT_LABELS.get(sport, sport),
        "version": version,
        "version_label": VERSION_LABELS.get(version, version),
        "title": clean_team_name(payload.title) or "قرعة War Zone",
        "placeholders": placeholders,
        "teams": teams,
        "assignments": {},
        "revealed": [],
        "status": "ready",
        "last_event": {"type": "setup", "event_id": hashlib.sha1(datetime.utcnow().isoformat().encode()).hexdigest()[:12], "at": datetime.utcnow().isoformat() + "Z"},
        "applied_aliases": {},
        "updated_at": datetime.utcnow().isoformat() + "Z",
    })
    ensure_draw_data(data)["active_key"] = make_draw_key(sport, version)
    save_data(data)
    return {"status": "success", "message": "تم حفظ إعدادات القرعة وتفعيل صفحة العرض", "draw": draw}


@app.post("/admin/draw/control")
def control_draw(payload: DrawControlPayload, request: Request):
    require_admin(request)
    sport, version = validate_draw_identity(payload.sport, payload.version)
    action = clean_team_name(payload.action)
    if action not in ["set_active", "start", "reveal_next", "shuffle_remaining", "reset"]:
        raise HTTPException(status_code=400, detail="أمر القرعة غير صحيح")

    data = load_data()
    draw_data = ensure_draw_data(data)
    draw = get_draw_record(data, sport, version)
    draw_data["active_key"] = make_draw_key(sport, version)

    if action == "set_active":
        draw["last_event"] = {"type": "set_active", "event_id": hashlib.sha1(datetime.utcnow().isoformat().encode()).hexdigest()[:12], "at": datetime.utcnow().isoformat() + "Z"}
        message = "تم تفعيل القرعة على صفحة العرض"

    elif action == "start":
        if not draw.get("placeholders") or not draw.get("teams"):
            raise HTTPException(status_code=400, detail="احفظ إعدادات القرعة الأول")
        draw["status"] = "running"
        draw["last_event"] = {"type": "start", "event_id": hashlib.sha1(datetime.utcnow().isoformat().encode()).hexdigest()[:12], "at": datetime.utcnow().isoformat() + "Z"}
        message = "بدأت القرعة على صفحة العرض"

    elif action == "reset":
        remove_draw_aliases(data, draw)
        draw["assignments"] = {}
        draw["revealed"] = []
        draw["status"] = "ready" if draw.get("placeholders") and draw.get("teams") else "empty"
        draw["last_event"] = {"type": "reset", "event_id": hashlib.sha1(datetime.utcnow().isoformat().encode()).hexdigest()[:12], "at": datetime.utcnow().isoformat() + "Z"}
        message = "تم تصفير القرعة وحذف الاستبدالات التي نتجت عنها"

    elif action == "reveal_next":
        if not draw.get("placeholders") or not draw.get("teams"):
            raise HTTPException(status_code=400, detail="احفظ إعدادات القرعة الأول")
        assignments = draw.setdefault("assignments", {})
        placeholders = list(draw.get("placeholders", []))
        teams = list(draw.get("teams", []))
        remaining_placeholders = [p for p in placeholders if p not in assignments]
        if not remaining_placeholders:
            draw["status"] = "finished"
            raise HTTPException(status_code=400, detail="كل الخانات اتسحبت بالفعل")
        assigned_teams = {normalize_text(t) for t in assignments.values()}
        remaining_teams = [t for t in teams if normalize_text(t) not in assigned_teams]
        if not remaining_teams:
            draw["status"] = "finished"
            raise HTTPException(status_code=400, detail="كل الفرق اتسحبت بالفعل")
        import random
        # السحب الجديد: الفريق الأول عشوائيًا، وبعده الرقم/الخانة عشوائيًا
        selected_team = random.choice(remaining_teams)
        selected_placeholder = random.choice(remaining_placeholders)
        assignments[selected_placeholder] = selected_team
        draw.setdefault("revealed", []).append(selected_placeholder)
        apply_draw_assignment_alias(data, draw, selected_placeholder, selected_team)
        draw["status"] = "finished" if len(assignments) >= len(placeholders) else "running"
        draw["last_event"] = {
            "type": "reveal",
            "event_id": hashlib.sha1(f"{datetime.utcnow().isoformat()}|{selected_team}|{selected_placeholder}".encode()).hexdigest()[:12],
            "placeholder": selected_placeholder,
            "team": selected_team,
            "revealed_count": len(assignments),
            "total": len(placeholders),
            "at": datetime.utcnow().isoformat() + "Z",
        }
        message = f"تم سحب الفريق {selected_team} ثم الرقم {selected_placeholder}"

    elif action == "shuffle_remaining":
        if not draw.get("placeholders") or not draw.get("teams"):
            raise HTTPException(status_code=400, detail="احفظ إعدادات القرعة الأول")
        import random
        assignments = draw.setdefault("assignments", {})
        placeholders = [p for p in draw.get("placeholders", []) if p not in assignments]
        assigned_teams = {normalize_text(t) for t in assignments.values()}
        remaining_teams = [t for t in draw.get("teams", []) if normalize_text(t) not in assigned_teams]
        if len(placeholders) != len(remaining_teams):
            raise HTTPException(status_code=400, detail="عدد الخانات المتبقية لا يساوي عدد الفرق المتبقية")
        random.shuffle(remaining_teams)
        batch = []
        for placeholder, team in zip(placeholders, remaining_teams):
            assignments[placeholder] = team
            if placeholder not in draw.setdefault("revealed", []):
                draw["revealed"].append(placeholder)
            apply_draw_assignment_alias(data, draw, placeholder, team)
            batch.append({"placeholder": placeholder, "team": team})
        draw["status"] = "finished"
        draw["last_event"] = {
            "type": "shuffle_remaining",
            "event_id": hashlib.sha1(datetime.utcnow().isoformat().encode()).hexdigest()[:12],
            "batch": batch,
            "revealed_count": len(assignments),
            "total": len(draw.get("placeholders", [])),
            "at": datetime.utcnow().isoformat() + "Z",
        }
        message = "تم سحب كل الخانات المتبقية وتحديث الجداول"

    draw["updated_at"] = datetime.utcnow().isoformat() + "Z"
    save_data(data)
    return {"status": "success", "message": message, "draw": draw, "public_state": draw_public_state(data)}


@app.get("/admin/sheet-links")
def get_sheet_links(request: Request):
    require_admin(request)
    data = load_data()
    links = ensure_sheet_links(data)
    return {
        "standings": links["standings"],
        "matches": links["matches"],
        "results": links.get("results", {}),
        "results_sheet_names": links.get("results_sheet_names", {}),
        "results_spreadsheet_id": links.get("results_spreadsheet_id", ""),
        "defaults": default_sheet_links(),
        "sports": SPORTS,
        "sport_labels": SPORT_LABELS,
        "version_labels": VERSION_LABELS,
        "day_labels": DAY_LABELS,
        "standings_labels": {
            key: f"{SPORT_LABELS.get(key[:-1] if key.endswith('2') else key, key)} / {VERSION_LABELS.get('2' if key.endswith('2') else '1')}"
            for key in DEFAULT_SHEET_URLS
        },
        "match_labels": {key: DAY_LABELS.get(key, key) for key in DEFAULT_MATCHES_URLS},
        "result_labels": {key: f"نتايج {DAY_LABELS.get(key, key)}" for key in DEFAULT_RESULTS_URLS},
        "sheets_write_enabled": drive_store.sheets_enabled(),
        "resolved_results_spreadsheet_id": get_results_spreadsheet_id(links),
    }


@app.post("/admin/sheet-links")
def save_sheet_links(payload: SheetLinksPayload, request: Request):
    require_admin(request)
    data = load_data()
    links = ensure_sheet_links(data)
    changed_standings = []
    changed_matches = []
    changed_results = []

    for key in DEFAULT_SHEET_URLS:
        if key in payload.standings:
            new_url = validate_sheet_url(payload.standings[key])
            if links["standings"].get(key) != new_url:
                changed_standings.append(key)
            links["standings"][key] = new_url

    for key in DEFAULT_MATCHES_URLS:
        if key in payload.matches:
            new_url = validate_sheet_url(payload.matches[key])
            if links["matches"].get(key) != new_url:
                changed_matches.append(key)
            links["matches"][key] = new_url

    # Results CSV links (optional empty)
    if payload.results:
        for key in DEFAULT_RESULTS_URLS:
            if key in payload.results:
                new_url = validate_sheet_url(payload.results[key], allow_empty=True)
                if links["results"].get(key) != new_url:
                    changed_results.append(key)
                links["results"][key] = new_url

    if payload.results_sheet_names:
        for key in DEFAULT_RESULTS_URLS:
            if key in payload.results_sheet_names:
                name = str(payload.results_sheet_names.get(key) or "").strip() or DEFAULT_RESULTS_SHEET_NAMES.get(key, key)
                links["results_sheet_names"][key] = name

    # Always accept spreadsheet id from payload when provided (including empty to clear).
    if getattr(payload, "results_spreadsheet_id", None) is not None:
        provided = False
        fields_set = getattr(payload, "model_fields_set", None) or getattr(payload, "__fields_set__", set())
        if "results_spreadsheet_id" in fields_set or str(payload.results_spreadsheet_id or "").strip():
            provided = True
        if provided:
            raw_sid = str(payload.results_spreadsheet_id or "").strip()
            if raw_sid:
                extracted = drive_store.extract_spreadsheet_id(raw_sid) or raw_sid
                links["results_spreadsheet_id"] = extracted
            else:
                # only clear if explicitly sent empty string in payload body
                if "results_spreadsheet_id" in fields_set:
                    links["results_spreadsheet_id"] = ""

    data["sheet_links"] = links
    save_data(data)

    # امسح الكاش عشان أول Refresh يسحب من الروابط الجديدة فورًا.
    for key in changed_standings:
        all_standings_sheet_data[key] = []
    for key in changed_matches:
        all_matches_data[key] = []
    for key in changed_results:
        all_results_sheet_data[key] = []

    return {
        "status": "success",
        "message": "تم حفظ لينكات الشيتات. اضغط تحديث بيانات الشيت الآن لو عايز تسحبها فورًا.",
        "changed_standings": changed_standings,
        "changed_matches": changed_matches,
        "changed_results": changed_results,
        "sheet_links": links,
    }



@app.post("/admin/sheet-links/reset")
def reset_sheet_links(request: Request):
    require_admin(request)
    data = load_data()
    data["sheet_links"] = default_sheet_links()
    save_data(data)
    for key in DEFAULT_SHEET_URLS:
        all_standings_sheet_data[key] = []
    for key in DEFAULT_MATCHES_URLS:
        all_matches_data[key] = []
    for key in DEFAULT_RESULTS_URLS:
        all_results_sheet_data[key] = []
    return {"status": "success", "message": "تم إرجاع كل لينكات الشيتات للأصل", "sheet_links": data["sheet_links"]}


@app.post("/admin/test-sheet-link")
def test_sheet_link(payload: Dict[str, str], request: Request):
    require_admin(request)
    url = validate_sheet_url(payload.get("url", ""), allow_empty=False)
    # If user pasted a normal sheets edit URL / id, report extracted id instead of forcing CSV.
    kind = str(payload.get("kind") or "").strip().lower()
    if kind in ("results_id", "spreadsheet_id") or (not url.startswith("http") or "/edit" in url or "/spreadsheets/d/" in url and "output=csv" not in url):
        sid = drive_store.extract_spreadsheet_id(url)
        if sid and drive_store.sheets_enabled():
            try:
                title = drive_store.resolve_sheet_title(sid, preferred_name=str(payload.get("sheet_name") or ""), gid=drive_store.extract_gid(url))
                return {
                    "status": "success",
                    "message": "تم التعرف على Google Sheet (للكتابة)",
                    "spreadsheet_id": sid,
                    "sheet_title": title,
                    "write_enabled": True,
                }
            except Exception as e:
                return {
                    "status": "success",
                    "message": f"تم استخراج spreadsheet id لكن فشل الوصول عبر API: {e}",
                    "spreadsheet_id": sid,
                    "write_enabled": False,
                }
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        response.encoding = "utf-8"
        df = pd.read_csv(StringIO(response.text))
        df.columns = df.columns.str.strip()
        return {"status": "success", "message": "اللينك شغال وتمت قراءة CSV", "rows": int(len(df)), "columns": list(df.columns)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"اللينك مش شغال أو مش CSV صحيح: {e}")


@app.post("/admin/group")
def save_group(payload: GroupPayload, request: Request):
    require_admin(request)
    sport = payload.sport.strip()
    version = str(payload.version).strip()
    group = payload.group.strip()
    if sport not in SPORTS:
        raise HTTPException(status_code=400, detail="اللعبة غير صحيحة")
    if version not in ["1", "2"]:
        raise HTTPException(status_code=400, detail="التاب غير صحيح")
    if not group:
        raise HTTPException(status_code=400, detail="اسم المجموعة مطلوب")

    teams = []
    seen = set()
    for team in payload.teams:
        clean = clean_team_name(team)
        key = normalize_text(clean)
        if clean and key not in seen:
            teams.append(clean)
            seen.add(key)
    if len(teams) < 2:
        raise HTTPException(status_code=400, detail="لازم تضيف فريقين على الأقل")

    data = load_data()
    data["groups"][sport][version][group] = teams
    save_data(data)
    return {"status": "success", "message": "تم حفظ المجموعة"}


@app.delete("/admin/group")
def delete_group(request: Request, sport: str = Query(...), version: str = Query(...), group: str = Query(...)):
    require_admin(request)
    data = load_data()
    if sport not in SPORTS or version not in ["1", "2"]:
        raise HTTPException(status_code=400, detail="بيانات غير صحيحة")
    groups = data["groups"].get(sport, {}).get(version, {})
    if group not in groups:
        raise HTTPException(status_code=404, detail="المجموعة غير موجودة")
    del groups[group]
    # سيب النتائج محفوظة للرجوع، لكنها لن تؤثر على الترتيب لو المجموعة اتحذفت
    save_data(data)
    return {"status": "success", "message": "تم حذف المجموعة"}


@app.post("/admin/group-override")
def save_group_override(payload: GroupOverridePayload, request: Request):
    require_admin(request)
    sport = clean_team_name(payload.sport)
    version = clean_team_name(payload.version)
    action = clean_team_name(payload.action)
    if sport not in SPORTS:
        raise HTTPException(status_code=400, detail="اللعبة غير صحيحة")
    if version not in ["1", "2"]:
        raise HTTPException(status_code=400, detail="التاب غير صحيح")
    if action not in ["add_team", "hide_team", "move_team", "hide_group"]:
        raise HTTPException(status_code=400, detail="نوع التعديل غير صحيح")

    record: Dict[str, Any] = {
        "sport": sport,
        "version": version,
        "action": action,
        "group": clean_team_name(payload.group),
        "team": clean_team_name(payload.team),
        "from_group": clean_team_name(payload.from_group),
        "to_group": clean_team_name(payload.to_group),
    }

    if action == "add_team" and (not record["group"] or not record["team"]):
        raise HTTPException(status_code=400, detail="اختار المجموعة واكتب اسم الفريق الجديد")
    if action == "hide_team" and (not record["group"] or not record["team"]):
        raise HTTPException(status_code=400, detail="اختار المجموعة والفريق اللي هيتشال")
    if action == "move_team" and (not record["team"] or not record["to_group"]):
        raise HTTPException(status_code=400, detail="اختار الفريق والمجموعة الجديدة")
    if action == "hide_group" and not record["group"]:
        raise HTTPException(status_code=400, detail="اختار المجموعة اللي هتتشال")

    record["id"] = make_group_override_id(record)
    record["created_at"] = datetime.utcnow().isoformat() + "Z"
    data = load_data()
    overrides = get_group_overrides(data, sport, version)
    if not any(str(o.get("id")) == record["id"] for o in overrides):
        overrides.append(record)
    save_data(data)
    return {"status": "success", "message": "تم حفظ تعديل المجموعات فوق الشيت", "override": record, "groups": get_effective_groups(data, sport, version)}


@app.delete("/admin/group-override/{override_id}")
def delete_group_override(override_id: str, request: Request):
    require_admin(request)
    data = load_data()
    removed = False
    for sport in SPORTS:
        for version in ["1", "2"]:
            overrides = get_group_overrides(data, sport, version)
            before = len(overrides)
            data["group_overrides"][sport][version] = [o for o in overrides if str(o.get("id")) != override_id]
            if len(data["group_overrides"][sport][version]) != before:
                removed = True
    if not removed:
        raise HTTPException(status_code=404, detail="التعديل غير موجود")
    save_data(data)
    return {"status": "success", "message": "تم حذف التعديل"}


@app.delete("/admin/group-overrides")
def reset_group_overrides(request: Request, sport: Optional[str] = Query(None), version: Optional[str] = Query(None)):
    require_admin(request)
    data = load_data()
    if sport and sport not in SPORTS:
        raise HTTPException(status_code=400, detail="اللعبة غير صحيحة")
    if version and version not in ["1", "2"]:
        raise HTTPException(status_code=400, detail="التاب غير صحيح")

    sports_to_clear = [sport] if sport else SPORTS
    versions_to_clear = [version] if version else ["1", "2"]
    for s in sports_to_clear:
        for v in versions_to_clear:
            data.setdefault("group_overrides", {}).setdefault(s, {})[v] = []
    save_data(data)
    return {"status": "success", "message": "تم مسح تعديلات المجموعات والرجوع للشيت/البديل"}


@app.get("/admin/available-schedule-matches")
def available_schedule_matches(request: Request, day_name: str = "Day1", sport: str = "Football"):
    require_admin(request)
    return build_available_schedule_matches(day_name, sport)


@app.post("/admin/result")
def save_result(payload: ResultPayload, request: Request):
    require_admin(request)
    data = load_data()
    ensure_result_valid(data, payload)
    key = payload.schedule_key.strip()
    if not key:
        raw = f"{payload.day_name}|{payload.sport}|{payload.version}|{payload.group}|{payload.team1}|{payload.team2}|{payload.match_time}|{payload.match_text}"
        key = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]

    team1_canonical = canonical_team_name(data, payload.sport, payload.version, payload.group, payload.team1)
    team2_canonical = canonical_team_name(data, payload.sport, payload.version, payload.group, payload.team2)

    data.setdefault("results", {})
    data["results"][key] = {
        "id": key,
        "schedule_key": key,
        "day_name": payload.day_name,
        "day_label": DAY_LABELS.get(payload.day_name, payload.day_name),
        "sport": payload.sport,
        "sport_label": SPORT_LABELS.get(payload.sport, payload.sport),
        "version": payload.version,
        "version_label": VERSION_LABELS.get(payload.version, payload.version),
        "group": payload.group,
        "team1": team1_canonical,
        "team2": team2_canonical,
        "score1": payload.score1,
        "score2": payload.score2,
        "match_time": payload.match_time,
        "match_text": payload.match_text,
        "played_at": datetime.utcnow().isoformat() + "Z",
    }
    save_data(data)

    sheet_sync = push_results_day_to_google_sheet(data, payload.day_name)

    sent_to = 0
    if payload.notify:
        title = f"نتيجة {SPORT_LABELS.get(payload.sport, payload.sport)} 🏆"
        body = f"{team1_canonical} {payload.score1} - {payload.score2} {team2_canonical} | {DAY_LABELS.get(payload.day_name)}"
        sent_to = send_push_to_all(title, body)

    msg = "تم حفظ النتيجة وتحديث الترتيب ونتائج اليوم"
    if sheet_sync.get("ok"):
        msg += " وتم تحديث شيت النتايج ✅"
    elif not sheet_sync.get("skipped"):
        msg += f" (تحذير: فشل تحديث شيت النتايج: {sheet_sync.get('reason')})"

    return {
        "status": "success",
        "message": msg,
        "sent_to": sent_to,
        "result": data["results"][key],
        "standings": calculate_standings(data, payload.sport, payload.version),
        "sheet_sync": sheet_sync,
    }


@app.delete("/admin/result/{result_id}")
def delete_result(result_id: str, request: Request):
    require_admin(request)
    data = load_data()
    if result_id not in data.get("results", {}):
        raise HTTPException(status_code=404, detail="النتيجة غير موجودة")
    day_name = data["results"][result_id].get("day_name") or ""
    del data["results"][result_id]
    save_data(data)
    sheet_sync = push_results_day_to_google_sheet(data, day_name) if day_name else {"ok": False, "skipped": True}
    msg = "تم حذف النتيجة والماتش رجع لقائمة التسجيل"
    if sheet_sync.get("ok"):
        msg += " وتم تحديث شيت النتايج ✅"
    return {"status": "success", "message": msg, "sheet_sync": sheet_sync}


@app.post("/admin/team-name-override")
def save_team_name_override(payload: TeamNameOverridePayload, request: Request):
    require_admin(request)
    old_name = clean_team_name(payload.old_name)
    new_name = clean_team_name(payload.new_name)
    if not old_name or not new_name:
        raise HTTPException(status_code=400, detail="اكتب الاسم القديم والاسم الجديد")
    data = load_data()
    data.setdefault("team_name_overrides", {})
    data["team_name_overrides"][old_name] = new_name
    save_data(data)
    return {"status": "success", "message": "تم حفظ استبدال الاسم. هيتطبق على المجموعات وجدول الماتشات والنتائج."}


@app.delete("/admin/team-name-override")
def delete_team_name_override(request: Request, old_name: str = Query(...)):
    require_admin(request)
    data = load_data()
    overrides = data.setdefault("team_name_overrides", {})
    found_key = None
    for key in list(overrides.keys()):
        if normalize_text(key) == normalize_text(old_name):
            found_key = key
            break
    if not found_key:
        raise HTTPException(status_code=404, detail="الاستبدال غير موجود")
    del overrides[found_key]
    save_data(data)
    return {"status": "success", "message": "تم حذف استبدال الاسم"}


@app.post("/admin/reload-sheets")
def reload_sheets(request: Request):
    require_admin(request)
    standings_count = 0
    matches_count = 0
    results_count = 0
    errors = []
    standing_urls = get_current_standings_urls()
    match_urls = get_current_matches_urls()
    for key, url in standing_urls.items():
        try:
            standings_count += len(fetch_standings_once(key, url))
        except Exception as e:
            errors.append(f"{key}: {e}")
    for day, url in match_urls.items():
        try:
            matches_count += len(fetch_matches_once(day, url))
        except Exception as e:
            errors.append(f"{day}: {e}")
    try:
        results_summary = sync_results_from_sheets(save=True)
        for day, info in (results_summary.get("days") or {}).items():
            if info.get("ok"):
                results_count += int(info.get("sheet_rows") or 0)
            elif not info.get("skipped"):
                errors.append(f"results:{day}: {info.get('error') or info.get('reason')}")
    except Exception as e:
        errors.append(f"results: {e}")
        results_summary = {"error": str(e)}
    return {
        "status": "success",
        "message": "تم تحديث بيانات الشيت",
        "standings_rows": standings_count,
        "matches_rows": matches_count,
        "results_rows": results_count,
        "results_summary": results_summary,
        "errors": errors,
    }


@app.post("/admin/results-sheet/push")
def push_results_sheet_now(request: Request):
    """Force push local results into the configured Google results spreadsheet."""
    require_admin(request)
    data = load_data()
    out = push_all_results_to_google_sheets(data)
    ok_any = any(v.get("ok") for v in out.values())
    return {
        "status": "success" if ok_any else "error",
        "message": "تم دفع النتايج للشيت" if ok_any else "فشل دفع النتايج للشيت — تأكد من لينك/صلاحيات الـ Service Account",
        "days": out,
        "write_enabled": drive_store.sheets_enabled(),
        "spreadsheet_id": get_results_spreadsheet_id(),
    }


@app.post("/admin/results-sheet/pull")
def pull_results_sheet_now(request: Request):
    """Force pull results from published CSV links into the site."""
    require_admin(request)
    summary = sync_results_from_sheets(save=True)
    return {"status": "success", "message": "تم سحب النتايج من الشيت", "summary": summary}


@app.post("/admin/finals")
def save_finals(payload: FinalsPayload, request: Request):
    require_admin(request)
    sport = payload.sport.strip()
    if sport not in SPORTS:
        raise HTTPException(status_code=400, detail="اللعبة غير صحيحة")
    data = load_data()
    data.setdefault("finals", {})
    data["finals"][sport] = {
        "sport": sport,
        "semi1": payload.semi1.dict(),
        "semi2": payload.semi2.dict(),
        "final": payload.final.dict(),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    save_data(data)
    return {"status": "success", "message": "تم حفظ النهائيات", "finals": data["finals"][sport]}


@app.post("/admin/visibility")
def save_visibility(payload: VisibilityPayload, request: Request):
    require_admin(request)
    data = load_data()
    current = data.get("visibility", DEFAULT_VISIBILITY.copy())
    for key in DEFAULT_VISIBILITY:
        if key in payload.visibility:
            current[key] = bool(payload.visibility[key])
    data["visibility"] = current
    save_data(data)
    return {"status": "success", "message": "تم تحديث إظهار/إخفاء التابات", "visibility": current}


