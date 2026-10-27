"""B站官方 web 接口：关键词搜索 + 评论抓取（免登录，需 buvid3/buvid4 指纹 cookie）。

实测（2026-10-21）：
- `GET /x/web-interface/search/type?search_type=video&keyword=...` 带指纹 cookie 返回 20 条/页，含 bvid/aid/播放/时长/UP主；
- `GET /x/v2/reply?type=1&oid=<aid>&pn=1&ps=20&sort=2` 返回热门评论（按点赞），总数可读；
- 不带指纹 cookie 会返回 `code=0 + v_voucher`（风控空包），因此必须先访问首页并取 `x/frontend/finger/spi`。
"""
import re
import hashlib
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
TAG_RE = re.compile(r"<[^>]+>")

# WBI 混淆表（B站前端公开算法）：img_key/sub_key 取 nav 接口返回的文件名
MIXIN_TABLE = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]


async def _wbi_mixin(client: httpx.AsyncClient) -> Optional[str]:
    """取 nav 的 img_key/sub_key，按混淆表拼出 32 位 mixin key。"""
    try:
        nav = await client.get("https://api.bilibili.com/x/web-interface/nav")
        data = (nav.json() or {}).get("data") or {}
        wbi = data.get("wbi_img") or {}
        img = str(wbi.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
        sub = str(wbi.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
        if not img or not sub:
            return None
        raw = img + sub
        return "".join(raw[i] for i in MIXIN_TABLE)[:32]
    except Exception:
        return None


def _sign_wbi(params: Dict[str, Any], mixin: str) -> str:
    """返回带 wts/w_rid 的完整 query string。"""
    payload = {**params, "wts": int(time.time())}
    query = "&".join(
        f"{key}={urllib.parse.quote(str(value), safe='')}" for key, value in sorted(payload.items())
    )
    query = "".join(ch for ch in query if ch not in "!'()*")
    w_rid = hashlib.md5((query + mixin).encode()).hexdigest()
    return f"{query}&w_rid={w_rid}"


async def _signed_get(client: httpx.AsyncClient, path: str, params: Dict[str, Any], referer: str) -> httpx.Response:
    mixin = await _wbi_mixin(client)
    if not mixin:
        return await client.get(f"https://api.bilibili.com{path}", params=params, headers={"Referer": referer})
    return await client.get(
        f"https://api.bilibili.com{path}?{_sign_wbi(params, mixin)}", headers={"Referer": referer}
    )


def _text(value: Any) -> str:
    return " ".join(TAG_RE.sub("", str(value or "")).split())


def _client(proxy: Optional[str], timeout_sec: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout_sec,
        follow_redirects=True,
        proxy=proxy or None,
        headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/", "Accept-Language": "zh-CN,zh;q=0.9"},
    )


async def _prime_cookies(client: httpx.AsyncClient) -> None:
    """访问一次首页拿 buvid3/b_nut，再取 buvid4，避免搜索接口返回 v_voucher 空包。"""
    try:
        await client.get("https://www.bilibili.com/")
        spi = await client.get("https://api.bilibili.com/x/frontend/finger/spi")
        data = (spi.json() or {}).get("data") or {}
        if data.get("b_3"):
            client.cookies.set("buvid3", data["b_3"], domain=".bilibili.com")
        if data.get("b_4"):
            client.cookies.set("buvid4", data["b_4"], domain=".bilibili.com")
    except Exception:
        pass


def _normalize_video(raw: Dict[str, Any]) -> Dict[str, Any]:
    bvid = raw.get("bvid") or ""
    aid = raw.get("aid")
    return {
        "platform": "bilibili",
        "bvid": bvid,
        "aid": aid,
        "title": _text(raw.get("title")),
        "author": _text(raw.get("author")),
        "author_id": raw.get("mid"),
        "cover": ("https:" + raw["pic"]) if str(raw.get("pic") or "").startswith("//") else raw.get("pic"),
        "play": raw.get("play"),
        "danmaku": raw.get("video_review") or raw.get("danmaku"),
        "favorites": raw.get("favorites"),
        "duration": raw.get("duration"),
        "pubdate": raw.get("pubdate") or raw.get("senddate"),
        "description": _text(raw.get("description"))[:300],
        "url": f"https://www.bilibili.com/video/{bvid}" if bvid else (raw.get("arcurl") or ""),
        "tag": _text(raw.get("tag"))[:120],
    }


async def search_videos(
    keyword: str, limit: int = 20, page: int = 1, proxy: Optional[str] = None, timeout_sec: float = 20.0
) -> Dict[str, Any]:
    """B站视频搜索（官方 web 接口）。返回 {'items': [...], 'total': int, 'page': int}。"""
    word = (keyword or "").strip()
    if not word:
        raise ValueError("搜索关键词不能为空")
    async with _client(proxy, timeout_sec) as client:
        await _prime_cookies(client)
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/search/type",
            params={"search_type": "video", "keyword": word, "page": max(1, int(page))},
            headers={"Referer": "https://search.bilibili.com/"},
        )
        payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if payload.get("code") != 0:
            raise RuntimeError(f"B站搜索 HTTP {resp.status_code}：{payload.get('message') or resp.text[:120]}")
        data = payload.get("data") or {}
        if data.get("v_voucher"):
            # 未签名请求被风控时，用 WBI 签名重试一次
            signed = await _signed_get(
                client, "/x/web-interface/wbi/search/type",
                {"search_type": "video", "keyword": word, "page": max(1, int(page))},
                "https://search.bilibili.com/",
            )
            sp = signed.json() if signed.headers.get("content-type", "").startswith("application/json") else {}
            data = (sp.get("data") or {})
            if sp.get("code") != 0 or data.get("v_voucher"):
                raise RuntimeError("B站搜索触发风控（v_voucher），请稍后重试或更换出口 IP")
        items = [_normalize_video(x) for x in (data.get("result") or [])][: max(1, min(int(limit), 40))]
        return {"keyword": word, "page": data.get("page") or page, "total": data.get("numResults"), "items": items}


async def fetch_comments(
    bvid: Optional[str] = None, aid: Optional[int] = None, page: int = 1, limit: int = 20,
    sort: str = "hot", proxy: Optional[str] = None, timeout_sec: float = 20.0,
) -> Dict[str, Any]:
    """抓取 B站视频评论；oid 即 aid。sort=hot 按热度（点赞），sort=new 按时间。"""
    if not aid and not bvid:
        raise ValueError("需要 bvid 或 aid")
    async with _client(proxy, timeout_sec) as client:
        await _prime_cookies(client)
        if not aid:
            view = await _signed_get(
                client, "/x/web-interface/wbi/view", {"bvid": bvid},
                f"https://www.bilibili.com/video/{bvid}/",
            )
            vp = view.json() if view.headers.get("content-type", "").startswith("application/json") else {}
            if vp.get("code") != 0:
                plain = await client.get(
                    "https://api.bilibili.com/x/web-interface/view",
                    params={"bvid": bvid},
                    headers={"Referer": f"https://www.bilibili.com/video/{bvid}/"},
                )
                vp = plain.json() if plain.headers.get("content-type", "").startswith("application/json") else {}
            if vp.get("code") != 0:
                raise RuntimeError(f"B站取 aid 失败（{vp.get('code') or view.status_code}）：{vp.get('message') or ''}")
            aid = (vp.get("data") or {}).get("aid")
        resp = await client.get(
            "https://api.bilibili.com/x/v2/reply",
            params={"type": 1, "oid": aid, "pn": max(1, int(page)), "ps": max(1, min(int(limit), 49)),
                    "sort": 2 if sort == "hot" else 0},
            headers={"Referer": f"https://www.bilibili.com/video/{bvid or 'av' + str(aid)}/"},
        )
        payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if payload.get("code") != 0:
            raise RuntimeError(f"B站评论 HTTP {resp.status_code}：{payload.get('message') or resp.text[:120]}")
        data = payload.get("data") or {}
        replies = data.get("replies") or []
        items: List[Dict[str, Any]] = []
        for item in replies:
            member = item.get("member") or {}
            content = item.get("content") or {}
            items.append(
                {
                    "rpid": item.get("rpid"),
                    "author": member.get("uname"),
                    "avatar": member.get("avatar"),
                    "level": (member.get("level_info") or {}).get("current_level"),
                    "content": (content.get("message") or "").strip(),
                    "like": item.get("like") or 0,
                    "reply_count": item.get("rcount") or 0,
                    "ctime": item.get("ctime"),
                    "is_up": bool((item.get("reply_control") or {}).get("is_up_top")) or member.get("mid") == (data.get("upper") or {}).get("mid"),
                }
            )
        page_info = data.get("page") or {}
        return {
            "bvid": bvid,
            "aid": aid,
            "page": page_info.get("num") or page,
            "total": page_info.get("count") or page_info.get("acount") or len(items),
            "sort": sort,
            "items": items,
        }
async def search_users(
    keyword: str, limit: int = 20, page: int = 1, proxy: Optional[str] = None, timeout_sec: float = 20.0
) -> Dict[str, Any]:
    """B站 UP主搜索（官方 bili_user 通道）：mid、昵称、粉丝数、投稿数、等级、认证、头像。"""
    word = (keyword or "").strip()
    if not word:
        raise ValueError("搜索关键词不能为空")
    async with _client(proxy, timeout_sec) as client:
        await _prime_cookies(client)
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/search/type",
            params={"search_type": "bili_user", "keyword": word, "page": max(1, int(page))},
            headers={"Referer": "https://search.bilibili.com/"},
        )
        payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        data = payload.get("data") or {}
        if payload.get("code") != 0 or data.get("v_voucher"):
            signed = await _signed_get(
                client, "/x/web-interface/wbi/search/type",
                {"search_type": "bili_user", "keyword": word, "page": max(1, int(page))},
                "https://search.bilibili.com/",
            )
            sp = signed.json() if signed.headers.get("content-type", "").startswith("application/json") else {}
            data = sp.get("data") or {}
            if sp.get("code") != 0 or data.get("v_voucher"):
                raise RuntimeError("B站 UP主搜索触发风控（v_voucher），请稍后重试")
        users: List[Dict[str, Any]] = []
        for raw in (data.get("result") or [])[: max(1, min(int(limit), 40))]:
            mid = raw.get("mid")
            official = (raw.get("official_verify") or {}).get("desc")
            users.append(
                {
                    "platform": "bilibili",
                    "mid": mid,
                    "uname": _text(raw.get("uname")),
                    "avatar": ("https:" + raw["upic"]) if str(raw.get("upic") or "").startswith("//") else raw.get("upic"),
                    "fans": raw.get("fans"),
                    "videos": raw.get("videos"),
                    "level": raw.get("level"),
                    "sign": _text(raw.get("usign"))[:160],
                    "official": _text(official)[:60] if official else None,
                    "url": f"https://space.bilibili.com/{mid}" if mid else None,
                }
            )
        return {"keyword": word, "page": data.get("page") or page, "total": data.get("numResults"), "items": users}
