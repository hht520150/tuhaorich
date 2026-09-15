# -*- coding: utf-8 -*-
"""
TuHao.RICH 网页版 - CS2 饰品实时查价（Firepulse API）
后端：Flask，复用原桌面版的 Firepulse 接口逻辑。
"""
import json
import os
import ssl
import urllib.request
import urllib.error

from flask import Flask, request, jsonify, send_from_directory

BASE_URL = "https://open.firepulse.com.cn/open"
SECTOR_BASE = "https://firepulse.com.cn"
IMG_BASE = "https://static.firepulse.com.cn"
DEFAULT_API_KEY = "GWVYB3NSFWO5BBWTUIUPIDQ"

WEAR_KEYWORDS = ["崭新出厂", "略有磨损", "久经沙场", "破损不堪", "战痕累累"]

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.json.ensure_ascii = False


def normalize(s):
    if not s:
        return ""
    s = s.replace("（★）", "").replace("(★)", "").replace("★", "")
    return " ".join(s.split())


def extract_wear(name):
    for kw in WEAR_KEYWORDS:
        if kw in name:
            return kw
    return ""


def full_img_url(u):
    if not u:
        return ""
    u = str(u)
    if u.startswith("http"):
        return u
    return IMG_BASE + (u if u.startswith("/") else "/" + u)


class FirepulseClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def _post(self, url, body, headers):
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            resp = urllib.request.urlopen(req, timeout=30, context=self.ctx)
            return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                msg = json.loads(raw).get("message") or raw
            except Exception:
                msg = raw
            return {"_error": True, "_code": e.code, "_msg": str(msg)[:200]}
        except Exception as e:
            return {"_error": True, "_code": 0, "_msg": str(e)}

    def skin_search(self, keyword):
        return self._post(
            BASE_URL + "/v1/wiki/skin_search",
            {"name": keyword},
            {"Content-Type": "application/json", "Api-Key": self.api_key,
             "User-Agent": "Mozilla/5.0"},
        )

    def query_price(self, name, wear=""):
        data = self.skin_search(name)
        if not data or data.get("_error"):
            return None, data
        items = []
        if data.get("code") == 200 and data.get("data"):
            items = data["data"].get("list") or []
        else:
            return None, data
        norm_name = normalize(name)
        matched = []
        for it in items:
            sn = normalize(it.get("short_name", ""))
            n = normalize(it.get("name", ""))
            if sn == norm_name or n == norm_name or norm_name in sn or norm_name in n:
                matched.append(it)
        if not matched:
            for it in items:
                sn = normalize(it.get("short_name", ""))
                if norm_name and (norm_name in sn or sn in norm_name):
                    matched.append(it)
        if wear:
            wm = [it for it in matched if extract_wear(it.get("name", "")) == wear]
            if wm:
                matched = wm
        seen = set()
        unique = []
        for it in matched:
            key = it.get("id") or it.get("name")
            if key not in seen:
                seen.add(key)
                unique.append(it)
        return unique, data

    def sector_post(self, path, body, referer_path=""):
        return self._post(
            SECTOR_BASE + path,
            body,
            {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0",
             "Referer": SECTOR_BASE + referer_path, "Accept": "application/json"},
        )

    def sector_list(self):
        data = self.sector_post(
            "/v1/market/facade/category/list/new",
            {"category_type": -1, "date_type": 1, "is_unique": 1, "has_sort": True},
            "/sector/1",
        )
        if not data or data.get("_error"):
            return data
        raw = data.get("data") or []
        if not isinstance(raw, list):
            return {"_error": True, "_code": 0, "_msg": "板块数据格式异常"}
        return [x for x in raw if isinstance(x, dict) and x.get("category_type") == 2]

    def sector_skins(self, category_id, page=1, page_size=20):
        return self.sector_post(
            "/v1/market/facade/category/skin/list",
            {"category_id": str(category_id), "date_type": 2, "sort": "desc",
             "sort_type": "change_percent", "page": page, "page_size": page_size,
             "display_point": True},
            "/sector/" + str(category_id),
        )

    def skin_t_chart(self, skin_id, date_range="1", platform="all"):
        return self.sector_post(
            "/v1/market/facade/quote/skin_t_chart",
            {"id": str(skin_id), "date_range": str(date_range), "platform": platform},
            "/sector/" + str(skin_id),
        )


client = FirepulseClient(os.environ.get("FIREPULSE_API_KEY", DEFAULT_API_KEY))

WEB_DIR = os.path.dirname(os.path.abspath(__file__))


@app.get("/")
def index():
    return send_from_directory(os.path.join(WEB_DIR, "static"), "index.html")


@app.post("/api/query")
def api_query():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    wear = (body.get("wear") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "请输入饰品名称"})
    results, data = client.query_price(name, wear)
    if results is None:
        err = ""
        if isinstance(data, dict):
            err = "{} {}".format(data.get("_code", ""), data.get("_msg", "")).strip()
        return jsonify({"ok": False, "error": err or "查询失败"})
    items = []
    for r in results:
        items.append({
            "id": r.get("id", ""),
            "name": r.get("name", ""),
            "wear": extract_wear(r.get("name", "")),
            "price": r.get("price", ""),
            "buy_price": r.get("buy_price", ""),
            "platform": r.get("platform", ""),
            "ratio": r.get("ratio", ""),
            "sell_count": r.get("sell_count", ""),
            "img": full_img_url(r.get("img", "") or r.get("image", "")),
        })
    return jsonify({"ok": True, "items": items})


@app.post("/api/chart")
def api_chart():
    body = request.get_json(silent=True) or {}
    skin_id = body.get("id")
    dr = str(body.get("range") or "1")
    pf = body.get("platform") or "all"
    if not skin_id:
        return jsonify({"ok": False, "error": "缺少饰品 id"})
    data = client.skin_t_chart(skin_id, dr, pf)
    if not data or data.get("_error"):
        msg = data.get("_msg", "趋势数据获取失败") if isinstance(data, dict) else "趋势数据获取失败"
        return jsonify({"ok": False, "error": str(msg)})
    raw = data.get("data") or []
    rows = []
    for r in raw:
        if not isinstance(r, (list, tuple)) or len(r) < 3:
            continue
        try:
            ts = int(float(r[0]))
            price = float(r[1])
            sell = float(r[2])
            buy = float(r[3]) if len(r) > 3 and r[3] not in (None, "") else 0.0
            buyc = float(r[4]) if len(r) > 4 and r[4] not in (None, "") else 0.0
        except Exception:
            continue
        rows.append([ts, price, sell, buy, buyc])
    return jsonify({"ok": True, "data": rows})


@app.get("/api/sectors")
def api_sectors():
    data = client.sector_list()
    if not isinstance(data, list):
        msg = data.get("_msg", "板块获取失败") if isinstance(data, dict) else "板块获取失败"
        return jsonify({"ok": False, "error": str(msg)})
    sectors = []
    for x in data:
        sectors.append({
            "id": x.get("id"),
            "name": x.get("name"),
            "index_value": x.get("current_index"),
            "change_index": x.get("change_index"),
            "change_index_percent": x.get("change_index_percent"),
            "index_values": x.get("index_values") or [],
            "img": full_img_url(x.get("img")),
        })
    return jsonify({"ok": True, "sectors": sectors})


@app.post("/api/sector_skins")
def api_sector_skins():
    body = request.get_json(silent=True) or {}
    cid = body.get("category_id")
    if not cid:
        return jsonify({"ok": False, "error": "缺少板块 id"})
    data = client.sector_skins(cid)
    if not data or data.get("_error"):
        msg = data.get("_msg", "饰品获取失败") if isinstance(data, dict) else "饰品获取失败"
        return jsonify({"ok": False, "error": str(msg)})
    d = data.get("data") or {}
    raw = d.get("skins") or d.get("list") or d.get("items") or []
    skins = []
    for x in raw:
        skins.append({
            "id": x.get("id") or x.get("skin_id"),
            "name": x.get("name") or x.get("skin_name"),
            "index_value": x.get("index_value"),
            "change_index": x.get("change_index"),
            "change_index_percent": x.get("change_index_percent"),
            "current_sell_count": x.get("current_sell_count"),
            "img": full_img_url(x.get("img") or x.get("icon") or x.get("image")),
        })
    return jsonify({"ok": True, "skins": skins, "total": d.get("total") or len(skins)})


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
