"""Клиент LLM с учётом usage и поддержкой GigaChat. Владелец: №2.

Каждый вызов добавляет LlmCall в UsageLog (модель, длительность, токены или None).
Ключи берутся только из переменных окружения (.env) и никогда не пишутся в файлы и логи.
По умолчанию используется новейшая флагманская модель Сбера GigaChat-3-Ultra.
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from harness.contracts import LlmCall, UsageLog

try:
    from gigachat import GigaChat as SberGigaChat
    from gigachat.models import Chat as SberChat, Messages as SberMessages, MessagesRole as SberMessagesRole

    GIGACHAT_SDK_AVAILABLE = True
except ImportError:
    GIGACHAT_SDK_AVAILABLE = False

DEFAULT_MODEL = "GigaChat-3-Ultra"
DEFAULT_SCOPE = "GIGACHAT_API_PERS"
OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
BASE_API_URL = "https://api.giga.chat/v1"


def load_env(env_path: Path | None = None) -> None:
    """Загружает переменные из .env файла в os.environ, если они еще не установлены."""
    if env_path is None:
        cur = Path.cwd().resolve()
        for p in [cur, *cur.parents]:
            candidate = p / ".env"
            if candidate.is_file():
                env_path = candidate
                break

    if env_path is None or not env_path.is_file():
        return

    try:
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                os.environ.setdefault(key, val)
    except Exception:
        pass


load_env()


class LlmError(RuntimeError):
    """Ошибка при вызове LLM API."""


@dataclass(frozen=True)
class LlmResponse:
    text: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    duration_sec: float


class GigaChatAuth:
    """Менеджер авторизации GigaChat (поддержка Bearer-токена и OAuth-обмена)."""

    def __init__(
        self,
        access_token: str | None = None,
        credentials: str | None = None,
        scope: str = DEFAULT_SCOPE,
        auth_url: str = OAUTH_URL,
        verify_ssl: bool = False,
        ca_bundle: str | None = None,
    ) -> None:
        self.access_token = access_token
        self.credentials = credentials
        self.scope = scope
        self.auth_url = auth_url
        self.verify_ssl = verify_ssl
        self.ca_bundle = ca_bundle

        self._cached_token: str | None = access_token
        self._expires_at: float = 0.0 if not access_token else float("inf")

    def _get_ssl_context(self) -> ssl.SSLContext:
        if not self.verify_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        if self.ca_bundle and os.path.isfile(self.ca_bundle):
            return ssl.create_default_context(cafile=self.ca_bundle)
        return ssl.create_default_context()

    def get_token(self) -> str:
        """Возвращает актуальный Bearer токен, обновляя его через OAuth при необходимости."""
        if self.access_token:
            return self.access_token

        now = time.time()
        if self._cached_token and now + 60 < self._expires_at:
            return self._cached_token

        if not self.credentials:
            raise LlmError(
                "GigaChat credentials not configured. Please set GIGACHAT_ACCESS_TOKEN or "
                "GIGACHAT_CREDENTIALS in .env or environment variables."
            )

        req_id = str(uuid.uuid4())
        auth_header = (
            self.credentials
            if self.credentials.startswith("Basic ") or self.credentials.startswith("Bearer ")
            else f"Basic {self.credentials}"
        )
        headers = {
            "Authorization": auth_header,
            "RqUID": req_id,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        body = urllib.parse.urlencode({"scope": self.scope}).encode("utf-8")

        req = urllib.request.Request(self.auth_url, data=body, headers=headers, method="POST")
        ssl_ctx = self._get_ssl_context()

        try:
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                token = data.get("access_token")
                if not token:
                    raise LlmError("OAuth response did not contain access_token")
                exp = data.get("expires_at", 0)
                if exp > 1e11:
                    exp = exp / 1000.0
                self._cached_token = str(token)
                self._expires_at = float(exp) if exp else (now + 1800)
                return self._cached_token
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise LlmError(f"OAuth request failed with HTTP {e.code}: {err_body}") from None
        except Exception as e:
            raise LlmError(f"OAuth request failed: {e}") from e


class LlmClient:
    """Клиент для общения с языковой моделью (GigaChat) с учетом затрат."""

    def __init__(
        self,
        model: str | None = None,
        usage: UsageLog | None = None,
        *,
        access_token: str | None = None,
        credentials: str | None = None,
        scope: str | None = None,
        base_url: str | None = None,
        auth_url: str | None = None,
        verify_ssl: bool | None = None,
        ca_bundle: str | None = None,
        timeout: float = 120.0,
        prefer_sdk: bool = True,
    ) -> None:
        load_env()

        self.model = model or os.environ.get("GIGACHAT_MODEL") or DEFAULT_MODEL
        self.usage = usage if usage is not None else UsageLog()
        self.base_url = (base_url or os.environ.get("GIGACHAT_BASE_URL") or BASE_API_URL).rstrip("/")
        self.timeout = timeout
        self.prefer_sdk = prefer_sdk

        if verify_ssl is None:
            env_ssl = os.environ.get("GIGACHAT_VERIFY_SSL", "false").strip().lower()
            self.verify_ssl = env_ssl in ("true", "1", "yes")
        else:
            self.verify_ssl = verify_ssl

        self.ca_bundle = ca_bundle or os.environ.get("GIGACHAT_CA_BUNDLE_FILE")

        token = access_token or os.environ.get("GIGACHAT_ACCESS_TOKEN")
        creds = credentials or os.environ.get("GIGACHAT_CREDENTIALS") or os.environ.get("GIGACHAT_API_KEY")

        # Если token выглядит как Base64-ключ (содержит разделитель : после декода), перенаправляем в creds
        if token and not creds and ":" in token or (token and len(token) > 80 and not token.startswith("eyJ")):
            try:
                import base64
                decoded = base64.b64decode(token).decode("utf-8", errors="ignore")
                if ":" in decoded:
                    creds = token
                    token = None
            except Exception:
                pass

        scp = scope or os.environ.get("GIGACHAT_SCOPE") or DEFAULT_SCOPE
        a_url = auth_url or os.environ.get("GIGACHAT_AUTH_URL") or OAUTH_URL

        self.auth = GigaChatAuth(
            access_token=token,
            credentials=creds,
            scope=scp,
            auth_url=a_url,
            verify_ssl=self.verify_ssl,
            ca_bundle=self.ca_bundle,
        )

        self._sdk_client = None
        if self.prefer_sdk and GIGACHAT_SDK_AVAILABLE and (token or creds):
            try:
                self._sdk_client = SberGigaChat(
                    base_url=self.base_url,
                    access_token=token,
                    credentials=creds,
                    scope=scp,
                    verify_ssl_certs=self.verify_ssl,
                    timeout=self.timeout,
                )
            except Exception:
                self._sdk_client = None

    def _get_ssl_context(self) -> ssl.SSLContext:
        if not self.verify_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        if self.ca_bundle and os.path.isfile(self.ca_bundle):
            return ssl.create_default_context(cafile=self.ca_bundle)
        return ssl.create_default_context()

    def complete(
        self,
        system: str,
        user: str,
        *,
        purpose: str,
        max_tokens: int = 8000,
        temperature: float = 0.0,
    ) -> LlmResponse:
        """Отправляет запрос на генерацию в GigaChat и записывает usage."""
        t0 = time.perf_counter()

        # 1. Попытка через официальный SDK GigaChat
        if self._sdk_client is not None:
            try:
                chat = SberChat(
                    model=self.model,
                    messages=[
                        SberMessages(role=SberMessagesRole.SYSTEM, content=system),
                        SberMessages(role=SberMessagesRole.USER, content=user),
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                resp = self._sdk_client.chat(chat)
                duration_sec = round(time.perf_counter() - t0, 3)

                text = resp.choices[0].message.content if resp.choices else ""
                input_tokens = resp.usage.prompt_tokens if resp.usage else None
                output_tokens = resp.usage.completion_tokens if resp.usage else None
                resp_model = resp.model or self.model

                call = LlmCall(
                    model=resp_model,
                    duration_sec=duration_sec,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    purpose=purpose,
                )
                self.usage.calls.append(call)

                return LlmResponse(
                    text=text,
                    model=resp_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    duration_sec=duration_sec,
                )
            except Exception:
                # Если SDK упал с сетевой ошибкой или не настроен, пробуем fallback на direct urllib
                pass

        # 2. Прямой HTTP-вызов через urllib
        token = self.auth.get_token()

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        req_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=req_body, headers=headers, method="POST")
        ssl_ctx = self._get_ssl_context()

        try:
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=self.timeout) as resp:
                raw_data = resp.read().decode("utf-8")
                data = json.loads(raw_data)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            duration_sec = round(time.perf_counter() - t0, 3)
            self.usage.calls.append(
                LlmCall(
                    model=self.model,
                    duration_sec=duration_sec,
                    input_tokens=None,
                    output_tokens=None,
                    purpose=f"{purpose}:error",
                )
            )
            raise LlmError(f"GigaChat API call failed with HTTP {e.code}: {err_body}") from None
        except Exception as e:
            duration_sec = round(time.perf_counter() - t0, 3)
            self.usage.calls.append(
                LlmCall(
                    model=self.model,
                    duration_sec=duration_sec,
                    input_tokens=None,
                    output_tokens=None,
                    purpose=f"{purpose}:error",
                )
            )
            raise LlmError(f"GigaChat API call failed: {e}") from e

        duration_sec = round(time.perf_counter() - t0, 3)

        choices = data.get("choices", [])
        if not choices:
            raise LlmError(f"GigaChat returned empty choices: {data}")

        message = choices[0].get("message", {})
        text = message.get("content", "")

        usage_info = data.get("usage", {})
        input_tokens = usage_info.get("prompt_tokens")
        output_tokens = usage_info.get("completion_tokens")
        resp_model = data.get("model", self.model)

        call = LlmCall(
            model=resp_model,
            duration_sec=duration_sec,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            purpose=purpose,
        )
        self.usage.calls.append(call)

        return LlmResponse(
            text=text,
            model=resp_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_sec=duration_sec,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Получает векторные представления текстов через /embeddings."""
        if not texts:
            return []

        if self._sdk_client is not None:
            try:
                embeddings_model = os.environ.get("GIGACHAT_EMBEDDINGS_MODEL", "Embeddings")
                resp = self._sdk_client.embeddings(texts, model=embeddings_model)
                if hasattr(resp, "data"):
                    return [item.embedding for item in resp.data]
            except Exception:
                pass

        token = self.auth.get_token()
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        embeddings_model = os.environ.get("GIGACHAT_EMBEDDINGS_MODEL", "Embeddings")
        payload = {
            "model": embeddings_model,
            "input": texts,
        }

        req_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=req_body, headers=headers, method="POST")
        ssl_ctx = self._get_ssl_context()

        try:
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise LlmError(f"GigaChat embeddings call failed: {e}") from e

        data_items = data.get("data", [])
        return [item.get("embedding", []) for item in data_items]
