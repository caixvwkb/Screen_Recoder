# This Python file uses the following encoding: utf-8
"""文件夹批量 OCR：把一个文件夹里的图片 / PDF 逐个识别成文字，每个文件生成一个说明.md。

与 ocr.py 的分工：
  - ocr.py 提供「单张图片 OCR（ocr_image）」与「多张图合并成一个说明.md」；
  - 本模块负责「批量扫描 + 每个文件对应一个 <文件名>_说明.md」的场景：
      图片  -> 直接 OCR；
      PDF   -> 用 PyMuPDF(fitz) 提取文字层；若是扫描件（无文字层）则逐页渲染成
               图片再 OCR。fitz 未安装时 PDF 跳过（图片仍可用）。
本模块不含任何 Qt / 界面代码，纯逻辑，可独立测试。
"""
import tracelog
import os
import shutil
import tempfile
from datetime import datetime

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}


def scan_folder(folder: str, recursive: bool = True, include_pdf: bool = True) -> list:
    """扫描文件夹，返回图片 / PDF 文件的绝对路径列表（按名称排序）。

    recursive: 是否包含子文件夹（os.walk）。
    include_pdf: 是否包含 .pdf 文件（需要 PyMuPDF）。
    """
    files = []
    if not os.path.isdir(folder):
        return files
    if recursive:
        for root, _dirs, names in os.walk(folder):
            for n in sorted(names):
                ext = os.path.splitext(n)[1].lower()
                if ext in IMAGE_EXTS or (include_pdf and ext == ".pdf"):
                    files.append(os.path.join(root, n))
    else:
        for n in sorted(os.listdir(folder)):
            p = os.path.join(folder, n)
            if not os.path.isfile(p):
                continue
            ext = os.path.splitext(n)[1].lower()
            if ext in IMAGE_EXTS or (include_pdf and ext == ".pdf"):
                files.append(p)
    return files


def ocr_pdf(pdf_path: str, progress_cb=None, model_dir: str = "") -> str:
    """提取 PDF 文字；无文字层（扫描件）时逐页渲染为图片再 OCR。

    返回按页组织的文本；失败 / 库不可用返回空串。
    progress_cb: 可选回调 (当前页, 总页数)，PDF 内部逐页时调用。
    model_dir: 可选，外置 OCR 模型目录（扫描件渲染识别用）。
    """
    try:
        import pymupdf as fitz  # 新版 PyMuPDF 包名（消除 fitz 弃用 warning）
    except ImportError:
        try:
            import fitz  # 旧版 (1.22 classic) 只提供 fitz 模块名
        except ImportError:
            tracelog.warn(f"[文件夹OCR] 未安装 PyMuPDF，跳过 PDF: {os.path.basename(pdf_path)}")
            return ""
    try:
        from ocr import ocr_image
        doc = fitz.open(pdf_path)
        total = doc.page_count
        pages = []
        from paths import cache_dir
        tmp = tempfile.mkdtemp(prefix="sr_pdfocr_", dir=cache_dir())
        try:
            for i, page in enumerate(doc):
                text = page.get_text().strip()
                if len(text) < 2:  # 无文字层 → 渲染成图再 OCR
                    pix = page.get_pixmap(dpi=150)
                    img_path = os.path.join(tmp, f"p{i}.png")
                    pix.save(img_path)
                    text = ocr_image(img_path, model_dir)
                pages.append(text)
                if progress_cb:
                    progress_cb(i + 1, total)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        doc.close()
        if not pages:
            return ""
        parts = [f"（共 {len(pages)} 页）"]
        for i, t in enumerate(pages, 1):
            parts.append(f"--- 第 {i} 页 ---\n{t.strip()}")
        return "\n\n".join(parts)
    except Exception as e:
        tracelog.error(f"[文件夹OCR] 解析 PDF 失败 {os.path.basename(pdf_path)}: {e}")
        return ""


def ocr_any_file(file_path: str, progress_cb=None, model_dir: str = "") -> str:
    """对单个文件做文字识别：图片直接 OCR，PDF 提取/渲染 OCR。"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return ocr_pdf(file_path, progress_cb, model_dir)
    from ocr import ocr_image
    return ocr_image(file_path, model_dir)


def ocr_files_parallel(files, max_workers=4, progress_cb=None, model_dir="",
                         cancel_event=None, on_file_done=None):
    """并行识别多个文件（图片 / PDF 混合），返回 {文件路径: 文字}。

    max_workers: 并行数。任务投递到常驻线程池（引擎常驻，一次加载长期复用），
                 onnxruntime 推理释放 GIL，多线程并行可显著加速（默认 4）。
    progress_cb: 可选回调 (已完成数, 总数, 当前文件名)。
    model_dir: 可选，外置 OCR 模型目录。
    cancel_event: threading.Event；置位时停止提交新任务并取消未开始的任务，
                  已完成的文件照常回调（打断后已识别内容不丢）。
    on_file_done: 可选回调 (文件路径, 识别文本)——每个文件识别完成立即调用
                  （按文件为单位即时输出，不等全部完成）。
    """
    from concurrent.futures import as_completed, CancelledError
    from ocr import get_ocr_pool
    results = {}
    files = list(files)
    total = len(files)
    if total == 0:
        return results
    pool = get_ocr_pool(max_workers)
    futures = {}
    for f in files:
        if cancel_event and cancel_event.is_set():
            break
        futures[pool.submit(ocr_any_file, f, None, model_dir)] = f
    for i, fut in enumerate(as_completed(futures), 1):
        if cancel_event and cancel_event.is_set():
            for f2 in list(futures):
                if not f2.done():
                    f2.cancel()
            break
        f = futures[fut]
        try:
            text = fut.result()
        except CancelledError:
            break
        except Exception as e:
            tracelog.error(f"[文件夹OCR] 并行识别失败 {os.path.basename(f)}: {e}")
            text = ""
        results[f] = text
        if progress_cb:
            progress_cb(i, total, os.path.basename(f))
        if on_file_done:
            try:
                on_file_done(f, text)
            except Exception:
                pass
    return results


def is_ocred(file_path: str, out_dir: str = None) -> bool:
    """时间标签识别：输出 <名>_说明.md 存在且修改时间 >= 源文件 → 已识别。

    用于未完成重传：批量识别前扫描，跳过已完成文件（软件重启/打断后
    也能准确识别哪些已完成）。
    """
    folder = out_dir or os.path.dirname(file_path)
    base = os.path.splitext(os.path.basename(file_path))[0]
    md = os.path.join(folder, f"{base}_说明.md")
    if not os.path.isfile(md):
        return False
    try:
        return os.path.getmtime(md) >= os.path.getmtime(file_path)
    except OSError:
        return False


def write_file_sidecar(file_path: str, text: str, out_dir: str = None) -> str:
    """生成 <文件名>_说明.md，返回 md 路径；失败返回空串。

    out_dir: 指定输出目录（汇总输出用）；None/空 = 写在源文件同目录。
    """
    try:
        folder = out_dir or os.path.dirname(file_path)
        os.makedirs(folder, exist_ok=True)
        base = os.path.splitext(os.path.basename(file_path))[0]
        md_path = os.path.join(folder, f"{base}_说明.md")
        kind = "PDF 文档" if os.path.splitext(file_path)[1].lower() == ".pdf" else "图片"
        lines = [
            f"# {os.path.basename(file_path)}",
            "",
            f"- 文件: `{file_path}`",
            f"- 类型: {kind}",
            f"- 识别时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 识别文字",
            "",
        ]
        t = (text or "").strip()
        if t:
            lines.append("```text")
            lines.append(t)
            lines.append("```")
        else:
            lines.append("（未识别到文字）")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return md_path
    except Exception as e:
        tracelog.error(f"[文件夹OCR] 生成说明失败 {file_path}: {e}")
        return ""


def write_merged_image_md(folder: str, items, md_name: str = None) -> str:
    """把多张图片的 OCR 结果合并写成一个 md 到 folder 下。

    items: list[dict]，每项含 {file: 图片路径, ocr_text: OCR 文字(可空)}。
    md_name: 合并文件命名，默认取 folder 的目录名（如 资料_图片说明.md）。
    返回 md 路径；失败返回空串。
    """
    try:
        if not items:
            return ""
        if not md_name:
            base = os.path.basename(os.path.normpath(folder)) or "图片"
            md_name = f"{base}_图片说明.md"
        os.makedirs(folder, exist_ok=True)
        lines = [
            "# 图片汇总说明",
            "",
            f"- 图片数量: {len(items)}",
            f"- 识别时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        for i, it in enumerate(items, 1):
            name = os.path.basename(it.get("file", ""))
            lines.append(f"## {i}. {name}")
            t = (it.get("ocr_text") or "").strip()
            if t:
                lines.append("```text")
                lines.append(t)
                lines.append("```")
            else:
                lines.append("（未识别到文字）")
            lines.append("")
        path = os.path.join(folder, md_name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return path
    except Exception as e:
        tracelog.error(f"[文件夹OCR] 生成合并说明失败: {e}")
        return ""
