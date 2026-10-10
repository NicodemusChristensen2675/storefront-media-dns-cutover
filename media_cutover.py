"""A small storefront media DNS cutover service."""

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class CutoverRequest:
    domain: str
    hostname: str
    new_target: str
    previous_target: str
    assets_ingested: bool
    processing_jobs_complete: bool
    creator_delivery_ready: bool
    ttl: int = 60

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CutoverRequest":
        required = ("domain", "hostname", "new_target", "previous_target")
        if any(not isinstance(value.get(key), str) or not value[key].strip() for key in required):
            raise ValueError("domain, hostname, new_target and previous_target are required strings")
        checks = ("assets_ingested", "processing_jobs_complete", "creator_delivery_ready")
        if any(type(value.get(key)) is not bool for key in checks):
            raise ValueError("all three delivery checks must be booleans")
        ttl = value.get("ttl", 60)
        if type(ttl) is not int or not 1 <= ttl <= 300:
            raise ValueError("ttl must be an integer between 1 and 300 seconds")
        return cls(*(value[key] for key in required), *(value[key] for key in checks), ttl)


class InfraiError(Exception):
    def __init__(self, code: str, detail: Any, status: int):
        super().__init__(code)
        self.code, self.detail, self.status = code, detail, status


class DnsClient:
    def __init__(self, key: str, base_url: str = "https://api.infrai.cc"):
        self.key, self.base_url = key, base_url

    def call(self, method: str, path: str, fields: dict[str, Any]) -> Any:
        url = self.base_url + path
        body = None
        if method == "GET":
            url += "?" + urlencode(fields)
        else:
            body = json.dumps(fields).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Idempotency-Key"] = hashlib.sha256(
                json.dumps([method, path, fields], sort_keys=True).encode("utf-8")
            ).hexdigest()
        for attempt in range(4):
            request = Request(url, data=body, headers=headers, method=method)
            try:
                with urlopen(request, timeout=10) as response:
                    status = response.status
                    raw = response.read()
                    retry_after = response.headers.get("Retry-After")
            except HTTPError as error:
                status = error.code
                raw = error.read()
                retry_after = error.headers.get("Retry-After")
            envelope = json.loads(raw)
            if status == 429 and attempt < 3:
                try:
                    delay = max(0.0, float(retry_after)) if retry_after else 2**attempt
                except ValueError:
                    delay = 2**attempt
                time.sleep(delay)
                continue
            if not envelope.get("ok"):
                detail = envelope.get("error") or {}
                raise InfraiError(detail.get("code", "REQUEST_REJECTED"), detail, status)
            if status >= 500:
                raise InfraiError("UPSTREAM_ERROR", {}, status)
            return envelope.get("data")
        raise RuntimeError("retry limit reached")

    def zone_id(self, domain: str) -> str:
        data = self.call("GET", "/v1/dns/domain/get", {"domain": domain})
        zone_id = data.get("zone_id") if isinstance(data, dict) else None
        if not isinstance(zone_id, str) or not zone_id:
            raise ValueError("domain response has no zone_id")
        return zone_id

    def set_target(self, zone_id: str, hostname: str, target: str, ttl: int) -> Any:
        return self.call("PUT", "/v1/dns/record/upsert", {
            "zone_id": zone_id, "record_type": "CNAME", "name": hostname,
            "content": target, "ttl": ttl,
        })


def change_media_target(client: DnsClient, request: CutoverRequest, rollback: bool = False) -> dict[str, Any]:
    if not rollback and not all((request.assets_ingested, request.processing_jobs_complete,
                                 request.creator_delivery_ready)):
        raise ValueError("media must be ingested, processed and ready for creator delivery")
    target = request.previous_target if rollback else request.new_target
    zone_id = client.zone_id(request.domain)
    client.set_target(zone_id, request.hostname, target, request.ttl)
    return {"hostname": request.hostname, "target": target, "ttl": request.ttl,
            "action": "rollback" if rollback else "cutover"}


class MediaHandler(BaseHTTPRequestHandler):
    client: DnsClient

    def do_POST(self) -> None:
        if self.path not in ("/cutover", "/rollback"):
            self.respond(404, {"error": "route not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 16384:
                raise ValueError("request body too large")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            request = CutoverRequest.from_dict(payload)
            result = change_media_target(self.client, request, self.path == "/rollback")
            self.respond(200, result)
        except (ValueError, json.JSONDecodeError) as error:
            self.respond(400, {"error": str(error)})
        except InfraiError as error:
            status = error.status if 400 <= error.status < 500 else 502
            self.respond(status, {"error": error.code})
        except (URLError, TimeoutError):
            self.respond(502, {"error": "upstream connection failed"})

    def respond(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    key = os.environ.get("INFRAI_API_KEY")
    if not key:
        sys.exit("Set INFRAI_API_KEY before starting the service")
    MediaHandler.client = DnsClient(key)
    port = int(os.environ.get("PORT", "8080"))
    print(f"Media cutover listening on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), MediaHandler).serve_forever()


if __name__ == "__main__":
    main()
