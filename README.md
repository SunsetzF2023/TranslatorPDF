# PDF 中英对照翻译 / Bilingual PDF Translator

把英文 PDF 变成中英对照阅读：左边原文、右边中文，逐段对齐，可导出双语 PDF / HTML。
完全免费，不需要任何 API key（使用 Google / Bing / MyMemory 的公开网页接口）。

## 安装

需要 Python 3.10+。

```bash
pip install -r requirements.txt
# Linux 上如果提示没有 tkinter：sudo apt install python3-tk
```

## 使用

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

- **引擎**：`google`（默认）、`bing`、`mymemory`。都是免费公开接口，没有官方 SLA；某个引擎被限流时会自动切换到下一个。数据中心 / 云服务器 IP 经常被 Google（HTTP 429）和 Bing（HTTP 401）拒绝，本机网络一般正常；开发环境里只有 `mymemory` 实测通过。
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
