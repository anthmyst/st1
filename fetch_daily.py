#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每天抓取 cooltv.top「词典 → BBC 学英语」下多个栏目的最新一期。

用法:
    python3 fetch_daily.py            # 各栏目抓取最新一期 + 刷新归档
    python3 fetch_daily.py --all 30   # 各栏目抓取最新 30 期（首次建立归档时用）

每个栏目产出:
    data/<prefix>latest.json    该栏目最新一期完整数据
    data/<prefix>episodes.json  该栏目最近若干期索引
    data/<prefix>archive/*.json 每一期的完整数据归档

当前栏目:
    take-away-english  随身英语   (prefix 为空)
    media-english      媒体英语   (prefix = media_)
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
UA = "Mozilla/5.0 (TAE-Daily/1.0; +https://cooltv.top)"
# 这几期 BBC 没提供官方 PDF，保留历史生成的中英对照版作为唯一 PDF
KEEP_BILINGUAL = {"14iz5ra", "14iz5rh", "14jns7a", "14jns84", "14jns8b"}
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ARCHIVE = os.path.join(DATA, "archive")

# (slug, 输出前缀, 中文名) —— 前缀为空时覆盖默认的 latest.json/episodes.json/archive
SERIES_LIST = [
    ("take-away-english", "", "随身英语"),
    ("media-english", "media_", "媒体英语"),
]


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


def fetch_series_index(slug):
    """栏目列表接口，拿到指定 slug 的基本信息。"""
    d = get_json("/api/bbcle/series")
    for g in d.get("groups", []):
        for it in g.get("items", []):
            if it.get("slug") == slug:
                return it
    return {"slug": slug, "name": slug}


def fetch_episode_list(slug):
    """指定栏目最新 60 期列表。"""
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
        "seriesName": article.get("seriesName") or "",
        "level": article.get("level") or "",
        "ep": article.get("ep") or "",
        "pub": article.get("pub") or "",
        "url": article.get("url") or "",
        "audio": audio,
        "pdf": "",                 # 由本地生成的中英对照 PDF 填充
        "pdfOfficial": pdf,        # BBC 官方英文 PDF（直链）
        "paragraphs": paras,
    }


def download_official_pdf(pdf_url, key, arch_dir=ARCHIVE):
    """把 BBC 官方英文 PDF 下载到本站目录。

    cooltv 的 /api/bbc-media 代理有防盗链：脚本直连（无 Referer）可下载，
    但浏览器新标签打开会带 Referer 被拒（403 空白页），且地址栏暴露 cooltv.top。
    所以抓取时落盘，页面指向本站文件。
    """
    if not pdf_url:
        return ""
    fn = f"{(key or 'ep').replace(' ', '_')}.official.pdf"
    path = os.path.join(arch_dir, fn)
    try:
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            return f"data/{os.path.basename(arch_dir)}/{fn}"
        req = Request(pdf_url, headers={"User-Agent": UA})
        with urlopen(req, timeout=60) as r, open(path, "wb") as f:
            f.write(r.read())
        if os.path.getsize(path) > 1000:
            return f"data/{os.path.basename(arch_dir)}/{fn}"
        os.remove(path)
    except Exception as e:                          # noqa: BLE001
        print(f"！官方 PDF 下载失败 {key}: {e}", file=sys.stderr)
    return ""


def purge_generated_pdfs(arch_dir=ARCHIVE):
    """清理已生成的中英对照 PDF：用户只要官方版，不再生成/保留对照版。

    删除 arch_dir 下 *.pdf（排除 *.official.pdf）。
    """
    removed = 0
    for fn in os.listdir(arch_dir):
        if fn.endswith(".pdf") and not fn.endswith(".official.pdf"):
            if fn[:-4] in KEEP_BILINGUAL:      # 这几期无官方 PDF，对照版要留着
                continue
            try:
                os.remove(os.path.join(arch_dir, fn))
                removed += 1
            except OSError:
                pass
    if removed:
        print(f"已清理 {removed} 个中英对照 PDF（仅保留官方版）")


def run_series(slug, prefix, display):
    arch_dir = ARCHIVE if not prefix else os.path.join(DATA, prefix + "archive")
    os.makedirs(arch_dir, exist_ok=True)
    purge_generated_pdfs(arch_dir)
    # 主栏目(前缀为空)额外清理历史生成的 latest.pdf
    if arch_dir == ARCHIVE:
        lp = os.path.join(DATA, "latest.pdf")
        if os.path.exists(lp):
            try:
                os.remove(lp)
            except OSError:
                pass

    series = fetch_series_index(slug)
    items = fetch_episode_list(slug)
    if not items:
        print(f"！[{display}] 未取到任何期数", file=sys.stderr)
        return

    want = max(1, args.all)
    picked = items[:want]

    have = {fn[:-5] for fn in os.listdir(arch_dir) if fn.endswith(".json")}

    new_count = 0
    for idx, it in enumerate(picked):
        link = it.get("link") or ""
        key = (it.get("id") or "").strip() or f"ep{idx}"
        if not link or key in have:
            continue
        try:
            art = fetch_article(link)
        except Exception as e:                      # noqa: BLE001
            print(f"！跳过 [{display}] {it.get('title', '')[:40]} —— {e}", file=sys.stderr)
            continue
        data = slim(art)
        data["id"] = it.get("id") or ""
        data["desc"] = it.get("desc") or ""
        # 官方英文 PDF 落盘到本站，避免浏览器直连 cooltv 代理（403 + 暴露来源）
        off = download_official_pdf(data.get("pdfOfficial") or "", key, arch_dir)
        data["pdfOfficial"] = off or data.get("pdfOfficial") or ""
        with open(os.path.join(arch_dir, f"{key}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        have.add(key)
        new_count += 1
        print(f"  ✓ [{display}] {data['ep'] or key}  {data['title'][:52]}")

    # ---- 生成 <prefix>latest.json / <prefix>episodes.json ----
    all_files = [f for f in os.listdir(arch_dir) if f.endswith(".json")]
    eps = []
    for fn in all_files:
        try:
            with open(os.path.join(arch_dir, fn), encoding="utf-8") as f:
                eps.append(json.load(f))
        except Exception:                           # noqa: BLE001
            continue
    eps.sort(key=lambda x: (x.get("pub") or "", x.get("ep") or ""), reverse=True)
    if not eps:
        print(f"！[{display}] 归档为空", file=sys.stderr)
        return

    # 把仍指向 cooltv 代理的官方 PDF 下载到本站（历史归档回填）
    for e in eps:
        changed = False
        eid = e.get("id") or ""
        if e.get("pdf") and eid not in KEEP_BILINGUAL:
            e["pdf"] = ""
            changed = True
        if e.get("thumb"):
            e["thumb"] = ""
            changed = True
        off = e.get("pdfOfficial") or ""
        if off.startswith("http"):
            local = download_official_pdf(off, eid, arch_dir)
            e["pdfOfficial"] = local if local else ""
            changed = True
        if not (e.get("pdfOfficial") or "").strip():
            cand = f"data/{prefix}archive/{eid}.pdf"
            if os.path.exists(os.path.join(HERE, *cand.split("/"))):
                e["pdfOfficial"] = cand
                changed = True
        if changed and e.get("id"):
            with open(os.path.join(arch_dir, f"{e.get('id')}.json"), "w", encoding="utf-8") as f:
                json.dump(e, f, ensure_ascii=False, indent=1)

    latest = eps[0]
    with open(os.path.join(DATA, f"{prefix}latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=1)

    index = [{
        "ep": e.get("ep") or "",
        "title": e.get("title") or "",
        "desc": e.get("desc") or "",
        "pub": e.get("pub") or "",
        "level": e.get("level") or "",
        "file": f"data/{prefix}archive/{e.get('id')}.json",
    } for e in eps[:60] if e.get("id")]
    with open(os.path.join(DATA, f"{prefix}episodes.json"), "w", encoding="utf-8") as f:
        json.dump({"series": display, "slug": slug,
                   "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "latest": index[0] if index else None,
                   "items": index}, f, ensure_ascii=False, indent=1)

    print(f"\n[{display}] 完成：新增 {new_count} 期，归档共 {len(eps)} 期")
    print(f"[{display}] 最新一期：{latest.get('ep')}  {latest.get('title')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", type=int, default=1,
                    help="每个栏目抓取最新 N 期（默认 1，仅最新一期）")
    ap.add_argument("--min", dest="minimum", type=int, default=1,
                    help="归档中至少保留的期数")
    global args
    args = ap.parse_args()

    for slug, prefix, display in SERIES_LIST:
        try:
            run_series(slug, prefix, display)
        except Exception as e:                      # noqa: BLE001
            print(f"！[{display}] 系列抓取失败: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
