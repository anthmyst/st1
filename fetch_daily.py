#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每天抓取 cooltv.top「词典 → BBC 学英语」的各栏目最新一期。

当前抓取两个栏目（在 SERIES 里增删即可）:
  - 随身英语  take-away-english  -> data/latest.json         + data/archive/
  - 媒体英语  media-english      -> data/media_latest.json   + data/archive_media/

用法:
    python3 fetch_daily.py                     # 抓取各栏目最新一期 + 刷新归档
    python3 fetch_daily.py --all 60            # 抓取各栏目最新 60 期（首次建归档）
    python3 fetch_daily.py --series media      # 只抓指定栏目（tae / media）

输出:
    data/latest.json, data/media_latest.json          最新一期（网页直接读取）
    data/episodes.json, data/media_episodes.json      最近若干期索引
    data/archive/*.json, data/archive_media/*.json    每期完整数据归档
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


def download_official_pdf(pdf_url, key, archive_name):
    """把 BBC 官方英文 PDF 下载到本站目录。

    cooltv 的 /api/bbc-media 代理有防盗链：脚本直连（无 Referer）可下载，
    但浏览器新标签打开会带 Referer 被拒（403 空白页），且地址栏暴露 cooltv.top。
    所以抓取时落盘，页面指向本站文件。
    """
    if not pdf_url:
        return ""
    fn = f"{(key or 'ep').replace(' ', '_')}.official.pdf"
    path = os.path.join(DATA, archive_name, fn)
    try:
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            return f"data/{archive_name}/{fn}"
        req = Request(pdf_url, headers={"User-Agent": UA})
        with urlopen(req, timeout=60) as r, open(path, "wb") as f:
            f.write(r.read())
        if os.path.getsize(path) > 1000:
            return f"data/{archive_name}/{fn}"
        os.remove(path)
    except Exception as e:                          # noqa: BLE001
        print(f"！官方 PDF 下载失败 {key}: {e}", file=sys.stderr)
    return ""


def purge_generated_pdfs(archive_name):
    """清理已生成的中英对照 PDF：用户只要官方版，不再生成/保留对照版。"""
    adir = os.path.join(DATA, archive_name)
    if not os.path.isdir(adir):
        return
    removed = 0
    for fn in os.listdir(adir):
        if fn.endswith(".pdf") and not fn.endswith(".official.pdf"):
            if fn[:-4] in KEEP_BILINGUAL:      # 这几期无官方 PDF，对照版要留着
                continue
            try:
                os.remove(os.path.join(adir, fn))
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
        print(f"已清理 {removed} 个中英对照 PDF（{archive_name}，仅保留官方版）")


def run_series(cfg, want):
    """抓取单个栏目，返回 (新增期数, 归档总期数, 最新一期)。"""
    name = cfg["name"]
    adir = os.path.join(DATA, cfg["archive"])
    os.makedirs(adir, exist_ok=True)
    purge_generated_pdfs(cfg["archive"])

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
        data["pdfOfficial"] = (download_official_pdf(data.get("pdfOfficial") or "", key, cfg["archive"])
                               or data.get("pdfOfficial") or "")
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
        off = e.get("pdfOfficial") or ""
        if off.startswith("http"):
            local = download_official_pdf(off, eid, cfg["archive"])
            if local:
                e["pdfOfficial"] = local
                changed = True
            else:
                # 官方 PDF 已失效（BBC 未发布或已下架）：留着死链会点开空白页，先清掉
                e["pdfOfficial"] = ""
                changed = True
        # 拿不到官方 PDF 时，若本地还有保留的中英对照版，就用它兜底
        if not (e.get("pdfOfficial") or "").strip():
            cand = f"data/{cfg['archive']}/{eid}.pdf"
            if os.path.exists(os.path.join(HERE, *cand.split("/"))):
                e["pdfOfficial"] = cand
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
        n, total, latest = run_series(cfg, args.all)
        if latest:
            print(f"  → 新增 {n} 期，归档共 {total} 期")
            print(f"  → 最新一期：{latest.get('ep')}  {latest.get('title')}")


if __name__ == "__main__":
    main()
