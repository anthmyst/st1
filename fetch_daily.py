#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每天抓取 cooltv.top「词典 → BBC 学英语」的各栏目最新一期。

当前抓取三个栏目（在 SERIES 里增删即可）:
  - 随身英语  take-away-english  -> data/latest.json         + data/archive/       (cooltv 接口)
  - 媒体英语  media-english      -> data/media_latest.json   + data/archive_media/ (cooltv 接口)
  - G(英国卫报) kekenet course 17491 -> data/g_latest.json   + data/archive_g/     (kekenet 接口，AES 解密)
  - V(VOA常速)  kekenet course 20123 -> data/v_latest.json   + data/archive_v/     (kekenet 接口，AES 解密)

用法:
    python3 fetch_daily.py                     # 抓取各栏目最新一期 + 刷新归档
    python3 fetch_daily.py --all 60            # 抓取各栏目最新 60 期（首次建归档）
    python3 fetch_daily.py --series v          # 只抓指定栏目（tae / media / g / v）

输出:
    data/latest.json, data/media_latest.json, data/g_latest.json, data/v_latest.json  最新一期（网页直接读取）
    data/episodes.json, data/media_episodes.json, data/g_episodes.json, data/v_episodes.json  最近若干期索引
    data/archive/*.json, data/archive_media/*.json, data/archive_g/*.json, data/archive_v/*.json  每期完整数据归档

依赖:
    可可英语接口响应为 AES 加密，需 pycryptodome（pip install pycryptodome）
"""

import argparse
import json
import os
import sys
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE = "https://cooltv.top"
UA = "Mozilla/5.0 (TAE-Daily/1.0; +https://cooltv.top)"
# 这几期 BBC 没提供官方 PDF，保留历史生成的中英对照版作为唯一 PDF
KEEP_BILINGUAL = {"14iz5ra", "14iz5rh", "14jns7a", "14jns84", "14jns8b"}
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# 栏目配置：key 用于 --series 过滤，其余决定输出路径
SERIES = [
    {
        "key": "tae",
        "slug": "take-away-english",
        "name": "随身英语",
        "archive": "archive",
        "latest": "latest.json",
        "episodes": "episodes.json",
    },
    {
        "key": "media",
        "slug": "media-english",
        "name": "媒体英语",
        "archive": "archive_media",
        "latest": "media_latest.json",
        "episodes": "media_episodes.json",
    },
    {
        "key": "g",
        "slug": "guardian",
        "name": "G",
        "archive": "archive_g",
        "latest": "g_latest.json",
        "episodes": "g_episodes.json",
        "source": "kekenet",         # 走 kekenet 接口（非 cooltv）
        "course_id": "17491",        # 英国卫报
    },
    {
        "key": "v",
        "slug": "voa-standard",
        "name": "VOA常速",
        "archive": "archive_v",
        "latest": "v_latest.json",
        "episodes": "v_episodes.json",
        "source": "kekenet",         # 走 kekenet 接口（同 G）
        "course_id": "20123",        # VOA 常速英语（可可英语专栏）
    },
]


# ----------------------------------------------------------------------------
# 可可英语（kekenet）专栏抓取
#   数据接口: POST https://mob2015.kekenet.com/keke/mobile/index.php
#   响应 Data 字段为 AES-256-CBC(Pkcs7) 加密，解密后得到 JSON。
#   音频托管在 https://k6.kekenet.com/，支持 Range，可直接热链（无需下载进仓库）。
# ----------------------------------------------------------------------------
KEKE_API = "https://mob2015.kekenet.com/keke/mobile/index.php"
KEKE_AUDIO = "https://k6.kekenet.com/"
KEKE_KEY = "51E881E6F2A6Y9K8"          # AES 密钥（UTF-8，16 字节）
KEKE_IV = "9F0885C2D686C418"           # AES 初始向量（UTF-8，16 字节）

try:
    from Crypto.Cipher import AES as _AES
    _HAVE_CRYPTO = True
except Exception:                       # noqa: BLE001
    _HAVE_CRYPTO = False


def _keke_decrypt(hexstr):
    """把接口返回的加密 Data 还原为明文字符串。"""
    if not _HAVE_CRYPTO:
        raise RuntimeError("缺少 pycryptodome，无法解密 kekenet 数据（pip install pycryptodome）")
    ct = bytes.fromhex(hexstr)
    cipher = _AES.new(KEKE_KEY.encode("utf-8"), _AES.MODE_CBC, KEKE_IV.encode("utf-8"))
    pt = cipher.decrypt(ct)
    pad = pt[-1]
    if 1 <= pad <= 16:
        pt = pt[:-pad]
    return pt.decode("utf-8", errors="replace")


def keke_call(method, params, retries=3):
    """调用 kekenet 接口并解密返回（失败自动重试）。"""
    body = {
        "Method": method,
        "Params": params,
        "Token": "", "Terminal": 13, "Version": "4.0", "UID": "",
        "AppFlag": 18, "Sign": "", "ApTime": int(time.time() * 1000),
        "ApVersionCode": 100,
    }
    last = None
    for i in range(retries):
        try:
            req = Request(KEKE_API, data=json.dumps(body).encode("utf-8"),
                          headers={"User-Agent": UA, "Content-Type": "application/json"})
            with urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8"))
            if d.get("Code") != 200 or not d.get("Data"):
                return None
            return json.loads(_keke_decrypt(d["Data"]))
        except Exception as e:          # noqa: BLE001
            last = e
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"kekenet 接口 {method} 失败: {last}")


def run_kekenet(cfg, want):
    """抓取可可英语某专栏，返回 (新增期数, 归档总期数, 最新一期)。"""
    name = cfg["name"]
    course_id = cfg["course_id"]
    adir = os.path.join(DATA, cfg["archive"])
    os.makedirs(adir, exist_ok=True)

    # 1) 列表（按发布时间倒序；接口每页上限 20 条，按需翻页补足 want）
    items = []
    page = 1
    while len(items) < want:
        try:
            listing = keke_call("web_waikan_wknewslist",
                                {"catid": str(course_id), "PageSize": 20,
                                 "PageIndex": page, "Sort": "inputtime desc"})
        except Exception as e:          # noqa: BLE001
            print(f"！[{name}] 列表第 {page} 页失败: {e}", file=sys.stderr)
            break
        if not listing or not listing.get("list"):
            break
        page_items = listing["list"]
        items.extend(page_items)
        if len(page_items) < 20:
            break
        page += 1
    if not items:
        print(f"！[{name}] 未取到任何期数", file=sys.stderr)
        return 0, 0, None

    # 2) 逐篇抓详情，已归档的跳过
    have = {fn[:-5] for fn in os.listdir(adir) if fn.endswith(".json")}
    new_count = 0
    for it in items[:max(1, want)]:
        nid = str(it.get("id") or "").strip()
        if not nid or nid in have:
            continue
        try:
            art = keke_call("web_waikan_wkgetcontent", {"id": int(nid)})
        except Exception as e:          # noqa: BLE001
            print(f"！跳过 {it.get('title', '')[:40]} —— {e}", file=sys.stderr)
            continue
        if not art:
            continue
        paras = []
        for p in art.get("content", []) or []:
            en = (p.get("en") or "").strip()
            zh = (p.get("cn") or "").strip()
            if not en and not zh:
                continue
            paras.append({"t": "p", "en": en, "zh": zh})
        audio = (art.get("mp3") or art.get("playurl") or art.get("download") or "")
        if audio and not audio.startswith("http"):
            audio = KEKE_AUDIO + audio.lstrip("/")
        data = {
            "id": nid,
            "title": art.get("title") or it.get("title") or "",
            "enTitle": art.get("en_title") or "",
            "seriesName": name,
            "level": art.get("level_title") or "",
            "ep": it.get("updatetime") or art.get("updatetime") or nid,
            "pub": it.get("updatetime") or art.get("updatetime") or "",
            "url": art.get("web_url") or art.get("shareurl") or "",
            "audio": audio,
            "pdf": "",
            "pdfOfficial": "",          # kekenet 专栏无官方 PDF 直链（pdf_down 为标志位非 URL），故留空
            "desc": art.get("abstract") or it.get("title") or "",
            "paragraphs": paras,
        }
        with open(os.path.join(adir, f"{nid}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        have.add(nid)
        new_count += 1
        print(f"  ✓ [{name}] {data['ep']}  {data['title'][:52]}  ({len(paras)} 段)")

    # 3) 整理归档 + 生成 latest / episodes（与 cooltv 栏目同构）
    eps = []
    for fn in os.listdir(adir):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(adir, fn), encoding="utf-8") as f:
                eps.append(json.load(f))
        except Exception:               # noqa: BLE001
            continue
    eps.sort(key=lambda x: (x.get("pub") or ""), reverse=True)
    if not eps:
        print(f"！[{name}] 归档为空", file=sys.stderr)
        return new_count, 0, None

    latest = eps[0]
    with open(os.path.join(DATA, cfg["latest"]), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=1)

    index = [{
        "ep": e.get("ep") or "",
        "title": e.get("title") or "",
        "desc": e.get("desc") or "",
        "pub": e.get("pub") or "",
        "level": e.get("level") or "",
        "file": f"data/{cfg['archive']}/{e.get('id')}.json",
    } for e in eps[:60] if e.get("id")]
    with open(os.path.join(DATA, cfg["episodes"]), "w", encoding="utf-8") as f:
        json.dump({"series": name, "slug": cfg["slug"],
                   "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "latest": index[0] if index else None,
                   "items": index}, f, ensure_ascii=False, indent=1)

    return new_count, len(eps), latest


def get_json(path, retries=3):
    """请求 cooltv.top 的 JSON 接口，失败自动重试。"""
    url = path if path.startswith("http") else BASE + path
    last = None
    for i in range(retries):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:                     # noqa: BLE001
            last = e
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"请求失败 {url}: {last}")


def fetch_series_index(slug, fallback_name):
    """栏目列表接口，拿到栏目的基本信息。"""
    try:
        d = get_json("/api/bbcle/series")
    except Exception:                              # noqa: BLE001
        return {"slug": slug, "name": fallback_name}
    for g in d.get("groups", []):
        for it in g.get("items", []):
            if it.get("slug") == slug:
                return it
    return {"slug": slug, "name": fallback_name}


def fetch_episode_list(slug):
    """栏目最新 60 期列表。"""
    d = get_json(f"/api/bbcle?series={slug}")
    if not d.get("ok"):
        raise RuntimeError(f"列表接口返回异常: {d}")
    return d.get("items", [])


def fetch_article(link):
    """抓取单期详情：中英对照正文 + 音频 + PDF。"""
    d = get_json(f"/api/bbcle/article?url={quote(link, safe='')}")
    if not d.get("ok"):
        raise RuntimeError(f"详情接口返回异常: {d}")
    return d


def slim(article, name):
    """精简字段，只保留网页需要的。"""
    paras = []
    for p in article.get("paragraphs", []):
        t = p.get("t") or "p"
        en = (p.get("en") or "").strip()
        zh = (p.get("zh") or "").strip()
        if not en and not zh:
            continue
        paras.append({"t": t, "en": en, "zh": zh})
    media = article.get("media") or {}
    audio = media.get("url") or ""
    if audio.startswith("/"):
        audio = BASE + audio
    pdf = article.get("pdf") or ""
    if pdf.startswith("/"):
        pdf = BASE + pdf
    return {
        "title": article.get("title") or "",
        "seriesName": article.get("seriesName") or name,
        "level": article.get("level") or "",
        "ep": article.get("ep") or "",
        "pub": article.get("pub") or "",
        "url": article.get("url") or "",
        "audio": audio,
        "pdf": "",                 # 由本地生成的中英对照 PDF 填充
        "pdfOfficial": pdf,        # BBC 官方英文 PDF（直链）
        "paragraphs": paras,
    }

    # PDF 改为直接链接 cooltv.top 官方代理（/api/bbc-media?u=…），不再本地下载/落盘。

def run_series(cfg, want):
    """抓取单个栏目，返回 (新增期数, 归档总期数, 最新一期)。"""
    name = cfg["name"]
    adir = os.path.join(DATA, cfg["archive"])
    os.makedirs(adir, exist_ok=True)

    series = fetch_series_index(cfg["slug"], name)
    items = fetch_episode_list(cfg["slug"])
    if not items:
        print(f"！[{name}] 未取到任何期数", file=sys.stderr)
        return 0, 0, None

    picked = items[:max(1, want)]

    # 读取已有归档，避免重复抓取
    have = set()
    for fn in os.listdir(adir):
        if fn.endswith(".json"):
            have.add(fn[:-5])

    new_count = 0
    for idx, it in enumerate(picked):
        link = it.get("link") or ""
        key = (it.get("id") or "").strip() or f"ep{idx}"
        if not link:
            continue
        if key in have:
            continue                      # 已归档，跳过
        try:
            art = fetch_article(link)
        except Exception as e:                      # noqa: BLE001
            print(f"！跳过 {it.get('title', '')[:40]} —— {e}", file=sys.stderr)
            continue
        data = slim(art, name)
        data["id"] = it.get("id") or ""
        data["desc"] = it.get("desc") or ""
        with open(os.path.join(adir, f"{key}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        have.add(key)
        new_count += 1
        print(f"  ✓ [{name}] {data['ep'] or key}  {data['title'][:52]}")

    # ---- 归档整理：按 pub 排序，回填官方 PDF 到本地 ----
    eps = []
    for fn in os.listdir(adir):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(adir, fn), encoding="utf-8") as f:
                eps.append(json.load(f))
        except Exception:                           # noqa: BLE001
            continue
    eps.sort(key=lambda x: (x.get("pub") or "", x.get("ep") or ""), reverse=True)
    if not eps:
        print(f"！[{name}] 归档为空", file=sys.stderr)
        return new_count, 0, None

    for e in eps:
        changed = False
        eid = e.get("id") or ""
        if e.get("pdf") and eid not in KEEP_BILINGUAL:
            e["pdf"] = ""                # 不再生成中英对照 PDF，清掉残留引用
            changed = True
        if e.get("thumb"):
            e["thumb"] = ""              # 不再抓取封面图，清掉已删除图片的残留路径
            changed = True
        if changed and e.get("id"):
            with open(os.path.join(adir, f"{e.get('id')}.json"), "w", encoding="utf-8") as f:
                json.dump(e, f, ensure_ascii=False, indent=1)

    latest = eps[0]
    with open(os.path.join(DATA, cfg["latest"]), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=1)

    index = [{
        "ep": e.get("ep") or "",
        "title": e.get("title") or "",
        "desc": e.get("desc") or "",
        "pub": e.get("pub") or "",
        "level": e.get("level") or "",
        "file": f"data/{cfg['archive']}/{e.get('id')}.json",
    } for e in eps[:60] if e.get("id")]
    with open(os.path.join(DATA, cfg["episodes"]), "w", encoding="utf-8") as f:
        json.dump({"series": series.get("name", name),
                   "slug": cfg["slug"],
                   "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "latest": index[0] if index else None,
                   "items": index}, f, ensure_ascii=False, indent=1)

    return new_count, len(eps), latest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", type=int, default=1,
                    help="抓取每个栏目最新 N 期（默认 1，仅最新一期）")
    ap.add_argument("--series", default="",
                    help="只抓指定栏目 key（tae / media），默认全部")
    args = ap.parse_args()

    targets = SERIES
    if args.series:
        targets = [c for c in SERIES if c["key"] == args.series]
        if not targets:
            print(f"！未知栏目 {args.series}，可选: {', '.join(c['key'] for c in SERIES)}",
                  file=sys.stderr)
            sys.exit(1)

    for cfg in targets:
        print(f"\n=== {cfg['name']} ({cfg['slug']}) ===")
        if cfg.get("source") == "kekenet":
            n, total, latest = run_kekenet(cfg, args.all)
        else:
            n, total, latest = run_series(cfg, args.all)
        if latest:
            print(f"  → 新增 {n} 期，归档共 {total} 期")
            print(f"  → 最新一期：{latest.get('ep')}  {latest.get('title')}")


if __name__ == "__main__":
    main()
