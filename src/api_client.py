"""HTTP client for the agent API (CLI / smoke). Single runtime entry to the service."""

from __future__ import annotations

from urllib.parse import quote

import httpx2

from src.json_types import JsonObject, as_json_object


class AgentApiError(Exception):
    """HTTP or protocol failure talking to the agent API."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AgentApiClient:
    """Thin client: all LLM/RAG work happens inside the agent service."""

    def __init__(self, base_url: str, *, timeout: float = 120.0) -> None:
        self._base = base_url.rstrip("/")
        self._http = httpx2.Client(base_url=self._base, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> AgentApiClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def health(self) -> JsonObject:
        return self._get_json("/api/health")

    def list_programs(
        self,
        *,
        q: str = "",
        as_of: str | None = None,
        limit: int = 20,
    ) -> list[JsonObject]:
        params: list[str] = [f"limit={limit}"]
        if q:
            params.append(f"q={quote(q)}")
        if as_of:
            params.append(f"as_of={as_of}")
        path = "/api/programs?" + "&".join(params)
        try:
            resp = self._http.get(path)
        except httpx2.RequestError as exc:
            raise AgentApiError(
                "Cannot reach the API. Start the stack (make up-d / make dev) first."
            ) from exc
        if resp.status_code >= 400:
            self._parse(resp)  # raises
        try:
            data = resp.json()
        except Exception as exc:
            raise AgentApiError("Invalid response from the API.") from exc
        if not isinstance(data, list):
            raise AgentApiError("Invalid programs catalog from the API.")
        return [as_json_object(item) if isinstance(item, dict) else {} for item in data]

    def create_session(
        self,
        *,
        program_slug: str | None = None,
        as_of: str | None = None,
    ) -> tuple[str, str, JsonObject]:
        body: JsonObject = {}
        if program_slug:
            body["program_slug"] = program_slug
        if as_of:
            body["as_of"] = as_of
        data = self._post_json("/api/session", json_body=body or None)
        sid = str(data.get("session_id") or "")
        opening = str(data.get("opening_message") or "")
        if not sid:
            raise AgentApiError("API create session returned no session_id")
        return sid, opening, data

    def chat(
        self,
        message: str,
        *,
        session_id: str,
        debug: bool = False,
    ) -> JsonObject:
        path = "/api/chat"
        if debug:
            path += "?debug=true"
        return self._post_json(
            path,
            json_body={"message": message, "session_id": session_id},
        )

    def state(self, session_id: str) -> JsonObject:
        return self._get_json(f"/api/session/{session_id}/state")

    def reset(
        self,
        session_id: str,
        *,
        program_slug: str | None = None,
        as_of: str | None = None,
    ) -> tuple[str, str, JsonObject]:
        body: JsonObject = {}
        if program_slug:
            body["program_slug"] = program_slug
        if as_of:
            body["as_of"] = as_of
        data = self._post_json(
            f"/api/session/{session_id}/reset",
            json_body=body or None,
        )
        return (
            str(data.get("session_id") or session_id),
            str(data.get("opening_message") or ""),
            data,
        )

    def _get_json(self, path: str) -> JsonObject:
        try:
            resp = self._http.get(path)
        except httpx2.RequestError as exc:
            raise AgentApiError(
                "Cannot reach the API. Start the stack (make up-d / make dev) first."
            ) from exc
        return self._parse(resp)

    def _post_json(self, path: str, *, json_body: JsonObject | None) -> JsonObject:
        try:
            resp = self._http.post(path, json=json_body if json_body is not None else {})
        except httpx2.RequestError as exc:
            raise AgentApiError(
                "Cannot reach the API. Start the stack (make up-d / make dev) first."
            ) from exc
        return self._parse(resp)

    def _parse(self, resp: httpx2.Response) -> JsonObject:
        if resp.status_code >= 400:
            detail = None
            try:
                body = resp.json()
                if isinstance(body, dict):
                    detail = body.get("detail")
            except Exception:
                detail = None
            if isinstance(detail, str) and detail.strip():
                msg = detail.strip()
            else:
                msg = "The service is temporarily unavailable. Please try again later."
            raise AgentApiError(msg, status_code=resp.status_code)
        try:
            data = resp.json()
        except Exception as exc:
            raise AgentApiError("Invalid response from the API.") from exc
        return as_json_object(data)
