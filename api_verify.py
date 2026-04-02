#!/usr/bin/env python3
import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import dotenv_values

BASE_URL = "http://127.0.0.1:8000"
ENV_PATH = "/home/ahmad/Desktop/Dany/safAI/API Backend/.env"


@dataclass
class Result:
    method: str
    path: str
    result: str
    http_status: Optional[int]
    note: str


class Runner:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.env = dotenv_values(ENV_PATH)
        self.results: List[Result] = []
        self.token: Optional[str] = None
        self.email = f"api-check-{uuid.uuid4().hex[:10]}@example.com"
        self.password = "StrongPass123!"
        self.full_name = "API Check User"
        self.personality_id: Optional[str] = None
        self.workspace_id: Optional[str] = None
        self.project_id: Optional[str] = None
        self.file_id: Optional[str] = None
        self.conversation_id: Optional[str] = None
        self.message_id: Optional[str] = None
        self.response_id: Optional[str] = None
        self.comment_id: Optional[str] = None
        self.proxy_image_url: Optional[str] = None
        self.upload_path: Optional[str] = None

    def headers(self, auth: bool = False) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def add(self, method: str, path: str, result: str, status: Optional[int], note: str) -> None:
        self.results.append(Result(method, path, result, status, note))
        status_text = "-" if status is None else str(status)
        print(f"[{result.upper():>14}] {method:<6} {path:<50} {status_text:<4} {note}", flush=True)

    def request(self, method: str, path: str, *, auth: bool = False, timeout: int = 180, **kwargs: Any) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers.update(self.headers(auth=auth))
        return self.session.request(method, f"{BASE_URL}{path}", headers=headers, timeout=timeout, **kwargs)

    def compact(self, response: requests.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                if "detail" in payload:
                    return f"detail={payload['detail']}"
                keys = ", ".join(sorted(payload.keys())[:6])
                return f"json keys={keys}" if keys else "json object"
            if isinstance(payload, list):
                return f"list len={len(payload)}"
        except Exception:
            pass
        text = response.text.strip().replace("\n", " ")
        return text[:220] if text else "empty response"

    def basic(self, method: str, path: str, *, expected: Tuple[int, ...] = (200,), note: str = "", **kwargs: Any) -> Optional[requests.Response]:
        try:
            response = self.request(method, path, **kwargs)
        except Exception as exc:
            self.add(method, path, "fail", None, f"{type(exc).__name__}: {exc}")
            return None
        outcome = "pass" if response.status_code in expected else "fail"
        self.add(method, path, outcome, response.status_code, note or self.compact(response))
        return response

    def protected(self, method: str, path: str, *, expected: Tuple[int, ...] = (200,), note: str = "", allow_public: bool = False, **kwargs: Any) -> Optional[requests.Response]:
        try:
            no_auth = self.request(method, path, auth=False, **kwargs)
            unauth_note = f"unauth={no_auth.status_code}"
        except Exception as exc:
            unauth_note = f"unauth-error={type(exc).__name__}"
            no_auth = None

        try:
            response = self.request(method, path, auth=True, **kwargs)
        except Exception as exc:
            self.add(method, path, "fail", None, f"{unauth_note}; auth-error={type(exc).__name__}: {exc}")
            return None

        if response.status_code in expected and (allow_public or (no_auth is not None and no_auth.status_code == 401)):
            self.add(method, path, "pass", response.status_code, f"{unauth_note}; {note or self.compact(response)}")
        else:
            self.add(method, path, "fail", response.status_code, f"{unauth_note}; {note or self.compact(response)}")
        return response

    def parse_stream(self, response: requests.Response) -> Tuple[bool, str, Optional[str], Optional[str]]:
        text = response.text
        conv = None
        img = None
        match = re.search(r'"conversation_id"\s*:\s*"([^"]+)"', text)
        if match:
            conv = match.group(1)
        match = re.search(r"<!--CONVERSATION_ID:([^>]+)-->", text)
        if match and not conv:
            conv = match.group(1)
        match = re.search(r"!\[[^\]]*\]\(([^)]+)\)", text)
        if match:
            img = match.group(1)
        lower = text.lower()
        errors = [
            "api error",
            "unsupported parameter",
            "unsupported value",
            "invalid api key",
            "not configured",
            "not found",
            "currently unavailable",
            "failed to connect",
            "timed out",
            '"type":"error"',
            '"type": "error"',
        ]
        ok = response.status_code == 200 and not any(term in lower for term in errors)
        return ok, text.replace("\n", " ")[:300], conv, img

    def provider(self, path: str, *, body: Optional[Dict[str, Any]] = None, auth: bool = False, config_key: Optional[str] = None) -> Optional[requests.Response]:
        if config_key and not self.env.get(config_key):
            self.add("POST", path, "blocked-config", None, f"{config_key} missing in .env")
            return None
        try:
            response = self.request("POST", path, auth=auth, json=body or {"messages": [{"role": "user", "content": "ping"}]})
        except Exception as exc:
            self.add("POST", path, "fail", None, f"{type(exc).__name__}: {exc}")
            return None
        ok, preview, conv, img = self.parse_stream(response)
        if conv and conv != "new_conversation" and not self.conversation_id:
            self.conversation_id = conv
        if img and img.startswith(("http://", "https://")) and not self.proxy_image_url:
            self.proxy_image_url = img
        self.add("POST", path, "pass" if ok else "fail", response.status_code, preview)
        return response

    def run(self) -> None:
        self.basic("GET", "/openapi.json", note="schema")
        self.basic("GET", "/", note="root")
        self.basic("GET", "/health", note="health")
        self.basic("GET", "/cors-test", note="cors")

        self.auth_flow()
        self.auth_checks()
        self.personality_checks()
        self.workspace_checks()
        self.project_checks()
        self.seed_conversation()
        self.conversation_checks()
        self.response_comment_checks()
        self.provider_checks()
        self.image_library_checks()
        self.cleanup()
        self.write_report()

    def auth_flow(self) -> None:
        register = self.request("POST", "/auth/register", json={"email": self.email, "password": self.password, "full_name": self.full_name})
        self.add("POST", "/auth/register", "pass" if register.status_code == 200 else "fail", register.status_code, self.compact(register))
        login = self.request("POST", "/auth/login", json={"email": self.email, "password": self.password})
        if login.status_code == 200:
            self.token = login.json()["access_token"]
        self.add("POST", "/auth/login", "pass" if login.status_code == 200 else "fail", login.status_code, self.compact(login))

    def auth_checks(self) -> None:
        self.basic("GET", "/auth/health")
        self.basic("GET", "/auth/pool-status")
        self.basic("GET", "/auth/test-connection")
        self.basic("GET", "/auth/dns-test")
        self.basic("POST", "/auth/reset-pool")
        self.basic("POST", "/auth/forgot-password", json={"email": self.email})
        self.protected("GET", "/auth/me")
        self.basic("GET", "/auth/google/login", expected=(302, 307), allow_redirects=False, note="oauth redirect")
        self.add("GET", "/auth/google/callback", "manual-only", None, "interactive OAuth flow required")

    def personality_checks(self) -> None:
        self.basic("GET", "/api/personalities/")
        create = self.request(
            "POST",
            "/api/personalities/",
            json={
                "name": f"Temp Personality {uuid.uuid4().hex[:6]}",
                "highlight": "temp",
                "description": "verification personality",
                "avatar_emoji": "T",
                "system_prompt": "You are a temporary verification personality.",
                "rules": {"temperature": 0.2},
                "display_order": 999,
            },
        )
        if create.status_code == 201:
            self.personality_id = create.json()["id"]
        self.add("POST", "/api/personalities/", "pass" if create.status_code == 201 else "fail", create.status_code, self.compact(create))
        if self.personality_id:
            self.basic("GET", f"/api/personalities/{self.personality_id}")
            self.basic("GET", f"/api/personalities/{self.personality_id}/prompt")
            self.basic("PUT", f"/api/personalities/{self.personality_id}", json={"description": "updated verification personality"})

    def workspace_checks(self) -> None:
        self.protected("GET", "/api/workspaces")
        create = self.request("POST", "/api/workspaces", auth=True, json={"name": f"Temp Workspace {uuid.uuid4().hex[:6]}", "description": "temp", "ai_model": "gpt-4o"})
        if create.status_code == 200:
            self.workspace_id = create.json()["workspace_id"]
        self.add("POST", "/api/workspaces", "pass" if create.status_code == 200 else "fail", create.status_code, self.compact(create))
        if self.workspace_id:
            self.protected("PUT", f"/api/workspaces/{self.workspace_id}", json={"description": "updated workspace"})

    def project_checks(self) -> None:
        self.protected("GET", "/api/libraries/status", allow_public=True)
        self.protected("GET", "/api/projects")
        create = self.request("POST", "/api/projects", auth=True, json={"name": f"Temp Project {uuid.uuid4().hex[:6]}", "description": "temp project"})
        if create.status_code == 200:
            self.project_id = create.json()["project_id"]
        self.add("POST", "/api/projects", "pass" if create.status_code == 200 else "fail", create.status_code, self.compact(create))
        if self.project_id:
            self.protected("PUT", f"/api/projects/{self.project_id}", json={"description": "updated project"})
            self.protected("GET", f"/api/projects/{self.project_id}/conversations")
            self.protected("GET", f"/api/projects/{self.project_id}/files")

            fd, path = tempfile.mkstemp(prefix="api-verify-", suffix=".txt")
            os.close(fd)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("temporary file for backend verification\n")
            self.upload_path = path
            with open(path, "rb") as handle:
                upload = self.request("POST", f"/api/projects/{self.project_id}/files", auth=True, files={"file": ("verify.txt", handle, "text/plain")})
            if upload.status_code == 200:
                self.file_id = upload.json()["file_id"]
            self.add("POST", f"/api/projects/{self.project_id}/files", "pass" if upload.status_code == 200 else "fail", upload.status_code, self.compact(upload))
            if self.file_id:
                self.protected("GET", f"/api/projects/{self.project_id}/files")
                self.protected("GET", f"/api/projects/{self.project_id}/files/{self.file_id}/content")

    def seed_conversation(self) -> None:
        body: Dict[str, Any] = {"messages": [{"role": "user", "content": "ping"}]}
        if self.project_id:
            body["project_id"] = self.project_id
        if self.personality_id:
            body["personality_id"] = self.personality_id
        resp = self.provider("/openai/gpt-4o/chat", body=body, auth=True)
        if resp is None:
            return
        if not self.conversation_id:
            convs = self.request("GET", "/api/conversations", auth=True)
            if convs.status_code == 200 and convs.json():
                self.conversation_id = convs.json()[0]["conversation_id"]
        if self.conversation_id:
            detail = self.request("GET", f"/api/conversations/{self.conversation_id}", auth=True)
            if detail.status_code == 200:
                bubbles = detail.json().get("bubbles", [])
                if bubbles and bubbles[0].get("messages"):
                    self.message_id = bubbles[0]["messages"][0]["message_id"]
            self.add("GET", f"/api/conversations/{self.conversation_id}", "pass" if detail.status_code == 200 else "fail", detail.status_code, self.compact(detail))
        if self.message_id:
            model_resp = self.request("POST", "/api/model-responses", auth=True, json={"message_id": self.message_id, "model_name": "verification-model", "content": "temporary model response", "response_order": 0})
            if model_resp.status_code == 200:
                self.response_id = model_resp.json()["response_id"]
            self.add("POST", "/api/model-responses", "pass" if model_resp.status_code == 200 else "fail", model_resp.status_code, self.compact(model_resp))
            if self.response_id:
                comment = self.request("POST", "/api/comments", auth=True, json={"response_id": self.response_id, "comment_text": "temporary verification comment"})
                if comment.status_code == 200:
                    self.comment_id = comment.json()["comment_id"]
                self.add("POST", "/api/comments", "pass" if comment.status_code == 200 else "fail", comment.status_code, self.compact(comment))

    def conversation_checks(self) -> None:
        self.protected("GET", "/api/conversations")
        self.protected("GET", "/api/conversations/search?q=ping")
        if self.conversation_id:
            self.protected("GET", f"/api/conversations/{self.conversation_id}")
        self.basic("GET", "/api/library/images/test")

    def response_comment_checks(self) -> None:
        if self.message_id:
            self.protected("GET", f"/api/model-responses/message/{self.message_id}")
        if self.response_id:
            self.protected("GET", f"/api/comments/response/{self.response_id}")
        if self.comment_id:
            self.protected("PUT", f"/api/comments/{self.comment_id}", json={"comment_text": "updated verification comment"})

    def provider_checks(self) -> None:
        self.basic("GET", "/openai/health")
        for path in [
            "/openai/gpt4-1/chat",
            "/openai/gpt-4/chat",
            "/openai/gpt-4o/chat",
            "/openai/gpt-4-1-mini/chat",
            "/openai/gpt-4-1-nano/chat",
            "/openai/o4-mini/chat",
            "/openai/o3-mini/chat",
            "/openai/deepseek-v3/chat",
            "/openai/deepseek-r1/chat",
            "/openai/grok-3/chat",
            "/openai/grok-4/chat",
            "/openai/qwen1/chat",
            "/openai/qwen2/chat",
        ]:
            body: Dict[str, Any] = {"messages": [{"role": "user", "content": "ping"}]}
            if self.conversation_id:
                body["conversation_id"] = self.conversation_id
            self.provider(path, body=body)

        image_body: Dict[str, Any] = {"messages": [{"role": "user", "content": "draw a small red square icon"}]}
        if self.conversation_id:
            image_body["conversation_id"] = self.conversation_id
        self.provider("/openai/gpt-image-1/chat", body=image_body, auth=True)

        self.provider("/xai/grok-4/chat", body={"messages": [{"role": "user", "content": "ping"}], **({"conversation_id": self.conversation_id} if self.conversation_id else {})}, config_key="XAI_API_KEY")
        self.provider("/xai/grok-3/chat", body={"messages": [{"role": "user", "content": "ping"}], **({"conversation_id": self.conversation_id} if self.conversation_id else {})}, config_key="XAI_API_KEY")
        self.provider("/xai/grok-2-image/chat", body=image_body, auth=True, config_key="XAI_API_KEY")

        self.provider("/qwen/qwen1/chat", body={"messages": [{"role": "user", "content": "ping"}]}, auth=True, config_key="QWEN_1_X_API_KEY")
        self.provider("/qwen/qwen2/chat", body={"messages": [{"role": "user", "content": "ping"}]}, auth=True, config_key="QWEN_2_API_KEY")
        self.provider("/qwen/qwen3/chat", body={"messages": [{"role": "user", "content": "ping"}]}, auth=True, config_key="QWEN_3_API_KEY")

        self.provider("/moonshot/k1/chat", body={"messages": [{"role": "user", "content": "ping"}], **({"conversation_id": self.conversation_id} if self.conversation_id else {})}, config_key="MOONSHOT_API_KEY")
        self.provider("/moonshot/k2/chat", body={"messages": [{"role": "user", "content": "ping"}], **({"conversation_id": self.conversation_id} if self.conversation_id else {})}, config_key="MOONSHOT_API_KEY")

        self.provider("/gemini/gemini-3-pro/chat", body={"messages": [{"role": "user", "content": "ping"}], **({"conversation_id": self.conversation_id} if self.conversation_id else {}), **({"project_id": self.project_id} if self.project_id else {})}, config_key="GEMINI_API_KEY")
        self.provider("/gemini/gemini-3-pro-image/chat", body=image_body, auth=True, config_key="GEMINI_API_KEY")

        self.provider("/perplexity/perplexity/chat", body={"messages": [{"role": "user", "content": "ping"}], **({"conversation_id": self.conversation_id} if self.conversation_id else {}), **({"project_id": self.project_id} if self.project_id else {})}, config_key="PPLX_API_KEY")
        self.provider("/anthropic/claude-sonnet-4-5/chat", body={"messages": [{"role": "user", "content": "ping"}], **({"conversation_id": self.conversation_id} if self.conversation_id else {}), **({"project_id": self.project_id} if self.project_id else {})}, config_key="ANTHROPIC_API_KEY")

        multi = {"messages": [{"role": "user", "content": "ping"}], "models": ["GPT-4o", "Perplexity"]}
        if self.conversation_id:
            multi["conversation_id"] = self.conversation_id
        self.provider("/api/multi-model/chat", body=multi, auth=True)

    def image_library_checks(self) -> None:
        images = self.protected("GET", "/api/library/images")
        if images is not None and images.status_code == 200 and not self.proxy_image_url:
            try:
                for item in images.json():
                    if item.get("image_url", "").startswith(("http://", "https://")):
                        self.proxy_image_url = item["image_url"]
                        break
            except Exception:
                pass
        if self.proxy_image_url:
            path = f"/api/library/images/proxy?url={requests.utils.quote(self.proxy_image_url, safe='')}"
            response = self.request("GET", path, auth=True)
            self.add("GET", "/api/library/images/proxy", "pass" if response.status_code == 200 else "fail", response.status_code, self.compact(response))
        else:
            self.add("GET", "/api/library/images/proxy", "fail", None, "no proxyable image URL produced by image endpoints")

    def cleanup(self) -> None:
        if self.comment_id:
            self.protected("DELETE", f"/api/comments/{self.comment_id}")
        if self.file_id and self.project_id:
            self.protected("DELETE", f"/api/projects/{self.project_id}/files/{self.file_id}")
        if self.workspace_id:
            self.protected("DELETE", f"/api/workspaces/{self.workspace_id}")
        if self.personality_id:
            self.basic("DELETE", f"/api/personalities/{self.personality_id}", expected=(204,))
        if self.conversation_id:
            self.protected("DELETE", f"/api/conversations/{self.conversation_id}")
        if self.project_id:
            self.protected("DELETE", f"/api/projects/{self.project_id}")
        if self.token:
            logout = self.request("POST", "/auth/logout", auth=True)
            self.add("POST", "/auth/logout", "pass" if logout.status_code == 200 else "fail", logout.status_code, self.compact(logout))
        if self.upload_path and os.path.exists(self.upload_path):
            os.remove(self.upload_path)

    def write_report(self) -> None:
        json_path = "/home/ahmad/Desktop/Dany/safAI/api_report.json"
        md_path = "/home/ahmad/Desktop/Dany/safAI/api_report.md"
        counts: Dict[str, int] = {}
        for item in self.results:
            counts[item.result] = counts.get(item.result, 0) + 1
        payload = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "base_url": BASE_URL,
            "summary": counts,
            "results": [asdict(item) for item in self.results],
            "excluded_mounted_routes": ["GET /openapi.json", "GET /docs", "GET /docs/oauth2-redirect", "GET /redoc", "STATIC /uploads"],
            "not_mounted_but_defined": ["enhanced_projects routes are defined in source but not mounted in main.py"],
        }
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

        lines = [
            "# API Verification Report",
            "",
            f"Base URL: `{BASE_URL}`",
            "",
            "## Summary",
            "",
        ]
        for key in sorted(counts):
            lines.append(f"- `{key}`: {counts[key]}")
        lines.extend(
            [
                "",
                "## Endpoint Matrix",
                "",
                "| Method | Path | Result | HTTP | Note |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in self.results:
            status = "" if item.http_status is None else str(item.http_status)
            note = item.note.replace("|", "\\|")
            lines.append(f"| {item.method} | {item.path} | {item.result} | {status} | {note} |")
        with open(md_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        print(f"REPORT_JSON={json_path}")
        print(f"REPORT_MD={md_path}")


if __name__ == "__main__":
    Runner().run()
