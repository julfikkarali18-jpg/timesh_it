import hashlib
import hmac
import html
import math
import os
import json
import re
import urllib.parse
from datetime import date, datetime, timedelta
import gspread
import streamlit as st
import streamlit.components.v1 as components
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

st.set_page_config(
    page_title="TIMESH",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

SPREADSHEET_NAME = "Untitled spreadsheet"
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
PHOTO_DIR = "faculty_photos"
os.makedirs(PHOTO_DIR, exist_ok=True)

USERS_TAB_NAME = "Users"
LOGS_TAB_NAME = "Activity_Logs"
REQUESTS_TAB_NAME = "Feature_Requests"
ATTENDANCE_BASE_TAB_CANDIDATES = ["Sheet8", "Sheet 8", "Attendance", "ATTENDANCE"]
ROSTER_TAB_CANDIDATES = ["Sheet2", "Sheet 2", "Roster", "ROSTER"]
ROSTER_STATUS_COLUMN = "Found_Status"
AUTO_REFRESH_SECONDS = 120
CACHE_TTL_SECONDS = 90

# Sheet8 base period: 01/01/2026 to 20/11/2026; forward projection up to 31/12/2026
BASE_PERIOD_END = date(2026, 11, 20)
PROJECTION_START = date(2026, 11, 21)
YEAR_END_CAP = date(2026, 12, 31)

# National holidays (YYYY-MM-DD); includes 24/11/2026 and 25/12/2026
NATIONAL_HOLIDAYS_2026 = {
    date(2026, 11, 24),
    date(2026, 12, 25),
}

USERS_HEADERS = ["Username", "Name", "Role", "Password_Hash", "Created_At"]
LOGS_HEADERS = ["Timestamp", "Username", "Name", "Role", "Action", "Module", "Details"]
REQUESTS_HEADERS = ["Timestamp", "Username", "Name", "Role", "Question", "Status", "Admin_Note"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

STATUS_OPTIONS = ["All", "(Blanks)", "Exit", "Expire", "OK"]
FORM_STATUS_OPTIONS = ["OK", "Exit", "Expire", ""]

LEAVE_TYPE_OPTIONS = ["CL", "El", "CCL"]
APPLYING_STATUS_OPTIONS = ["YES", "NO"]
TAKE_ACTION_BY_OPTIONS = ["Julfikkar", "Azad", "Safiur"]


def hash_password(password: str, salt: str = "timesh_secure_salt_2026") -> str:
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password), str(stored_hash).strip())


DEFAULT_USERS = {
    "admin": {
        "name": "System Admin",
        "role": "admin",
        "password_hash": hash_password("admin@123"),
        "created_at": "2026-01-01 00:00:00",
    },
    "staff": {
        "name": "Staff User",
        "role": "user",
        "password_hash": hash_password("timesh@123"),
        "created_at": "2026-01-01 00:00:00",
    },
}

NAV_ITEMS = [
    {"key": "Analytics Dashboard", "icon": "📊", "title": "Analytics"},
    {"key": "FACULTY_CORNER", "icon": "👨‍🏫", "title": "FACULTY_CORNER"},
    {"key": "Roster", "icon": "📋", "title": "Roster"},
    {"key": "Leave", "icon": "🗓️", "title": "Leave"},
    {"key": "Do Not Punch", "icon": "🚫", "title": "Do Not Punch"},
    {"key": "Other Sheet Tabs", "icon": "📑", "title": "Other Tabs"},
    {"key": "Users", "icon": "🔐", "title": "Users & Logs"},
]

CHART_COLORS = [
    "#14b8a6", "#38bdf8", "#f59e0b", "#f43f5e", "#a855f7",
    "#22c55e", "#fb923c", "#6366f1", "#ec4899", "#94a3b8",
]

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
}

.stApp {
    background: radial-gradient(circle at top right, rgba(20, 184, 166, 0.08), transparent 36%),
                radial-gradient(circle at top left, rgba(56, 189, 248, 0.07), transparent 32%),
                #0b1120;
    color: #f1f5f9;
}

.login-minimal-brand {
    text-align: center;
    padding: 24px 16px 14px 16px;
}

.login-minimal-title {
    font-size: 32px;
    font-weight: 800;
    color: #f8fafc;
    letter-spacing: 0.6px;
    line-height: 1.15;
}

.login-minimal-sub {
    font-size: 14px;
    font-weight: 500;
    color: #94a3b8;
    margin-top: 4px;
}

section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172a 0%, #0b1120 100%);
    border-right: 1px solid rgba(148, 163, 184, 0.14);
}

section[data-testid="stSidebar"] > div:first-child {
    padding-top: 1.2rem;
}

.sidebar-brand {
    background: linear-gradient(135deg, rgba(20, 184, 166, 0.20), rgba(56, 189, 248, 0.10));
    border: 1px solid rgba(20, 184, 166, 0.38);
    border-radius: 14px;
    padding: 14px 16px;
    margin-bottom: 14px;
}

.sidebar-brand-title {
    font-size: 16px;
    font-weight: 700;
    color: #f8fafc;
    letter-spacing: 0.3px;
}

.sidebar-brand-sub {
    font-size: 12px;
    color: #94a3b8;
    margin-top: 2px;
}

.nav-section-label {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.9px;
    color: #64748b;
    margin: 8px 0 10px 4px;
}

div[data-testid="stSidebar"] div.stButton > button {
    width: 100%;
    text-align: left !important;
    justify-content: flex-start !important;
    background: rgba(15, 23, 42, 0.65);
    border: 1px solid rgba(148, 163, 184, 0.14);
    border-radius: 11px;
    padding: 10px 13px;
    color: #cbd5e1;
    font-weight: 600;
    font-size: 14px;
    transition: all 0.16s ease;
    margin-bottom: 6px;
}

div[data-testid="stSidebar"] div.stButton > button:hover {
    background: rgba(30, 41, 59, 0.9);
    border-color: rgba(20, 184, 166, 0.45);
    color: #f8fafc;
}

div[data-testid="stSidebar"] div.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, rgba(20, 184, 166, 0.24), rgba(13, 148, 136, 0.14)) !important;
    border: 1px solid rgba(45, 212, 191, 0.65) !important;
    border-left: 4px solid #2dd4bf !important;
    color: #5eead4 !important;
    font-weight: 700 !important;
    box-shadow: 0 6px 16px -8px rgba(20, 184, 166, 0.45);
}

.sidebar-info-box {
    background: rgba(15, 23, 42, 0.72);
    border: 1px solid rgba(148, 163, 184, 0.14);
    border-radius: 12px;
    padding: 12px 14px;
    font-size: 12px;
    color: #94a3b8;
    margin-top: 8px;
}

.sidebar-info-row {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 5px;
}

.sidebar-info-row:last-child {
    margin-bottom: 0;
}

.sidebar-info-val {
    color: #e2e8f0;
    font-weight: 600;
    text-align: right;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.page-banner {
    background: linear-gradient(120deg, rgba(17, 24, 39, 0.96), rgba(15, 23, 42, 0.92));
    border: 1px solid rgba(148, 163, 184, 0.16);
    border-left: 4px solid #14b8a6;
    border-radius: 14px;
    padding: 18px 22px;
    margin-bottom: 18px;
    box-shadow: 0 10px 25px -10px rgba(0, 0, 0, 0.55);
}

.page-banner-title {
    font-size: 24px;
    font-weight: 700;
    color: #f8fafc;
    margin: 0;
    line-height: 1.25;
}

.page-banner-meta {
    font-size: 13px;
    color: #94a3b8;
    margin-top: 6px;
}

div[data-testid="stMetric"] {
    background: rgba(17, 24, 39, 0.88);
    border: 1px solid rgba(148, 163, 184, 0.16);
    border-radius: 12px;
    padding: 14px 18px;
    box-shadow: 0 6px 18px -8px rgba(0, 0, 0, 0.45);
}

div[data-testid="stMetric"] label {
    color: #94a3b8 !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
    color: #f8fafc !important;
    font-weight: 700 !important;
}

button[data-baseweb="tab"] {
    background-color: rgba(15, 23, 42, 0.7) !important;
    border: 1px solid rgba(148, 163, 184, 0.14) !important;
    border-radius: 10px 10px 0 0 !important;
    color: #94a3b8 !important;
    font-weight: 600 !important;
    padding: 10px 18px !important;
    margin-right: 6px !important;
}

button[data-baseweb="tab"][aria-selected="true"] {
    background-color: rgba(20, 184, 166, 0.16) !important;
    border-color: rgba(20, 184, 166, 0.5) !important;
    color: #5eead4 !important;
}

.stMain .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #0d9488, #14b8a6);
    color: #06202a;
    font-weight: 700;
    border: none;
    border-radius: 9px;
}

.stMain .stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #14b8a6, #2dd4bf);
    color: #041820;
}

.stMain .stButton > button {
    border-radius: 9px;
    border: 1px solid rgba(148, 163, 184, 0.22);
    font-weight: 500;
}

/* Roster Green Found & Red Not Found buttons */
div[class*="st-key-roster_found_"] button {
    background: linear-gradient(135deg, #15803d, #22c55e) !important;
    color: #ffffff !important;
    border: 1px solid rgba(134, 239, 172, 0.65) !important;
    font-weight: 700 !important;
    box-shadow: 0 4px 12px -4px rgba(34, 197, 94, 0.55);
}

div[class*="st-key-roster_found_"] button:hover {
    background: linear-gradient(135deg, #16a34a, #4ade80) !important;
    color: #052e16 !important;
    border-color: #bbf7d0 !important;
}

div[class*="st-key-roster_not_found_"] button {
    background: linear-gradient(135deg, #be123c, #ef4444) !important;
    color: #ffffff !important;
    border: 1px solid rgba(253, 164, 175, 0.65) !important;
    font-weight: 700 !important;
    box-shadow: 0 4px 12px -4px rgba(239, 68, 68, 0.55);
}

div[class*="st-key-roster_not_found_"] button:hover {
    background: linear-gradient(135deg, #e11d48, #f87171) !important;
    color: #ffffff !important;
    border-color: #fecdd3 !important;
}

.form-panel {
    background: rgba(17, 24, 39, 0.86);
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 14px;
    padding: 18px 20px;
    margin: 12px 0 18px 0;
}

.dept-open-panel {
    background: linear-gradient(180deg, rgba(15, 23, 42, 0.94), rgba(17, 24, 39, 0.90));
    border: 1px solid rgba(45, 212, 191, 0.42);
    border-top: 4px solid #14b8a6;
    border-radius: 16px;
    padding: 18px 20px 14px 20px;
    margin: 14px 0 18px 0;
    box-shadow: 0 12px 26px -12px rgba(0, 0, 0, 0.65);
}

.desig-sub-label {
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.85px;
    color: #94a3b8;
    border-bottom: 1px dashed rgba(148, 163, 184, 0.22);
    padding-bottom: 4px;
    margin: 12px 0 8px 2px;
}

.profile-spotlight-box {
    background: linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(17, 24, 39, 0.95));
    border: 1px solid rgba(45, 212, 191, 0.45);
    border-top: 4px solid #14b8a6;
    border-radius: 14px;
    padding: 18px 20px;
    margin: 12px 0 20px 0;
    box-shadow: 0 12px 28px -12px rgba(0, 0, 0, 0.65);
}

.section-tag {
    display: inline-block;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.7px;
    color: #5eead4;
    background: rgba(20, 184, 166, 0.14);
    border: 1px solid rgba(20, 184, 166, 0.3);
    padding: 3px 9px;
    border-radius: 999px;
    margin-bottom: 10px;
}

.leave-badge {
    display: inline-block;
    padding: 2px 9px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    background: rgba(56, 189, 248, 0.15);
    color: #7dd3fc;
    border: 1px solid rgba(56, 189, 248, 0.3);
}

.found-pill {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    background: rgba(34, 197, 94, 0.18);
    color: #86efac;
    border: 1px solid rgba(34, 197, 94, 0.4);
}

.not-found-pill {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    background: rgba(244, 63, 94, 0.18);
    color: #fda4af;
    border: 1px solid rgba(244, 63, 94, 0.4);
}

.days-pill {
    display: inline-block;
    padding: 2px 9px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    background: rgba(245, 158, 11, 0.16);
    color: #fcd34d;
    border: 1px solid rgba(245, 158, 11, 0.32);
}

.muted-sub {
    color: #94a3b8;
    font-size: 12.5px;
}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def inject_auto_refresh(interval_seconds: int = AUTO_REFRESH_SECONDS, enabled: bool = False):
    if not enabled or interval_seconds <= 0:
        return
    ms = int(interval_seconds * 1000)
    components.html(
        f"""
        <script>
        (function() {{
            if (window.__timeshRefreshTimer) {{
                clearTimeout(window.__timeshRefreshTimer);
            }}
            window.__timeshRefreshTimer = setTimeout(function() {{
                try {{
                    window.parent.location.reload();
                }} catch (e) {{
                    window.location.reload();
                }}
            }}, {ms});
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def render_banner(title, subtitle):
    st.markdown(
        f"<div class='page-banner'>"
        f"<div class='page-banner-title'>{html.escape(title)}</div>"
        f"<div class='page-banner-meta'>{subtitle}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


@st.cache_resource
def get_gspread_client():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
    return gspread.authorize(creds)


@st.cache_resource
def get_spreadsheet(sheet_name):
    return get_gspread_client().open(sheet_name)


def clear_sheet_cache():
    st.cache_data.clear()


@st.cache_resource
def _system_tabs_verified(sheet_name):
    sh = get_spreadsheet(sheet_name)
    existing_titles = {ws.title: ws for ws in sh.worksheets()}

    if USERS_TAB_NAME not in existing_titles:
        ws_users = sh.add_worksheet(title=USERS_TAB_NAME, rows=100, cols=10)
        ws_users.append_row(USERS_HEADERS, value_input_option="USER_ENTERED")
        for uname, info in DEFAULT_USERS.items():
            ws_users.append_row(
                [uname, info["name"], info["role"], info["password_hash"], info.get("created_at", "2026-01-01 00:00:00")],
                value_input_option="USER_ENTERED",
            )
    else:
        ws_users = existing_titles[USERS_TAB_NAME]
        vals = ws_users.get_all_values()
        if not vals:
            ws_users.append_row(USERS_HEADERS, value_input_option="USER_ENTERED")
        if len(vals) <= 1:
            for uname, info in DEFAULT_USERS.items():
                ws_users.append_row(
                    [uname, info["name"], info["role"], info["password_hash"], info.get("created_at", "2026-01-01 00:00:00")],
                    value_input_option="USER_ENTERED",
                )

    if LOGS_TAB_NAME not in existing_titles:
        ws_logs = sh.add_worksheet(title=LOGS_TAB_NAME, rows=1000, cols=10)
        ws_logs.append_row(LOGS_HEADERS, value_input_option="USER_ENTERED")
    elif not existing_titles[LOGS_TAB_NAME].get_all_values():
        existing_titles[LOGS_TAB_NAME].append_row(LOGS_HEADERS, value_input_option="USER_ENTERED")

    if REQUESTS_TAB_NAME not in existing_titles:
        ws_req = sh.add_worksheet(title=REQUESTS_TAB_NAME, rows=500, cols=10)
        ws_req.append_row(REQUESTS_HEADERS, value_input_option="USER_ENTERED")
    elif not existing_titles[REQUESTS_TAB_NAME].get_all_values():
        existing_titles[REQUESTS_TAB_NAME].append_row(REQUESTS_HEADERS, value_input_option="USER_ENTERED")

    return True


def ensure_system_tabs(sheet_name):
    return _system_tabs_verified(sheet_name)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def load_users_from_sheet(sheet_name):
    sh = get_spreadsheet(sheet_name)
    ws = sh.worksheet(USERS_TAB_NAME)
    values = ws.get_all_values()
    users_map = {}
    if not values or len(values) < 2:
        return users_map

    headers = [str(h).strip() for h in values[0]]
    for row_idx, raw in enumerate(values[1:], start=2):
        if not any(str(c).strip() for c in raw):
            continue
        rec = {headers[i]: (raw[i] if i < len(raw) else "") for i in range(len(headers)) if headers[i]}
        uname = str(rec.get("Username", "")).strip().lower()
        if not uname:
            continue
        users_map[uname] = {
            "_sheet_row": row_idx,
            "name": str(rec.get("Name", uname)).strip(),
            "role": str(rec.get("Role", "user")).strip().lower() or "user",
            "password_hash": str(rec.get("Password_Hash", "")).strip(),
            "created_at": str(rec.get("Created_At", "")).strip(),
        }
    return users_map


def add_user_to_sheet(sheet_name, username, full_name, role, raw_password):
    sh = get_spreadsheet(sheet_name)
    ws = sh.worksheet(USERS_TAB_NAME)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row(
        [username.strip().lower(), full_name.strip() or username.strip().lower(), role.strip().lower(), hash_password(raw_password), now_str],
        value_input_option="USER_ENTERED",
    )
    clear_sheet_cache()


def update_user_password_in_sheet(sheet_name, username, new_password):
    sh = get_spreadsheet(sheet_name)
    ws = sh.worksheet(USERS_TAB_NAME)
    values = ws.get_all_values()
    if not values:
        return False
    headers = [str(h).strip() for h in values[0]]
    uname_col = headers.index("Username") + 1 if "Username" in headers else 1
    hash_col = headers.index("Password_Hash") + 1 if "Password_Hash" in headers else 4

    for r_idx in range(2, len(values) + 1):
        cell_u = str(values[r_idx - 1][uname_col - 1]).strip().lower() if len(values[r_idx - 1]) >= uname_col else ""
        if cell_u == username.strip().lower():
            ws.update_cell(r_idx, hash_col, hash_password(new_password))
            clear_sheet_cache()
            return True
    return False


def write_activity_log(sheet_name, actor_user, action, module, details):
    try:
        sh = get_spreadsheet(sheet_name)
        ws_logs = sh.worksheet(LOGS_TAB_NAME)
        u = actor_user or {}
        ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws_logs.append_row(
            [
                ts_str,
                str(u.get("username", "unknown")).strip(),
                str(u.get("name", "Unknown")).strip(),
                str(u.get("role", "user")).strip().upper(),
                str(action).strip(),
                str(module).strip(),
                str(details).strip(),
            ],
            value_input_option="USER_ENTERED",
        )
    except Exception:
        pass


def update_feature_notice_status(sheet_name, sheet_row, new_status, admin_note=""):
    sh = get_spreadsheet(sheet_name)
    ws = sh.worksheet(REQUESTS_TAB_NAME)
    ws.update_cell(int(sheet_row), 6, str(new_status).strip())
    ws.update_cell(int(sheet_row), 7, str(admin_note).strip())
    clear_sheet_cache()


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def load_worksheet_rows_with_index(sheet_name, tab_name):
    sh = get_spreadsheet(sheet_name)
    ws = sh.worksheet(tab_name)
    values = ws.get_all_values()
    if not values:
        return [], []
    headers = [str(h).strip() for h in values[0]]
    rows = []
    for idx, raw_row in enumerate(values[1:], start=2):
        if not any(str(cell).strip() for cell in raw_row):
            continue
        row_dict = {"_sheet_row": idx}
        for col_i, h in enumerate(headers):
            if h:
                row_dict[h] = raw_row[col_i] if col_i < len(raw_row) else ""
        rows.append(row_dict)
    return headers, rows


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_all_tab_names(sheet_name):
    sh = get_spreadsheet(sheet_name)
    return [ws.title for ws in sh.worksheets()]


def parse_sheet_date(raw_val):
    s = str(raw_val).strip()
    if not s:
        return None
    date_part = s.split(" ")[0].strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(date_part, fmt).date()
        except ValueError:
            continue
    return None


def parse_int_safe(raw_val, default=0):
    s = str(raw_val or "").strip()
    if not s:
        return default
    cleaned = re.sub(r"[^0-9.-]", "", s)
    if not cleaned:
        return default
    try:
        return int(float(cleaned))
    except ValueError:
        return default


def is_date_in_range(target_dt: date, start_dt: date, end_dt: date) -> bool:
    if start_dt is not None and end_dt is not None:
        if end_dt < start_dt:
            start_dt, end_dt = end_dt, start_dt
        return start_dt <= target_dt <= end_dt
    if start_dt is not None:
        return target_dt == start_dt
    if end_dt is not None:
        return target_dt == end_dt
    return False


def get_leave_recent_sort_key(row):
    from_dt = parse_sheet_date(row.get("From", ""))
    upto_dt = parse_sheet_date(row.get("Upto", ""))
    primary_dt = from_dt or upto_dt
    secondary_dt = upto_dt or from_dt
    has_date = 1 if (primary_dt is not None or secondary_dt is not None) else 0
    return (has_date, primary_dt.toordinal() if primary_dt else -1, secondary_dt.toordinal() if secondary_dt else -1, row.get("_sheet_row", 0))


def get_dnp_recent_sort_key(row):
    from_dt = parse_sheet_date(row.get("Do Not Punch From", ""))
    upto_dt = parse_sheet_date(row.get("Do Not Punch Upto", ""))
    notif_dt = parse_sheet_date(row.get("Notification Date", ""))
    primary_dt = from_dt or notif_dt or upto_dt
    secondary_dt = upto_dt or from_dt or notif_dt
    has_date = 1 if (primary_dt is not None or secondary_dt is not None) else 0
    return (has_date, primary_dt.toordinal() if primary_dt else -1, secondary_dt.toordinal() if secondary_dt else -1, row.get("_sheet_row", 0))


def get_next_sl_number(rows, sl_column="SL"):
    max_num = 0
    for r in rows:
        raw_sl = str(r.get(sl_column, "")).strip()
        if not raw_sl:
            continue
        match = re.search(r"(\d+)\s*$", raw_sl)
        if match:
            val = int(match.group(1))
            if val > max_num:
                max_num = val
    return str(max_num + 1) if max_num >= 0 else "1"


def sanitize_filename(text):
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(text).strip())
    return cleaned.strip("_") or "faculty"


def find_faculty_photo(emp_code, emp_name):
    candidates = []
    if str(emp_code).strip():
        candidates.append(sanitize_filename(emp_code))
    if str(emp_code).strip() and str(emp_name).strip():
        candidates.append(f"{sanitize_filename(emp_code)}_{sanitize_filename(emp_name)}")
    if str(emp_name).strip():
        candidates.append(sanitize_filename(emp_name))
    for base in candidates:
        for ext in [".png", ".jpg", ".jpeg", ".webp"]:
            p = os.path.join(PHOTO_DIR, base + ext)
            if os.path.exists(p):
                return p
    return None


def save_faculty_photo(uploaded_file, emp_code, emp_name):
    _, ext = os.path.splitext(uploaded_file.name.lower())
    if ext not in [".png", ".jpg", ".jpeg", ".webp"]:
        ext = ".png"
    base = (
        f"{sanitize_filename(emp_code)}_{sanitize_filename(emp_name)}"
        if (str(emp_code).strip() and str(emp_name).strip())
        else sanitize_filename(emp_code or emp_name)
    )
    save_path = os.path.join(PHOTO_DIR, f"{base}{ext}")
    with open(save_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return save_path


def update_sheet_row(sheet_name, tab_name, headers, sheet_row, updated_data):
    sh = get_spreadsheet(sheet_name)
    ws = sh.worksheet(tab_name)
    new_values = [str(updated_data.get(h, "")) for h in headers]
    end_col_letter = gspread.utils.rowcol_to_a1(1, len(headers)).replace("1", "")
    ws.update(f"A{sheet_row}:{end_col_letter}{sheet_row}", [new_values], value_input_option="USER_ENTERED")
    clear_sheet_cache()


def append_sheet_row(sheet_name, tab_name, headers, new_data):
    sh = get_spreadsheet(sheet_name)
    ws = sh.worksheet(tab_name)
    new_values = [str(new_data.get(h, "")) for h in headers]
    ws.append_row(new_values, value_input_option="USER_ENTERED")
    clear_sheet_cache()


def delete_sheet_row(sheet_name, tab_name, sheet_row, actor_user=None):
    if not actor_user or actor_user.get("role") != "admin":
        raise PermissionError("Only Admin users are allowed to delete records.")
    sh = get_spreadsheet(sheet_name)
    ws = sh.worksheet(tab_name)
    ws.delete_rows(int(sheet_row))
    clear_sheet_cache()


def resolve_field_value(row_dict, target_header):
    if target_header in row_dict:
        return str(row_dict.get(target_header, "")).strip()
    norm_target = re.sub(r"[^a-z0-9]", "", target_header.lower())
    for k, v in row_dict.items():
        if k == "_sheet_row":
            continue
        if re.sub(r"[^a-z0-9]", "", str(k).lower()) == norm_target:
            return str(v).strip()
    return ""


def get_roster_found_status(row_dict: dict) -> str:
    val = (
        resolve_field_value(row_dict, ROSTER_STATUS_COLUMN)
        or resolve_field_value(row_dict, "Found / Not Found")
        or resolve_field_value(row_dict, "Roster_Status")
    )
    low = val.strip().lower()
    if low in {"found", "yes", "present", "ok", "true"}:
        return "Found"
    if low in {"not found", "notfound", "no", "absent", "false"}:
        return "Not Found"
    return val.strip()


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_roster_target_col(sheet_name, tab_name):
    sh = get_spreadsheet(sheet_name)
    ws = sh.worksheet(tab_name)
    first_row = ws.row_values(1)
    headers = [str(h).strip() for h in first_row]
    date_cols = []
    for idx, h in enumerate(headers, start=1):
        dt = parse_sheet_date(h)
        if dt is not None:
            date_cols.append((dt, idx))
    if date_cols:
        date_cols.sort(key=lambda x: x[0])
        return date_cols[-1][1], headers[date_cols[-1][1] - 1]

    for idx, h in enumerate(headers, start=1):
        norm_h = re.sub(r"[^a-z0-9]", "", h.lower())
        if norm_h in {"foundstatus", "foundnotfound", "rosterstatus", "status"}:
            return idx, h

    fallback_idx = max(len(headers), 1)
    fallback_name = headers[fallback_idx - 1] if headers else ROSTER_STATUS_COLUMN
    return fallback_idx, fallback_name


def get_roster_date_column_index(headers: list) -> int:
    date_cols = []
    for idx, h in enumerate(headers, start=1):
        dt = parse_sheet_date(str(h).strip())
        if dt is not None:
            date_cols.append((dt, idx))
    if date_cols:
        date_cols.sort(key=lambda x: x[0])
        return date_cols[-1][1]
    for idx, h in enumerate(headers, start=1):
        norm_h = re.sub(r"[^a-z0-9]", "", str(h).lower())
        if norm_h in {"foundstatus", "foundnotfound", "rosterstatus", "status"}:
            return idx
    return max(len(headers), 1)


def get_roster_line_status(row_dict: dict, headers: list) -> str:
    if "_override_status" in row_dict and row_dict["_override_status"]:
        return row_dict["_override_status"]
    date_col_idx = get_roster_date_column_index(headers)
    if 1 <= date_col_idx <= len(headers):
        col_name = headers[date_col_idx - 1]
        val = str(row_dict.get(col_name, "")).strip()
        low = val.lower()
        if low in {"found", "yes", "present", "ok", "true"}:
            return "Found"
        if low in {"not found", "notfound", "no", "absent", "false"}:
            return "Not Found"
        if val:
            return val
    return get_roster_found_status(row_dict)


def save_roster_found_status_instant(sheet_name, tab_name, sheet_row, status_value):
    sh = get_spreadsheet(sheet_name)
    ws = sh.worksheet(tab_name)
    col_idx, col_name = get_roster_target_col(sheet_name, tab_name)
    ws.update_cell(int(sheet_row), int(col_idx), str(status_value).strip())
    return col_name


def roster_sl_sort_key(row_dict: dict):
    raw_sl = resolve_field_value(row_dict, "SL")
    match = re.search(r"(\d+)", raw_sl)
    if match:
        return (0, int(match.group(1)), raw_sl.lower(), row_dict.get("_sheet_row", 0))
    if raw_sl:
        return (1, 0, raw_sl.lower(), row_dict.get("_sheet_row", 0))
    return (2, 0, "", row_dict.get("_sheet_row", 0))


def compute_roster_present_bonus(roster_rows, emp_code: str, emp_name: str, as_of_date: date) -> int:
    if not roster_rows:
        return 0
    norm_code = str(emp_code or "").strip().lower()
    norm_name = re.sub(r"\s+", " ", str(emp_name or "").strip()).lower()
    cap_dt = min(as_of_date, YEAR_END_CAP)
    bonus = 0
    for rr in roster_rows:
        r_code = resolve_field_value(rr, "EMP_Code").lower()
        r_name = re.sub(r"\s+", " ", (resolve_field_value(rr, "EMP_Name") or resolve_field_value(rr, "Emp_Name")).lower())
        matched = (norm_code and r_code and r_code == norm_code) or ((not norm_code or not r_code) and norm_name and r_name == norm_name)
        if not matched or get_roster_found_status(rr) == "Not Found":
            continue
        raw_status = (resolve_field_value(rr, "Attendance_Status") or resolve_field_value(rr, "Status") or resolve_field_value(rr, "Present")).strip().lower()
        if raw_status in {"absent", "a", "leave", "l", "no", "off", "holiday", "not found"}:
            continue
        r_date = parse_sheet_date(resolve_field_value(rr, "Date")) or parse_sheet_date(resolve_field_value(rr, "Roster_Date")) or parse_sheet_date(resolve_field_value(rr, "From"))
        if r_date and PROJECTION_START <= r_date <= cap_dt and (r_date.weekday() == 6 or r_date in NATIONAL_HOLIDAYS_2026):
            bonus += 1
    return bonus


def compute_faculty_working_and_present(
    emp_code: str, emp_name: str, sheet8_rows: list, leave_rows: list, dnp_rows: list,
    roster_rows: list = None, as_of_date: date = None, holidays: set = None,
) -> dict:
    if as_of_date is None:
        as_of_date = date.today()
    if holidays is None:
        holidays = NATIONAL_HOLIDAYS_2026

    norm_code = str(emp_code or "").strip().lower()
    norm_name = re.sub(r"\s+", " ", str(emp_name or "").strip()).lower()

    matched_s8 = None
    for sr in sheet8_rows:
        s_code = resolve_field_value(sr, "EMP_Code").lower()
        s_name = re.sub(r"\s+", " ", (resolve_field_value(sr, "EMP_Name") or resolve_field_value(sr, "Emp_Name")).lower())
        if (norm_code and s_code and s_code == norm_code) or ((not norm_code or not s_code) and norm_name and s_name == norm_name):
            matched_s8 = sr
            break

    base_working_days = 0
    base_days_present = 0
    found_in_sheet8 = False
    if matched_s8 is not None:
        found_in_sheet8 = True
        base_working_days = parse_int_safe(
            resolve_field_value(matched_s8, "Total Working days") or resolve_field_value(matched_s8, "Total_Working_Days") or resolve_field_value(matched_s8, "Working Days"),
            0,
        )
        base_days_present = parse_int_safe(
            resolve_field_value(matched_s8, "Total Days Present") or resolve_field_value(matched_s8, "Total_Days_Present") or resolve_field_value(matched_s8, "Days Present"),
            0,
        )

    fac_leave_intervals = []
    for lr in leave_rows:
        l_code = resolve_field_value(lr, "EMP_Code").lower()
        l_name = re.sub(r"\s+", " ", (resolve_field_value(lr, "Emp_Name") or resolve_field_value(lr, "EMP_Name")).lower())
        if (norm_code and l_code and l_code == norm_code) or ((not norm_code or not l_code) and norm_name and l_name == norm_name):
            lf, lu = parse_sheet_date(resolve_field_value(lr, "From")), parse_sheet_date(resolve_field_value(lr, "Upto"))
            if lf or lu:
                fac_leave_intervals.append((lf, lu))

    fac_dnp_intervals = []
    for dr in dnp_rows:
        d_code = resolve_field_value(dr, "EMP_Code").lower()
        d_name = re.sub(r"\s+", " ", (resolve_field_value(dr, "EMP_Name") or resolve_field_value(dr, "Emp_Name")).lower())
        if (norm_code and d_code and d_code == norm_code) or ((not norm_code or not d_code) and norm_name and d_name == norm_name):
            df, du = parse_sheet_date(resolve_field_value(dr, "Do Not Punch From")), parse_sheet_date(resolve_field_value(dr, "Do Not Punch Upto"))
            if df or du:
                fac_dnp_intervals.append((df, du))

    effective_end = min(as_of_date, YEAR_END_CAP)
    added_working_days = 0
    excluded_leave_dnp_days = 0
    skipped_sundays_holidays = 0

    curr_dt = PROJECTION_START
    while curr_dt <= effective_end:
        if curr_dt.weekday() == 6 or curr_dt in holidays:
            skipped_sundays_holidays += 1
        elif any(is_date_in_range(curr_dt, lf, lu) for lf, lu in fac_leave_intervals) or any(is_date_in_range(curr_dt, df, du) for df, du in fac_dnp_intervals):
            excluded_leave_dnp_days += 1
        else:
            added_working_days += 1
        curr_dt += timedelta(days=1)

    roster_present_bonus = compute_roster_present_bonus(roster_rows or [], emp_code, emp_name, effective_end)

    return {
        "Found in Sheet8": "Yes" if found_in_sheet8 else "No (0 Base)",
        "Base Period (Sheet8)": "01/01/2026 – 20/11/2026",
        "Calculated Up To": effective_end.strftime("%d/%m/%Y"),
        "Base Working Days (Sheet8)": base_working_days,
        "Added Working Days (Day-by-Day)": added_working_days,
        "Excluded Leave / DNP Days": excluded_leave_dnp_days,
        "Total Working Days": base_working_days + added_working_days,
        "Base Days Present (Sheet8)": base_days_present,
        "Roster Holiday/Sun Present": roster_present_bonus,
        "Total Days Present": base_days_present + roster_present_bonus,
    }


def get_designation_rank(desig_str):
    d = re.sub(r"\s+", " ", str(desig_str or "").strip()).lower()
    if not d or d == "other / unspecified":
        return (99, d)
    if "associate" in d and "prof" in d:
        return (2, d)
    if ("assistant" in d or "asst" in d) and "prof" in d:
        return (3, d)
    if "prof" in d:
        return (1, d)
    if "lecturer" in d:
        return (4, d)
    if any(k in d for k in ("hod", "head", "dean", "principal", "director")):
        return (0, d)
    return (10, d)


def normalize_category_label(raw_cat):
    s = re.sub(r"\s+", " ", str(raw_cat or "").strip()).lower().replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", s).strip()


def compute_ok_category_metrics(ok_rows):
    total_virtual = 0
    pure_inhouse = 0
    for r in ok_rows:
        cat_norm = normalize_category_label(resolve_field_value(r, "CATEGORY"))
        if not cat_norm:
            continue
        if cat_norm in {"pure virtual", "purevirtual", "inhouse virtual", "in house virtual", "inhousevirtual", "inhou virtual"}:
            total_virtual += 1
        elif cat_norm in {"pure inhouse", "pure in house", "pureinhouse", "inhouse", "in house"} or ("inhouse" in cat_norm and "virtual" not in cat_norm):
            pure_inhouse += 1
    return total_virtual, pure_inhouse


def render_html_table(rows, max_rows=300):
    if not rows:
        st.info("No records to display.")
        return

    clean_rows = [{k: v for k, v in r.items() if k != "_sheet_row"} for r in rows[:max_rows]]
    if len(rows) > max_rows:
        st.info(f"Showing first {max_rows} of {len(rows)} records.")

    cols = list(clean_rows[0].keys())
    th_html = "".join(
        f"<th style='position:sticky;top:0;z-index:2;text-align:left;padding:10px 14px;"
        f"border-bottom:1px solid rgba(148,163,184,0.22);background:#0f172a;color:#5eead4;"
        f"font-size:12.5px;font-weight:700;letter-spacing:0.3px;white-space:nowrap;'>{html.escape(str(c))}</th>"
        for c in cols
    )
    body_html_parts = []
    for idx_r, r in enumerate(clean_rows):
        row_bg = "rgba(15, 23, 42, 0.75)" if idx_r % 2 == 0 else "rgba(30, 41, 59, 0.45)"
        tds = "".join(
            f"<td style='padding:9px 14px;border-bottom:1px solid rgba(148,163,184,0.10);"
            f"color:#e2e8f0;white-space:nowrap;'>{html.escape(str(r.get(c, '')))}</td>"
            for c in cols
        )
        body_html_parts.append(f"<tr style='background:{row_bg};'>{tds}</tr>")

    table_html = (
        "<div style='overflow-x:auto;max-height:480px;overflow-y:auto;"
        "border:1px solid rgba(148,163,184,0.18);border-radius:12px;"
        "background:rgba(15,23,42,0.85);box-shadow:0 8px 20px -10px rgba(0,0,0,0.5);'>"
        "<table style='width:100%;border-collapse:collapse;font-size:13.5px;'>"
        f"<thead><tr>{th_html}</tr></thead>"
        f"<tbody>{''.join(body_html_parts)}</tbody>"
        "</table></div>"
    )
    st.markdown(table_html, unsafe_allow_html=True)


def make_slice_url(field_name, label_val):
    qs = urllib.parse.urlencode({
        "slice": "Analytics Dashboard",
        "pie_field": field_name,
        "pie_val": label_val,
    })
    return f"?{qs}"


def build_pie_chart_html(title, rows, field_name, active_field="", active_val="", top_n=8):
    counts = {}
    for r in rows:
        raw_val = str(r.get(field_name, "")).strip()
        label = raw_val if raw_val else "(Blanks)"
        counts[label] = counts.get(label, 0) + 1

    total = sum(counts.values())
    if total == 0:
        return (
            "<div style='border:1px solid rgba(148,163,184,0.18);border-radius:14px;padding:18px;"
            "background:rgba(17,24,39,0.9);'>"
            f"<div style='font-weight:700;font-size:16px;color:#f8fafc;margin-bottom:8px;'>{html.escape(title)}</div>"
            "<div style='color:#94a3b8;font-size:14px;'>No data available.</div></div>"
        )

    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_items) > top_n:
        main_items = sorted_items[:top_n]
        other_count = sum(v for _, v in sorted_items[top_n:])
        if other_count > 0:
            main_items.append(("Others", other_count))
    else:
        main_items = sorted_items

    cx, cy, radius = 92, 92, 82
    slices_svg = []
    legend_html = []

    if len(main_items) == 1:
        lbl, cnt = main_items[0]
        color = CHART_COLORS[0]
        href = html.escape(make_slice_url(field_name, lbl))
        slices_svg.append(
            f"<a href='{href}' target='_self' style='cursor:pointer;'>"
            f"<circle cx='{cx}' cy='{cy}' r='{radius}' fill='{color}'>"
            f"<title>{html.escape(lbl)}: {cnt} (100.0%)</title></circle></a>"
        )
        is_selected = (active_field == field_name and active_val == lbl)
        row_bg = "background:rgba(20,184,166,0.18);border:1px solid rgba(20,184,166,0.4);border-radius:7px;padding:5px 8px;" if is_selected else "padding:5px 8px;border-radius:7px;"
        legend_html.append(
            f"<a href='{href}' target='_self' style='text-decoration:none;display:flex;align-items:center;"
            f"justify-content:space-between;gap:8px;margin-bottom:4px;font-size:13px;color:#f1f5f9;{row_bg}'>"
            f"<span style='display:flex;align-items:center;gap:8px;'>"
            f"<span style='display:inline-block;width:11px;height:11px;border-radius:3px;background:{color};flex-shrink:0;'></span>"
            f"<span>{html.escape(lbl)}</span></span>"
            f"<span style='color:#94a3b8;white-space:nowrap;font-weight:600;'>{cnt} (100.0%)</span></a>"
        )
    else:
        start_angle = -90.0
        for idx, (lbl, cnt) in enumerate(main_items):
            pct = (cnt / total) * 100.0
            sweep = (cnt / total) * 360.0
            end_angle = start_angle + sweep
            large_arc = 1 if sweep > 180.0 else 0

            start_rad = math.radians(start_angle)
            end_rad = math.radians(end_angle)

            x1 = cx + radius * math.cos(start_rad)
            y1 = cy + radius * math.sin(start_rad)
            x2 = cx + radius * math.cos(end_rad)
            y2 = cy + radius * math.sin(end_rad)

            color = CHART_COLORS[idx % len(CHART_COLORS)]
            href = html.escape(make_slice_url(field_name, lbl))
            path_d = (
                f"M {cx},{cy} L {x1:.2f},{y1:.2f} "
                f"A {radius},{radius} 0 {large_arc},1 {x2:.2f},{y2:.2f} Z"
            )
            slices_svg.append(
                f"<a href='{href}' target='_self' style='cursor:pointer;'>"
                f"<path d='{path_d}' fill='{color}' stroke='#111827' stroke-width='2'>"
                f"<title>{html.escape(lbl)}: {cnt} ({pct:.1f}%)</title></path></a>"
            )

            is_selected = (active_field == field_name and active_val == lbl)
            row_bg = "background:rgba(20,184,166,0.18);border:1px solid rgba(20,184,166,0.4);border-radius:7px;padding:5px 8px;" if is_selected else "padding:5px 8px;border-radius:7px;"
            legend_html.append(
                f"<a href='{href}' target='_self' style='text-decoration:none;display:flex;align-items:center;"
                f"justify-content:space-between;gap:8px;margin-bottom:4px;font-size:13px;color:#f1f5f9;{row_bg}'>"
                f"<span style='display:flex;align-items:center;gap:8px;overflow:hidden;text-overflow:ellipsis;'>"
                f"<span style='display:inline-block;width:11px;height:11px;border-radius:3px;background:{color};flex-shrink:0;'></span>"
                f"<span style='overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>{html.escape(lbl)}</span></span>"
                f"<span style='color:#94a3b8;white-space:nowrap;font-weight:600;'>{cnt} ({pct:.1f}%)</span></a>"
            )
            start_angle = end_angle

    svg_block = (
        f"<svg width='184' height='184' viewBox='0 0 184 184' style='flex-shrink:0;'>"
        f"{''.join(slices_svg)}</svg>"
    )

    return (
        "<div style='border:1px solid rgba(148,163,184,0.18);border-radius:14px;padding:18px;"
        "background:rgba(17,24,39,0.9);box-shadow:0 8px 22px -10px rgba(0,0,0,0.5);height:100%;'>"
        f"<div style='font-weight:700;font-size:16px;color:#f8fafc;margin-bottom:12px;'>{html.escape(title)}</div>"
        "<div style='display:flex;align-items:center;gap:18px;flex-wrap:wrap;'>"
        f"{svg_block}"
        f"<div style='flex:1;min-width:155px;max-height:196px;overflow-y:auto;'>{''.join(legend_html)}</div>"
        "</div></div>"
    )


def filter_rows_by_pie_selection(rows, field_name, selected_label):
    if not field_name or not selected_label:
        return []
    return [r for r in rows if (str(r.get(field_name, "")).strip() or "(Blanks)") == selected_label]


def find_option_index(options, current_val):
    curr = str(current_val).strip()
    if not curr:
        return None
    for i, opt in enumerate(options):
        if opt.lower() == curr.lower():
            return i
    return None


def build_leave_suggestions(leave_rows, today_date):
    by_faculty = {}
    for r in leave_rows:
        code = str(r.get("EMP_Code", "")).strip()
        name = str(r.get("Emp_Name", r.get("EMP_Name", ""))).strip()
        sl_val = str(r.get("SL", "")).strip()
        key = code if code else name
        if not key:
            continue

        upto_dt = parse_sheet_date(r.get("Upto", ""))
        from_dt = parse_sheet_date(r.get("From", ""))

        if key not in by_faculty:
            by_faculty[key] = {
                "EMP_Code": code,
                "Emp_Name": name,
                "Emp_Designation": str(r.get("Emp_Designation", "")).strip(),
                "Emp_Department": str(r.get("Emp_Department", "")).strip(),
                "SL": sl_val,
                "Total_Leave_Entries": 0,
                "Latest_Upto_Date": None,
                "Latest_From_Date": None,
                "Last_Leave_Type": str(r.get("Leave_types", "")).strip(),
                "Last_Applying_Status": str(r.get("Applying_Stutas.", r.get("Applying_Status", ""))).strip(),
                "Take_Action_By": str(r.get("Take_Action_By", "")).strip(),
                "Sample_Row": r,
            }

        entry = by_faculty[key]
        entry["Total_Leave_Entries"] += 1
        if not entry["Emp_Name"] and name:
            entry["Emp_Name"] = name
        if not entry["Emp_Designation"] and str(r.get("Emp_Designation", "")).strip():
            entry["Emp_Designation"] = str(r.get("Emp_Designation", "")).strip()
        if not entry["Emp_Department"] and str(r.get("Emp_Department", "")).strip():
            entry["Emp_Department"] = str(r.get("Emp_Department", "")).strip()
        if not entry["SL"] and sl_val:
            entry["SL"] = sl_val

        if upto_dt is not None:
            if entry["Latest_Upto_Date"] is None or upto_dt > entry["Latest_Upto_Date"]:
                entry["Latest_Upto_Date"] = upto_dt
                entry["Latest_From_Date"] = from_dt
                entry["Last_Leave_Type"] = str(r.get("Leave_types", "")).strip()
                entry["Last_Applying_Status"] = str(r.get("Applying_Stutas.", r.get("Applying_Status", ""))).strip()
                if str(r.get("Take_Action_By", "")).strip():
                    entry["Take_Action_By"] = str(r.get("Take_Action_By", "")).strip()
                entry["Sample_Row"] = r

    suggestions = []
    for uid, item in by_faculty.items():
        latest_upto = item["Latest_Upto_Date"]
        if latest_upto is not None:
            days_diff = (today_date - latest_upto).days
            latest_upto_str = latest_upto.strftime("%Y-%m-%d")
        else:
            days_diff = 999999
            latest_upto_str = "No Date"

        suggestions.append({
            "_uid": uid,
            "EMP_Code": item["EMP_Code"],
            "Emp_Name": item["Emp_Name"],
            "Emp_Designation": item["Emp_Designation"],
            "Emp_Department": item["Emp_Department"],
            "SL": item["SL"],
            "Latest_Upto": latest_upto_str,
            "Days_Since_Last_Upto": days_diff if latest_upto is not None else "N/A",
            "Total_Leave_Entries": item["Total_Leave_Entries"],
            "Last_Leave_Type": item["Last_Leave_Type"],
            "Last_Applying_Status": item["Last_Applying_Status"],
            "Take_Action_By": item["Take_Action_By"],
            "Sample_Row": item["Sample_Row"],
            "_sort_days": days_diff,
        })

    suggestions.sort(key=lambda x: x["_sort_days"], reverse=True)
    for rank, s in enumerate(suggestions, start=1):
        s["Priority_Rank"] = rank

    return suggestions


def build_auth_token(username: str, password_hash: str) -> str:
    msg = f"{username.strip().lower()}:{password_hash.strip()}"
    return hmac.new(b"timesh_session_key_2026", msg.encode("utf-8"), hashlib.sha256).hexdigest()


# ================= ENSURE SYSTEM SHEETS & LOAD USERS =================
try:
    ensure_system_tabs(SPREADSHEET_NAME)
    sheet_users_db = load_users_from_sheet(SPREADSHEET_NAME)
except Exception as e:
    st.error(f"Failed to connect or initialize system tabs in Google Sheet: {e}")
    st.stop()

if not sheet_users_db:
    sheet_users_db = dict(DEFAULT_USERS)

if "logged_in_user" not in st.session_state:
    st.session_state["logged_in_user"] = None
if "auto_refresh_enabled" not in st.session_state:
    st.session_state["auto_refresh_enabled"] = False
if "roster_status_overrides" not in st.session_state:
    st.session_state["roster_status_overrides"] = {}

qp_auth_u = str(st.query_params.get("auth_u", "")).strip().lower()
qp_auth_t = str(st.query_params.get("auth_t", "")).strip()

if st.session_state["logged_in_user"] is None and qp_auth_u and qp_auth_t:
    u_match = sheet_users_db.get(qp_auth_u)
    if u_match and hmac.compare_digest(qp_auth_t, build_auth_token(qp_auth_u, u_match["password_hash"])):
        st.session_state["logged_in_user"] = {
            "username": qp_auth_u,
            "name": u_match["name"],
            "role": u_match["role"],
        }

# ================= MINIMAL LOGIN SCREEN =================
if st.session_state["logged_in_user"] is None:
    inject_auto_refresh(AUTO_REFRESH_SECONDS, enabled=st.session_state["auto_refresh_enabled"])
    st.markdown(
        "<div class='login-minimal-brand'>"
        "<div class='login-minimal-title'>TIMESH</div>"
        "<div class='login-minimal-sub'>facuty mangment</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    _, login_col, _ = st.columns([1.2, 1.2, 1.2])
    with login_col:
        with st.form("timesh_login_form"):
            login_username = st.text_input("Username", placeholder="Username").strip().lower()
            login_password = st.text_input("Password", type="password", placeholder="Password")
            submitted = st.form_submit_button("Login", type="primary", use_container_width=True)

        if submitted:
            u_rec = sheet_users_db.get(login_username)
            if u_rec and verify_password(login_password, u_rec["password_hash"]):
                logged_user_obj = {
                    "username": login_username,
                    "name": u_rec["name"],
                    "role": u_rec["role"],
                }
                st.session_state["logged_in_user"] = logged_user_obj
                st.query_params["auth_u"] = login_username
                st.query_params["auth_t"] = build_auth_token(login_username, u_rec["password_hash"])
                write_activity_log(
                    SPREADSHEET_NAME,
                    logged_user_obj,
                    action="Login",
                    module="Authentication",
                    details=f"User '{login_username}' signed in successfully.",
                )
                st.rerun()
            else:
                write_activity_log(
                    SPREADSHEET_NAME,
                    {"username": login_username or "guest", "name": "Unknown", "role": "guest"},
                    action="Failed Login",
                    module="Authentication",
                    details=f"Failed login attempt for username '{login_username}'.",
                )
                st.error("Invalid username or password.")
    st.stop()

current_user = st.session_state["logged_in_user"]
is_admin_user = current_user.get("role") == "admin"

q_params = st.query_params
qp_slice = str(q_params.get("slice", "")).strip()
qp_field = str(q_params.get("pie_field", "")).strip()
qp_val = str(q_params.get("pie_val", "")).strip()

valid_nav_keys = [item["key"] for item in NAV_ITEMS]
if "active_nav_slice" not in st.session_state:
    st.session_state["active_nav_slice"] = qp_slice if qp_slice in valid_nav_keys else "Analytics Dashboard"
elif qp_slice in valid_nav_keys and qp_slice != st.session_state.get("_last_qp_slice"):
    st.session_state["active_nav_slice"] = qp_slice
st.session_state["_last_qp_slice"] = qp_slice

try:
    all_tabs = get_all_tab_names(SPREADSHEET_NAME)
except Exception as e:
    st.error(f"Failed to connect to Google Sheet: {e}")
    st.stop()

faculty_tab_candidates = ["Sheet1", "Sheet 1", "Main Faculty List", "FACULTY CORNER", "Faculty Corner", "FACULTY_CORNER", "Faculty"]
faculty_tab = next((t for t in faculty_tab_candidates if t in all_tabs), all_tabs[0] if all_tabs else None)

roster_tab = next((t for t in ROSTER_TAB_CANDIDATES if t in all_tabs), all_tabs[1] if len(all_tabs) >= 2 else None)

leave_tab_candidates = ["Sheet3", "Sheet 3", "Leave", "Leaves", "Faculty Leave", "FACULTY_LEAVE"]
leave_tab = next((t for t in leave_tab_candidates if t in all_tabs), all_tabs[2] if len(all_tabs) >= 3 else (all_tabs[-1] if all_tabs else None))

dnp_tab_candidates = ["Don Not Punch", "Do Not Punch", "DON NOT PUNCH", "DO NOT PUNCH", "Do_Not_Punch", "Don_Not_Punch"]
dnp_tab = next((t for t in dnp_tab_candidates if t in all_tabs), None)

attendance_base_tab = next((t for t in ATTENDANCE_BASE_TAB_CANDIDATES if t in all_tabs), None)

pending_notices_list = []
if is_admin_user and st.session_state.get("active_nav_slice") == "Users" and REQUESTS_TAB_NAME in all_tabs:
    try:
        _, req_rows_all = load_worksheet_rows_with_index(SPREADSHEET_NAME, REQUESTS_TAB_NAME)
        pending_notices_list = [r for r in req_rows_all if str(r.get("Status", "")).strip().lower() == "pending"]
    except Exception:
        pending_notices_list = []

# ================= SIDEBAR NAVIGATION =================
with st.sidebar:
    st.markdown(
        "<div class='sidebar-brand'>"
        "<div class='sidebar-brand-title'>🎓 TIMESH</div>"
        "<div class='sidebar-brand-sub'>Faculty & Leave Management Suite</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    if is_admin_user and len(pending_notices_list) > 0:
        if st.button(
            f"🔔 Admin Notices ({len(pending_notices_list)} New)",
            key="sidebar_admin_notice_btn",
            use_container_width=True,
        ):
            st.session_state["active_nav_slice"] = "Users"
            st.query_params["slice"] = "Users"
            st.rerun()

    st.markdown("<div class='nav-section-label'>Navigation</div>", unsafe_allow_html=True)

    for nav in NAV_ITEMS:
        is_curr = st.session_state["active_nav_slice"] == nav["key"]
        nav_title = "Security" if (nav["key"] == "Users" and not is_admin_user) else nav["title"]
        if st.button(
            f"{nav['icon']}  {nav_title}",
            key=f"nav_btn_{nav['key']}",
            type="primary" if is_curr else "secondary",
            use_container_width=True,
        ):
            st.session_state["active_nav_slice"] = nav["key"]
            st.query_params["slice"] = nav["key"]
            st.rerun()

    st.markdown(
        f"<div class='sidebar-info-box'>"
        f"<div class='sidebar-info-row'><span>User</span><span class='sidebar-info-val'>{html.escape(str(current_user.get('name', '-')))}</span></div>"
        f"<div class='sidebar-info-row'><span>Role</span><span class='sidebar-info-val'>{html.escape(str(current_user.get('role', '-')).upper())}</span></div>"
        f"<div class='sidebar-info-row'><span>Sheet</span><span class='sidebar-info-val'>{html.escape(SPREADSHEET_NAME)}</span></div>"
        f"<div class='sidebar-info-row'><span>Roster Tab</span><span class='sidebar-info-val'>{html.escape(str(roster_tab or 'Sheet2'))}</span></div>"
        f"<div class='sidebar-info-row'><span>Leave Tab</span><span class='sidebar-info-val'>{html.escape(str(leave_tab or '-'))}</span></div>"
        f"<div class='sidebar-info-row'><span>DNP Tab</span><span class='sidebar-info-val'>{html.escape(str(dnp_tab or 'Don Not Punch'))}</span></div>"
        f"<div class='sidebar-info-row'><span>Auto Refresh</span><span class='sidebar-info-val'>Every {AUTO_REFRESH_SECONDS}s</span></div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.session_state["auto_refresh_enabled"] = st.checkbox(
        f"Auto-refresh every {AUTO_REFRESH_SECONDS}s",
        value=st.session_state["auto_refresh_enabled"],
        key="sidebar_auto_refresh_chk",
    )

    st.write("")
    if st.button("🔄 Refresh Sheet Data", key="sidebar_refresh_btn", use_container_width=True):
        st.session_state["roster_status_overrides"] = {}
        clear_sheet_cache()
        st.rerun()
    if st.button("🚪 Logout", key="sidebar_logout_btn", use_container_width=True):
        write_activity_log(
            SPREADSHEET_NAME,
            current_user,
            action="Logout",
            module="Authentication",
            details=f"User '{current_user.get('username', '')}' logged out.",
        )
        st.session_state["logged_in_user"] = None
        st.query_params.pop("auth_u", None)
        st.query_params.pop("auth_t", None)
        st.rerun()

inject_auto_refresh(AUTO_REFRESH_SECONDS, enabled=st.session_state["auto_refresh_enabled"])

slice_choice = st.session_state["active_nav_slice"]


# ================= SLICE 1: ANALYTICS PIE DASHBOARD =================
if slice_choice == "Analytics Dashboard":
    render_banner(
        "Analytics Dashboard",
        f"Active Filter: <b>Status = OK</b>  |  Spreadsheet: <b>{html.escape(SPREADSHEET_NAME)}</b>  |  Tab: <b>{html.escape(str(faculty_tab))}</b>",
    )
    if not faculty_tab:
        st.warning("No worksheet tab found.")
        st.stop()

    _, all_rows = load_worksheet_rows_with_index(SPREADSHEET_NAME, faculty_tab)
    ok_rows = [r for r in all_rows if str(r.get("Status", "")).strip().lower() == "ok"]
    total_virtual_ok, pure_inhouse_ok = compute_ok_category_metrics(ok_rows)

    m1, m2, m3 = st.columns(3)
    m1.metric("Active Faculty (Status: OK)", len(ok_rows))
    m2.metric("Total_Virtual", total_virtual_ok)
    m3.metric("Pure_Inhouse", pure_inhouse_ok)

    st.write("")
    row1_col1, row1_col2 = st.columns(2)
    with row1_col1:
        st.markdown(build_pie_chart_html("Category Distribution", ok_rows, "CATEGORY", qp_field, qp_val), unsafe_allow_html=True)
    with row1_col2:
        st.markdown(build_pie_chart_html("Department Distribution", ok_rows, "Emp_Department", qp_field, qp_val), unsafe_allow_html=True)

    st.write("")
    row2_col1, _ = st.columns([1, 1])
    with row2_col1:
        st.markdown(build_pie_chart_html("Designation Distribution", ok_rows, "Emp_Designation", qp_field, qp_val), unsafe_allow_html=True)

    valid_pie_fields = {"CATEGORY": "Category", "Emp_Department": "Department", "Emp_Designation": "Designation"}
    if qp_field in valid_pie_fields and qp_val:
        st.divider()
        drill_rows = filter_rows_by_pie_selection(ok_rows, qp_field, qp_val)
        hdr_c1, hdr_c2 = st.columns([4, 1])
        hdr_c1.subheader(f"Filtered Records — {valid_pie_fields[qp_field]}: {qp_val} ({len(drill_rows)})")
        if hdr_c2.button("Clear Selection", use_container_width=True):
            st.query_params.clear()
            st.rerun()
        render_html_table(drill_rows, max_rows=500)


# ================= SLICE 2: FACULTY_CORNER =================
elif slice_choice == "FACULTY_CORNER":
    target_dnp_lookup_tab = dnp_tab or "Don Not Punch"
    target_base_tab = attendance_base_tab or "Sheet8"
    render_banner(
        "FACULTY_CORNER",
        f"Spreadsheet: <b>{html.escape(SPREADSHEET_NAME)}</b>  |  Faculty Tab: <b>{html.escape(str(faculty_tab))}</b>  |  Leave Tab: <b>{html.escape(str(leave_tab))}</b>  |  DNP Tab: <b>{html.escape(str(target_dnp_lookup_tab))}</b>  |  Base Tab: <b>{html.escape(str(target_base_tab))}</b>",
    )
    if not faculty_tab:
        st.warning("No worksheet tab found.")
        st.stop()

    headers, all_rows = load_worksheet_rows_with_index(SPREADSHEET_NAME, faculty_tab)
    faculty_rows = all_rows

    tab_view, tab_edit, tab_add, tab_photo = st.tabs([
        "📋 View Faculty",
        "✏️ Edit Faculty",
        "➕ Add New Faculty",
        "🖼️ Upload Photo",
    ])

    with tab_view:
        if "selected_dept_in_view" not in st.session_state:
            st.session_state["selected_dept_in_view"] = None
        if "selected_faculty_sheet_row" not in st.session_state:
            st.session_state["selected_faculty_sheet_row"] = None

        st.markdown("<div class='form-panel'><div class='section-tag'>Search & Filter</div>", unsafe_allow_html=True)
        f_col1, f_col2, f_col3, f_col4 = st.columns([1.8, 1.1, 1.0, 1.4])
        search_code_name = f_col1.text_input("Search Name / EMP_Code", "", placeholder="Type name or EMP_Code...", key="view_search_code_name").strip().lower()
        search_sl = f_col2.text_input("Search SL", "", placeholder="Type SL...", key="view_search_sl").strip().lower()
        categories = sorted({resolve_field_value(r, "CATEGORY") for r in faculty_rows if resolve_field_value(r, "CATEGORY")})
        sel_status = f_col3.selectbox("Status", STATUS_OPTIONS, index=STATUS_OPTIONS.index("OK"), key="view_status")
        sel_categories = f_col4.multiselect("Category", categories, default=[], placeholder="All Categories", key="view_categories")
        st.markdown("</div>", unsafe_allow_html=True)

        selected_cat_set = {c.strip() for c in sel_categories}
        filtered_rows = []
        for r in faculty_rows:
            row_status = resolve_field_value(r, "Status")
            if sel_status == "(Blanks)" and row_status != "":
                continue
            elif sel_status != "All" and row_status.lower() != sel_status.lower():
                continue
            if selected_cat_set and resolve_field_value(r, "CATEGORY") not in selected_cat_set:
                continue
            if search_sl and search_sl not in resolve_field_value(r, "SL").lower():
                continue
            if search_code_name:
                hay = " ".join([
                    resolve_field_value(r, "EMP_Code"),
                    resolve_field_value(r, "EMP_Name") or resolve_field_value(r, "Emp_Name"),
                    resolve_field_value(r, "Emp_Designation"),
                ]).lower()
                if search_code_name not in hay:
                    continue
            filtered_rows.append(r)

        dept_groups = {}
        for r in filtered_rows:
            dept_name = resolve_field_value(r, "Emp_Department") or "Other / Unassigned Department"
            desig_name = resolve_field_value(r, "Emp_Designation") or "Other / Unspecified"
            dept_groups.setdefault(dept_name, {}).setdefault(desig_name, []).append(r)

        sorted_dept_names = sorted(dept_groups.keys(), key=lambda x: (x == "Other / Unassigned Department", x.lower()))
        active_dept = st.session_state.get("selected_dept_in_view")
        if (search_code_name or search_sl) and len(sorted_dept_names) == 1:
            active_dept = sorted_dept_names[0]
            st.session_state["selected_dept_in_view"] = active_dept
        elif active_dept and active_dept not in dept_groups:
            active_dept = None
            st.session_state["selected_dept_in_view"] = None

        st.markdown("<div class='section-tag'>Departments</div>", unsafe_allow_html=True)
        for d_start in range(0, len(sorted_dept_names), 3):
            d_chunk = sorted_dept_names[d_start:d_start + 3]
            d_cols = st.columns(3)
            for offset, d_name in enumerate(d_chunk):
                d_count = sum(len(v) for v in dept_groups[d_name].values())
                is_open = (active_dept == d_name)
                if d_cols[offset].button(
                    f"🏛️ {d_name} ({d_count})",
                    key=f"dept_select_btn_{d_start}_{offset}",
                    type="primary" if is_open else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["selected_dept_in_view"] = None if is_open else d_name
                    st.session_state["selected_faculty_sheet_row"] = None
                    st.rerun()

        if active_dept and active_dept in dept_groups:
            desig_map = dept_groups[active_dept]
            dept_total = sum(len(v) for v in desig_map.values())
            sorted_desigs = sorted(desig_map.keys(), key=get_designation_rank)
            sel_row_idx = st.session_state.get("selected_faculty_sheet_row")
            selected_fac_row = next((r for r in faculty_rows if r.get("_sheet_row") == sel_row_idx), None)

            st.markdown("<div class='dept-open-panel'>", unsafe_allow_html=True)
            dh1, dh2 = st.columns([4.5, 1])
            dh1.markdown(
                f"<div class='section-tag'>Selected Department</div>"
                f"<div style='font-size:20px;font-weight:700;color:#f8fafc;'>🏛️ {html.escape(active_dept)} "
                f"<span style='font-size:13px;color:#5eead4;font-weight:600;'>({dept_total} Faculty)</span></div>",
                unsafe_allow_html=True,
            )
            if dh2.button("✖ Close Dept", key="close_active_dept_btn", use_container_width=True):
                st.session_state["selected_dept_in_view"] = None
                st.session_state["selected_faculty_sheet_row"] = None
                st.rerun()

            for desig_name in sorted_desigs:
                fac_list = sorted(desig_map[desig_name], key=lambda x: (resolve_field_value(x, "EMP_Name") or resolve_field_value(x, "Emp_Name")).lower())
                st.markdown(f"<div class='desig-sub-label'>{html.escape(desig_name)} ({len(fac_list)})</div>", unsafe_allow_html=True)
                for start_i in range(0, len(fac_list), 4):
                    chunk = fac_list[start_i:start_i + 4]
                    btn_cols = st.columns(4)
                    for col_offset, f_row in enumerate(chunk):
                        f_sheet_row = f_row["_sheet_row"]
                        f_name = resolve_field_value(f_row, "EMP_Name") or resolve_field_value(f_row, "Emp_Name") or "Unnamed"
                        f_code = resolve_field_value(f_row, "EMP_Code")
                        f_sl = resolve_field_value(f_row, "SL")
                        meta_parts = [p for p in [f_code, f"SL:{f_sl}" if f_sl else ""] if p]
                        meta_txt = f" ({', '.join(meta_parts)})" if meta_parts else ""
                        if btn_cols[col_offset].button(
                            f"👤 {f_name}{meta_txt}",
                            key=f"fac_in_dept_btn_{f_sheet_row}",
                            type="primary" if sel_row_idx == f_sheet_row else "secondary",
                            use_container_width=True,
                        ):
                            st.session_state["selected_faculty_sheet_row"] = f_sheet_row
                            st.rerun()

            if selected_fac_row is not None:
                sel_name = resolve_field_value(selected_fac_row, "EMP_Name") or resolve_field_value(selected_fac_row, "Emp_Name") or "Unknown"
                sel_code = resolve_field_value(selected_fac_row, "EMP_Code")
                sel_sl = resolve_field_value(selected_fac_row, "SL")
                sel_desig = resolve_field_value(selected_fac_row, "Emp_Designation")
                sel_dept_name = resolve_field_value(selected_fac_row, "Emp_Department")

                _, sheet3_leave_rows = load_worksheet_rows_with_index(SPREADSHEET_NAME, leave_tab) if leave_tab else ([], [])
                _, dnp_lookup_rows = load_worksheet_rows_with_index(SPREADSHEET_NAME, target_dnp_lookup_tab) if target_dnp_lookup_tab in all_tabs else ([], [])
                _, sheet8_attendance_rows = load_worksheet_rows_with_index(SPREADSHEET_NAME, attendance_base_tab) if attendance_base_tab else ([], [])
                _, roster_lookup_rows = load_worksheet_rows_with_index(SPREADSHEET_NAME, roster_tab) if roster_tab else ([], [])

                st.markdown("<div class='profile-spotlight-box'>", unsafe_allow_html=True)
                top_p1, top_p2 = st.columns([4.5, 1])
                top_p1.markdown(
                    f"<div class='section-tag'>Faculty Details, Working Days & Present Summary</div>"
                    f"<div style='font-size:21px;font-weight:700;color:#f8fafc;'>{html.escape(sel_name)} "
                    f"<span style='font-size:14px;color:#5eead4;font-weight:600;'>({html.escape(sel_code or 'No Code')} · SL: {html.escape(sel_sl or '-')})</span></div>"
                    f"<div class='muted-sub' style='margin-top:2px;'>{html.escape(sel_desig or '-')}  •  {html.escape(sel_dept_name or '-')}</div>",
                    unsafe_allow_html=True,
                )
                if top_p2.button("✖ Close Details", key="close_faculty_spotlight_btn", use_container_width=True):
                    st.session_state["selected_faculty_sheet_row"] = None
                    st.rerun()

                st.write("")
                p_left, p_right = st.columns([1, 3.6])
                with p_left:
                    photo_path = find_faculty_photo(sel_code, sel_name)
                    if photo_path:
                        st.image(photo_path, caption=sel_name, width=165)
                    else:
                        st.info("No photo uploaded.")
                with p_right:
                    st.markdown("<div style='font-weight:700;color:#cbd5e1;font-size:13.5px;margin-bottom:6px;'>📋 Faculty Details</div>", unsafe_allow_html=True)
                    render_html_table([{k: v for k, v in selected_fac_row.items() if k != "_sheet_row"}], max_rows=1)

                att_summary = compute_faculty_working_and_present(
                    sel_code, sel_name, sheet8_attendance_rows, sheet3_leave_rows, dnp_lookup_rows, roster_lookup_rows, date.today(), NATIONAL_HOLIDAYS_2026
                )
                st.write("")
                st.markdown(f"<div style='font-weight:700;color:#2dd4bf;font-size:14.5px;margin-bottom:8px;'>📊 Working Days & Total Days Present ({html.escape(target_base_tab)} + Day-by-Day till 31/12/2026)</div>", unsafe_allow_html=True)
                render_html_table([att_summary], max_rows=1)

                norm_sel_code = sel_code.strip().lower()
                norm_sel_name = re.sub(r"\s+", " ", sel_name.strip()).lower()

                matched_leaves_s3 = [
                    lr for lr in sheet3_leave_rows
                    if (norm_sel_code and resolve_field_value(lr, "EMP_Code").lower() == norm_sel_code)
                    or ((not norm_sel_code or not resolve_field_value(lr, "EMP_Code")) and norm_sel_name and re.sub(r"\s+", " ", (resolve_field_value(lr, "Emp_Name") or resolve_field_value(lr, "EMP_Name")).lower()) == norm_sel_name)
                ]
                matched_leaves_s3.sort(key=get_leave_recent_sort_key, reverse=True)
                st.write("")
                st.markdown(f"<div style='font-weight:700;color:#5eead4;font-size:14.5px;margin-bottom:8px;'>🗓️ Leave Record ({html.escape(str(leave_tab or 'Sheet3'))}) — Total: {len(matched_leaves_s3)}</div>", unsafe_allow_html=True)
                if matched_leaves_s3:
                    render_html_table(matched_leaves_s3, max_rows=200)
                else:
                    st.info(f"No leave records found for {sel_name}.")

                matched_dnp_rows = [
                    dr for dr in dnp_lookup_rows
                    if (norm_sel_code and resolve_field_value(dr, "EMP_Code").lower() == norm_sel_code)
                    or ((not norm_sel_code or not resolve_field_value(dr, "EMP_Code")) and norm_sel_name and re.sub(r"\s+", " ", (resolve_field_value(dr, "EMP_Name") or resolve_field_value(dr, "Emp_Name")).lower()) == norm_sel_name)
                ]
                matched_dnp_rows.sort(key=get_dnp_recent_sort_key, reverse=True)
                st.write("")
                st.markdown(f"<div style='font-weight:700;color:#fbbf24;font-size:14.5px;margin-bottom:8px;'>🚫 Do Not Punch Record ({html.escape(target_dnp_lookup_tab)}) — Total: {len(matched_dnp_rows)}</div>", unsafe_allow_html=True)
                if matched_dnp_rows:
                    render_html_table(matched_dnp_rows, max_rows=200)
                else:
                    st.info(f"No Do Not Punch records found for {sel_name}.")

                st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("</div>", unsafe_allow_html=True)

    with tab_edit:
        st.subheader("Edit Existing Faculty")
        if faculty_rows:
            ec1, ec2 = st.columns([2, 1])
            edit_search_code_name = ec1.text_input("Search by EMP_Code or Name", "", key="edit_search_code_name").strip().lower()
            edit_search_sl = ec2.text_input("Search by SL", "", key="edit_search_sl").strip().lower()

            matched_edit_rows = [
                r for r in faculty_rows
                if (not edit_search_code_name or edit_search_code_name in f"{r.get('EMP_Code', '')} {r.get('EMP_Name', '')}".lower())
                and (not edit_search_sl or edit_search_sl in str(r.get("SL", "")).strip().lower())
            ]

            if not matched_edit_rows:
                st.warning("No matching faculty found for the search criteria.")
            else:
                edit_map = {
                    f"[Row {r['_sheet_row']}] {r.get('EMP_Code', '')} — {r.get('EMP_Name', '')} (SL: {r.get('SL', '')})": r
                    for r in matched_edit_rows
                }
                selected_edit_key = st.selectbox("Select Faculty to Edit", list(edit_map.keys()))
                target_row = edit_map[selected_edit_key]
                row_id = target_row["_sheet_row"]

                existing_col_options = {}
                for h in headers:
                    if h.upper() == "STATUS":
                        opts = list(dict.fromkeys(FORM_STATUS_OPTIONS + [str(r.get(h, "")).strip() for r in all_rows if str(r.get(h, "")).strip()]))
                    else:
                        opts = sorted({str(r.get(h, "")).strip() for r in all_rows if str(r.get(h, "")).strip()})
                    existing_col_options[h] = opts

                st.markdown("<div class='form-panel'><div class='section-tag'>Frozen Identifiers</div>", unsafe_allow_html=True)
                frozen_cols = {"EMP_Code", "EMP_Name", "SL"}
                fc1, fc2, fc3 = st.columns(3)
                fc1.text_input("EMP_Code (Frozen)", value=str(target_row.get("EMP_Code", "")), disabled=True, key=f"edit_frozen_code_{row_id}")
                fc2.text_input("EMP_Name (Frozen)", value=str(target_row.get("EMP_Name", "")), disabled=True, key=f"edit_frozen_name_{row_id}")
                fc3.text_input("SL (Frozen)", value=str(target_row.get("SL", "")), disabled=True, key=f"edit_frozen_sl_{row_id}")
                st.markdown("</div>", unsafe_allow_html=True)

                st.markdown("<div class='form-panel'><div class='section-tag'>Editable Fields</div>", unsafe_allow_html=True)
                editable_headers = [h for h in headers if h not in frozen_cols]
                updated_other_values = {}
                cols = st.columns(2)

                for i, h in enumerate(editable_headers):
                    with cols[i % 2]:
                        curr_val = str(target_row.get(h, "")).strip()
                        opts = existing_col_options.get(h, [])
                        if curr_val and curr_val not in opts:
                            opts = [curr_val] + opts

                        if not opts:
                            updated_other_values[h] = st.text_input(h, value=curr_val, key=f"edit_text_{row_id}_{h}")
                        else:
                            dropdown_choices = list(opts) + ["+ Custom / New Value"]
                            def_idx = dropdown_choices.index(curr_val) if curr_val in dropdown_choices else 0
                            picked = st.selectbox(h, dropdown_choices, index=def_idx, key=f"edit_dd_{row_id}_{h}")
                            if picked == "+ Custom / New Value":
                                updated_other_values[h] = st.text_input(f"Custom {h}", value=curr_val, key=f"edit_custom_{row_id}_{h}")
                            else:
                                updated_other_values[h] = picked

                st.write("")
                if st.button("Save Changes", type="primary"):
                    final_updated = {
                        h: (str(target_row.get(h, "")) if h in frozen_cols else str(updated_other_values.get(h, "")).strip())
                        for h in headers
                    }
                    try:
                        update_sheet_row(SPREADSHEET_NAME, faculty_tab, headers, row_id, final_updated)
                        write_activity_log(
                            SPREADSHEET_NAME,
                            current_user,
                            action="Edit Faculty",
                            module="FACULTY_CORNER",
                            details=f"Updated row {row_id} — EMP_Code: {target_row.get('EMP_Code', '')}, EMP_Name: {target_row.get('EMP_Name', '')}",
                        )
                        st.success("Faculty details updated!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Update failed: {e}")
                st.markdown("</div>", unsafe_allow_html=True)

    with tab_add:
        st.subheader("Add New Faculty")
        next_sl_suggested = get_next_sl_number(all_rows, "SL")

        existing_col_options = {}
        for h in headers:
            if h.upper() == "STATUS":
                opts = list(dict.fromkeys(FORM_STATUS_OPTIONS + [str(r.get(h, "")).strip() for r in all_rows if str(r.get(h, "")).strip()]))
            else:
                opts = sorted({str(r.get(h, "")).strip() for r in all_rows if str(r.get(h, "")).strip()})
            existing_col_options[h] = opts

        st.markdown("<div class='form-panel'><div class='section-tag'>Basic Details</div>", unsafe_allow_html=True)
        top_c1, top_c2, top_c3 = st.columns(3)
        emp_code_input = top_c1.text_input("EMP_Code", "", key="add_emp_code")
        emp_name_input = top_c2.text_input("EMP_Name", "", key="add_emp_name")
        sl_input = top_c3.text_input("SL (Auto Next)", value=next_sl_suggested, key="add_sl_auto")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='form-panel'><div class='section-tag'>Role & Profile</div>", unsafe_allow_html=True)
        other_headers = [h for h in headers if h not in {"EMP_Code", "EMP_Name", "SL"}]
        selected_other_values = {}
        cols = st.columns(2)

        for idx, h in enumerate(other_headers):
            with cols[idx % 2]:
                opts = existing_col_options.get(h, [])
                dropdown_choices = list(opts) + ["+ Custom / New Value"]
                default_idx = 0
                if h.upper() == "CATEGORY" and "Faculty" in opts:
                    default_idx = opts.index("Faculty")
                elif h.upper() == "STATUS" and "OK" in opts:
                    default_idx = opts.index("OK")

                if not opts:
                    selected_other_values[h] = st.text_input(h, value="", key=f"add_text_{h}")
                else:
                    picked = st.selectbox(h, dropdown_choices, index=default_idx, key=f"add_dd_{h}")
                    if picked == "+ Custom / New Value":
                        selected_other_values[h] = st.text_input(f"Custom {h}", value="", key=f"add_custom_{h}")
                    else:
                        selected_other_values[h] = picked

        new_photo = st.file_uploader("Upload Photo (Optional)", type=["png", "jpg", "jpeg", "webp"], key="add_photo")

        if st.button("Add Faculty", type="primary"):
            new_row_dict = {
                h: (
                    emp_code_input.strip() if h == "EMP_Code"
                    else emp_name_input.strip() if h == "EMP_Name"
                    else sl_input.strip() if h == "SL"
                    else str(selected_other_values.get(h, "")).strip()
                )
                for h in headers
            }
            try:
                append_sheet_row(SPREADSHEET_NAME, faculty_tab, headers, new_row_dict)
                if new_photo is not None:
                    save_faculty_photo(new_photo, new_row_dict.get("EMP_Code", ""), new_row_dict.get("EMP_Name", ""))
                write_activity_log(
                    SPREADSHEET_NAME,
                    current_user,
                    action="Add Faculty",
                    module="FACULTY_CORNER",
                    details=f"Added faculty — EMP_Code: {new_row_dict.get('EMP_Code', '')}, EMP_Name: {new_row_dict.get('EMP_Name', '')}, SL: {new_row_dict.get('SL', '')}",
                )
                st.success(f"New faculty added (SL: {new_row_dict.get('SL', '')})!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to add faculty: {e}")
        st.markdown("</div>", unsafe_allow_html=True)

    with tab_photo:
        st.markdown("<div class='form-panel'><div class='section-tag'>Faculty Photo Manager</div>", unsafe_allow_html=True)
        if faculty_rows:
            photo_target_map = {f"{r.get('EMP_Code', '')} — {r.get('EMP_Name', '')}": r for r in faculty_rows}
            p_row = photo_target_map[st.selectbox("Select Faculty", list(photo_target_map.keys()), key="photo_sel")]
            emp_code_val = str(p_row.get("EMP_Code", "")).strip()
            emp_name_val = str(p_row.get("EMP_Name", "")).strip()
            existing_photo = find_faculty_photo(emp_code_val, emp_name_val)
            if existing_photo:
                st.image(existing_photo, caption="Current Photo", width=180)
            uploaded_img = st.file_uploader("Choose Photo", type=["png", "jpg", "jpeg", "webp"], key="photo_up")
            if st.button("Save Photo"):
                if uploaded_img is None:
                    st.warning("Please choose a photo first.")
                else:
                    saved_path = save_faculty_photo(uploaded_img, emp_code_val, emp_name_val)
                    write_activity_log(
                        SPREADSHEET_NAME,
                        current_user,
                        action="Upload Photo",
                        module="FACULTY_CORNER",
                        details=f"Uploaded photo for {emp_name_val} ({emp_code_val}) -> {saved_path}",
                    )
                    st.success(f"Photo saved to: {saved_path}")
                    st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


# ================= SLICE 3: ROSTER (SHEET2) =================
elif slice_choice == "Roster":
    st.query_params["slice"] = "Roster"
    target_roster_tab = roster_tab or "Sheet2"

    render_banner(
        "Roster",
        f"Tab: <b>{html.escape(target_roster_tab)}</b>  |  Sorted by: <b>SL (Ascending)</b>  |  Auto-Refresh: <b>{AUTO_REFRESH_SECONDS}s</b>",
    )

    try:
        roster_headers, roster_rows = load_worksheet_rows_with_index(SPREADSHEET_NAME, target_roster_tab)
    except Exception as e:
        st.error(f"Failed to load '{target_roster_tab}': {e}")
        st.stop()

    if not roster_rows:
        st.info(f"No records found in '{target_roster_tab}'.")
        st.stop()

    overrides = st.session_state["roster_status_overrides"]
    for rr in roster_rows:
        r_num = rr["_sheet_row"]
        if r_num in overrides:
            rr["_override_status"] = overrides[r_num]

    rc1, rc2, rc3 = st.columns([2, 1.2, 0.8])
    r_search = rc1.text_input("Search Name / EMP_Code / SL", "", placeholder="Filter roster...", key="roster_filter_box").strip().lower()
    r_depts = sorted({resolve_field_value(r, "Emp_Department") for r in roster_rows if resolve_field_value(r, "Emp_Department")})
    r_dept = rc2.selectbox("Department", ["All"] + r_depts, key="roster_dept_filter")
    page_size = rc3.selectbox("Rows / Page", [25, 50, 100, 250], index=1, key="roster_page_size")

    filtered_roster = []
    for rr in roster_rows:
        if r_dept != "All" and resolve_field_value(rr, "Emp_Department") != r_dept:
            continue
        if r_search:
            hay = f"{resolve_field_value(rr, 'SL')} {resolve_field_value(rr, 'EMP_Code')} {resolve_field_value(rr, 'EMP_Name') or resolve_field_value(rr, 'Emp_Name')}".lower()
            if r_search not in hay:
                continue
        filtered_roster.append(rr)

    sorted_roster_rows = sorted(filtered_roster, key=roster_sl_sort_key)
    total_pages = max(1, math.ceil(len(sorted_roster_rows) / page_size))
    curr_page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1, key="roster_page_num")
    start_idx = (curr_page - 1) * page_size
    page_rows = sorted_roster_rows[start_idx:start_idx + page_size]

    st.markdown("<div class='form-panel'>", unsafe_allow_html=True)
    for rr in page_rows:
        r_num = rr["_sheet_row"]
        r_code = resolve_field_value(rr, "EMP_Code") or "-"
        r_name = resolve_field_value(rr, "EMP_Name") or resolve_field_value(rr, "Emp_Name") or "-"
        r_desig = resolve_field_value(rr, "Emp_Designation") or "-"
        r_dept_val = resolve_field_value(rr, "Emp_Department") or "-"
        r_sl = resolve_field_value(rr, "SL") or "-"
        curr_status = get_roster_line_status(rr, roster_headers)

        if curr_status == "Found":
            st_badge = "<span class='found-pill'>Found</span>"
        elif curr_status == "Not Found":
            st_badge = "<span class='not-found-pill'>Not Found</span>"
        else:
            st_badge = f"<span class='muted-sub'>{html.escape(curr_status or '-')}</span>"

        c_sl, c_code, c_name, c_desig, c_dept_c, c_st, c_found, c_nf = st.columns(
            [0.65, 1.0, 1.85, 1.45, 1.35, 0.95, 0.85, 1.05]
        )
        c_sl.markdown(f"<span style='font-weight:700;color:#5eead4;'>{html.escape(r_sl)}</span>", unsafe_allow_html=True)
        c_code.markdown(f"<span class='muted-sub'>{html.escape(r_code)}</span>", unsafe_allow_html=True)
        c_name.markdown(f"<div style='font-weight:600;color:#f8fafc;'>{html.escape(r_name)}</div>", unsafe_allow_html=True)
        c_desig.markdown(f"<span class='muted-sub'>{html.escape(r_desig)}</span>", unsafe_allow_html=True)
        c_dept_c.markdown(f"<span class='muted-sub'>{html.escape(r_dept_val)}</span>", unsafe_allow_html=True)
        c_st.markdown(st_badge, unsafe_allow_html=True)

        if c_found.button("Found", key=f"roster_found_{r_num}", use_container_width=True):
            try:
                col_name = save_roster_found_status_instant(SPREADSHEET_NAME, target_roster_tab, r_num, "Found")
                st.session_state["roster_status_overrides"][r_num] = "Found"
                st.session_state["active_nav_slice"] = "Roster"
                st.query_params["slice"] = "Roster"
                write_activity_log(
                    SPREADSHEET_NAME,
                    current_user,
                    action="Roster Found",
                    module="Roster",
                    details=f"SL {r_sl} — {r_name} ({r_code}) marked 'Found' in '{col_name}'.",
                )
                st.toast(f"{r_name}: Found", icon="✅")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")

        if c_nf.button("Not Found", key=f"roster_not_found_{r_num}", use_container_width=True):
            try:
                col_name = save_roster_found_status_instant(SPREADSHEET_NAME, target_roster_tab, r_num, "Not Found")
                st.session_state["roster_status_overrides"][r_num] = "Not Found"
                st.session_state["active_nav_slice"] = "Roster"
                st.query_params["slice"] = "Roster"
                write_activity_log(
                    SPREADSHEET_NAME,
                    current_user,
                    action="Roster Not Found",
                    module="Roster",
                    details=f"SL {r_sl} — {r_name} ({r_code}) marked 'Not Found' in '{col_name}'.",
                )
                st.toast(f"{r_name}: Not Found", icon="❌")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")

        st.markdown("<hr style='margin:6px 0;border:none;border-top:1px solid rgba(148,163,184,0.10);'>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


# ================= SLICE 4: LEAVE MANAGEMENT =================
elif slice_choice == "Leave":
    render_banner(
        "Leave Management",
        f"Spreadsheet: <b>{html.escape(SPREADSHEET_NAME)}</b>  |  Source Tab: <b>{html.escape(str(faculty_tab))}</b>  |  Leave Tab: <b>{html.escape(str(leave_tab))}</b>",
    )
    if not leave_tab:
        st.warning("No leave worksheet tab found.")
        st.stop()

    leave_headers, leave_rows = load_worksheet_rows_with_index(SPREADSHEET_NAME, leave_tab)
    _, sheet1_faculty_rows = load_worksheet_rows_with_index(SPREADSHEET_NAME, faculty_tab) if faculty_tab else ([], [])

    if "active_leave_add_uid" not in st.session_state:
        st.session_state["active_leave_add_uid"] = None
    if "editing_leave_sheet_row" not in st.session_state:
        st.session_state["editing_leave_sheet_row"] = None
    if "confirm_delete_leave_row" not in st.session_state:
        st.session_state["confirm_delete_leave_row"] = None
    if not is_admin_user:
        st.session_state["confirm_delete_leave_row"] = None

    today_val = date.today()
    tab_upcoming, tab_suggest, tab_all_records, tab_add_leave = st.tabs([
        "📅 Upcoming Leave",
        "💡 Leave Suggest",
        "🗂️ All Leave Records",
        "➕ Add Leave",
    ])

    with tab_upcoming:
        st.subheader(f"Upcoming Leave (Upto ≥ {today_val.strftime('%Y-%m-%d')})")
        uc1, uc2, uc3 = st.columns([2, 1, 1])
        leave_search = uc1.text_input("Search by EMP_Code, Name, or SL", "", placeholder="Search faculty...", key="leave_upcoming_search").strip().lower()
        leave_depts = sorted({str(r.get("Emp_Department", "")).strip() for r in leave_rows if str(r.get("Emp_Department", "")).strip()})
        sel_leave_dept = uc2.selectbox("Department", ["All"] + leave_depts, key="leave_upcoming_dept")
        uc3.metric("Today's Date", today_val.strftime("%Y-%m-%d"))

        upcoming_rows = []
        for r in leave_rows:
            upto_dt = parse_sheet_date(r.get("Upto", ""))
            if upto_dt is None or upto_dt < today_val:
                continue
            if sel_leave_dept != "All" and str(r.get("Emp_Department", "")).strip() != sel_leave_dept:
                continue
            if leave_search:
                hay = f"{r.get('EMP_Code', '')} {r.get('Emp_Name', r.get('EMP_Name', ''))} {r.get('SL', '')}".lower()
                if leave_search not in hay:
                    continue
            upcoming_rows.append(r)

        upcoming_rows.sort(key=lambda row: parse_sheet_date(row.get("Upto", "")) or date.max)
        st.metric("Total Upcoming Leave Records", len(upcoming_rows))
        render_html_table(upcoming_rows, max_rows=300)

    with tab_suggest:
        st.subheader("Leave Suggest (Longest Days Since Latest Upto)")
        sc1, sc2 = st.columns([2, 1])
        suggest_search = sc1.text_input("Search by EMP_Code, Name, or SL", "", placeholder="Search faculty...", key="leave_suggest_search").strip().lower()
        suggest_depts = sorted({str(r.get("Emp_Department", "")).strip() for r in leave_rows if str(r.get("Emp_Department", "")).strip()})
        sel_suggest_dept = sc2.selectbox("Department", ["All"] + suggest_depts, key="leave_suggest_dept")

        filtered_source_rows = [
            r for r in leave_rows
            if (sel_suggest_dept == "All" or str(r.get("Emp_Department", "")).strip() == sel_suggest_dept)
            and (not suggest_search or suggest_search in f"{r.get('EMP_Code', '')} {r.get('Emp_Name', r.get('EMP_Name', ''))} {r.get('SL', '')}".lower())
        ]

        suggestion_list = build_leave_suggestions(filtered_source_rows, today_val)
        st.metric("Total Faculty Evaluated", len(suggestion_list))

        selected_uid = st.session_state.get("active_leave_add_uid")
        selected_person = next((s for s in suggestion_list if s["_uid"] == selected_uid), None)

        if selected_person is not None:
            sample = selected_person.get("Sample_Row", {})
            next_leave_sl = get_next_sl_number(leave_rows, "SL")
            st.markdown(
                f"<div class='form-panel'><div class='section-tag'>Add Leave Entry</div>"
                f"<div style='font-size:18px;font-weight:700;color:#f8fafc;margin-bottom:12px;'>"
                f"{html.escape(selected_person['Emp_Name'])} <span class='muted-sub'>({html.escape(selected_person['EMP_Code'])})</span></div>",
                unsafe_allow_html=True,
            )
            f_c1, f_c2, f_c3 = st.columns(3)
            f_c1.text_input("Emp_Name (Frozen)", value=selected_person["Emp_Name"], disabled=True, key=f"lv_f_name_{selected_uid}")
            f_c2.text_input("EMP_Code (Frozen)", value=selected_person["EMP_Code"], disabled=True, key=f"lv_f_code_{selected_uid}")
            f_c3.text_input("SL (Frozen)", value=next_leave_sl, disabled=True, key=f"lv_f_sl_{selected_uid}")

            f_c4, f_c5 = st.columns(2)
            f_c4.text_input("Emp_Designation (Frozen)", value=selected_person["Emp_Designation"], disabled=True, key=f"lv_f_desig_{selected_uid}")
            f_c5.text_input("Emp_Department (Frozen)", value=selected_person["Emp_Department"], disabled=True, key=f"lv_f_dept_{selected_uid}")

            d_c1, d_c2 = st.columns(2)
            from_date_val = d_c1.date_input("From", value=today_val, key=f"lv_edit_from_{selected_uid}")
            upto_date_val = d_c2.date_input("Upto", value=today_val, key=f"lv_edit_upto_{selected_uid}")

            e_c1, e_c2, e_c3 = st.columns(3)
            leave_type_val = e_c1.selectbox("Leave_types", LEAVE_TYPE_OPTIONS, index=None, placeholder="Select Leave Type", key=f"lv_edit_type_{selected_uid}")
            applying_status_val = e_c2.selectbox("Applying_Stutas.", APPLYING_STATUS_OPTIONS, index=None, placeholder="Select Status (YES / NO)", key=f"lv_edit_status_{selected_uid}")
            take_action_by_val = e_c3.selectbox("Take_Action_By", TAKE_ACTION_BY_OPTIONS, index=None, placeholder="Select Action By", key=f"lv_edit_action_{selected_uid}")

            b_c1, b_c2 = st.columns([1.2, 4])
            if b_c1.button("Save Leave", type="primary", key=f"lv_save_btn_{selected_uid}", use_container_width=True):
                if upto_date_val < from_date_val:
                    st.error("Upto date cannot be earlier than From date.")
                else:
                    new_leave_record = {}
                    for h in leave_headers:
                        hc = h.strip()
                        if not hc:
                            continue
                        if hc == "EMP_Code": new_leave_record[h] = selected_person["EMP_Code"]
                        elif hc in {"Emp_Name", "EMP_Name"}: new_leave_record[h] = selected_person["Emp_Name"]
                        elif hc == "Emp_Designation": new_leave_record[h] = selected_person["Emp_Designation"]
                        elif hc == "Emp_Department": new_leave_record[h] = selected_person["Emp_Department"]
                        elif hc == "SL": new_leave_record[h] = next_leave_sl
                        elif hc == "From": new_leave_record[h] = from_date_val.strftime("%Y-%m-%d")
                        elif hc == "Upto": new_leave_record[h] = upto_date_val.strftime("%Y-%m-%d")
                        elif hc == "Leave_types": new_leave_record[h] = str(leave_type_val or "").strip()
                        elif hc in {"Applying_Stutas.", "Applying_Status"}: new_leave_record[h] = str(applying_status_val or "").strip()
                        elif hc == "Take_Action_By": new_leave_record[h] = str(take_action_by_val or "").strip()
                        else: new_leave_record[h] = str(sample.get(h, "")).strip()
                    append_sheet_row(SPREADSHEET_NAME, leave_tab, leave_headers, new_leave_record)
                    write_activity_log(SPREADSHEET_NAME, current_user, "Add Leave", "Leave", f"Added leave for {selected_person['Emp_Name']} ({from_date_val} to {upto_date_val})")
                    st.session_state["active_leave_add_uid"] = None
                    st.success("Leave saved!")
                    st.rerun()
            if b_c2.button("Cancel", key=f"lv_cancel_btn_{selected_uid}"):
                st.session_state["active_leave_add_uid"] = None
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        if suggestion_list:
            st.markdown("<div class='form-panel'><div class='section-tag'>Priority Queue</div>", unsafe_allow_html=True)
            for item in suggestion_list[:100]:
                c_rank, c_code, c_name, c_dept, c_upto, c_days, c_btn = st.columns([0.65, 1.15, 2.1, 1.5, 1.35, 1.2, 0.85])
                c_rank.markdown(f"<span style='color:#5eead4;font-weight:700;'>#{item['Priority_Rank']}</span>", unsafe_allow_html=True)
                c_code.markdown(f"<span class='muted-sub'>{html.escape(item['EMP_Code'] or '-')}</span>", unsafe_allow_html=True)
                c_name.markdown(f"<div style='font-weight:600;color:#f8fafc;'>{html.escape(item['Emp_Name'] or '-')}</div>", unsafe_allow_html=True)
                c_dept.markdown(f"<span class='muted-sub'>{html.escape(item['Emp_Department'] or '-')}</span>", unsafe_allow_html=True)
                c_upto.markdown(f"<span class='muted-sub'>Upto: {html.escape(item['Latest_Upto'])}</span>", unsafe_allow_html=True)
                c_days.markdown(f"<span class='days-pill'>{html.escape(str(item['Days_Since_Last_Upto']))} days</span>", unsafe_allow_html=True)
                if c_btn.button("Add", key=f"btn_add_leave_{item['_uid']}", use_container_width=True):
                    st.session_state["active_leave_add_uid"] = item["_uid"]
                    st.rerun()
                st.markdown("<hr style='margin:6px 0;border:none;border-top:1px solid rgba(148,163,184,0.10);'>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    with tab_all_records:
        st.subheader("All Leave Records")
        ac1, ac2, ac3 = st.columns([2, 1, 1])
        all_lv_search = ac1.text_input("Search by EMP_Code, Name, or SL", "", placeholder="Search faculty...", key="all_leave_search_in_leave").strip().lower()
        all_lv_depts = sorted({str(r.get("Emp_Department", "")).strip() for r in leave_rows if str(r.get("Emp_Department", "")).strip()})
        sel_all_lv_dept = ac2.selectbox("Department", ["All"] + all_lv_depts, key="all_leave_dept_in_leave")
        all_lv_types = sorted({str(r.get("Leave_types", "")).strip() for r in leave_rows if str(r.get("Leave_types", "")).strip()})
        sel_all_lv_type = ac3.selectbox("Leave Type", ["All"] + all_lv_types, key="all_leave_type_in_leave")

        filtered_all_leaves = [
            r for r in leave_rows
            if (sel_all_lv_dept == "All" or str(r.get("Emp_Department", "")).strip() == sel_all_lv_dept)
            and (sel_all_lv_type == "All" or str(r.get("Leave_types", "")).strip() == sel_all_lv_type)
            and (not all_lv_search or all_lv_search in f"{r.get('EMP_Code', '')} {r.get('Emp_Name', r.get('EMP_Name', ''))} {r.get('SL', '')}".lower())
        ]
        filtered_all_leaves.sort(key=get_leave_recent_sort_key, reverse=True)
        st.metric("Total Leave Records Shown", len(filtered_all_leaves))

        editing_row_num = st.session_state.get("editing_leave_sheet_row")
        row_to_edit = next((r for r in leave_rows if r.get("_sheet_row") == editing_row_num), None)
        if row_to_edit is not None:
            edit_name = str(row_to_edit.get("Emp_Name", row_to_edit.get("EMP_Name", ""))).strip()
            edit_code = str(row_to_edit.get("EMP_Code", "")).strip()
            st.markdown(f"<div class='form-panel'><div class='section-tag'>Edit Leave Record</div><div style='font-size:18px;font-weight:700;color:#f8fafc;'>{html.escape(edit_name)} ({html.escape(edit_code)})</div>", unsafe_allow_html=True)
            parsed_from = parse_sheet_date(row_to_edit.get("From", "")) or today_val
            parsed_upto = parse_sheet_date(row_to_edit.get("Upto", "")) or parsed_from
            ed_d1, ed_d2 = st.columns(2)
            ed_from_val = ed_d1.date_input("From", value=parsed_from, key=f"ed_lv_from_{editing_row_num}")
            ed_upto_val = ed_d2.date_input("Upto", value=parsed_upto, key=f"ed_lv_upto_{editing_row_num}")

            curr_ltype = str(row_to_edit.get("Leave_types", "")).strip()
            curr_astatus = str(row_to_edit.get("Applying_Stutas.", row_to_edit.get("Applying_Status", ""))).strip()
            curr_action = str(row_to_edit.get("Take_Action_By", "")).strip()
            ltype_opts = list(dict.fromkeys(LEAVE_TYPE_OPTIONS + ([curr_ltype] if curr_ltype else [])))
            astatus_opts = list(dict.fromkeys(APPLYING_STATUS_OPTIONS + ([curr_astatus] if curr_astatus else [])))
            action_opts = list(dict.fromkeys(TAKE_ACTION_BY_OPTIONS + ([curr_action] if curr_action else [])))

            ed_e1, ed_e2, ed_e3 = st.columns(3)
            ed_ltype_val = ed_e1.selectbox("Leave_types", ltype_opts, index=find_option_index(ltype_opts, curr_ltype), key=f"ed_lv_type_{editing_row_num}")
            ed_astatus_val = ed_e2.selectbox("Applying_Stutas.", astatus_opts, index=find_option_index(astatus_opts, curr_astatus), key=f"ed_lv_status_{editing_row_num}")
            ed_action_val = ed_e3.selectbox("Take_Action_By", action_opts, index=find_option_index(action_opts, curr_action), key=f"ed_lv_action_{editing_row_num}")

            frozen_leave_cols = {"", "EMP_Code", "Emp_Name", "EMP_Name", "Emp_Designation", "Emp_Department", "SL"}
            eb1, eb2 = st.columns([1.2, 4])
            if eb1.button("Update Leave", type="primary", key=f"ed_lv_save_{editing_row_num}", use_container_width=True):
                updated_rec = {}
                for h in leave_headers:
                    hc = h.strip()
                    if not hc: continue
                    if hc in frozen_leave_cols: updated_rec[h] = str(row_to_edit.get(h, ""))
                    elif hc == "From": updated_rec[h] = ed_from_val.strftime("%Y-%m-%d")
                    elif hc == "Upto": updated_rec[h] = ed_upto_val.strftime("%Y-%m-%d")
                    elif hc == "Leave_types": updated_rec[h] = str(ed_ltype_val or "").strip()
                    elif hc in {"Applying_Stutas.", "Applying_Status"}: updated_rec[h] = str(ed_astatus_val or "").strip()
                    elif hc == "Take_Action_By": updated_rec[h] = str(ed_action_val or "").strip()
                    else: updated_rec[h] = str(row_to_edit.get(h, ""))
                update_sheet_row(SPREADSHEET_NAME, leave_tab, leave_headers, editing_row_num, updated_rec)
                write_activity_log(SPREADSHEET_NAME, current_user, "Edit Leave", "Leave", f"Updated row {editing_row_num} for {edit_name}")
                st.session_state["editing_leave_sheet_row"] = None
                st.success("Leave updated!")
                st.rerun()
            if eb2.button("Cancel Edit", key=f"ed_lv_cancel_{editing_row_num}"):
                st.session_state["editing_leave_sheet_row"] = None
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        del_row_num = st.session_state.get("confirm_delete_leave_row")
        row_to_del = next((r for r in leave_rows if r.get("_sheet_row") == del_row_num), None)
        if row_to_del is not None and is_admin_user:
            st.warning(f"Delete leave for **{row_to_del.get('Emp_Name', '')}** [Row {del_row_num}]?")
            dc1, dc2, _ = st.columns([1.4, 1.2, 4])
            if dc1.button("Confirm Delete", type="primary", key=f"conf_del_lv_{del_row_num}"):
                delete_sheet_row(SPREADSHEET_NAME, leave_tab, del_row_num, actor_user=current_user)
                write_activity_log(SPREADSHEET_NAME, current_user, "Delete Leave", "Leave", f"Deleted row {del_row_num}")
                st.session_state["confirm_delete_leave_row"] = None
                st.rerun()
            if dc2.button("Keep Record", key=f"keep_del_lv_{del_row_num}"):
                st.session_state["confirm_delete_leave_row"] = None
                st.rerun()

        if filtered_all_leaves:
            st.markdown("<div class='form-panel'><div class='section-tag'>Leave Ledger</div>", unsafe_allow_html=True)
            for rec in filtered_all_leaves[:80]:
                r_num = rec["_sheet_row"]
                r_code = str(rec.get("EMP_Code", "")).strip() or "-"
                r_name = str(rec.get("Emp_Name", rec.get("EMP_Name", ""))).strip() or "-"
                r_dept = str(rec.get("Emp_Department", "")).strip() or "-"
                r_from = str(rec.get("From", "")).strip() or "-"
                r_upto = str(rec.get("Upto", "")).strip() or "-"
                r_ltype = str(rec.get("Leave_types", "")).strip() or "-"

                cols_lv = st.columns([1.05, 2.0, 1.5, 1.65, 0.85, 0.78, 0.85] if is_admin_user else [1.15, 2.2, 1.6, 1.85, 0.9, 0.85])
                cols_lv[0].markdown(f"<span class='muted-sub'>{html.escape(r_code)}</span>", unsafe_allow_html=True)
                cols_lv[1].markdown(f"<div style='font-weight:600;color:#f8fafc;'>{html.escape(r_name)}</div>", unsafe_allow_html=True)
                cols_lv[2].markdown(f"<span class='muted-sub'>{html.escape(r_dept)}</span>", unsafe_allow_html=True)
                cols_lv[3].markdown(f"<span style='font-size:13px;color:#e2e8f0;'>{html.escape(r_from)} → {html.escape(r_upto)}</span>", unsafe_allow_html=True)
                cols_lv[4].markdown(f"<span class='leave-badge'>{html.escape(r_ltype)}</span>", unsafe_allow_html=True)
                if cols_lv[5].button("Edit", key=f"btn_edit_lv_{r_num}", use_container_width=True):
                    st.session_state["editing_leave_sheet_row"] = r_num
                    st.rerun()
                if is_admin_user and cols_lv[6].button("Delete", key=f"btn_del_lv_{r_num}", use_container_width=True):
                    st.session_state["confirm_delete_leave_row"] = r_num
                    st.rerun()
                st.markdown("<hr style='margin:6px 0;border:none;border-top:1px solid rgba(148,163,184,0.10);'>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    with tab_add_leave:
        st.subheader(f"Add Leave (Search from {faculty_tab or 'Sheet1'} → Save to {leave_tab})")
        st.markdown("<div class='form-panel'><div class='section-tag'>Search Faculty in Sheet1</div>", unsafe_allow_html=True)
        s_box1, s_box2 = st.columns([2.2, 1])
        add_lv_q_name_code = s_box1.text_input("Search Name or EMP_Code", "", placeholder="Type faculty Name or EMP_Code...", key="add_leave_search_name_code").strip().lower()
        add_lv_q_sl = s_box2.text_input("Search SL", "", placeholder="Type SL...", key="add_leave_search_sl").strip().lower()

        matched_s1 = [
            fr for fr in sheet1_faculty_rows
            if (not add_lv_q_name_code or add_lv_q_name_code in (resolve_field_value(fr, "EMP_Name") or resolve_field_value(fr, "Emp_Name")).lower() or add_lv_q_name_code in resolve_field_value(fr, "EMP_Code").lower())
            and (not add_lv_q_sl or add_lv_q_sl in resolve_field_value(fr, "SL").lower())
        ]
        if matched_s1:
            s1_map = {
                f"{resolve_field_value(fr, 'EMP_Name') or resolve_field_value(fr, 'Emp_Name') or '-'}  |  EMP_Code: {resolve_field_value(fr, 'EMP_Code') or '-'}  |  SL: {resolve_field_value(fr, 'SL') or '-'}": fr
                for fr in matched_s1[:200]
            }
            chosen_s1 = s1_map[st.selectbox("Select Matched Faculty", list(s1_map.keys()), key="add_leave_picked_faculty_box")]
            f_emp_code = resolve_field_value(chosen_s1, "EMP_Code")
            f_emp_name = resolve_field_value(chosen_s1, "EMP_Name") or resolve_field_value(chosen_s1, "Emp_Name")
            f_desig = resolve_field_value(chosen_s1, "Emp_Designation")
            f_dept = resolve_field_value(chosen_s1, "Emp_Department")
            f_sl = resolve_field_value(chosen_s1, "SL")

            frz1, frz2, frz3 = st.columns(3)
            frz1.text_input("Emp_Name (Frozen)", value=f_emp_name, disabled=True, key="add_lv_frz_name")
            frz2.text_input("EMP_Code (Frozen)", value=f_emp_code, disabled=True, key="add_lv_frz_code")
            frz3.text_input("SL (Frozen)", value=f_sl, disabled=True, key="add_lv_frz_sl")

            with st.form("add_leave_sheet3_form"):
                add_d1, add_d2 = st.columns(2)
                new_lv_from = add_d1.date_input("From", value=today_val, key="add_lv_from_date")
                new_lv_upto = add_d2.date_input("Upto", value=today_val, key="add_lv_upto_date")
                add_e1, add_e2, add_e3 = st.columns(3)
                new_lv_type = add_e1.selectbox("Leave_types", LEAVE_TYPE_OPTIONS, index=None, key="add_lv_type_sel")
                new_lv_status = add_e2.selectbox("Applying_Stutas.", APPLYING_STATUS_OPTIONS, index=None, key="add_lv_status_sel")
                new_lv_action = add_e3.selectbox("Take_Action_By", TAKE_ACTION_BY_OPTIONS, index=None, key="add_lv_action_sel")
                if st.form_submit_button("Save Leave", type="primary"):
                    payload = {h: "" for h in leave_headers if h.strip()}
                    for h in leave_headers:
                        hc = h.strip()
                        if not hc: continue
                        nh = re.sub(r"[^a-z0-9]", "", hc.lower())
                        if nh == "empcode": payload[h] = f_emp_code
                        elif nh == "empname": payload[h] = f_emp_name
                        elif nh == "empdesignation": payload[h] = f_desig
                        elif nh == "empdepartment": payload[h] = f_dept
                        elif nh == "sl": payload[h] = f_sl
                        elif nh == "from": payload[h] = new_lv_from.strftime("%Y-%m-%d")
                        elif nh == "upto": payload[h] = new_lv_upto.strftime("%Y-%m-%d")
                        elif nh == "leavetypes": payload[h] = str(new_lv_type or "").strip()
                        elif nh in {"applyingstutas", "applyingstatus"}: payload[h] = str(new_lv_status or "").strip()
                        elif nh == "takeactionby": payload[h] = str(new_lv_action or "").strip()
                    append_sheet_row(SPREADSHEET_NAME, leave_tab, leave_headers, payload)
                    write_activity_log(SPREADSHEET_NAME, current_user, "Add Leave", "Leave", f"Added leave for {f_emp_name} ({f_emp_code})")
                    st.success(f"Leave saved to '{leave_tab}'!")
                    st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


# ================= SLICE 5: DO NOT PUNCH =================
elif slice_choice == "Do Not Punch":
    target_dnp_tab = dnp_tab or "Don Not Punch"
    render_banner("Do Not Punch", f"Source Faculty Tab: <b>{html.escape(str(faculty_tab))}</b>  |  Save To Tab: <b>{html.escape(str(target_dnp_tab))}</b>")
    if not faculty_tab:
        st.stop()

    _, source_faculty_rows = load_worksheet_rows_with_index(SPREADSHEET_NAME, faculty_tab)
    dnp_headers, dnp_rows = load_worksheet_rows_with_index(SPREADSHEET_NAME, target_dnp_tab) if target_dnp_tab in all_tabs else ([], [])

    if "editing_dnp_sheet_row" not in st.session_state:
        st.session_state["editing_dnp_sheet_row"] = None
    if "confirm_delete_dnp_row" not in st.session_state:
        st.session_state["confirm_delete_dnp_row"] = None
    if not is_admin_user:
        st.session_state["confirm_delete_dnp_row"] = None

    today_val = date.today()
    tab_dnp_add, tab_dnp_records = st.tabs(["➕ Add", "📄 Do Not Punch Record"])

    with tab_dnp_add:
        st.subheader("Add Do Not Punch (From Faculty Sheet)")
        st.markdown("<div class='form-panel'><div class='section-tag'>Search Faculty (Sheet1)</div>", unsafe_allow_html=True)
        sb1, sb2, sb3 = st.columns(3)
        dnp_q_name = sb1.text_input("Search Name", "", placeholder="Type faculty name...", key="dnp_search_name").strip().lower()
        dnp_q_code = sb2.text_input("Search EMP Code", "", placeholder="Type EMP_Code...", key="dnp_search_code").strip().lower()
        dnp_q_sl = sb3.text_input("Search SL", "", placeholder="Type SL...", key="dnp_search_sl").strip().lower()

        matched_faculties = [
            fr for fr in source_faculty_rows
            if (not dnp_q_name or dnp_q_name in (resolve_field_value(fr, "EMP_Name") or resolve_field_value(fr, "Emp_Name")).lower())
            and (not dnp_q_code or dnp_q_code in resolve_field_value(fr, "EMP_Code").lower())
            and (not dnp_q_sl or dnp_q_sl in resolve_field_value(fr, "SL").lower())
        ]
        if matched_faculties:
            fac_choice_map = {
                f"{resolve_field_value(fr, 'EMP_Name') or resolve_field_value(fr, 'Emp_Name') or '-'}  |  EMP_Code: {resolve_field_value(fr, 'EMP_Code') or '-'}  |  SL: {resolve_field_value(fr, 'SL') or '-'}": fr
                for fr in matched_faculties[:200]
            }
            chosen_fac = fac_choice_map[st.selectbox("Select Matched Faculty", list(fac_choice_map.keys()), key="dnp_selected_faculty_box")]
            fac_emp_code = resolve_field_value(chosen_fac, "EMP_Code")
            fac_emp_name = resolve_field_value(chosen_fac, "EMP_Name") or resolve_field_value(chosen_fac, "Emp_Name")
            fac_desig = resolve_field_value(chosen_fac, "Emp_Designation")
            fac_dept = resolve_field_value(chosen_fac, "Emp_Department")
            fac_sl = resolve_field_value(chosen_fac, "SL")
            fac_status = resolve_field_value(chosen_fac, "Status")
            fac_category = resolve_field_value(chosen_fac, "CATEGORY")

            dt1, dt2 = st.columns(2)
            dnp_from_date = dt1.date_input("Do Not Punch From", value=today_val, key="dnp_from_input")
            dnp_upto_date = dt2.date_input("Do Not Punch Upto", value=today_val, key="dnp_upto_input")
            nf1, nf2 = st.columns(2)
            dnp_notif_date = nf1.date_input("Notification Date", value=today_val, key="dnp_notif_date_input")
            dnp_issue_by = nf2.text_input("Notification issue By", value=current_user.get("name", ""), key="dnp_issue_by_input").strip()

            if st.button("Save Do Not Punch", type="primary", key="dnp_save_btn"):
                field_map = {
                    "empcode": fac_emp_code, "empname": fac_emp_name, "empdesignation": fac_desig,
                    "empdepartment": fac_dept, "sl": fac_sl, "status": fac_status, "category": fac_category,
                    "donotpunchfrom": dnp_from_date.strftime("%Y-%m-%d"),
                    "donotpunchupto": dnp_upto_date.strftime("%Y-%m-%d"),
                    "notificationdate": dnp_notif_date.strftime("%Y-%m-%d"),
                    "notificationissueby": dnp_issue_by,
                }
                new_dnp_row = {
                    h: field_map.get(re.sub(r"[^a-z0-9]", "", h.strip().lower()), "")
                    for h in dnp_headers if h.strip()
                }
                append_sheet_row(SPREADSHEET_NAME, target_dnp_tab, dnp_headers, new_dnp_row)
                write_activity_log(SPREADSHEET_NAME, current_user, "Add Do Not Punch", "Do Not Punch", f"Added DNP for {fac_emp_name} ({fac_emp_code})")
                st.success(f"Saved to '{target_dnp_tab}'!")
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    with tab_dnp_records:
        st.subheader(f"Do Not Punch Record ({target_dnp_tab})")
        sorted_dnp = sorted(dnp_rows, key=get_dnp_recent_sort_key, reverse=True)
        for rec in sorted_dnp[:80]:
            r_num = rec["_sheet_row"]
            r_code = resolve_field_value(rec, "EMP_Code") or "-"
            r_name = resolve_field_value(rec, "EMP_Name") or resolve_field_value(rec, "Emp_Name") or "-"
            r_dept = resolve_field_value(rec, "Emp_Department") or "-"
            r_from = resolve_field_value(rec, "Do Not Punch From") or "-"
            r_upto = resolve_field_value(rec, "Do Not Punch Upto") or "-"
            r_iss = resolve_field_value(rec, "Notification issue By") or "-"
            cols_d = st.columns([1.05, 1.9, 1.35, 1.75, 1.15, 0.85] if is_admin_user else [1.15, 2.05, 1.45, 1.85, 1.25])
            cols_d[0].markdown(f"<span class='muted-sub'>{html.escape(r_code)}</span>", unsafe_allow_html=True)
            cols_d[1].markdown(f"<div style='font-weight:600;color:#f8fafc;'>{html.escape(r_name)}</div>", unsafe_allow_html=True)
            cols_d[2].markdown(f"<span class='muted-sub'>{html.escape(r_dept)}</span>", unsafe_allow_html=True)
            cols_d[3].markdown(f"<span style='font-size:13px;color:#e2e8f0;'>{html.escape(r_from)} → {html.escape(r_upto)}</span>", unsafe_allow_html=True)
            cols_d[4].markdown(f"<span class='leave-badge'>{html.escape(r_iss)}</span>", unsafe_allow_html=True)
            if is_admin_user and cols_d[5].button("Delete", key=f"btn_del_dnp_{r_num}", use_container_width=True):
                delete_sheet_row(SPREADSHEET_NAME, target_dnp_tab, r_num, actor_user=current_user)
                write_activity_log(SPREADSHEET_NAME, current_user, "Delete Do Not Punch", "Do Not Punch", f"Deleted DNP row {r_num}")
                st.rerun()
        render_html_table(sorted_dnp, max_rows=300)


# ================= SLICE 6: OTHER SHEET TABS =================
elif slice_choice == "Other Sheet Tabs":
    render_banner("Other Sheet Tabs", f"Spreadsheet: <b>{html.escape(SPREADSHEET_NAME)}</b>")
    known = {t for t in [faculty_tab, leave_tab, dnp_tab, attendance_base_tab, roster_tab, USERS_TAB_NAME, LOGS_TAB_NAME, REQUESTS_TAB_NAME] if t}
    other_tabs = [t for t in all_tabs if t not in known] or [t for t in all_tabs if t not in {USERS_TAB_NAME, LOGS_TAB_NAME, REQUESTS_TAB_NAME}]
    if other_tabs:
        selected_tab = st.selectbox("Select Tab", other_tabs)
        _, tab_rows = load_worksheet_rows_with_index(SPREADSHEET_NAME, selected_tab)
        render_html_table(tab_rows, max_rows=150)


# ================= SLICE 7: USERS, SECURITY, LOGS & ADMIN NOTICES =================
elif slice_choice == "Users":
    render_banner(
        "Security & Password" if not is_admin_user else "Users, Activity Logs & Admin Notices",
        f"Logged in as: <b>{html.escape(current_user['name'])}</b>",
    )
    if is_admin_user:
        tab_users_mgmt, tab_admin_notices, tab_activity_logs = st.tabs([
            "👥 Users & Password",
            "🔔 Admin Notices",
            "📜 Activity Log List",
        ])
    else:
        tab_users_mgmt = st.container()
        tab_admin_notices = None
        tab_activity_logs = None

    with tab_users_mgmt:
        if is_admin_user:
            st.markdown("<div class='form-panel'><div class='section-tag'>Users (From Google Sheet)</div>", unsafe_allow_html=True)
            render_html_table([
                {"Username": u, "Full Name": info["name"], "Role": info["role"].upper(), "Created At": info.get("created_at", "")}
                for u, info in sheet_users_db.items()
            ], max_rows=100)
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("<div class='form-panel'><div class='section-tag'>Add New User</div>", unsafe_allow_html=True)
            with st.form("add_new_user_form"):
                u1, u2, u3 = st.columns(3)
                new_uname = u1.text_input("New Username", placeholder="e.g. hr_user").strip().lower()
                new_fullname = u2.text_input("Full Name", placeholder="e.g. HR Officer").strip()
                new_role = u3.selectbox("Role", ["user", "admin"])
                new_pass = st.text_input("Initial Password", type="password", placeholder="Set password")
                if st.form_submit_button("Create User", type="primary"):
                    if new_uname and new_pass and new_uname not in sheet_users_db:
                        add_user_to_sheet(SPREADSHEET_NAME, new_uname, new_fullname, new_role, new_pass)
                        write_activity_log(SPREADSHEET_NAME, current_user, "Create User", "Users & Security", f"Created user '{new_uname}'")
                        st.success(f"User '{new_uname}' created!")
                        st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='form-panel'><div class='section-tag'>Change My Password</div>", unsafe_allow_html=True)
        with st.form("change_pw_form"):
            curr_pw = st.text_input("Current Password", type="password")
            next_pw = st.text_input("New Password", type="password")
            if st.form_submit_button("Update Password", type="primary"):
                uname = current_user["username"]
                rec = sheet_users_db.get(uname)
                if rec and verify_password(curr_pw, rec["password_hash"]) and next_pw:
                    if update_user_password_in_sheet(SPREADSHEET_NAME, uname, next_pw):
                        st.query_params["auth_t"] = build_auth_token(uname, hash_password(next_pw))
                        write_activity_log(SPREADSHEET_NAME, current_user, "Change Password", "Users & Security", f"Updated password for '{uname}'")
                        st.success("Password updated!")
                        st.rerun()
                else:
                    st.error("Current password is incorrect or new password is empty.")
        st.markdown("</div>", unsafe_allow_html=True)

    if is_admin_user and tab_admin_notices is not None:
        with tab_admin_notices:
            _, all_notices = load_worksheet_rows_with_index(SPREADSHEET_NAME, REQUESTS_TAB_NAME)
            for n_rec in reversed(all_notices):
                n_row = n_rec["_sheet_row"]
                nc1, nc2, nc3 = st.columns([3.2, 1.3, 1.2])
                nc1.markdown(f"<div style='font-weight:700;color:#f8fafc;'>“{html.escape(str(n_rec.get('Question', '')))}”</div><div class='muted-sub'>By: {html.escape(str(n_rec.get('Name', n_rec.get('Username', ''))))}</div>", unsafe_allow_html=True)
                new_st = nc2.selectbox("Status", ["Pending", "Option Created", "Dismissed"], key=f"notice_st_{n_row}", label_visibility="collapsed")
                if nc3.button("Save Status", key=f"notice_save_{n_row}", use_container_width=True):
                    update_feature_notice_status(SPREADSHEET_NAME, n_row, new_st, str(n_rec.get("Admin_Note", "")))
                    st.rerun()

    if is_admin_user and tab_activity_logs is not None:
        with tab_activity_logs:
            _, raw_logs = load_worksheet_rows_with_index(SPREADSHEET_NAME, LOGS_TAB_NAME)
            render_html_table(list(reversed(raw_logs)), max_rows=300)