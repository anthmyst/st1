# 随身英语 · 每日一读

每天自动抓取 cooltv.top「词典 → BBC 学英语 → 随身英语（Take Away English）」的最新一期，
生成一个可以直接打开的网页：英文正文、官方中文导读、词汇表、测验与答案、音频播放器、PDF 下载。

打开网页即是当天内容，不用再去网站一层层点。

## 文件结构

```
cooltv-tae/
├── index.html                  # 每日一屏网页（打开即读）
├── fetch_daily.py              # 抓取脚本（Python 3，无第三方依赖）
├── gen_pdf.py                  # 把某期数据渲染成中英对照 PDF（依赖 weasyprint）
├── requirements.txt            # PDF 生成依赖（weasyprint）
├── data/
│   ├── latest.json             # 最新一期完整数据
│   ├── latest.pdf              # 最新一期的中英对照 PDF
│   ├── episodes.json           # 往期索引
│   ├── archive/*.json          # 每期完整数据归档
│   ├── archive/*.pdf           # 每期中英对照 PDF（可单期下载）
│   └── img/*.jpg               # 每期封面（本地化，绕开防盗链）
└── .github/workflows/daily.yml # GitHub Actions 每日自动抓取+发布
```

## 方案一：云端全自动（推荐，电脑不开机也能更新）

1. 在 GitHub 新建一个仓库（Public），把这个文件夹整个推上去：

   ```bash
   cd cooltv-tae
   git init && git add -A && git commit -m "init: 随身英语每日一读"
   git branch -M main
   git remote add origin https://github.com/<你的用户名>/<仓库名>.git
   git push -u origin main
   ```

2. 开启 GitHub Pages：仓库 **Settings → Pages → Build and deployment →
   Source 选「GitHub Actions」**（只需设置这一次）。

3. 手动跑一次验证：仓库 **Actions → daily-take-away-english → Run workflow**。
   成功后访问 `https://<你的用户名>.github.io/<仓库名>/` 即可。

之后每天北京时间约 **06:30** 自动抓取、自动发布，手机把该网址「添加到主屏幕」，
就是一个每天更新的 App。

> 免费额度足够：每天一次运行约 30 秒，远低于免费额度上限。

## 方案二：本地手动运行

```bash
python3 fetch_daily.py          # 抓最新 1 期
python3 fetch_daily.py --all 60 # 首次使用：补齐最近 60 期归档
```

然后随便起个静态服务器看 `index.html`：

```bash
python3 -m http.server 8899
# 浏览器打开 http://localhost:8899
```

注意：直接双击 index.html（file:// 协议）无法读取 data/*.json，
必须走 http 服务或部署到线上。

## 网页功能

- 音频播放器：倍速（0.7×/0.85×/1×/1.25×）、循环、拖动进度
- 「只看英文」模式：隐藏中文导读，做阅读训练
- 点任意英文单词：自动朗读 + 显示音标提示
- 往期回顾：右上角「往期」抽屉，共 60 期可回看
- 下载 PDF（中英对照）/ 官方 PDF（BBC 英文版）/ MP3：一键保存到本地
- 移动端自适应，支持「添加到主屏幕」

## PDF 说明

`fetch_daily.py` 在抓取每期的同时，会用 `gen_pdf.py` 生成一份**中英对照 PDF**
（暖色手作风，含英文正文、官方中文导读、词汇表、测验与答案、原文链接），
保存到 `data/archive/<id>.pdf`，最新一期另存 `data/latest.pdf`。

本地运行需满足：① `pip install -r requirements.txt`；② 系统装有 CJK 字体
（Linux：`sudo apt-get install fonts-noto-cjk`；macOS：`brew install font-noto-cjk`）。
仅想要 BBC 官方英文 PDF 的，网页「官方PDF」按钮即可。

> 注意：PDF 里的音频/原文链接指向 BBC 官方页。cooltv 的音频代理有防盗链，
> 在浏览器直开会 403；听音频请在网页播放器里点（已用 no-referrer 处理）。

## 数据来源与版权

内容来自 [BBC Learning English - 随身英语](https://www.bbc.co.uk/learningenglish/chinese/features/take-away-english)，
经 cooltv.top 的公开接口加速获取，版权归 BBC 所有，仅供个人学习使用，请勿商用或二次分发。
