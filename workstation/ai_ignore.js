// ============================================================
// AI 工作站 · 扫描忽略规则
// ============================================================
// 每次点「建立/刷新索引」时，Python 会读取本文件。
// 改完保存即可，不用重启软件。
//
// 用法：
//   IGNORE_DIRS  —— 忽略这些目录名（递归扫描时整目录跳过）
//   IGNORE_EXTS  —— 忽略这些后缀（这些文件不进索引）
// ============================================================

const IGNORE_DIRS = [
    "node_modules", ".git", "__pycache__", "build", "dist",
    ".idea", ".vscode", "Debug", "Release", "out", "bin",
    ".qtcreator", ".pio", ".meteor", "coverage", ".nyc_output"
];

const IGNORE_EXTS = [
    ".exe", ".dll", ".pdb", ".obj", ".o", ".a", ".lib", ".so", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".psd",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".iso",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flv",
    ".pyc", ".pyo", ".class", ".jar", ".wasm",
    ".lock", ".log", ".tmp", ".cache"
];
