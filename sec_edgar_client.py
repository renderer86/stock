from __future__ import annotations

import os
import time
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import requests


DEFAULT_CONTACT_EMAIL = "renderer86@gmail.com"
DEFAULT_MIN_INTERVAL = 0.15
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class SecAccessError(RuntimeError):
    """Raised when SEC rejects or repeatedly fails a request."""


def sec_headers(contact_email: str | None = None) -> dict[str, str]:
    contact = (
        contact_email
        or os.environ.get("SEC_CONTACT_EMAIL", "").strip()
        or DEFAULT_CONTACT_EMAIL
    )
    return {
        "User-Agent": f"renderer86-stock-data/1.0 ({contact})",
        "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "sec-ch-ua": (
            '"Chromium";v="124", "Google Chrome";v="124", '
            '"Not-A.Brand";v="99"'
        ),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    }


def retry_delay(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After", "").strip()
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                return max(0.0, retry_at.timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                pass
    return min(30.0, 1.5 * (attempt + 1))


class SecEdgarClient:
    def __init__(
        self,
        *,
        contact_email: str | None = None,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        attempts: int = 4,
        timeout: int = 45,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(sec_headers(contact_email))
        self.min_interval = max(0.1, float(min_interval))
        self.attempts = max(1, int(attempts))
        self.timeout = max(1, int(timeout))
        self.clock = clock
        self.sleeper = sleeper
        self.last_request_at: float | None = None
        self.blocked_error: SecAccessError | None = None

    def wait_for_slot(self) -> None:
        if self.last_request_at is None:
            return
        remaining = self.min_interval - (self.clock() - self.last_request_at)
        if remaining > 0:
            self.sleeper(remaining)

    def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        if self.blocked_error is not None:
            raise self.blocked_error

        last_error: Exception | None = None
        for attempt in range(self.attempts):
            self.wait_for_slot()
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                )
                self.last_request_at = self.clock()
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 < self.attempts:
                    self.sleeper(min(30.0, 1.5 * (attempt + 1)))
                    continue
                break

            if response.status_code == 403:
                self.blocked_error = SecAccessError(
                    "SEC returned HTTP 403. Verify the contact email and pause "
                    "automated requests before retrying."
                )
                raise self.blocked_error
            if response.status_code == 404:
                raise SecAccessError(f"SEC resource was not found: {response.url}")
            if response.status_code in RETRYABLE_STATUS_CODES:
                last_error = requests.HTTPError(
                    f"SEC HTTP {response.status_code}: {response.url}"
                )
                if attempt + 1 < self.attempts:
                    self.sleeper(retry_delay(response, attempt))
                    continue
                break

            try:
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt + 1 < self.attempts:
                    self.sleeper(min(30.0, 1.5 * (attempt + 1)))
                    continue
                break

        raise SecAccessError(f"SEC request failed: {url}: {last_error}") from None
