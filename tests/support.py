import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import config, db


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "test.db"
        self.patcher = patch.object(config, "DB_PATH", self.db_path)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        db.init_db()
