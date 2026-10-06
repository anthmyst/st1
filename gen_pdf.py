#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把抓取到的随身英语数据（data/archive/*.json 或 data/latest.json）渲染成
一份中英对照的 PDF（暖色手作风，与网页一致）。

依赖: weasyprint + 系统 CJK 字体（Noto Sans CJK）。
本地: 字体已装；GitHub Actions: 工作流里 apt-get install fonts-noto-cjk。
"""
import json
import os
import re

import weasyprint

HERE = os.path.dirname(os.path.abspath(__file__))


def esc(s):
    s = s if s else ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def en_part(t):
    if not t:
        return ""
    m = re.search(r"[\u4e00-\u9fff]", t)
    return (t[:m.start()].strip() if m and m.start() > 0 else t).strip()


def zh_part(t):
    if not t:
        return ""
    m = re.search(r"[\u4e00-\u9fff]", t)
    return t[m.start():].strip() if m else ""


def build_html(d):
    paras = d.get("paragraphs", [])
    body = []
    for p in paras:
        t = p.get("t") or "p"
        en = (p.get("en") or "").strip()
        zh = (p.get("zh") or "").strip()
        if t == "h":
            body.append(f'<h2 class="sec">{esc(zh or en)}</h2>')
            continue
        if t == "vocab":
            vzh = f'<div class="vzh">{esc(zh)}</div>' if zh else ""
            body.append(f'<div class="vocab"><div class="ven">{esc(en)}</div>{vzh}</div>')
            continue
        if t == "note":
            inner = ""
            if en:
                inner += f'<div class="nen">{esc(en)}</div>'
            if zh:
                inner += f'<div class="nzh">{esc(zh)}</div>'
            if inner:
                body.append(f'<div class="note">{inner}</div>')
            continue
        if not en and zh:
            body.append(f'<div class="note"><div class="nzh">{esc(zh)}</div></div>')
            continue
        # 普通段落
        num = ""
        if re.match(r"^\d+\s", en):
            m = re.match(r"^(\d+)\s+(.*)$", en, re.S)
            num, en = m.group(1), m.group(2)
        cls = "para"
        en_html = f'<span class="num">{num}</span>' if num else ""
        en_html += esc(en)
        zh_html = f'<div class="zh">{esc(zh)}</div>' if zh else ""
        body.append(f'<div class="{cls}"><div class="en">{en_html}</div>{zh_html}</div>')

    audio = d.get("audio") or ""
    src = d.get("url") or "https://www.bbc.co.uk/learningenglish/chinese/features/take-away-english"
    # PDF 里点击链接是在浏览器新标签页打开，会带 Referer → cooltv 代理会 403，
    # 故音频/原文统一指向 BBC 官方页（稳定可达）。
    audio_link = src
    date = d.get("pub") or ""
    if date:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
            date = f"{dt.year} 年 {dt.month} 月 {dt.day} 日"
        except Exception:
            pass

    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
@page {{ size: A4; margin: 16mm 15mm 18mm;
  @bottom-center {{ content: "随身英语 · 每日一读 · 第 {esc(d.get('ep','').replace('Episode ','') or '')} 期";
    font-family: W; font-size: 8.5px; color:#B9A894; }} }}
@font-face {{ font-family: W; src: local('Noto Sans CJK SC'), local('Noto Sans CJK JP'),
  local('NotoSansCJK-Regular'); }}
* {{ box-sizing: border-box; }}
body {{ font-family: W, sans-serif; color:#3D2E22; font-size: 10.6pt; line-height: 1.72;
  margin:0; }}
.head {{ border-bottom: 2px solid #EFE0CE; padding-bottom: 9pt; margin-bottom: 11pt; }}
.kick {{ font-size: 8.5pt; letter-spacing: .6px; color:#C2703D; font-weight:700;
  text-transform: uppercase; margin-bottom: 5pt; }}
.kick .pill {{ background:#FBEDDD; color:#C2703D; padding:1pt 7pt; border-radius:99pt;
  font-weight:700; }}
.title {{ font-size: 16pt; font-weight:700; color:#3D2E22; line-height:1.35; margin:0 0 2pt; }}
.sub {{ font-size: 11.5pt; color:#9C7B5C; font-weight:700; margin:0 0 3pt; }}
.meta {{ font-size: 9pt; color:#B9A894; margin-top:5pt; }}
.audio {{ font-size: 8.6pt; color:#9C7B5C; margin-top:4pt; word-break: break-all; }}
.note {{ background:#FBEDDD; border-radius: 7pt; padding: 8pt 11pt; margin: 7pt 0;
  font-size: 10pt; }}
.note .nen {{ color:#7A5530; font-weight:700; margin-bottom:3pt; }}
.note .nzh {{ color:#8A6034; }}
.sec {{ font-size: 11pt; font-weight:700; color:#C2703D; letter-spacing:.4px;
  margin: 13pt 0 6pt; padding-bottom:4pt; border-bottom:1px solid #EFE0CE; }}
.para {{ margin: 0 0 9pt; }}
.para .en {{ font-size: 10.6pt; color:#3D2E22; }}
.para .num {{ color:#C2703D; font-weight:700; margin-right:5pt; }}
.para .zh {{ font-size: 9.4pt; color:#9C7B5C; margin-top:2.5pt; padding-left:9pt;
  border-left:1.5pt solid #EFE0CE; }}
.vocab {{ background:#fff; border:1px solid #EFE0CE; border-radius:7pt; padding:6pt 10pt;
  margin:6pt 0; }}
.vocab .ven {{ font-weight:700; color:#C2703D; }}
.vocab .vzh {{ font-size:9.6pt; color:#7A5530; margin-top:2pt; }}
.foot {{ font-size: 8.4pt; color:#B9A894; margin-top: 12pt; border-top:1px solid #EFE0CE;
  padding-top:6pt; line-height:1.6; }}
.foot a {{ color:#C2703D; }}
</style></head><body>
<div class="head">
  <div class="kick"><span class="pill">{esc(d.get('level') or '中级')}</span>
    &nbsp;{esc(d.get('ep') or '')} · 随身英语 · TAKE AWAY ENGLISH</div>
  <div class="title">{esc(en_part(d.get('title'))) or esc(d.get('title',''))}</div>
  <div class="sub">{esc(zh_part(d.get('title')))}</div>
  <div class="meta">{esc(date)} · 中英对照阅读</div>
  {('<div class="audio">配套音频与原文：<a href="'+esc(audio_link)+'">'+esc(audio_link)+'</a></div>') if audio_link else ''}
</div>
{''.join(body)}
<div class="foot">内容版权归 BBC Learning English 所有，数据经 cooltv.top 获取，仅供个人学习使用。<br>
原文：<a href="{esc(src)}">{esc(src)}</a></div>
</body></html>"""


def build_pdf(data, out_path):
    """根据单期数据生成 PDF。返回输出路径。"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    html = build_html(data)
    weasyprint.HTML(string=html).write_pdf(out_path)
    return out_path


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data", "latest.json")
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "data", "latest.pdf")
    d = json.load(open(src, encoding="utf-8"))
    build_pdf(d, out)
    print("PDF ->", out, os.path.getsize(out), "bytes")
