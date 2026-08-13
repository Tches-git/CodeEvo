import os
import tempfile
import unittest

from codeevo.annotation import AnnotationService
from codeevo.auth import Principal
from codeevo.store import TaskStore
from codeevo.annotation_demo import seed


class AnnotationDemoTests(unittest.TestCase):
    def test_demo_seed_is_idempotent_and_cannot_pass_public_export_gate(self):
        handle, path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        try:
            self.assertEqual(4, seed(path))
            self.assertEqual(0, seed(path))
            store = TaskStore(path)
            cases = store.list_annotation_cases("default", None, None, 100)
            self.assertEqual(4, len(cases))
            approved = next(item for item in cases if item["status"] == "approved")
            self.assertEqual("demo-fixture", approved["source"]["kind"])
            service = AnnotationService(store, github=None)
            with self.assertRaisesRegex(ValueError, "public GitHub PR"):
                service.export(
                    "default", "demo-admin", "demo-data", "1.0.0",
                    [approved["split"]], [approved["id"]],
                )
            detail = service.get_case(
                "default", approved["id"],
                Principal("local", "local", "default", "admin"),
            )
            self.assertEqual(2, len(detail["submissions"]))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
