"""开放 API 平台层的持久化：套餐 / 客户 / 密钥 / 用量事件 / 充值 / 幂等缓存。

设计要点（与主流搜索 API 对齐）：
- 密钥只存 SHA-256 摘要，明文仅在签发时返回一次；
- 每次成功调用落一条 ``platform_usage_events``，既用于计量扣费，也用于
  账单、成功率与 P95 延迟统计；
- 余额以「次数（units）」为单位，套餐用 ``price_per_1k_cny`` 表达千次单价；
- 所有写操作走 ``_db_lock``，与主库保持一致的单连接加锁模型。
"""
import hashlib
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.core.database import _db_lock, get_conn

# ==================== 常量与默认值 ====================

#: 端点计费单位。按「次」计量，套餐用 ¥/千次 定价。
DEFAULT_UNITS: Dict[str, Any] = {
    "search": {"basic": 1, "advanced": 2, "deep": 3},
    "extract": {"per_url": 1},
    "answer": {"fast": 2, "deep": 5},
    "research": {"deep": 5, "agentic": 8},
    "chat": 2,
    "max_extract_urls": 20,
}

DEFAULT_PLANS: List[Dict[str, Any]] = [
    {
        "id": "trial",
        "name": "体验版",
        "tagline": "注册即送 500 次，先验证检索质量再付费",
        "price_per_1k_cny": 0.0,
        "min_topup_cny": 0.0,
        "included_units": 500,
        "rpm_limit": 60,
        "rpd_limit": 1000,
        "max_results": 10,
        "allow_rerank": 0,
        "allow_extract": 1,
        "allow_answer": 0,
        "allow_deep": 0,
        "allow_stream": 0,
        "allow_postpaid": 0,
        "features_json": json.dumps(
            ["多源聚合搜索", "跨源去重融合", "500 次免费额度", "无需外币卡与代理"], ensure_ascii=False
        ),
        "highlight": 0,
        "enabled": 1,
    },
    {
        "id": "basic",
        "name": "轻量版 Starter",
        "tagline": "免 Key 源自建为主，单价压到行业最低档",
        "price_per_1k_cny": 19.0,
        "min_topup_cny": 100.0,
        "included_units": 0,
        "rpm_limit": 60,
        "rpd_limit": 3000,
        "max_results": 20,
        "allow_rerank": 0,
        "allow_extract": 1,
        "allow_answer": 1,
        "allow_deep": 0,
        "allow_stream": 1,
        "allow_postpaid": 0,
        "features_json": json.dumps(
            ["多源聚合搜索", "网页正文抽取（Markdown）", "带引用的答案生成", "SSE 流式输出", "人民币结算"], ensure_ascii=False
        ),
        "highlight": 0,
        "enabled": 1,
    },
    {
        "id": "pro",
        "name": "标准版 Pro",
        "tagline": "4 源并发 + RRF 融合 + 语义重排，个人与团队主力档",
        "price_per_1k_cny": 35.0,
        "min_topup_cny": 500.0,
        "included_units": 0,
        "rpm_limit": 300,
        "rpd_limit": 50000,
        "max_results": 40,
        "allow_rerank": 1,
        "allow_extract": 1,
        "allow_answer": 1,
        "allow_deep": 1,
        "allow_stream": 1,
        "allow_postpaid": 0,
        "features_json": json.dumps(
            ["全部搜索能力", "语义重排 Rerank", "深度研究 / Deep Research",
             "自定义引擎编排", "更高并发与配额", "用量账单导出"], ensure_ascii=False
        ),
        "highlight": 1,
        "enabled": 1,
    },
    {
        "id": "max",
        "name": "专业版 Max",
        "tagline": "含 Tavily advanced / Exa 等高价源与优先队列",
        "price_per_1k_cny": 59.0,
        "min_topup_cny": 2000.0,
        "included_units": 0,
        "rpm_limit": 600,
        "rpd_limit": 200000,
        "max_results": 50,
        "allow_rerank": 1,
        "allow_extract": 1,
        "allow_answer": 1,
        "allow_deep": 1,
        "allow_stream": 1,
        "allow_postpaid": 0,
        "features_json": json.dumps(
            ["高级上游源（Tavily advanced / Exa）", "AI 摘要与深度报告",
             "SSE 流式 + MCP 接入", "结果可溯源与原始排名", "优先队列与更高并发"], ensure_ascii=False
        ),
        "highlight": 0,
        "enabled": 1,
    },
    {
        "id": "enterprise",
        "name": "企业版 Enterprise",
        "tagline": "年框 ≥¥5 万，独享源、SLA 与私有化部署",
        "price_per_1k_cny": 45.0,
        "min_topup_cny": 5000.0,
        "included_units": 0,
        "rpm_limit": 3000,
        "rpd_limit": 1000000,
        "max_results": 50,
        "allow_rerank": 1,
        "allow_extract": 1,
        "allow_answer": 1,
        "allow_deep": 1,
        "allow_stream": 1,
        "allow_postpaid": 1,
        "features_json": json.dumps(
            ["独享上游渠道与配额", "99.9% SLA 与专属技术支持", "月结后付费 / 专票",
             "定制引擎与路由策略", "私有化 / 专线部署", "全链路审计日志"], ensure_ascii=False
        ),
        "highlight": 0,
        "enabled": 1,
    },
]

KEY_PREFIX = "sk-omni-"


# ==================== 工具函数 ====================

def _now() -> float:
    return time.time()


def _day_start(ts: Optional[float] = None) -> float:
    dt = datetime.fromtimestamp(ts if ts is not None else time.time())
    return dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_key() -> Tuple[str, str, str]:
    """返回 (明文密钥, 摘要, 掩码)。明文只在签发时返回一次。"""
    raw = f"{KEY_PREFIX}{secrets.token_hex(20)}"
    masked = f"{raw[:16]}...{raw[-4:]}"
    return raw, hash_key(raw), masked


def _row_to_dict(row: Any) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def _load_json(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _mask_key_row(row: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(row)
    row.pop("key_hash", None)
    return row


# ==================== 建表与种子 ====================

def init_platform_db() -> None:
    with _db_lock:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_plans (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                tagline TEXT DEFAULT '',
                price_per_1k_cny REAL DEFAULT 0,
                min_topup_cny REAL DEFAULT 0,
                included_units INTEGER DEFAULT 0,
                rpm_limit INTEGER DEFAULT 120,
                rpd_limit INTEGER DEFAULT 20000,
                max_results INTEGER DEFAULT 20,
                allow_rerank INTEGER DEFAULT 0,
                allow_extract INTEGER DEFAULT 1,
                allow_answer INTEGER DEFAULT 0,
                allow_deep INTEGER DEFAULT 0,
                allow_stream INTEGER DEFAULT 1,
                allow_postpaid INTEGER DEFAULT 0,
                features_json TEXT DEFAULT '[]',
                highlight INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                created_at REAL NOT NULL
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT DEFAULT '',
                company TEXT DEFAULT '',
                plan_id TEXT NOT NULL DEFAULT 'trial',
                status TEXT DEFAULT 'active',
                balance_units INTEGER DEFAULT 0,
                billing_mode TEXT DEFAULT 'prepaid',
                credit_limit_cny REAL DEFAULT 0,
                total_topup_cny REAL DEFAULT 0,
                note TEXT DEFAULT '',
                source TEXT DEFAULT 'admin',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_api_keys (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                label TEXT DEFAULT '默认密钥',
                key_prefix TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                masked TEXT NOT NULL,
                scopes_json TEXT DEFAULT '["search"]',
                rpm_limit INTEGER DEFAULT 0,
                rpd_limit INTEGER DEFAULT 0,
                ip_allowlist TEXT DEFAULT '',
                expires_at REAL DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                revoked_at REAL DEFAULT 0,
                total_units INTEGER DEFAULT 0,
                last_used_at REAL DEFAULT 0,
                created_at REAL NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pak_client ON platform_api_keys(client_id)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                client_id TEXT NOT NULL,
                key_id TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                route TEXT DEFAULT '',
                units INTEGER DEFAULT 0,
                unit_price REAL DEFAULT 0,
                cost_cny REAL DEFAULT 0,
                status TEXT DEFAULT 'success',
                http_status INTEGER DEFAULT 200,
                error_code TEXT DEFAULT '',
                latency_ms INTEGER DEFAULT 0,
                cached INTEGER DEFAULT 0,
                query TEXT DEFAULT '',
                result_count INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_pue_client_time ON platform_usage_events(client_id, created_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_pue_key_time ON platform_usage_events(key_id, created_at)"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pue_time ON platform_usage_events(created_at)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_topups (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                amount_cny REAL NOT NULL,
                units INTEGER NOT NULL,
                note TEXT DEFAULT '',
                operator TEXT DEFAULT 'admin',
                created_at REAL NOT NULL
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_idempotency (
                idem_key TEXT NOT NULL,
                client_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                status INTEGER DEFAULT 200,
                body_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (idem_key, client_id)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            )
            """
        )

        # 套餐种子：只补齐缺失项，不覆盖运营已调整的定价
        for plan in DEFAULT_PLANS:
            cur.execute("SELECT id FROM platform_plans WHERE id = ?", (plan["id"],))
            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO platform_plans (
                        id, name, tagline, price_per_1k_cny, min_topup_cny, included_units,
                        rpm_limit, rpd_limit, max_results, allow_rerank, allow_extract,
                        allow_answer, allow_deep, allow_stream, allow_postpaid,
                        features_json, highlight, enabled, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan["id"], plan["name"], plan["tagline"], plan["price_per_1k_cny"],
                        plan["min_topup_cny"], plan["included_units"], plan["rpm_limit"],
                        plan["rpd_limit"], plan["max_results"], plan["allow_rerank"],
                        plan["allow_extract"], plan["allow_answer"], plan["allow_deep"],
                        plan["allow_stream"], plan["allow_postpaid"], plan["features_json"],
                        plan["highlight"], plan["enabled"], _now(),
                    ),
                )

        cur.execute("SELECT key FROM platform_settings WHERE key = 'units'")
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO platform_settings (key, value_json) VALUES ('units', ?)",
                (json.dumps(DEFAULT_UNITS, ensure_ascii=False),),
            )
        cur.execute("SELECT key FROM platform_settings WHERE key = 'signup'")
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO platform_settings (key, value_json) VALUES ('signup', ?)",
                (json.dumps({"enabled": True, "plan_id": "trial", "daily_limit": 50}, ensure_ascii=False),),
            )

        # 内部工作台客户：站内控制台不计费，仅用于产生可观测的演示数据
        cur.execute("SELECT id FROM platform_clients WHERE id = 'internal'")
        if not cur.fetchone():
            cur.execute(
                """
                INSERT INTO platform_clients (
                    id, name, email, company, plan_id, status, balance_units,
                    billing_mode, total_topup_cny, note, source, created_at, updated_at
                ) VALUES ('internal', '站内工作台（不计费）', '', 'OmniSearch', 'enterprise',
                          'active', 1000000000, 'internal', 0, '控制台内部调用专用，免鉴权免扣费',
                          'internal', ?, ?)
                """,
                (_now(), _now()),
            )

        conn.commit()
        conn.close()


# ==================== 平台设置 ====================

def get_platform_setting(key: str, default: Any = None) -> Any:
    with _db_lock:
        conn = get_conn()
        row = conn.execute("SELECT value_json FROM platform_settings WHERE key = ?", (key,)).fetchone()
        conn.close()
    if not row:
        return default
    return _load_json(row["value_json"], default)


def set_platform_setting(key: str, value: Any) -> None:
    with _db_lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO platform_settings (key, value_json) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        conn.commit()
        conn.close()


def get_units_config() -> Dict[str, Any]:
    cfg = get_platform_setting("units", DEFAULT_UNITS) or {}
    merged = json.loads(json.dumps(DEFAULT_UNITS))
    for section, value in cfg.items():
        if isinstance(value, dict) and isinstance(merged.get(section), dict):
            merged[section].update(value)
        else:
            merged[section] = value
    return merged


# ==================== 套餐 ====================

def list_plans(enabled_only: bool = False) -> List[Dict[str, Any]]:
    with _db_lock:
        conn = get_conn()
        sql = "SELECT * FROM platform_plans"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY price_per_1k_cny ASC, created_at ASC"
        rows = conn.execute(sql).fetchall()
        conn.close()
    return [_plan_out(dict(r)) for r in rows]


def _plan_out(plan: Dict[str, Any]) -> Dict[str, Any]:
    plan = dict(plan)
    plan["features"] = _load_json(plan.pop("features_json", "[]"), [])
    return plan


def get_plan(plan_id: str) -> Optional[Dict[str, Any]]:
    with _db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM platform_plans WHERE id = ?", (plan_id,)).fetchone()
        conn.close()
    return _plan_out(dict(row)) if row else None


def upsert_plan(plan_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    fields = [
        "name", "tagline", "price_per_1k_cny", "min_topup_cny", "included_units",
        "rpm_limit", "rpd_limit", "max_results", "allow_rerank", "allow_extract",
        "allow_answer", "allow_deep", "allow_stream", "allow_postpaid",
        "features_json", "highlight", "enabled",
    ]
    with _db_lock:
        conn = get_conn()
        existing = conn.execute("SELECT * FROM platform_plans WHERE id = ?", (plan_id,)).fetchone()
        if existing:
            sets, values = [], []
            for f in fields:
                if f in data and data[f] is not None:
                    sets.append(f"{f} = ?")
                    values.append(data[f])
            if sets:
                values.append(plan_id)
                conn.execute(f"UPDATE platform_plans SET {', '.join(sets)} WHERE id = ?", values)
        else:
            payload = {f: data.get(f) for f in fields}
            payload.setdefault("name", plan_id)
            payload.setdefault("price_per_1k_cny", 0.0)
            payload.setdefault("min_topup_cny", 0.0)
            payload.setdefault("included_units", 0)
            payload.setdefault("rpm_limit", 120)
            payload.setdefault("rpd_limit", 20000)
            payload.setdefault("max_results", 20)
            payload.setdefault("enabled", 1)
            payload["features_json"] = payload.get("features_json") or "[]"
            cols = ["id"] + fields + ["created_at"]
            vals = [plan_id] + [payload.get(f) for f in fields] + [_now()]
            conn.execute(
                f"INSERT INTO platform_plans ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
                vals,
            )
        conn.commit()
        conn.close()
    return get_plan(plan_id) or {}


def delete_plan(plan_id: str) -> None:
    with _db_lock:
        conn = get_conn()
        conn.execute("UPDATE platform_plans SET enabled = 0 WHERE id = ?", (plan_id,))
        conn.commit()
        conn.close()


# ==================== 客户 ====================

def create_client(
    name: str,
    email: str = "",
    company: str = "",
    plan_id: str = "trial",
    note: str = "",
    source: str = "admin",
    billing_mode: str = "prepaid",
    grant_units: Optional[int] = None,
) -> Dict[str, Any]:
    client_id = f"cli_{uuid.uuid4().hex[:12]}"
    plan = get_plan(plan_id) or get_plan("trial") or {}
    balance = int(plan.get("included_units") or 0) if grant_units is None else int(grant_units)
    with _db_lock:
        conn = get_conn()
        conn.execute(
            """
            INSERT INTO platform_clients (
                id, name, email, company, plan_id, status, balance_units,
                billing_mode, total_topup_cny, note, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 0, ?, ?, ?, ?)
            """,
            (client_id, name, email, company, plan["id"] if plan else plan_id, balance,
             billing_mode, note, source, _now(), _now()),
        )
        conn.commit()
        conn.close()
    return get_client(client_id) or {}


def list_clients(query: str = "", limit: int = 200) -> List[Dict[str, Any]]:
    sql = """
        SELECT c.*, p.name AS plan_name, p.price_per_1k_cny,
               (SELECT COUNT(*) FROM platform_api_keys k WHERE k.client_id = c.id AND k.enabled = 1 AND k.revoked_at = 0) AS active_keys
        FROM platform_clients c
        LEFT JOIN platform_plans p ON p.id = c.plan_id
    """
    params: List[Any] = []
    if query:
        sql += " WHERE c.name LIKE ? OR c.email LIKE ? OR c.id LIKE ?"
        like = f"%{query}%"
        params.extend([like, like, like])
    sql += " ORDER BY c.created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 1000)))
    with _db_lock:
        conn = get_conn()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
    return [dict(r) for r in rows]


def get_client(client_id: str) -> Optional[Dict[str, Any]]:
    with _db_lock:
        conn = get_conn()
        row = conn.execute(
            """
            SELECT c.*, p.name AS plan_name, p.price_per_1k_cny
            FROM platform_clients c LEFT JOIN platform_plans p ON p.id = c.plan_id
            WHERE c.id = ?
            """,
            (client_id,),
        ).fetchone()
        conn.close()
    return dict(row) if row else None


def update_client(client_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = ["name", "email", "company", "plan_id", "status", "billing_mode",
               "credit_limit_cny", "note", "balance_units"]
    sets, values = [], []
    for field in allowed:
        if field in data and data[field] is not None:
            sets.append(f"{field} = ?")
            values.append(data[field])
    if sets:
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(client_id)
        with _db_lock:
            conn = get_conn()
            conn.execute(f"UPDATE platform_clients SET {', '.join(sets)} WHERE id = ?", values)
            conn.commit()
            conn.close()
    return get_client(client_id)


def topup_client(client_id: str, amount_cny: float, units: Optional[int] = None,
                 note: str = "", operator: str = "admin") -> Dict[str, Any]:
    client = get_client(client_id)
    if not client:
        raise ValueError("客户不存在")
    plan = get_plan(client["plan_id"]) or {}
    price = float(plan.get("price_per_1k_cny") or 0)
    if units is None:
        if amount_cny <= 0 or price <= 0:
            raise ValueError("该套餐为免费套餐或金额非法，请直接指定充值次数")
        units = int(round(amount_cny / price * 1000))
    units = int(units)
    if units <= 0:
        raise ValueError("充值次数必须大于 0")
    with _db_lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO platform_topups (id, client_id, amount_cny, units, note, operator, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"top_{uuid.uuid4().hex[:10]}", client_id, float(amount_cny), units,
             note, operator, _now()),
        )
        conn.execute(
            "UPDATE platform_clients SET balance_units = balance_units + ?, "
            "total_topup_cny = total_topup_cny + ?, updated_at = ? WHERE id = ?",
            (units, float(amount_cny), _now(), client_id),
        )
        conn.commit()
        conn.close()
    return get_client(client_id) or {}


def list_topups(client_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM platform_topups"
    params: List[Any] = []
    if client_id:
        sql += " WHERE client_id = ?"
        params.append(client_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    with _db_lock:
        conn = get_conn()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
    return [dict(r) for r in rows]


# ==================== API 密钥 ====================

def create_api_key(
    client_id: str,
    label: str = "默认密钥",
    scopes: Optional[List[str]] = None,
    rpm_limit: int = 0,
    rpd_limit: int = 0,
    ip_allowlist: str = "",
    expires_at: float = 0,
) -> Tuple[str, Dict[str, Any]]:
    raw, digest, masked = generate_key()
    key_id = f"key_{uuid.uuid4().hex[:12]}"
    with _db_lock:
        conn = get_conn()
        conn.execute(
            """
            INSERT INTO platform_api_keys (
                id, client_id, label, key_prefix, key_hash, masked, scopes_json,
                rpm_limit, rpd_limit, ip_allowlist, expires_at, enabled, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (key_id, client_id, label, raw[:16], digest, masked,
             json.dumps(scopes or ["search", "extract", "answer", "chat"], ensure_ascii=False),
             int(rpm_limit), int(rpd_limit), ip_allowlist, float(expires_at), _now()),
        )
        conn.commit()
        conn.close()
    row = get_api_key(key_id)
    return raw, row or {}


def get_api_key(key_id: str) -> Optional[Dict[str, Any]]:
    with _db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM platform_api_keys WHERE id = ?", (key_id,)).fetchone()
        conn.close()
    if not row:
        return None
    data = _mask_key_row(dict(row))
    data["scopes"] = _load_json(data.pop("scopes_json", "[]"), [])
    return data


def list_api_keys(client_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM platform_api_keys"
    params: List[Any] = []
    if client_id:
        sql += " WHERE client_id = ?"
        params.append(client_id)
    sql += " ORDER BY created_at DESC"
    with _db_lock:
        conn = get_conn()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
    out = []
    for row in rows:
        data = _mask_key_row(dict(row))
        data["scopes"] = _load_json(data.pop("scopes_json", "[]"), [])
        out.append(data)
    return out


def resolve_api_key(raw_key: str) -> Optional[Dict[str, Any]]:
    """按密钥摘要解析出 (key, client, plan)；不判断状态，交给鉴权层。"""
    digest = hash_key(raw_key)
    with _db_lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM platform_api_keys WHERE key_hash = ?", (digest,)
        ).fetchone()
        if not row:
            conn.close()
            return None
        key = _mask_key_row(dict(row))
        client_row = conn.execute(
            "SELECT * FROM platform_clients WHERE id = ?", (key["client_id"],)
        ).fetchone()
        plan_row = None
        if client_row:
            plan_row = conn.execute(
                "SELECT * FROM platform_plans WHERE id = ?", (client_row["plan_id"],)
            ).fetchone()
        conn.close()
    key["scopes"] = _load_json(key.pop("scopes_json", "[]"), [])
    client = dict(client_row) if client_row else None
    plan = _plan_out(dict(plan_row)) if plan_row else None
    return {"key": key, "client": client, "plan": plan}


def update_api_key(key_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = ["label", "scopes_json", "rpm_limit", "rpd_limit", "ip_allowlist",
               "expires_at", "enabled"]
    sets, values = [], []
    for field in allowed:
        if field in data and data[field] is not None:
            sets.append(f"{field} = ?")
            values.append(data[field])
    if sets:
        values.append(key_id)
        with _db_lock:
            conn = get_conn()
            conn.execute(f"UPDATE platform_api_keys SET {', '.join(sets)} WHERE id = ?", values)
            conn.commit()
            conn.close()
    return get_api_key(key_id)


def revoke_api_key(key_id: str) -> bool:
    with _db_lock:
        conn = get_conn()
        cur = conn.execute(
            "UPDATE platform_api_keys SET enabled = 0, revoked_at = ? WHERE id = ?",
            (_now(), key_id),
        )
        conn.commit()
        count = cur.rowcount
        conn.close()
    return count > 0


def touch_api_key(key_id: str) -> None:
    with _db_lock:
        conn = get_conn()
        conn.execute("UPDATE platform_api_keys SET last_used_at = ? WHERE id = ?", (_now(), key_id))
        conn.commit()
        conn.close()


# ==================== 用量事件与计费 ====================

def record_usage_event(
    request_id: str,
    client_id: str,
    key_id: str,
    endpoint: str,
    units: int = 0,
    unit_price: float = 0.0,
    status: str = "success",
    http_status: int = 200,
    error_code: str = "",
    latency_ms: int = 0,
    cached: bool = False,
    query: str = "",
    route: str = "",
    result_count: int = 0,
    charge: bool = True,
) -> int:
    """写入一条用量事件，并按 ``units`` 扣减预付费余额。返回扣费后余额。"""
    cost = round(units * unit_price / 1000.0, 6)
    with _db_lock:
        conn = get_conn()
        remaining = 0
        client_row = conn.execute(
            "SELECT balance_units, billing_mode FROM platform_clients WHERE id = ?", (client_id,)
        ).fetchone()
        if client_row is None:
            conn.close()
            return 0
        remaining = int(client_row["balance_units"] or 0)
        if charge and units > 0:
            if (client_row["billing_mode"] or "prepaid") == "prepaid":
                remaining = max(0, remaining - units)
                conn.execute(
                    "UPDATE platform_clients SET balance_units = ?, updated_at = ? WHERE id = ?",
                    (remaining, _now(), client_id),
                )
            else:
                remaining = -1  # 后付费：余额无意义
            conn.execute(
                "UPDATE platform_api_keys SET total_units = total_units + ? WHERE id = ?",
                (units, key_id),
            )
        conn.execute(
            """
            INSERT INTO platform_usage_events (
                request_id, client_id, key_id, endpoint, route, units, unit_price,
                cost_cny, status, http_status, error_code, latency_ms, cached,
                query, result_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (request_id, client_id, key_id, endpoint, route, units, unit_price, cost,
             status, http_status, error_code, latency_ms, 1 if cached else 0,
             (query or "")[:200], result_count, _now()),
        )
        conn.commit()
        conn.close()
    return remaining


def count_key_requests_today(key_id: str) -> int:
    with _db_lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM platform_usage_events WHERE key_id = ? AND created_at >= ?",
            (key_id, _day_start()),
        ).fetchone()
        conn.close()
    return int(row["c"]) if row else 0


def count_ip_requests_today(ip: str) -> int:
    """按 request_id 前缀无法定位 IP，这里退化为按 client 自注册来源限流由上层处理。"""
    return 0


def query_usage_events(
    client_id: Optional[str] = None,
    key_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    status: Optional[str] = None,
    since_ts: Optional[float] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    where, params = [], []
    if client_id:
        where.append("u.client_id = ?")
        params.append(client_id)
    if key_id:
        where.append("u.key_id = ?")
        params.append(key_id)
    if endpoint:
        where.append("u.endpoint = ?")
        params.append(endpoint)
    if status:
        where.append("u.status = ?")
        params.append(status)
    if since_ts:
        where.append("u.created_at >= ?")
        params.append(since_ts)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with _db_lock:
        conn = get_conn()
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM platform_usage_events u{clause}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"""
            SELECT u.*, c.name AS client_name, p.name AS plan_name
            FROM platform_usage_events u
            LEFT JOIN platform_clients c ON c.id = u.client_id
            LEFT JOIN platform_plans p ON p.id = c.plan_id
            {clause.replace('u.', 'u.')}
            ORDER BY u.created_at DESC LIMIT ? OFFSET ?
            """,
            params + [max(1, min(limit, 1000)), max(0, offset)],
        ).fetchall()
        conn.close()
    return {"total": total, "items": [dict(r) for r in rows]}


def usage_stats(
    client_id: Optional[str] = None,
    days: int = 30,
    top_queries: int = 10,
) -> Dict[str, Any]:
    """按天序列 + 端点分布 + Top 查询 + 延迟分位，供控制台与客户用量页复用。"""
    since = _day_start() - (max(1, days) - 1) * 86400
    where = "WHERE created_at >= ?"
    params: List[Any] = [since]
    if client_id:
        where += " AND client_id = ?"
        params.append(client_id)

    with _db_lock:
        conn = get_conn()

        series_rows = conn.execute(
            f"""
            SELECT strftime('%Y-%m-%d', created_at, 'unixepoch', 'localtime') AS day,
                   COUNT(*) AS requests,
                   COALESCE(SUM(units), 0) AS units,
                   COALESCE(SUM(cost_cny), 0) AS cost_cny,
                   SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
                   SUM(CASE WHEN cached = 1 THEN 1 ELSE 0 END) AS cached
            FROM platform_usage_events {where}
            GROUP BY day ORDER BY day ASC
            """,
            params,
        ).fetchall()

        endpoint_rows = conn.execute(
            f"""
            SELECT endpoint, COUNT(*) AS requests, COALESCE(SUM(units), 0) AS units
            FROM platform_usage_events {where}
            GROUP BY endpoint ORDER BY requests DESC
            """,
            params,
        ).fetchall()

        totals = conn.execute(
            f"""
            SELECT COUNT(*) AS requests,
                   COALESCE(SUM(units), 0) AS units,
                   COALESCE(SUM(cost_cny), 0) AS cost_cny,
                   SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors,
                   SUM(CASE WHEN cached = 1 THEN 1 ELSE 0 END) AS cached,
                   COALESCE(AVG(latency_ms), 0) AS avg_latency
            FROM platform_usage_events {where}
            """,
            params,
        ).fetchone()

        latencies = [
            int(r["latency_ms"])
            for r in conn.execute(
                f"SELECT latency_ms FROM platform_usage_events {where} ORDER BY latency_ms ASC",
                params,
            ).fetchall()
        ]

        top_q = conn.execute(
            f"""
            SELECT query, COUNT(*) AS hits FROM platform_usage_events {where}
            {"AND" if where else "WHERE"} status = 'success' AND query <> ''
            GROUP BY query ORDER BY hits DESC LIMIT ?
            """,
            params + [top_queries],
        ).fetchall()

        conn.close()

    def pct(values: List[int], p: float) -> int:
        if not values:
            return 0
        idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * p))))
        return values[idx]

    totals_d = dict(totals) if totals else {}
    requests_count = int(totals_d.get("requests") or 0)
    errors = int(totals_d.get("errors") or 0)
    return {
        "range": {"days": max(1, days), "since": since, "until": _now()},
        "totals": {
            "requests": requests_count,
            "units": int(totals_d.get("units") or 0),
            "cost_cny": round(float(totals_d.get("cost_cny") or 0), 4),
            "errors": errors,
            "error_rate": round(errors / requests_count * 100, 2) if requests_count else 0.0,
            "cached": int(totals_d.get("cached") or 0),
            "cache_hit_rate": round(int(totals_d.get("cached") or 0) / requests_count * 100, 2)
            if requests_count else 0.0,
            "avg_latency_ms": int(totals_d.get("avg_latency") or 0),
            "p50_latency_ms": pct(latencies, 0.50),
            "p95_latency_ms": pct(latencies, 0.95),
        },
        "series": [dict(r) for r in series_rows],
        "endpoints": [dict(r) for r in endpoint_rows],
        "top_queries": [dict(r) for r in top_q],
    }


def monthly_invoice(month: Optional[str] = None) -> List[Dict[str, Any]]:
    """按自然月汇总每个客户的使用次数与金额（用于开票/对账）。"""
    if not month:
        month = datetime.now().strftime("%Y-%m")
    try:
        start = datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise ValueError("month 格式应为 YYYY-MM")
    start_ts = start.timestamp()
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    end_ts = end.timestamp()

    with _db_lock:
        conn = get_conn()
        rows = conn.execute(
            """
            SELECT u.client_id, c.name AS client_name, c.plan_id, p.name AS plan_name,
                   p.price_per_1k_cny,
                   COUNT(*) AS requests,
                   COALESCE(SUM(u.units), 0) AS units,
                   COALESCE(SUM(u.cost_cny), 0) AS cost_cny,
                   SUM(CASE WHEN u.status = 'error' THEN 1 ELSE 0 END) AS errors
            FROM platform_usage_events u
            LEFT JOIN platform_clients c ON c.id = u.client_id
            LEFT JOIN platform_plans p ON p.id = c.plan_id
            WHERE u.created_at >= ? AND u.created_at < ?
            GROUP BY u.client_id
            ORDER BY cost_cny DESC
            """,
            (start_ts, end_ts),
        ).fetchall()
        conn.close()
    items = []
    for r in rows:
        d = dict(r)
        d["cost_cny"] = round(float(d.get("cost_cny") or 0), 4)
        items.append(d)
    return items


def revenue_summary(days: int = 30) -> Dict[str, Any]:
    since = _day_start() - (max(1, days) - 1) * 86400
    with _db_lock:
        conn = get_conn()
        topup_row = conn.execute(
            "SELECT COUNT(*) AS orders, COALESCE(SUM(amount_cny), 0) AS amount, "
            "COALESCE(SUM(units), 0) AS units FROM platform_topups WHERE created_at >= ?",
            (since,),
        ).fetchone()
        total_row = conn.execute(
            "SELECT COUNT(*) AS orders, COALESCE(SUM(amount_cny), 0) AS amount "
            "FROM platform_topups"
        ).fetchone()
        client_row = conn.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active, "
            "COALESCE(SUM(balance_units), 0) AS balance "
            "FROM platform_clients WHERE source <> 'internal'"
        ).fetchone()
        paid_clients = conn.execute(
            "SELECT COUNT(DISTINCT client_id) AS c FROM platform_topups WHERE client_id <> 'internal'"
        ).fetchone()
        conn.close()
    return {
        "revenue_window_cny": round(float(topup_row["amount"] or 0), 2),
        "recharge_orders_window": int(topup_row["orders"] or 0),
        "recharged_units_window": int(topup_row["units"] or 0),
        "revenue_total_cny": round(float(total_row["amount"] or 0), 2),
        "recharge_orders_total": int(total_row["orders"] or 0),
        "clients_total": int(client_row["total"] or 0),
        "clients_active": int(client_row["active"] or 0),
        "clients_paid": int(paid_clients["c"] or 0),
        "balance_units_total": int(client_row["balance"] or 0),
    }


# ==================== 幂等 ====================

def idempotency_get(client_id: str, idem_key: str, request_hash: str, ttl_sec: int = 600) -> Optional[Tuple[int, Any]]:
    with _db_lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT status, body_json, request_hash, created_at FROM platform_idempotency "
            "WHERE idem_key = ? AND client_id = ?",
            (idem_key, client_id),
        ).fetchone()
        conn.close()
    if not row:
        return None
    if row["request_hash"] != request_hash:
        raise ValueError("Idempotency-Key 已被用于不同的请求体")
    if _now() - float(row["created_at"] or 0) > ttl_sec:
        return None
    return int(row["status"]), _load_json(row["body_json"], {})


def idempotency_put(client_id: str, idem_key: str, request_hash: str, status: int, body: Any) -> None:
    with _db_lock:
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO platform_idempotency "
            "(idem_key, client_id, request_hash, status, body_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (idem_key, client_id, request_hash, status,
             json.dumps(body, ensure_ascii=False, default=str), _now()),
        )
        conn.execute(
            "DELETE FROM platform_idempotency WHERE created_at < ?", (_now() - 86400,)
        )
        conn.commit()
        conn.close()
