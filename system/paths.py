# -*- coding: utf-8 -*-
"""绿色化路径解析（设置/缓存随程序目录，打包多文件模式适用）。

- 源码运行：程序根 = 项目根（本文件所在目录）
- 打包后（standalone 多文件）：程序根 = exe 所在目录
- settings.json / 缓存文件夹 / 默认输出 全部落在程序根下，随程序走，
  拷贝整个文件夹即绿色便携。
"""
import os
import sys

from system.tracelog import info, debug, warn


def is_compiled() -> bool:
    """是否编译打包环境（Nuitka standalone / PyInstaller）。

    注意：Nuitka **默认不设置 sys.frozen**（那是 PyInstaller 的约定），
    可靠检测是 `"__compiled__" in globals()`；此处两者都兼容，
    避免打包版把程序根/模型探测路径算错（曾导致 OCR/ASR 外置模型找不到）。
    """
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


# 路径解析日志去重（app_root/app_base_candidates 会被高频调用，值不变不重复刷屏；
# 值变化说明运行环境/目录异常，此时必定记录）
_last_logged_candidates = None
_last_logged_root = None


def _source_root() -> str:
    """源码运行的项目根：从本文件所在目录（system/）向上找含 pyproject.toml 的目录。

    重构后 paths.py 位于 system/ 包内，__file__ 目录不再是程序根；
    打包环境不经过此函数（走 sys.executable 分支）。
    """
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.exists(os.path.join(d, "pyproject.toml")) or os.path.exists(os.path.join(d, "mainwindow_fluent.py")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.dirname(os.path.abspath(__file__))


def app_base_candidates() -> list:
    """候选程序根目录列表（多来源兜底，避免单一路径判断在打包环境出错）。

    - 编译环境：sys.executable 所在目录（exe 同级，多文件模式程序根）
    - 源码运行：项目根（_source_root()，含 pyproject.toml 的特征目录）
    - 各自父级（兼容 models 放在上级目录的布局）
    自动过滤含 .exe 后缀的伪路径（Nuitka 编译模块 __file__ 可能为伪路径）。
    """
    global _last_logged_candidates
    dirs = []
    if is_compiled() and sys.executable:
        dirs.append(os.path.dirname(sys.executable))
    dirs.append(_source_root() if not is_compiled() else os.path.dirname(os.path.abspath(__file__)))
    out = []
    for d in dirs:
        d = os.path.normpath(d)
        if not d or d in out:
            continue
        if ".exe" in d.lower() and not os.path.isdir(d):
            continue  # Nuitka 伪路径（形如 ...\mainwindow_fluent.exe\ocr.py → dirname 含 .exe 且非目录）
        out.append(d)
        parent = os.path.dirname(d)
        if parent and parent != d and parent not in out:
            out.append(parent)
    if out != _last_logged_candidates:
        _last_logged_candidates = out
        info(f"[路径] 候选程序根目录: {out}")
    return out


def app_root() -> str:
    """程序根目录：打包后=exe 同级；源码运行=项目根（system/ 上级的特征目录）。"""
    global _last_logged_root
    if is_compiled():
        root = os.path.dirname(sys.executable)
    else:
        root = _source_root()
    if root != _last_logged_root:
        _last_logged_root = root
        info(f"[路径] 程序根: {root}（{'编译环境，exe 同级' if is_compiled() else '源码运行，项目根'}）")
    return root


def cache_dir() -> str:
    """缓存文件夹（程序根/cache，自动创建）。

    各功能（ASR 临时转码 wav、文件夹 OCR 的 PDF 扫描件渲染页等）的
    中间缓存统一放这里，随程序目录走，不污染系统临时目录。
    """
    d = os.path.join(app_root(), "cache")
    os.makedirs(d, exist_ok=True)
    debug(f"[路径] 缓存目录: {d}")
    return d


def settings_file() -> str:
    """绿色配置文件路径：程序根/settings.json。"""
    p = os.path.join(app_root(), "settings.json")
    debug(f"[路径] 配置文件: {p}")
    return p


def default_output_dir() -> str:
    """默认录制输出目录：程序根/Recordings。"""
    d = os.path.join(app_root(), "Recordings")
    os.makedirs(d, exist_ok=True)
    debug(f"[路径] 默认输出目录: {d}")
    return d
