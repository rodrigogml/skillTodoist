import configparser
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from todoist import Client, TodoistError, load_settings, read_token


class TodoistTests(unittest.TestCase):
    def profile(self, text=None):
        content = text or """[todoist]
api_base = https://api.todoist.com/api/v1
[vault]
command = python
script = vault.py
config = keepass.ini
entry_path = APIs/Todoist
field = password
auth_json = {\"mode\":\"windows_credential_manager\",\"target\":\"test\"}
"""
        handle, filename = tempfile.mkstemp(suffix=".ini")
        import os
        os.close(handle)
        path = Path(filename)
        path.write_text(content, encoding="utf-8")
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def test_rejects_non_https_or_wrong_host(self):
        with self.assertRaises(TodoistError):
            load_settings(str(self.profile("""[todoist]\napi_base = http://example.test\n[vault]\n""")))

    def test_reads_secret_without_exposing_provider_errors(self):
        settings = load_settings(str(self.profile()))
        payload = {"ok": True, "data": {"value": "secret-token"}}
        with patch("todoist.subprocess.run", return_value=type("R", (), {"stdout": json.dumps(payload), "returncode": 0})()) as run:
            self.assertEqual(read_token(settings), "secret-token")
            self.assertNotIn("secret-token", json.dumps(run.call_args.args))

    def test_rejects_bad_vault_response(self):
        settings = load_settings(str(self.profile()))
        with patch("todoist.subprocess.run", return_value=type("R", (), {"stdout": "{}", "returncode": 1})()):
            with self.assertRaisesRegex(TodoistError, "token"):
                read_token(settings)

    def test_operation_allowlist(self):
        client = Client(load_settings(str(self.profile())), "x")
        with self.assertRaises(TodoistError):
            client.request("arbitrary.delete", {}, {})

    def test_missing_path_parameter(self):
        client = Client(load_settings(str(self.profile())), "x")
        with self.assertRaises(TodoistError):
            client.request("tasks.get", {}, {})

    def test_upload_requires_a_file_path(self):
        client = Client(load_settings(str(self.profile())), "x")
        with self.assertRaises(TodoistError):
            client.request("uploads.create", {}, {}, {})


if __name__ == "__main__":
    unittest.main()
