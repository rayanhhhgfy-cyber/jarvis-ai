# ====================================================================
# JARVIS OMEGA - Business Database (Phase 11)
# ====================================================================
"""
SQLite schema for the autonomous marketing agency.

Tables:
  clients        - companies / leads JARVIS is selling on behalf of
  contacts       - individual people at clients
  deals          - pipeline of in-progress / won / lost deals
  campaigns      - marketing campaigns (content + posting schedule)
  posts          - individual social posts + status
  tickets        - support tickets
  orders         - ecommerce orders
  products       - products / SKUs
  invoices       - sent invoices
  opportunities  - background-scanned business opportunities (HN/Reddit/etc.)
  audit_log      - every external action JARVIS takes
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import settings
from shared.logger import get_logger

log = get_logger("business_db")

_DB_PATH = Path("./storage/business.db")


def db_path() -> Path:
    return _DB_PATH


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    niche TEXT,
    website TEXT,
    email TEXT,
    status TEXT DEFAULT 'prospect',     -- prospect | active | churned
    onboarded_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    role TEXT,
    email TEXT,
    phone TEXT,
    linkedin TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    value REAL DEFAULT 0,
    currency TEXT DEFAULT 'USD',
    stage TEXT DEFAULT 'lead',           -- lead | qualified | pitched | negotiated | won | lost
    probability INTEGER DEFAULT 10,
    expected_close TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    platform TEXT,                       -- twitter | linkedin | reddit | mastodon | email | blog
    objective TEXT,                      -- awareness | leads | sales | retention
    start_date TEXT,
    end_date TEXT,
    status TEXT DEFAULT 'planned',       -- planned | active | paused | completed
    budget REAL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    content TEXT NOT NULL,
    hashtags TEXT,
    media_path TEXT,
    scheduled_at TEXT,
    posted_at TEXT,
    external_id TEXT,
    status TEXT DEFAULT 'draft',         -- draft | scheduled | posted | failed
    engagement JSON,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    channel TEXT,                        -- email | twitter | web | chat
    subject TEXT NOT NULL,
    body TEXT,
    requester_name TEXT,
    requester_email TEXT,
    priority TEXT DEFAULT 'normal',      -- low | normal | high | urgent
    status TEXT DEFAULT 'open',          -- open | pending | resolved | closed
    assigned_to TEXT,
    response TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    sku TEXT UNIQUE,
    price REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    inventory INTEGER DEFAULT 0,
    description TEXT,
    image_url TEXT,
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    customer_name TEXT NOT NULL,
    customer_email TEXT,
    customer_address TEXT,
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER DEFAULT 1,
    unit_price REAL,
    total REAL,
    currency TEXT DEFAULT 'USD',
    status TEXT DEFAULT 'pending',       -- pending | paid | fulfilled | shipped | delivered | refunded
    payment_intent TEXT,
    tracking_number TEXT,
    carrier TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    number TEXT UNIQUE,
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    due_date TEXT,
    status TEXT DEFAULT 'draft',         -- draft | sent | paid | overdue | void
    pdf_path TEXT,
    paid_at TEXT,
    stripe_link TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,                -- hackernews | reddit | producthunt | trends | manual
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    niche TEXT,
    score REAL DEFAULT 0,                -- 0-100 estimated attractiveness
    monetization TEXT,                   -- 'digital_product' | 'saas' | 'affiliate' | 'lead_gen' | 'newsletter' | 'service'
    action_taken TEXT,
    status TEXT DEFAULT 'new',           -- new | reviewing | acted_on | rejected
    discovered_at TEXT NOT NULL,
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    category TEXT,                       -- marketing | sales | support | ecommerce | website | payments | biz_intel
    target TEXT,
    details JSON,
    timestamp TEXT NOT NULL
);

-- Phase 12: portfolio (up to 50 businesses under one Sir)
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER,                -- groups businesses Sir owns
    name TEXT NOT NULL,
    niche TEXT NOT NULL,
    language TEXT DEFAULT 'ar',          -- ar | en | mixed
    country TEXT DEFAULT 'JO',
    currency TEXT DEFAULT 'JOD',
    city TEXT DEFAULT 'Amman',
    monetization TEXT,                   -- saas | digital_product | affiliate | lead_gen | newsletter | service
    deployed_url TEXT,                   -- live landing-page URL once deployed
    landing_path TEXT,                   -- local path to the generated HTML
    status TEXT DEFAULT 'idea',          -- idea | building | live | paused | archived
    target_revenue_monthly REAL DEFAULT 0,
    actual_revenue_monthly REAL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS products_ext (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    base_product_id INTEGER REFERENCES products(id),  -- links to existing products table
    name_ar TEXT,                        -- Arabic name
    name_en TEXT,                        -- English name
    description_ar TEXT,
    description_en TEXT,
    price_local REAL,                    -- price in business.currency
    price_usd REAL,
    stripe_link TEXT,
    status TEXT DEFAULT 'concept',       -- concept | built | live | paused
    created_at TEXT NOT NULL
);

-- Phase 12: customer notifications log
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
    ticket_id INTEGER REFERENCES tickets(id) ON DELETE CASCADE,
    channel TEXT,                        -- email | sms | whatsapp | telegram
    recipient TEXT,
    subject TEXT,
    body TEXT,
    status TEXT DEFAULT 'queued',        -- queued | sent | failed
    sent_at TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);

-- Phase 12: continuous-build state — so JARVIS can pick up where he left off
CREATE TABLE IF NOT EXISTS continuous_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,                  -- 'always_on' | 'paused'
    last_build_at TEXT,
    next_build_at TEXT,
    last_niche TEXT,
    total_businesses_built INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);

-- Phase 13: YouTube uploads
CREATE TABLE IF NOT EXISTS youtube_uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT,
    title TEXT,
    description TEXT,
    tags TEXT,
    script_path TEXT,
    thumbnail_path TEXT,
    video_path TEXT,
    status TEXT DEFAULT 'draft',         -- draft | rendered | uploaded | failed
    views INTEGER DEFAULT 0,
    revenue_jod REAL DEFAULT 0,
    uploaded_at TEXT,
    created_at TEXT NOT NULL
);

-- Phase 13: WhatsApp messages
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT,                       -- 'in' | 'out'
    recipient TEXT,
    body TEXT,
    media_path TEXT,
    status TEXT DEFAULT 'pending',        -- pending | sent | failed | received
    external_id TEXT,
    error TEXT,
    sent_at TEXT,
    created_at TEXT NOT NULL
);

-- Phase 13: Trading paper account
CREATE TABLE IF NOT EXISTS paper_account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    balance_usd REAL NOT NULL,
    starting_balance_usd REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,                   -- 'buy' | 'sell'
    quantity REAL NOT NULL,
    price_usd REAL NOT NULL,
    fee_usd REAL DEFAULT 0,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    condition TEXT NOT NULL,              -- 'above' | 'below'
    target_price REAL NOT NULL,
    channel TEXT,                         -- 'telegram' | 'discord' | 'email'
    triggered INTEGER DEFAULT 0,
    triggered_at TEXT,
    created_at TEXT NOT NULL
);

-- Phase 13: Affiliate links
CREATE TABLE IF NOT EXISTS affiliate_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network TEXT,
    product_name TEXT,
    product_url TEXT,
    cloaked_slug TEXT,
    clicks INTEGER DEFAULT 0,
    earnings_jod REAL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Phase 13: SEO rank history
CREATE TABLE IF NOT EXISTS rank_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    url TEXT,
    position INTEGER,
    date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backlinks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL,
    target_url TEXT,
    anchor TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT
);

-- Phase 13: Jordan real-estate listings
CREATE TABLE IF NOT EXISTS property_listings_jo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,                          -- 'aqar.fm' | 'bayut.jo' | 'opensooq' | 'manual'
    url TEXT,
    title TEXT,
    description TEXT,
    price_jod REAL,
    location TEXT,
    city TEXT,
    neighborhood TEXT,
    sqm REAL,
    bedrooms INTEGER,
    bathrooms INTEGER,
    property_type TEXT,                   -- 'apartment' | 'villa' | 'land' | 'office' | 'shop'
    listing_type TEXT,                    -- 'sale' | 'rent'
    agent_phone TEXT,
    scraped_at TEXT,
    investment_score REAL,
    notes TEXT,
    UNIQUE(url)
);

-- Phase 14: Knowledge Codex
CREATE TABLE IF NOT EXISTS codex_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,                          -- 'gmail' | 'github' | 'notion' | 'local_docs' | 'manual'
    source_id TEXT,
    title TEXT,
    content TEXT,
    content_hash TEXT UNIQUE,
    metadata_json TEXT,
    ingested_at TEXT NOT NULL
);

-- Phase 14: Council decisions
CREATE TABLE IF NOT EXISTS council_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    transcripts_json TEXT,
    votes_json TEXT,
    final_decision TEXT,
    dissent TEXT,
    created_at TEXT NOT NULL
);

-- Phase 14: Twin outputs
CREATE TABLE IF NOT EXISTS twin_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    output_type TEXT,                     -- 'voice' | 'video' | 'text'
    prompt TEXT,
    output_path TEXT,
    watermarked INTEGER DEFAULT 1,
    consent_confirmed INTEGER DEFAULT 0,
    timestamp TEXT NOT NULL
);

-- Phase 14: App/SaaS/GitHub projects
CREATE TABLE IF NOT EXISTS app_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    niche TEXT,
    platform TEXT,                        -- 'android' | 'ios' | 'both'
    repo_url TEXT,
    play_url TEXT,
    apk_path TEXT,
    status TEXT DEFAULT 'idea',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saas_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    niche TEXT,
    repo_url TEXT,
    live_url TEXT,
    mrr_usd REAL DEFAULT 0,
    status TEXT DEFAULT 'idea',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gh_repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT UNIQUE,
    description TEXT,
    stars INTEGER DEFAULT 0,
    sponsors_revenue_monthly_usd REAL DEFAULT 0,
    last_auto_activity TEXT,
    created_at TEXT NOT NULL
);

-- Phase 14: Family office assets
CREATE TABLE IF NOT EXISTS family_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type TEXT,                      -- 'cash' | 'crypto' | 'stock' | 'real_estate_jo' | 'business'
    name TEXT,
    value_usd REAL,
    value_jod REAL,
    custodian TEXT,
    notes TEXT,
    updated_at TEXT NOT NULL
);

-- Phase 14: Media Empire publications
CREATE TABLE IF NOT EXISTS media_empire_publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea TEXT,
    platforms TEXT,
    twin_video_path TEXT,
    shorts_paths TEXT,
    newsletter_url TEXT,
    music_path TEXT,
    status TEXT DEFAULT 'planned',
    published_at TEXT,
    created_at TEXT NOT NULL
);

-- Phase 16+17 tables
CREATE TABLE IF NOT EXISTS sales_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_name TEXT,
    prospect_phone TEXT,
    prospect_instagram TEXT,
    prospect_business TEXT,
    channel TEXT,
    status TEXT DEFAULT 'pitching',
    conversation_json TEXT,
    deal_value_jod REAL DEFAULT 0,
    business_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS email_sequences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    trigger_event TEXT,
    steps_json TEXT,
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_sequence_enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence_id INTEGER REFERENCES email_sequences(id),
    contact_email TEXT,
    current_step INTEGER DEFAULT 0,
    enrolled_at TEXT NOT NULL,
    next_send_at TEXT
);

CREATE TABLE IF NOT EXISTS subscription_boxes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    niche TEXT,
    monthly_price_jod REAL,
    subscriber_count INTEGER DEFAULT 0,
    items_json TEXT,
    status TEXT DEFAULT 'planned',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscription_subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    box_id INTEGER REFERENCES subscription_boxes(id),
    customer_name TEXT,
    customer_phone TEXT,
    customer_address TEXT,
    status TEXT DEFAULT 'active',
    started_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_name TEXT,
    date TEXT,
    stops_json TEXT,
    status TEXT DEFAULT 'planned',
    optimized INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crm_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    phone TEXT,
    email TEXT,
    instagram TEXT,
    source TEXT,
    business_id INTEGER,
    score INTEGER DEFAULT 0,
    status TEXT DEFAULT 'new',
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_monitored_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    our_product_name TEXT,
    competitor_url TEXT,
    competitor_name TEXT,
    last_price_jod REAL,
    our_price_jod REAL,
    last_checked TEXT,
    UNIQUE(competitor_url)
);

CREATE TABLE IF NOT EXISTS linkedin_posts_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT,
    topic TEXT,
    posted_at TEXT,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    status TEXT DEFAULT 'draft',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS grant_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grant_name TEXT,
    organization TEXT,
    amount_usd REAL,
    deadline TEXT,
    status TEXT DEFAULT 'found',
    proposal_path TEXT,
    submitted_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS restaurant_menus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_name TEXT,
    phone TEXT,
    menu_json TEXT,
    qr_path TEXT,
    monthly_fee_jod REAL DEFAULT 20,
    status TEXT DEFAULT 'lead',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS influencer_outreach_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    influencer_handle TEXT,
    platform TEXT,
    followers INTEGER,
    status TEXT DEFAULT 'identified',
    deal_type TEXT,
    response TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_scheduled ON posts(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals(stage);
CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
"""


def initialize() -> None:
    """Create all tables if missing. Safe to call repeatedly."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
    log.info("business_db_initialized", path=str(_DB_PATH))


def query(sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    with _connect() as conn:
        return list(conn.execute(sql, params).fetchall())


def query_one(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params: tuple = ()) -> int:
    """Run a write query, return lastrowid or rowcount."""
    with _connect() as conn:
        cur = conn.execute(sql, params)
        try:
            conn.commit()
        except Exception:
            pass
        return cur.lastrowid or cur.rowcount


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def rows_to_dicts(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


def audit(action: str, category: str, target: str = "", details: Optional[Dict[str, Any]] = None) -> None:
    """Append to the audit log. Non-blocking on failure."""
    import json as _json
    try:
        execute(
            "INSERT INTO audit_log (action, category, target, details, timestamp) VALUES (?, ?, ?, ?, ?)",
            (action, category, target, _json.dumps(details or {}), datetime.utcnow().isoformat()),
        )
    except Exception as e:
        log.warning("audit_log_write_failed", error=str(e))


# Initialize on import so first call to any tool finds tables ready.
try:
    initialize()
except Exception as e:
    log.warning("business_db_init_failed_on_import", error=str(e))
