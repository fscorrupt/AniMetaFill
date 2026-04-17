import sqlite3
import json
import time
import os
import sys
import re
from typing import List, Dict, Any, Optional
from app.providers import EpisodeData, EpisodeCategory

from app.logger import logger

class AnimeDatabase:
    """
    Manages local storage of anime episode classifications using SQLite.
    Stores and retrieves mapping data for Canon, Filler, and Mixed episodes.
    """
    def __init__(self, db_path: str):
        self.db_path = db_path
        # Ensure directory exists and check permissions
        db_dir = os.path.dirname(self.db_path)
        try:
            os.makedirs(db_dir, exist_ok=True)
        except PermissionError:
            logger.error(f"FATAL: No permission to create or write to the database directory: '{db_dir}'")
            if os.name != 'nt':
                logger.error("FIX: Run 'chown -R 1000:1000 /data' on your host system to fix permissions.")
            sys.exit(1)

        if not os.access(db_dir, os.W_OK):
            logger.error(f"FATAL: Database directory '{db_dir}' is NOT writable.")
            if os.name != 'nt': # Linux/Docker specific advice
                logger.error("FIX: Run 'chown -R 1000:1000 /data' on your host system.")
            raise PermissionError(f"No write access to {db_dir}")

        self.init_db()

    def _get_connection(self):
        """Standard SQLite connection wrapper."""
        return sqlite3.connect(self.db_path)

    def init_db(self):
        """Initializes the database schema (tables for episode data and update timestamps)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS episodes (
                    anime_title TEXT,
                    absolute_number INTEGER,
                    category TEXT,
                    PRIMARY KEY (anime_title, absolute_number)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS updates (
                    anime_title TEXT PRIMARY KEY,
                    last_checked REAL
                )
            ''')
            conn.commit()

    def upsert_episodes(self, anime_title: str, episodes_list: List[EpisodeData]):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Delete old records for this title to ensure we have fresh data
            cursor.execute("DELETE FROM episodes WHERE anime_title = ?", (anime_title,))

            for ep in episodes_list:
                cursor.execute(
                    "INSERT OR REPLACE INTO episodes (anime_title, absolute_number, category) VALUES (?, ?, ?)",
                    (anime_title, ep.number, ep.category.value)
                )

            cursor.execute(
                "INSERT OR REPLACE INTO updates (anime_title, last_checked) VALUES (?, ?)",
                (anime_title, time.time())
            )
            conn.commit()

    def get_episodes(self, anime_title: str) -> Dict[str, List[int]]:
        result = {"canon": [], "filler": [], "mixed": []}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT absolute_number, category FROM episodes WHERE anime_title = ?",
                (anime_title,)
            )
            rows = cursor.fetchall()
            for row in rows:
                abs_num, category = row
                if category in result:
                    result[category].append(abs_num)

        # Sort for consistency
        for cat in result:
            result[cat].sort()

        return result

    def has_ever_synced(self, anime_title: str) -> bool:
        """Returns True if this show has ever been searched via a provider."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT last_checked FROM updates WHERE anime_title = ?", (anime_title,))
            return cursor.fetchone() is not None

    def _slugify(self, title: str) -> str:
        """Internal title to slug generator for file-naming consistency."""
        slug = title.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'[\s]+', '-', slug)
        return slug.strip('-')

    def export_to_json(self, filepath: str):
        master_dict = {}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT anime_title FROM episodes")
            titles = [row[0] for row in cursor.fetchall()]

            for title in titles:
                slug = self._slugify(title)
                mapping = self.get_episodes(title)
                # Only include if we have data
                if any(mapping.values()):
                    master_dict[slug] = mapping

        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        tmp_filepath = f"{filepath}.tmp"
        try:
            with open(tmp_filepath, 'w') as f:
                json.dump(master_dict, f, indent=2)
            os.replace(tmp_filepath, filepath)
            logger.db(f"Exported database to {filepath}")
        except Exception as e:
            if os.path.exists(tmp_filepath): os.remove(tmp_filepath)
            logger.error(f"Failed to export DB JSON: {e}")
