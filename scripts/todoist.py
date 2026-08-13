#!/usr/bin/env python3
"""Secure JSON CLI for the Todoist API v1 and Sync API."""

from __future__ import annotations

import argparse
import base64
import configparser
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class TodoistError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Settings:
    api_base: str
    timeout: float
    retries: int
    page_size: int
    vault_command: tuple[str, ...]
    vault_config: str
    vault_entry: str
    vault_field: str
    vault_auth: Mapping[str, Any]


def fail(code: str, message: str, status: int | None = None) -> None:
    raise TodoistError(code, message, status)


def load_settings(path: str) -> Settings:
    parser = configparser.ConfigParser(interpolation=None)
    config_path = Path(path)
    if not config_path.is_file():
        fail("config_not_found", "Arquivo de configuração não encontrado.")
    try:
        with config_path.open(encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, UnicodeError):
        fail("invalid_config", "Não foi possível ler o arquivo de configuração.")
    if not parser.has_section("todoist") or not parser.has_section("vault"):
        fail("missing_config", "O perfil deve conter [todoist] e [vault].")
    todo = parser["todoist"]
    vault = parser["vault"]
    try:
        timeout = float(todo.get("timeout_seconds", "30"))
        retries = int(todo.get("max_retries", "2"))
        page_size = int(todo.get("page_size", "100"))
    except ValueError:
        fail("invalid_config", "timeout_seconds, max_retries e page_size devem ser numéricos.")
    if timeout <= 0 or retries < 0 or not 1 <= page_size <= 200:
        fail("invalid_config", "Valores de timeout, retries ou page_size inválidos.")
    api_base = todo.get("api_base", "https://api.todoist.com/api/v1").rstrip("/")
    if not api_base.startswith("https://api.todoist.com/"):
        fail("invalid_config", "api_base deve usar https://api.todoist.com/.")
    command = tuple(vault.get("command", "python").split())
    script = vault.get("script", "").strip()
    config = vault.get("config", "").strip()
    entry = vault.get("entry_path", "").strip()
    field = vault.get("field", "password").strip()
    try:
        auth = json.loads(vault.get("auth_json", "{}"))
    except json.JSONDecodeError:
        fail("invalid_config", "vault.auth_json deve conter JSON válido.")
    if not command or not script or not config or not entry or field not in {"password", "notes"}:
        fail("invalid_config", "Configuração do Vault incompleta ou campo inválido.")
    return Settings(api_base, timeout, retries, page_size, command + (script,), config, entry, field, auth)


def read_token(settings: Settings) -> str:
    request = {
        "version": 1,
        "operation": "read",
        "entry": {"path": settings.vault_entry},
        "field": settings.vault_field,
        "auth": dict(settings.vault_auth),
    }
    try:
        result = subprocess.run(
            [*settings.vault_command, "--config", settings.vault_config],
            input=json.dumps(request), text=True, capture_output=True,
            timeout=settings.timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        fail("vault_unavailable", "Não foi possível consultar o provedor KeePassVault.")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        fail("vault_protocol_error", "O provedor KeePassVault não retornou JSON válido.")
    if result.returncode != 0 or payload.get("ok") is not True:
        fail("vault_read_failed", "Não foi possível ler o token do Vault.")
    value = payload.get("data", {}).get("value")
    if not isinstance(value, str) or not value:
        fail("vault_secret_missing", "O campo configurado no Vault está vazio.")
    return value


# Explicitly supported operations. Values are (HTTP method, relative path).
OPERATIONS: dict[str, tuple[str, str]] = {
    "user.get": ("GET", "/user"),
    "tasks.list": ("GET", "/tasks"), "tasks.get": ("GET", "/tasks/{task_id}"),
    "tasks.create": ("POST", "/tasks"), "tasks.update": ("POST", "/tasks/{task_id}"),
    "tasks.close": ("POST", "/tasks/{task_id}/close"), "tasks.reopen": ("POST", "/tasks/{task_id}/reopen"),
    "tasks.delete": ("DELETE", "/tasks/{task_id}"), "tasks.filter": ("GET", "/tasks/filter"),
    "projects.list": ("GET", "/projects"), "projects.get": ("GET", "/projects/{project_id}"),
    "projects.create": ("POST", "/projects"), "projects.update": ("POST", "/projects/{project_id}"),
    "projects.delete": ("DELETE", "/projects/{project_id}"), "projects.archive": ("POST", "/projects/{project_id}/archive"),
    "projects.unarchive": ("POST", "/projects/{project_id}/unarchive"), "projects.archived": ("GET", "/projects/archived"),
    "sections.list": ("GET", "/sections"), "sections.get": ("GET", "/sections/{section_id}"),
    "sections.create": ("POST", "/sections"), "sections.update": ("POST", "/sections/{section_id}"),
    "sections.delete": ("DELETE", "/sections/{section_id}"), "sections.archive": ("POST", "/sections/{section_id}/archive"),
    "sections.unarchive": ("POST", "/sections/{section_id}/unarchive"),
    "labels.list": ("GET", "/labels"), "labels.get": ("GET", "/labels/{label_id}"),
    "labels.create": ("POST", "/labels"), "labels.update": ("POST", "/labels/{label_id}"), "labels.delete": ("DELETE", "/labels/{label_id}"),
    "labels.shared.list": ("GET", "/labels/shared"), "labels.shared.rename": ("POST", "/labels/shared/rename"),
    "labels.shared.remove": ("POST", "/labels/shared/remove"),
    "comments.list": ("GET", "/comments"), "comments.get": ("GET", "/comments/{comment_id}"),
    "comments.create": ("POST", "/comments"), "comments.update": ("POST", "/comments/{comment_id}"), "comments.delete": ("DELETE", "/comments/{comment_id}"),
    "collaborators.list": ("GET", "/projects/{project_id}/collaborators"),
    "activity.list": ("GET", "/activity"), "reminders.list": ("GET", "/reminders"),
    "reminders.get": ("GET", "/reminders/{reminder_id}"), "reminders.create": ("POST", "/reminders"),
    "reminders.update": ("POST", "/reminders/{reminder_id}"), "reminders.delete": ("DELETE", "/reminders/{reminder_id}"),
    "uploads.create": ("POST", "/uploads"), "uploads.delete": ("DELETE", "/uploads/{upload_id}"),
    "backups.list": ("GET", "/backups"), "backups.download": ("GET", "/backups/{backup_id}"),
    "emails.get": ("GET", "/emails"), "notifications.get": ("GET", "/notifications"),
    "tokens.revoke": ("POST", "/revoke"),
}


def substitute(path: str, params: Mapping[str, Any]) -> str:
    for key in [part[1:-1] for part in path.split("/") if part.startswith("{") and part.endswith("}")]:
        value = params.get(key)
        if value is None or isinstance(value, (dict, list)):
            fail("missing_parameter", f"Parâmetro obrigatório ausente: {key}.")
        path = path.replace("{" + key + "}", str(value))
    return path


class Client:
    def __init__(self, settings: Settings, token: str):
        self.settings, self.token = settings, token

    def request(self, operation: str, params: Mapping[str, Any], query: Mapping[str, Any], body: Any = None) -> Any:
        if operation not in OPERATIONS:
            fail("unsupported_operation", "Operação Todoist não permitida.")
        method, template = OPERATIONS[operation]
        path = substitute(template, params)
        if operation == "uploads.create":
            return self.upload(body)
        if query:
            path += "?" + urlencode({k: v for k, v in query.items() if v is not None}, doseq=True)
        data = None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.settings.api_base + path, data=data, headers=headers, method=method)
        for attempt in range(self.settings.retries + 1):
            try:
                with urlopen(request, timeout=self.settings.timeout) as response:
                    raw = response.read()
                    if not raw:
                        return None
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        return {"raw_base64": base64.b64encode(raw).decode("ascii")}
            except HTTPError as exc:
                if exc.code in {429, 500, 502, 503, 504} and attempt < self.settings.retries:
                    delay = float(exc.headers.get("Retry-After", "1"))
                    time.sleep(min(delay, 10))
                    continue
                fail("todoist_http_error", f"Todoist retornou HTTP {exc.code}.", exc.code)
            except URLError:
                if attempt < self.settings.retries:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                fail("network_error", "Não foi possível conectar à API Todoist.")
        fail("request_failed", "A requisição não foi concluída.")

    def upload(self, body: Any) -> Any:
        if not isinstance(body, Mapping) or not isinstance(body.get("file_path"), str):
            fail("invalid_upload", "uploads.create exige body.file_path.")
        file_path = Path(body["file_path"])
        if not file_path.is_file():
            fail("file_not_found", "Arquivo para upload não encontrado.")
        content = file_path.read_bytes()
        boundary = "----TodoistSkillBoundary7d6a"
        filename = str(body.get("filename") or file_path.name).replace('"', "")
        field = str(body.get("file_field", "file"))
        multipart = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
            f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        request = Request(
            self.settings.api_base + "/uploads", data=multipart,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"}, method="POST",
        )
        try:
            with urlopen(request, timeout=self.settings.timeout) as response:
                return json.loads(response.read())
        except (HTTPError, URLError, json.JSONDecodeError):
            fail("upload_failed", "O upload para a API Todoist falhou.")

    def sync(self, commands: list[Mapping[str, Any]], sync_token: str = "*") -> Any:
        if not isinstance(commands, list) or any(not isinstance(c, Mapping) for c in commands):
            fail("invalid_commands", "commands deve ser uma lista de objetos.")
        body = json.dumps({"sync_token": sync_token, "resource_types": ["all"], "commands": commands}).encode()
        request = Request(self.settings.api_base + "/sync", data=body, headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.settings.timeout) as response:
                return json.loads(response.read())
        except (HTTPError, URLError, json.JSONDecodeError):
            fail("sync_failed", "A sincronização Todoist falhou.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, Mapping) or request.get("version") != 1:
            fail("unsupported_version", "Somente requisições com version=1 são aceitas.")
        settings = load_settings(args.config)
        token = read_token(settings)
        client = Client(settings, token)
        operation = request.get("operation")
        if operation == "sync":
            data = client.sync(request.get("commands", []), request.get("sync_token", "*"))
        else:
            data = client.request(operation, request.get("params", {}), request.get("query", {}), request.get("body"))
        print(json.dumps({"version": 1, "ok": True, "operation": operation, "data": data}, ensure_ascii=False))
        return 0
    except json.JSONDecodeError:
        error = {"code": "invalid_json", "message": "A entrada não contém JSON válido."}
    except TodoistError as exc:
        error = {"code": exc.code, "message": exc.message}
    except Exception:
        error = {"code": "internal_error", "message": "Falha interna ao processar a solicitação."}
    print(json.dumps({"version": 1, "ok": False, "error": error}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
