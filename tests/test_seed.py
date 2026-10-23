import unittest

from server import db, seed
from tests.support import DatabaseTestCase


class SeedTest(DatabaseTestCase):
    def test_seed_is_repeatable_and_creates_demo_patients(self):
        first = seed.seed()
        second = seed.seed()
        self.assertEqual(len(first), 3)
        self.assertEqual([row["id"] for row in second], ["PT-0001", "PT-0002", "PT-0003"])
        self.assertIsNotNone(db.get_patient_binding("PT-0001"))

    def test_seed_binds_real_board_device(self):
        seed.seed()
        binding = db.get_active_binding("esp32")
        self.assertEqual(binding["patient_id"], "PT-0003")
