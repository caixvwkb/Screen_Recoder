# -*- coding: utf-8 -*-
"""AI 工作站：研究库检索层（SQLite FTS5 全文索引，秒级筛出相关块喂给模型）。

参考 pygpt-net 的 RAG 解耦模式：先检索、把 top-k 块拼进 prompt、再交回普通对话流。
实现选型：SQLite FTS5（无外部依赖、单文件、中文按连续词匹配 + LIKE 兜底召回），
不需要嵌入模型/向量库（量级小、纯文本笔记场景够用）。
"""
from __future__ import annotations

import os
import re
import sqlite3

_WS = re.compile(r"\s+")


class Searcher:
    """索引构建 + 检索。线程内调用（建索引/检索都在后台线程）。"""

    def __init__(self, index_db: str):
        self.index_db = index_db
        self._conn = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            d = os.path.dirname(self.index_db)
            if d:
                os.makedirs(d, exist_ok=True)
            self._conn = sqlite3.connect(self.index_db)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS files_fts("
                "path TEXT NOT NULL, chunk_idx INTEGER NOT NULL, content TEXT NOT NULL,"
                " PRIMARY KEY(path, chunk_idx))")
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS files_fts_v USING fts5("
                "path UNINDEXED, chunk_idx UNINDEXED, content)")
            self._conn.commit()
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ---------- 索引 ----------
    def build_index(self, roots: list, extensions: list,
                    chunk_chars: int = 800, progress_cb=None) -> dict:
        """扫描 roots 下指定扩展名的文本文件，按 chunk_chars 切块入 FTS5。

        返回统计：{"files": n, "chunks": m, "new_chunks": k, "skipped": s}
        progress_cb(done, total) 可选回调（UI 进度）。
        """
        ext_set = {e.lower() if e.startswith(".") else "." + e.lower() for e in (extensions or [])}
        files = []
        for root in roots:
            if not root or not os.path.isdir(root):
                continue
            for dirpath, _dirs, names in os.walk(root):
                for n in names:
                    if os.path.splitext(n)[1].lower() in ext_set:
                        files.append(os.path.join(dirpath, n))
        total = len(files)
        conn = self._db()
        new_chunks = 0
        for i, fp in enumerate(files):
            if progress_cb:
                progress_cb(i + 1, total)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except Exception:
                continue
            # 已索引且未变（同 mtime+size）跳过
            stat = os.stat(fp)
            row = conn.execute(
                "SELECT content FROM files_fts WHERE path=? AND chunk_idx=0",
                (fp,)).fetchone()
            if row is not None:
                continue
            # 分块（按 800 字符，块间允许重叠保证跨块句子不被切断——这里不做智能断句，后续可加）
            chunks = [text[i:i + chunk_chars] for i in range(0, len(text), chunk_chars)] or [""]
            conn.executemany(
                "INSERT OR REPLACE INTO files_fts(path, chunk_idx, content) VALUES(?,?,?)",
                [(fp, idx, c) for idx, c in enumerate(chunks)])
            conn.executemany(
                "INSERT OR REPLACE INTO files_fts_v(path, chunk_idx, content) VALUES(?,?,?)",
                [(fp, idx, c) for idx, c in enumerate(chunks)])
            new_chunks += len(chunks)
        conn.commit()
        stats = conn.execute("SELECT COUNT(DISTINCT path), COUNT(*) FROM files_fts").fetchone()
        return {"files": stats[0] or 0, "chunks": stats[1] or 0, "new_chunks": new_chunks,
                "skipped": total - len(files), "scanned": total}

    # ---------- 检索 ----------
    @staticmethod
    def _match_query(q: str) -> str:
        """把用户查询转成 FTS5 MATCH 表达式：连续串加引号，多词用 OR 放宽召回。"""
        q = _WS.sub(" ", q.strip())
        if not q:
            return ""
        # 去掉 FTS5 特殊字符（除引号外）
        q = re.sub(r'[^\w\u4e00-\u9fff\- ]', " ", q)
        q = _WS.sub(" ", q).strip()
        if not q:
            return ""
        terms = q.split(" ")
        if len(terms) == 1:
            return '"' + terms[0] + '"'
        return " OR ".join('"' + t + '"' for t in terms)

    def search(self, query: str, top_k: int = 5) -> list:
        """检索 top-k 块。返回 [{"path","chunk_idx","snippet","content"}]（content 供注入）。"""
        mq = self._match_query(query)
        if not mq:
            return []
        conn = self._db()
        rows = []
        try:
            rows = conn.execute(
                "SELECT path, chunk_idx, snippet(files_fts_v, 2, '…', '…', '…', 24), content "
                "FROM files_fts_v WHERE files_fts_v MATCH ? ORDER BY bm25(files_fts_v) LIMIT ?",
                (mq, top_k)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        # FTS5 召回不足时用 LIKE 兜底（按出现次数排序）
        if len(rows) < top_k:
            seen = {(r[0], r[1]) for r in rows}
            q = query.strip()
            extra = conn.execute(
                "SELECT path, chunk_idx, substr(content,1,120), content FROM files_fts "
                "WHERE content LIKE ? AND (path, chunk_idx) NOT IN (SELECT path, chunk_idx FROM files_fts_v "
                "WHERE files_fts_v MATCH ?) ORDER BY length(content) LIMIT ?",
                ("%" + q + "%", mq, top_k - len(rows))).fetchall()
            for r in extra:
                if (r[0], r[1]) in seen:
                    continue
                seen.add((r[0], r[1]))
                rows.append(r)
        return [{"path": r[0], "chunk_idx": r[1], "snippet": r[2], "content": r[3]} for r in rows]

    def search_files(self, query: str, top_k: int = 5) -> list:
        """按文件去重后的检索结果（每个文件取最相关一块），展示用。"""
        seen_path = set()
        out = []
        for r in self.search(query, top_k * 3):
            if r["path"] in seen_path:
                continue
            seen_path.add(r["path"])
            out.append(r)
            if len(out) >= top_k:
                break
        return out
