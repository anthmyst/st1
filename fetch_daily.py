#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每天抓取 cooltv.top「词典 → BBC 学英语 → 随身英语」的最新一期。

用法:
    python3 fetch_daily.py            # 抓取最新一期 + 刷新归档
    python3 fetch_daily.py --all 30   # 抓取最新 30 期（首次建立归档时用）

输出:
    data/latest.json   最新一期完整数据（网页直接读取）
    data/episodes.json 最近若干期索引（历史列表）
    data/archive/*.json 每一期的完整数据归档
"""

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE = "https://cooltv.top"
SERIES = "take-away-english"          # 随身英语
UA = "Mozilla/5.0 (TAE-Daily/1.0; +https://cooltv.top)"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ARCHIVE = os.path.join(DATA, "archive")
IMAGES = os.path.join(DATA, "img")


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


def fetch_series_index():
    """栏目列表接口，拿到随身英语的基本信息。"""
    d = get_json(f"/api/bbcle/series")
    for g in d.get("groups", []):
        for it in g.get("items", []):
            if it.get("slug") == SERIES:
                return it
    return {"slug": SERIES, "name": "随身英语"}


def fetch_episode_list():
    """随身英语最新 60 期列表。"""
    d = get_json(f"/api/bbcle?series={SERIES}")
    if not d.get("ok"):
        raise RuntimeError(f"列表接口返回异常: {d}")
    return d.get("items", [])


def fetch_article(link):
    """抓取单期详情：中英对照正文 + 音频 + PDF。"""
    d = get_json(f"/api/bbcle/article?url={quote(link, safe='')}")
    if not d.get("ok"):
        raise RuntimeError(f"详情接口返回异常: {d}")
    return d


def slim(article):
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
        "seriesName": article.get("seriesName") or "随身英语",
        "level": article.get("level") or "",
        "ep": article.get("ep") or "",
        "pub": article.get("pub") or "",
        "url": article.get("url") or "",
        "audio": audio,
        "pdf": "",                 # 由本地生成的中英对照 PDF 填充
        "pdfOfficial": pdf,        # BBC 官方英文 PDF（直链）
        "paragraphs": paras,
    }


def download_thumb(thumb_url, ep_id):
    """把封面图下载到本地（cooltv 的图片代理有防盗链，浏览器直连会 403）。"""
    if not thumb_url:
        return ""
    os.makedirs(IMAGES, exist_ok=True)
    ext = ".jpg"
    m = re.search(r"(jpeg|jpg|png|webp|gif)", (thumb_url.split("ctype=")[0] + thumb_url).lower())
    if m:
        ext = "." + m.group(1).replace("jpeg", "jpg")
    fn = f"{(ep_id or 'cover').replace(' ', '_')}{ext}"
    path = os.path.join(IMAGES, fn)
    if os.path.exists(path) and os.path.getsize(path) > 500:
        return f"data/img/{fn}"
    try:
        req = Request(thumb_url, headers={"User-Agent": UA})
        with urlopen(req, timeout=30) as r, open(path, "wb") as f:
            f.write(r.read())
        return f"data/img/{fn}"
    except Exception as e:                          # noqa: BLE001
        print(f"！封面下载失败 {ep_id}: {e}", file=sys.stderr)
        return ""


def download_official_pdf(pdf_url, key):
    """把 BBC 官方英文 PDF 下载到本站目录。

    cooltv 的 /api/bbc-media 代理有防盗链：脚本直连（无 Referer）可下载，
    但浏览器新标签打开会带 Referer 被拒（403 空白页），且地址栏暴露 cooltv.top。
    所以抓取时落盘，页面指向本站文件。
    """
    if not pdf_url:
        return ""
    fn = f"{(key or 'ep').replace(' ', '_')}.official.pdf"
    path = os.path.join(ARCHIVE, fn)
    try:
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            return f"data/archive/{fn}"
        req = Request(pdf_url, headers={"User-Agent": UA})
        with urlopen(req, timeout=60) as r, open(path, "wb") as f:
            f.write(r.read())
        if os.path.getsize(path) > 1000:
            return f"data/archive/{fn}"
        os.remove(path)
    except Exception as e:                          # noqa: BLE001
        print(f"！官方 PDF 下载失败 {key}: {e}", file=sys.stderr)
    return ""


def purge_generated_pdfs():
    """清理已生成的中英对照 PDF：用户只要官方版，不再生成/保留对照版。

    删除 data/archive/*.pdf（排除 *.official.pdf）与 data/latest.pdf。
    工作流随后会把这些删除提交上去，仓库里就只剩官方版。
    """
    removed = 0
    for fn in os.listdir(ARCHIVE):
        if fn.endswith(".pdf") and not fn.endswith(".official.pdf"):
            try:
                os.remove(os.path.join(ARCHIVE, fn))
                removed += 1
            except OSError:
                pass
    lp = os.path.join(DATA, "latest.pdf")
    if os.path.exists(lp):
        try:
            os.remove(lp)
            removed += 1
        except OSError:
            pass
    if removed:
        print(f"已清理 {removed} 个中英对照 PDF（仅保留官方版）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", type=int, default=1,
                    help="抓取最新 N 期（默认 1，仅最新一期）")
    ap.add_argument("--min", dest="minimum", type=int, default=1,
                    help="归档中至少保留的期数")
    args = ap.parse_args()

    os.makedirs(ARCHIVE, exist_ok=True)
    purge_generated_pdfs()          # 只要官方版：清掉历史生成的中英对照 PDF

    series = fetch_series_index()
    items = fetch_episode_list()
    if not items:
        print("！未取到任何期数", file=sys.stderr)
        sys.exit(1)

    want = max(1, args.all)
    picked = items[:want]

    # 读取已有归档，避免重复抓取（除非指定 --all 强制刷新）
    have = set()
    for fn in os.listdir(ARCHIVE):
        if fn.endswith(".json"):
            have.add(fn[:-5])

    new_count = 0
    for idx, it in enumerate(picked):
        link = it.get("link") or ""
        # 文件名用期号 id（如 14joj3a）
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
        data = slim(art)
        data["id"] = it.get("id") or ""
        remote_thumb = (BASE + it["thumb"]) if (it.get("thumb") or "").startswith("/") else (it.get("thumb") or "")
        data["thumb"] = download_thumb(remote_thumb, data.get("ep") or key) or remote_thumb
        data["desc"] = it.get("desc") or ""
        # 官方英文 PDF 落盘到本站，避免浏览器直连 cooltv 代理（403 + 暴露来源）
        data["pdfOfficial"] = (download_official_pdf(data.get("pdfOfficial") or "", key)
                               or data.get("pdfOfficial") or "")
        with open(os.path.join(ARCHIVE, f"{key}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        have.add(key)
        new_count += 1
        print(f"  ✓ {data['ep'] or key}  {data['title'][:52]}")

    # ---- 生成 latest.json ----
    latest_key = None
    newest = None
    for it in items:
        key = (it.get("id") or "").strip()
        # 期号在详情里；这里按列表顺序，第一个有归档的就是最新
        if key:
            # 列表不带 ep，需要靠归档内文件匹配
            pass
    # 直接用归档文件按 pub 时间排序取最新
    all_files = [f for f in os.listdir(ARCHIVE) if f.endswith(".json")]
    eps = []
    for fn in all_files:
        try:
            with open(os.path.join(ARCHIVE, fn), encoding="utf-8") as f:
                d = json.load(f)
            eps.append(d)
        except Exception:                           # noqa: BLE001
            continue
    eps.sort(key=lambda x: (x.get("pub") or "", x.get("ep") or ""), reverse=True)
    if not eps:
        print("！归档为空", file=sys.stderr)
        sys.exit(1)

    # 为尚未生成 PDF 的归档补一份（首次运行或新增时）
    # 同时把仍指向 cooltv 代理的官方 PDF 下载到本站（历史归档回填）
    for e in eps:
        changed = False
        if e.get("pdf"):                 # 不再生成中英对照 PDF，清掉残留引用
            e["pdf"] = ""
            changed = True
        off = e.get("pdfOfficial") or ""
        if off.startswith("http"):
            local = download_official_pdf(off, e.get("id") or "")
            if local:
                e["pdfOfficial"] = local
                changed = True
        if changed and e.get("id"):
            with open(os.path.join(ARCHIVE, f"{e.get('id')}.json"), "w", encoding="utf-8") as f:
                json.dump(e, f, ensure_ascii=False, indent=1)

    latest = eps[0]
    with open(os.path.join(DATA, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=1)

    index = [{
        "ep": e.get("ep") or "",
        "title": e.get("title") or "",
        "desc": e.get("desc") or "",
        "pub": e.get("pub") or "",
        "level": e.get("level") or "",
        "thumb": e.get("thumb") or "",
        "file": f"data/archive/{e.get('id')}.json",
    } for e in eps[:60] if e.get("id")]
    with open(os.path.join(DATA, "episodes.json"), "w", encoding="utf-8") as f:
        json.dump({"series": series.get("name", "随身英语"),
                   "slug": SERIES,
                   "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "latest": index[0] if index else None,
                   "items": index}, f, ensure_ascii=False, indent=1)

    print(f"\n完成：新增 {new_count} 期，归档共 {len(eps)} 期")
    print(f"最新一期：{latest.get('ep')}  {latest.get('title')}")


if __name__ == "__main__":
    main()
