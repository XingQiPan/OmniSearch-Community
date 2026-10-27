import random
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def current_day_usage(key: Dict[str, Any]) -> int:
    """Local calendar day; read-only projection also works after a service restart."""
    last_used = key.get("last_used_at") or 0
    if last_used and datetime.fromtimestamp(last_used).date() == datetime.now().date():
        return int(key.get("used_today") or 0)
    return 0

from app.core.database import _db_lock, get_conn, get_settings, mask_key


class KeyPoolManager:
    def __init__(self) -> None:
        self._rr_counters: Dict[str, int] = {}
        self._lock = threading.Lock()

    def get_provider(self, provider_id: str) -> Optional[Dict[str, Any]]:
        with _db_lock:
            conn = get_conn()
            row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
            conn.close()
            return dict(row) if row else None

    def list_providers(self, provider_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with _db_lock:
            conn = get_conn()
            if provider_type:
                rows = conn.execute(
                    "SELECT * FROM providers WHERE provider_type = ? ORDER BY weight DESC, id ASC",
                    (provider_type,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM providers ORDER BY provider_type ASC, weight DESC").fetchall()

            key_rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
            conn.close()

        keys_by_provider: Dict[str, List[Dict[str, Any]]] = {}
        for kr in key_rows:
            kd = dict(kr)
            kd["api_key_masked"] = mask_key(kd.pop("api_key"))
            kd["used_today"] = current_day_usage(kd)
            # Upstream error bodies may contain echoed credentials; do not expose them.
            kd["last_error"] = "上游调用失败，请检查渠道配置" if kd.get("last_error") else ""
            keys_by_provider.setdefault(kd["provider_id"], []).append(kd)

        now = time.time()
        result = []
        for r in rows:
            d = dict(r)
            p_keys = keys_by_provider.get(d["id"], [])
            active_keys = [k for k in p_keys if k["enabled"] and k["used_today"] < k["daily_quota"]]
            d["keys"] = p_keys
            d["active_key_count"] = len(active_keys)
            d["total_key_count"] = len(p_keys)
            d["is_circuit_open"] = bool(d["circuit_open_until"] and d["circuit_open_until"] > now)
            # Determine operational readiness
            if not d["enabled"]:
                d["health_status"] = "disabled"
            elif d["is_circuit_open"]:
                d["health_status"] = "circuit_open"
            elif d["requires_key"] and len(active_keys) == 0:
                d["health_status"] = "missing_key"
            else:
                d["health_status"] = "ready"
            result.append(d)
        return result

    def acquire_credentials(
        self, provider_id: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
        """
        Returns (provider_dict, selected_key_dict_or_None, resolved_proxy_url_or_None)
        """
        provider = self.get_provider(provider_id)
        if not provider:
            return None, None, None

        settings = get_settings()
        global_proxy = settings.get("global_proxy", "http://127.0.0.1:7890")
        enable_global_proxy = settings.get("enable_global_proxy", True)

        with _db_lock:
            conn = get_conn()
            key_rows = conn.execute(
                "SELECT * FROM api_keys WHERE provider_id = ? AND enabled = 1",
                (provider_id,)
            ).fetchall()
            conn.close()

        valid_keys = []
        for row in key_rows:
            key = dict(row)
            key["used_today"] = current_day_usage(key)
            if key["used_today"] < key["daily_quota"]:
                valid_keys.append(key)

        selected_key: Optional[Dict[str, Any]] = None
        if valid_keys:
            strategy = provider.get("strategy", "round_robin")
            if strategy == "least_used":
                selected_key = min(valid_keys, key=lambda x: x["used_today"])
            elif strategy == "priority":
                selected_key = max(valid_keys, key=lambda x: x["weight"])
            elif strategy == "weighted":
                weights = [max(1, k["weight"]) for k in valid_keys]
                selected_key = random.choices(valid_keys, weights=weights, k=1)[0]
            else:
                with self._lock:
                    idx = self._rr_counters.get(provider_id, 0)
                    selected_key = valid_keys[idx % len(valid_keys)]
                    self._rr_counters[provider_id] = idx + 1

        # Resolve proxy
        use_proxy = bool(provider.get("use_proxy", 0))
        custom_proxy = provider.get("custom_proxy", "").strip()
        if selected_key:
            if selected_key.get("use_proxy", -1) in (0, 1):
                use_proxy = bool(selected_key["use_proxy"])
            if selected_key.get("custom_proxy", "").strip():
                custom_proxy = selected_key["custom_proxy"].strip()

        resolved_proxy: Optional[str] = None
        if custom_proxy:
            resolved_proxy = custom_proxy
        elif use_proxy and enable_global_proxy and global_proxy:
            resolved_proxy = global_proxy

        return provider, selected_key, resolved_proxy

    def record_execution(
        self,
        provider_id: str,
        key_id: Optional[str],
        success: bool,
        latency_ms: int,
        error_msg: str = "",
    ) -> None:
        settings = get_settings()
        threshold = int(settings.get("circuit_breaker_threshold", 4))
        cooldown = int(settings.get("circuit_breaker_cooldown_sec", 120))
        now = time.time()

        with _db_lock:
            conn = get_conn()
            prov = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
            if prov:
                total = prov["total_calls"] + 1
                succ = prov["success_calls"] + (1 if success else 0)
                fail = prov["failed_calls"] + (0 if success else 1)
                old_avg = prov["avg_latency_ms"] or float(latency_ms)
                new_avg = round(old_avg * 0.75 + latency_ms * 0.25, 1) if success else old_avg

                if success:
                    consec_fail = 0
                    circuit_until = 0.0
                    last_err = ""
                else:
                    consec_fail = prov["consecutive_failures"] + 1
                    circuit_until = (now + cooldown) if consec_fail >= threshold else prov["circuit_open_until"]
                    last_err = error_msg[:300]

                conn.execute("""
                UPDATE providers SET
                    total_calls = ?,
                    success_calls = ?,
                    failed_calls = ?,
                    avg_latency_ms = ?,
                    consecutive_failures = ?,
                    circuit_open_until = ?,
                    last_error = ?,
                    last_checked_at = ?
                WHERE id = ?
                """, (total, succ, fail, new_avg, consec_fail, circuit_until, last_err, now, provider_id))

            if key_id:
                previous_key = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
                used_today = current_day_usage(dict(previous_key)) if previous_key else 0
                conn.execute("""
                UPDATE api_keys SET
                    used_today = ?,
                    total_used = total_used + 1,
                    last_used_at = ?,
                    last_latency_ms = ?,
                    last_status = ?,
                    last_error = ?
                WHERE id = ?
                """, (used_today + 1, now, latency_ms, "healthy" if success else "error", "" if success else error_msg[:200], key_id))

            conn.commit()
            conn.close()

    def reset_circuit(self, provider_id: str) -> None:
        with _db_lock:
            conn = get_conn()
            conn.execute(
                "UPDATE providers SET consecutive_failures = 0, circuit_open_until = 0, last_error = '' WHERE id = ?",
                (provider_id,)
            )
            conn.commit()
            conn.close()


key_pool = KeyPoolManager()
