"""Every form in the catalogue must run its own example through the real operation (keeps the web forms and the backend in step)."""
import json
import unittest

from scical.domains import forms
from scical.services.tasks import run

KINDS = {"text", "textarea", "number", "quantity", "select", "bool", "list", "pairs", "table"}


class FormsTest(unittest.TestCase):
    def test_catalogue_shape(self):
        for dom, d in forms.catalogue().items():
            ids = [o["id"] for o in d["ops"]]
            self.assertEqual(len(ids), len(set(ids)), dom)
            for o in d["ops"]:
                keys = [f["key"] for f in o["fields"]]
                self.assertEqual(len(keys), len(set(keys)), f"{dom}.{o['id']} has duplicate keys")
                for f in o["fields"]:
                    self.assertIn(f["kind"], KINDS, f"{dom}.{o['id']}.{f['key']}")
                    if f["kind"] == "select":
                        self.assertTrue(f["options"])
                    if "when" in f:
                        self.assertIn("mode", keys, f"{dom}.{o['id']}: 'when' needs a mode field")
                    if f["kind"] == "table":
                        self.assertTrue(f["columns"])
                json.dumps(o)

    def test_examples_run(self):
        for dom, d in forms.catalogue().items():
            for o in d["ops"]:
                with self.subTest(op=f"{dom}.{o['id']}"):
                    domain = "formulas" if dom == "formulas" else dom
                    res = run({"kind": "domain", "domain": domain, "op": o["id"], "params": o["example"], "settings": {}})
                    self.assertTrue(res.get("ok"), res)
                    json.dumps(res, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
