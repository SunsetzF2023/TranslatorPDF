# PDF 中英对照翻译 / Bilingual PDF Translator

把英文 PDF 变成中英对照阅读：左边原文、右边中文，逐段对齐，可导出双语 PDF / HTML。
完全免费，不需要任何 API key（使用 Google / Bing / MyMemory 的公开网页接口）。

两种用法：**网页版**（GitHub Pages，打开就能用，零安装）和**桌面版**（Python，可导出双语 PDF）。

## 网页版（GitHub Pages）

`docs/` 是一个纯静态页面，没有后端：PDF 在浏览器里用 pdf.js 解析，文件不上传，只有段落文本会发给翻译接口。

开启方法：仓库 Settings → Pages → Source 选 `Deploy from a branch`，分支 `main`、目录 `/docs`，保存后访问 `https://<用户名>.github.io/<仓库名>/`。

本地预览：

```bash
python -m http.server 8000 --directory docs   # 打开 http://localhost:8000
```

功能：选择 / 拖入 PDF、页码范围、引擎（Google / MyMemory）、简繁体、停止、浏览器打印或“存为 PDF”、下载中英对照 HTML；译文缓存在浏览器 localStorage。

## 安装（桌面版）

需要 Python 3.10+。

```bash
pip install -r requirements.txt
# Linux 上如果提示没有 tkinter：sudo apt install python3-tk
```

## 使用（桌面版）

桌面界面：

```bash
python app.py
```

1. 打开 PDF → 2.（可选）填页码范围、选引擎和简/繁 → 3. 开始翻译 → 4. 导出 PDF / HTML。

命令行（批量、无界面）：

```bash
python app.py paper.pdf                          # 生成 paper_bilingual.pdf
python app.py paper.pdf -o out.html --provider bing --first-page 1 --last-page 10
```

## 说明

- **引擎**：`google`（默认，用 `translate_a/t` —— Chrome 词典的接口，带 `Access-Control-Allow-Origin: *`，所以网页版也能用）、`bing`（桌面版专用，本开发环境返回 HTTP 401）、`mymemory`（有每日额度，频繁调用会 HTTP 429）。都是免费公开接口，没有官方 SLA；失败会重试并自动切换到另一个引擎。
- **重试**：网页版里已翻译的段落会缓存，再点一次“开始翻译”只会重试失败的段落。
- **缓存**：译文按段落哈希存在 `~/.pdf_bilingual_translator/cache.sqlite3`，重复翻译同一文档不再消耗网络。
- **排版**：按 PDF 文本块切段，自动合并跨行断词和跨块的半句。扫描件（图片型 PDF）没有文字层，需要先 OCR。
- **导出 PDF** 使用 PyMuPDF 内置中日韩字体（简体 `china-s`，繁体 `china-t`），不依赖系统字体。

## 结构

| 文件 | 作用 |
| --- | --- |
| `pdfbt/pdf_reader.py` | 提取段落、合并断行 |
| `pdfbt/translator.py` | 三个免费翻译后端 + 线程池 + 回退 |
| `pdfbt/cache.py` | SQLite 译文缓存 |
| `pdfbt/exporter.py` | 导出双语 PDF / HTML |
| `pdfbt/gui.py` | tkinter 界面（左右分栏、同步滚动） |
| `pdfbt/cli.py` | 命令行模式 |
| `docs/` | GitHub Pages 网页版（pdf.js + fetch，无后端） |
