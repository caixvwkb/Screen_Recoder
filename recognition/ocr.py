# This Python file uses the following encoding: utf-8
"""OCR 与 AI 友好输出支持。

目标：让截取的图片 / 打包的 PDF 方便 AI 查看理解。提供三件事：
  1. OCR 文字识别：基于 RapidOCR（rapidocr-onnxruntime），中文友好、可离线。
     —— 可选依赖：未安装时静默降级（不识别），不影响正常截图。
  2. 配套说明文件：批量截图 / PDF 输出后生成「说明.md」，AI 可直接读取
     （文件名 + 每张图的 OCR 文字）。
  3. PDF 隐形文字层：在 PDF 每页图片上叠加一层透明文字，AI / PDF 工具
     无需视觉也能直接提取文字。
"""
import os
import sys
import threading
import system.tracelog as tracelog
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

_engine_local = threading.local()  # 每线程一个 OCR 引擎（并行识别时互不干扰）

# 常驻 OCR 线程池：引擎在线程内懒加载并常驻，避免每次批量识别都重新加载模型
_ocr_pool = None
_ocr_pool_size = 0
_ocr_pool_lock = threading.Lock()

# 外置模型需要的 3 个文件（默认；若目录内存在 config.json 则以配置为准）
MODEL_FILES = [
    "ch_PP-OCRv4_det_infer.onnx",
    "ch_PP-OCRv4_rec_infer.onnx",
    "ch_ppocr_mobile_v2.0_cls_infer.onnx",
]


def _load_ocr_config(model_dir: str) -> dict:
    """读取 models/<dir>/config.json（相对路径配置模型组成）。

    文件不存在/解析失败返回空 dict（调用方回退默认硬编码）。
    支持的键（均为相对 model_dir 的文件名）：
      name        —— 模型名（日志展示用）；
      det_model / rec_model / cls_model —— 检测 / 识别 / 方向分类三个 onnx。
    """
    if not model_dir:
        return {}
    p = os.path.join(model_dir, "config.json")
    if not os.path.isfile(p):
        return {}
    try:
        import json
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            raise ValueError("config.json 顶层必须是 JSON 对象")
        return cfg
    except Exception as e:
        tracelog.warn(f"[OCR] config.json 读取失败（使用默认配置）: {e}")
        return {}


def _cfg_model_files(cfg: dict) -> list:
    """目录完整性/加载清单：config.json 指定 > 默认 MODEL_FILES。"""
    det = (cfg.get("det_model") or "").strip()
    rec = (cfg.get("rec_model") or "").strip()
    cls = (cfg.get("cls_model") or "").strip()
    if det and rec and cls:
        return [det, rec, cls]
    return list(MODEL_FILES)


def _cfg_name(cfg: dict) -> str:
    return (cfg.get("name") or "").strip() or "PP-OCRv4（默认配置）"


def _cfg_source_label(model_dir: str) -> str:
    """配置来源标注：config.json（外置） vs 内置默认（无 config.json）。"""
    if model_dir and os.path.isfile(os.path.join(model_dir, "config.json")):
        return "config.json（外置）"
    return "内置默认（无 config.json）"


# 模型来源日志去重（多线程加载只打一次避免刷屏；输出统一走 tracelog → trace.log）
_logged_sources = set()
_log_lock = threading.Lock()


def _log_engine_source(source: str):
    """每个模型来源只打印一次详细日志（4 个并行线程首次加载会各自触发，去重防刷屏）。

    来源变化（如用户换了模型目录）会重新打印。
    """
    key = os.path.normpath(source) if os.path.sep in source else source
    with _log_lock:
        if key in _logged_sources:
            return
        _logged_sources.add(key)
    tracelog.info(source)


def models_complete(model_dir: str) -> bool:
    """模型目录是否包含完整 OCR 模型（config.json 指定 > 默认清单）。"""
    if not model_dir or not os.path.isdir(model_dir):
        return False
    required = _cfg_model_files(_load_ocr_config(model_dir))
    return all(os.path.isfile(os.path.join(model_dir, n)) for n in required)


def resolve_model_dir(explicit_dir: str = "") -> str:
    """解析外置 OCR 模型目录：显式指定 > 自动探测 > 包内默认。

    自动探测顺序（按用途分目录的结构）：
      1. 打包后 exe 同级 models/ocr/ 或 models/；
      2. 源码运行则项目根 models/ocr/ 或 models/。
    返回目录路径；None 表示没有可用外置目录（回退 rapidocr 包内默认模型）。
    """
    if explicit_dir and models_complete(explicit_dir):
        return explicit_dir
    # 自动探测：多候选根（exe 同级 / 项目根 / 各自父级），兼容 Nuitka/PyInstaller
    from system.paths import app_base_candidates
    candidates = []
    for root in app_base_candidates():
        candidates.append(os.path.join(root, "models", "ocr"))  # 分用途目录（新结构）
        candidates.append(os.path.join(root, "models"))          # 兼容旧结构
    for c in candidates:
        if models_complete(c):
            tracelog.info(f"[OCR] 模型目录选定: {c}")
            return c
    tracelog.warn(f"[OCR] 未找到外置模型目录（已探测 {len(candidates)} 个候选，均不完整）")
    for c in candidates:
        tracelog.info(f"[OCR]   候选: {c}")
    return None


def _ocr_providers():
    """推理后端：有 CUDA EP 就优先 GPU（失败回退 CPU）；纯 CPU 环境返回 None（不传，保持现状）。"""
    try:
        import onnxruntime as ort
        if "CUDAExecutionProvider" in ort.get_available_providers():
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    except Exception:
        pass
    return None


def list_ocr_models(root_dir: str = "") -> list:
    """扫描 OCR 模型根目录，返回可用模型列表。

    每个可用模型 = 一个子目录（含 config.json 且 det/rec/cls 完整）；
    根目录本身也算一个（兼容旧扁平结构）。返回 [{name, path, label}]。
    """
    root = (root_dir or "").strip()
    if not root:
        root = resolve_model_dir("")
    if not root or not os.path.isdir(root):
        return []

    items = []
    if models_complete(root):
        cfg = _load_ocr_config(root)
        items.append({
            "name": _cfg_name(cfg),
            "path": root,
            "label": "",
        })
    for sub in sorted(os.listdir(root)):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        if not models_complete(d):
            continue
        cfg = _load_ocr_config(d)
        items.append({
            "name": _cfg_name(cfg),
            "path": d,
            "label": sub,
        })
    return items


def get_ocr_engine(model_dir: str = ""):
    """返回当前线程的 OCR 引擎（懒加载，每线程一个实例）。

    model_dir: 外置模型目录（可空）。指定后从该目录加载模型；留空自动探测
               （exe/源码旁 models/），都没有则用 rapidocr 包内默认模型。
    模型目录变化时自动重建引擎（缓存按目录作 key）。

    为什么每线程一个：RapidOCR 封装未承诺线程安全，若多个线程共用同一
    引擎实例就需加锁串行化，会抵消并行加速。改为每线程独立实例后，
    onnxruntime 推理会释放 GIL，多线程并行 OCR 可显著提速。
    单引擎限制 1 个推理线程：N 个并行引擎 = N 个 CPU 核，避免多引擎同时
    各占全部核导致严重超订（那会造成桌面卡顿）。
    不可用（未安装/加载失败）返回 None。
    """
    key = explicit_dir = (model_dir or "").strip()
    engine = getattr(_engine_local, "engine", None)
    engine_key = getattr(_engine_local, "engine_key", None)
    if engine is not None and engine_key == key:
        return engine if engine is not False else None
    files = list(MODEL_FILES)
    name = "PP-OCRv4（默认配置）"
    try:
        from rapidocr_onnxruntime import RapidOCR
        resolved = resolve_model_dir(explicit_dir)
        if resolved:  # 外置模型目录加载（热替换：换模型文件即生效）
            cfg = _load_ocr_config(resolved)
            files = _cfg_model_files(cfg)
            name = _cfg_name(cfg)
            _prov = _ocr_providers()
            _kw = {} if _prov is None else {"providers": _prov}
            _engine_local.engine = RapidOCR(
                det_model_path=os.path.join(resolved, files[0]),
                rec_model_path=os.path.join(resolved, files[1]),
                cls_model_path=os.path.join(resolved, files[2]),
                intra_op_num_threads=1, **_kw)
            _log_engine_source(
                f"[OCR] OCR 引擎加载成功：本地外置模型 {os.path.normpath(resolved)}（{name}）\n"
                f"      模型: {files[0]} / {files[1]} / {files[2]}\n"
                f"      推理: {'GPU（CUDA）' if _prov else 'CPU'}\n"
                f"      配置来源: {_cfg_source_label(resolved)}")
        else:  # 回退包内默认模型（rapidocr 自带 models/）
            _prov = _ocr_providers()
            _kw = {} if _prov is None else {"providers": _prov}
            try:
                _engine_local.engine = RapidOCR(intra_op_num_threads=1, **_kw)
            except TypeError:
                _engine_local.engine = RapidOCR(**_kw)
            _log_engine_source(
                f"[OCR] OCR 引擎加载成功：rapidocr 包内默认模型（未找到外置模型目录）"
                f"（推理: {'GPU（CUDA）' if _prov else 'CPU'}）")
        _engine_local.engine_key = key
    except Exception as e:
        tracelog.error(f"[OCR] 引擎加载失败，OCR 功能禁用: {e}")
        tracelog.error(f"[OCR] 提示：请将 OCR 模型（{' / '.join(files)}）"
               f"放到程序目录 models\\ocr\\ 下后重启软件（源码运行=项目根，打包版=exe 同级）")
        _engine_local.engine = False
        _engine_local.engine_key = key
    return _engine_local.engine if _engine_local.engine is not False else None


def get_ocr_pool(max_workers):
    """返回可容纳 max_workers 个并发任务的常驻线程池。

    关键：线程池常驻，池线程内的 OCR 引擎一次加载、长期复用——彻底避免
    "每次批量识别都要重新加载模型"导致的启动漫长。扩容（用户调高并发数）
    时重建并预热新引擎。
    """
    global _ocr_pool, _ocr_pool_size
    if _ocr_pool is not None and _ocr_pool_size >= max_workers:
        return _ocr_pool
    with _ocr_pool_lock:
        if _ocr_pool is not None and _ocr_pool_size >= max_workers:
            return _ocr_pool
        if _ocr_pool is not None:
            _ocr_pool.shutdown(wait=False)
        _ocr_pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ocr")
        _ocr_pool_size = max_workers
        # 预热：让每个池线程先加载引擎，避免首个任务真正开始时才触发加载
        # （那会表现为"点了识别半天没反应"）。首次加载不可避免，之后常驻秒开。
        warmups = [_ocr_pool.submit(get_ocr_engine) for _ in range(max_workers)]
        for f in warmups:
            try:
                f.result()
            except Exception:
                pass
    return _ocr_pool


def ocr_image_ndarray(img, model_dir: str = "") -> str:
    """识别内存图像（numpy ndarray，BGR/RGB 均可）文字，返回纯文本。

    供 PDF 内存合成等"无中间散图文件"场景使用：图像不落盘直接识别。
    失败 / 不可用返回空串。
    """
    engine = get_ocr_engine(model_dir)
    if engine is None or img is None:
        return ""
    try:
        result = engine(img)
        if isinstance(result, tuple):
            result = result[0]
        if not result:
            return ""
        lines = []
        for item in result:
            if isinstance(item, (list, tuple)) and len(item) >= 2 and item[1]:
                lines.append(str(item[1]))
        return "\n".join(lines)
    except Exception as e:
        tracelog.error(f"[OCR] 内存图像识别失败: {e}")
        return ""


def ocr_image(image_path: str, model_dir: str = "") -> str:
    """识别单张图片文字，返回纯文本（多行）。失败 / 不可用返回空串。

    model_dir: 可选，外置 OCR 模型目录。
    """
    engine = get_ocr_engine(model_dir)
    if engine is None or not os.path.exists(image_path):
        return ""
    try:
        result = engine(image_path)  # 每线程独立引擎，无需加锁
        # rapidocr_onnxruntime 返回 (result, elapse)，result 为 [box, text, score] 列表
        if isinstance(result, tuple):
            result = result[0]
        if not result:
            return ""
        lines = []
        for item in result:
            if isinstance(item, (list, tuple)) and len(item) >= 2 and item[1]:
                lines.append(str(item[1]))
        return "\n".join(lines)
    except Exception as e:
        tracelog.error(f"[OCR] 识别 {os.path.basename(image_path)} 失败: {e}")
        return ""


def ocr_images_parallel(files, max_workers=4, progress_cb=None, model_dir=""):
    """并行识别多张图片文字，返回 {图片路径: 文字}。

    max_workers: 并行数。任务投递到常驻线程池（引擎常驻，一次加载长期复用）；
                 onnxruntime 推理释放 GIL，多线程并行可显著加速（默认 4）。
    progress_cb: 可选回调 (已完成数, 总数, 当前文件名)。
    model_dir: 可选，外置 OCR 模型目录。
    """
    results = {}
    files = list(files)
    total = len(files)
    if total == 0:
        return results
    pool = get_ocr_pool(max_workers)
    futures = {pool.submit(ocr_image, f, model_dir): f for f in files}
    for i, fut in enumerate(as_completed(futures), 1):
        f = futures[fut]
        try:
            results[f] = fut.result()
        except Exception as e:
            tracelog.error(f"[OCR] 并行识别失败 {os.path.basename(f)}: {e}")
            results[f] = ""
        if progress_cb:
            progress_cb(i, total, os.path.basename(f))
    ok = sum(1 for v in results.values() if (v or "").strip())
    tracelog.info(f"[OCR] 批量识别完成: 共 {total} 个文件，识别出文字 {ok} 个，空/失败 {total - ok} 个"
           f"（模型: {model_dir or '自动探测'}）")
    return results


def ocr_images_ndarray_parallel(frames, max_workers=4, progress_cb=None, model_dir=""):
    """并行识别内存帧（QImage 列表），返回 {索引: 文字}。

    供 PDF 内存合成使用：全程无中间散图文件。QImage 在本线程（后台导出
    线程）读取像素是只读操作，跨线程安全；识别前转为 ndarray。
    """
    results = {}
    frames = list(frames)
    total = len(frames)
    if total == 0:
        return results
    import numpy as np

    def _frame_to_rgb(img):
        try:
            # PySide6 枚举是类属性（img.Format_RGB888 实例访问会 AttributeError）；
            # constBits() 返回 memoryview（无 setsize，np.frombuffer 直接用）；
            # QImage 扫描线按 4 字节对齐，需按 bytesPerLine 取行再去 padding。
            from PySide6.QtGui import QImage
            rgb = img.convertToFormat(QImage.Format.Format_RGB888)
            h, w = rgb.height(), rgb.width()
            bpl = rgb.bytesPerLine()
            view = rgb.constBits()          # memoryview
            row = np.frombuffer(view, dtype=np.uint8).reshape(h, bpl)
            return row[:, :w * 3].reshape(h, w, 3).copy()
        except Exception:
            return None

    arrays = [(i, _frame_to_rgb(f)) for i, f in enumerate(frames)]
    arrays = [(i, a) for i, a in arrays if a is not None]
    if not arrays:
        return results
    pool = get_ocr_pool(max_workers)
    futures = {pool.submit(ocr_image_ndarray, a, model_dir): i for i, a in arrays}
    for fut in as_completed(futures):
        i = futures[fut]
        try:
            results[i] = fut.result()
        except Exception as e:
            tracelog.error(f"[OCR] 内存帧 {i} 识别失败: {e}")
            results[i] = ""
        if progress_cb:
            progress_cb(len(results), total, f"帧 {i+1}")
    return results


def write_sidecar_md(folder: str, items, md_name: str = "说明.md") -> str:
    """在 folder 下生成说明.md。

    items: list[dict]，每项含 {file: 图片路径, ocr_text: OCR 文字(可空)}。
    md_name: 说明文件名（默认 说明.md）。
    返回生成的 .md 路径；失败返回空串。
    """
    try:
        if not items:
            return ""
        os.makedirs(folder, exist_ok=True)
        lines = [
            "# 截图说明",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        for i, it in enumerate(items, 1):
            name = os.path.basename(it.get("file", ""))
            lines.append(f"## {i}. {name}")
            ocr_text = (it.get("ocr_text") or "").strip()
            if ocr_text:
                lines.append("```text")
                lines.append(ocr_text)
                lines.append("```")
            lines.append("")
        path = os.path.join(folder, md_name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return path
    except Exception as e:
        tracelog.error(f"[OCR] 生成说明.md 失败: {e}")
        return ""


def build_ocr_items(files) -> list:
    """对一批图片做 OCR，返回 write_sidecar_md 可用的 items 列表。"""
    items = []
    for f in files:
        items.append({"file": f, "ocr_text": ocr_image(f)})
    return items
