import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from server import main
from tests.support import DatabaseTestCase


class ApiTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.patches = [
            patch.object(main.ingestor, "start", lambda: None),
            patch.object(main.ingestor, "stop", lambda: None),
            patch.object(main.monitor, "start", lambda: None),
            patch.object(main.monitor, "stop", lambda: None),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_pages_and_patient_workflow(self):
        with TestClient(main.app) as client:
            self.assertEqual(
                client.get("/", follow_redirects=False).headers["location"], "/clinic"
            )
            self.assertEqual(client.get("/clinic").status_code, 200)
            payload = {
                "display_name": "API Demo",
                "dob": "1940-01-01",
                "program": "hospice",
                "device_id": "sim01",
            }
            self.assertEqual(client.post("/api/patients", json=payload).status_code, 200)
            self.assertEqual(
                client.post(
                    "/api/patients", json={**payload, "display_name": "Duplicate"}
                ).status_code,
                409,
            )
            self.assertIn("patients", client.get("/api/clinic/worklist").json())

    def test_spa_routes_and_api_isolation(self):
        with TestClient(main.app) as client:
            for path in [
                "/clinic",
                "/clinic/patient/PT-0001",
                "/care",
                "/history",
                "/live",
            ]:
                response = client.get(path)
                self.assertEqual(response.status_code, 200, path)
                self.assertIn('id="app"', response.text, path)
            self.assertEqual(client.get("/api/does-not-exist").status_code, 404)
            self.assertEqual(client.get("/does-not-exist").status_code, 404)
            self.assertNotIn("<html", client.get("/api/health").text.lower())

