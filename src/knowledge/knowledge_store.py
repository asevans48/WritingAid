"""Local knowledge store backed by SQLite FTS5 for fast full-text search.

Stores articles from Wikipedia, Britannica, and custom sources.
Provides a unified search interface used by the RAG system.
"""

import sqlite3
import threading
from pathlib import Path
from typing import List, Optional, Dict
from dataclasses import dataclass
from datetime import datetime


@dataclass
class KnowledgeArticle:
    """A single knowledge base article."""
    title: str
    content: str
    source: str  # "wikipedia", "britannica", "custom", "encyclopedia"
    category: str = ""
    url: str = ""


_DEFAULT_DB_PATH = Path.home() / ".writer_platform" / "knowledge.db"


class KnowledgeStore:
    """SQLite FTS5-backed knowledge store for external reference material.

    Uses per-thread connections to avoid SQLite's threading restrictions.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    def _ensure_schema(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'custom',
                category TEXT DEFAULT '',
                url TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
                title, content, category,
                content='articles',
                content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
                INSERT INTO articles_fts(rowid, title, content, category)
                VALUES (new.id, new.title, new.content, new.category);
            END;

            CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
                INSERT INTO articles_fts(articles_fts, rowid, title, content, category)
                VALUES ('delete', old.id, old.title, old.content, old.category);
            END;

            CREATE TABLE IF NOT EXISTS sources (
                name TEXT PRIMARY KEY,
                status TEXT DEFAULT 'not_installed',
                article_count INTEGER DEFAULT 0,
                installed_at TEXT,
                size_mb REAL DEFAULT 0
            );
        """)
        conn.commit()

    def add_article(self, article: KnowledgeArticle):
        """Add a single article to the store."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO articles (title, content, source, category, url) VALUES (?, ?, ?, ?, ?)",
            (article.title, article.content, article.source, article.category, article.url)
        )
        conn.commit()

    def add_articles_batch(self, articles: List[KnowledgeArticle], batch_size: int = 500):
        """Add articles in batches for performance."""
        conn = self._get_conn()
        rows = [
            (a.title, a.content, a.source, a.category, a.url)
            for a in articles
        ]
        for i in range(0, len(rows), batch_size):
            conn.executemany(
                "INSERT INTO articles (title, content, source, category, url) VALUES (?, ?, ?, ?, ?)",
                rows[i:i + batch_size]
            )
            conn.commit()

    def search(self, query: str, source: Optional[str] = None,
               max_results: int = 10) -> List[KnowledgeArticle]:
        """Search articles using FTS5 full-text search."""
        conn = self._get_conn()

        # Sanitize query for FTS5
        safe_query = " ".join(
            word for word in query.split() if word.strip()
        )
        if not safe_query:
            return []

        try:
            if source:
                rows = conn.execute("""
                    SELECT a.title, a.content, a.source, a.category, a.url
                    FROM articles_fts f
                    JOIN articles a ON a.id = f.rowid
                    WHERE articles_fts MATCH ? AND a.source = ?
                    ORDER BY rank
                    LIMIT ?
                """, (safe_query, source, max_results)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT a.title, a.content, a.source, a.category, a.url
                    FROM articles_fts f
                    JOIN articles a ON a.id = f.rowid
                    WHERE articles_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (safe_query, max_results)).fetchall()
        except sqlite3.OperationalError:
            # FTS query syntax error — fall back to LIKE
            rows = conn.execute("""
                SELECT title, content, source, category, url
                FROM articles
                WHERE title LIKE ? OR content LIKE ?
                ORDER BY title
                LIMIT ?
            """, (f"%{safe_query}%", f"%{safe_query}%", max_results)).fetchall()

        return [
            KnowledgeArticle(
                title=r[0], content=r[1], source=r[2],
                category=r[3], url=r[4]
            )
            for r in rows
        ]

    def get_source_status(self) -> Dict[str, dict]:
        """Get status of all knowledge sources."""
        conn = self._get_conn()
        rows = conn.execute("SELECT name, status, article_count, installed_at, size_mb FROM sources").fetchall()
        result = {}
        for r in rows:
            result[r[0]] = {
                "status": r[1], "article_count": r[2],
                "installed_at": r[3], "size_mb": r[4]
            }
        return result

    def set_source_status(self, name: str, status: str,
                          article_count: int = 0, size_mb: float = 0):
        """Update source status."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO sources (name, status, article_count, installed_at, size_mb)
            VALUES (?, ?, ?, ?, ?)
        """, (name, status, article_count,
              datetime.now().isoformat() if status == "installed" else None, size_mb))
        conn.commit()

    def remove_source(self, source_name: str):
        """Remove all articles from a source."""
        conn = self._get_conn()
        conn.execute("DELETE FROM articles WHERE source = ?", (source_name,))
        conn.execute("DELETE FROM sources WHERE name = ?", (source_name,))
        conn.commit()
        # Rebuild FTS index
        conn.execute("INSERT INTO articles_fts(articles_fts) VALUES('rebuild')")
        conn.commit()

    def get_article_count(self, source: Optional[str] = None) -> int:
        """Get total article count, optionally filtered by source."""
        conn = self._get_conn()
        if source:
            return conn.execute(
                "SELECT COUNT(*) FROM articles WHERE source = ?", (source,)
            ).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

    def close(self):
        conn = getattr(self._local, 'conn', None)
        if conn:
            conn.close()
            self._local.conn = None


# Global instance
_store: Optional[KnowledgeStore] = None


def get_knowledge_store() -> KnowledgeStore:
    """Get the global knowledge store instance."""
    global _store
    if _store is None:
        _store = KnowledgeStore()
    return _store
