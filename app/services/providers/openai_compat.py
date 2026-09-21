from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.services.providers.base import ModelProvider

# 主流厂商 OpenAI 兼容端点预设（base_url 均需以 /v1 或厂商等价前缀结尾）
_SHARED_CLIENTS: dict = {}

VENDOR_PRESETS = {
    "openai": ("OpenAI", "https://api.openai.com/v1"),
    "deepseek": ("DeepSeek", "https://api.deepseek.com/v1"),
    "glm": ("智谱 GLM", "https://open.bigmodel.cn/api/paas/v4"),
    "moonshot": ("月之暗面 Kimi", "https://api.moonshot.cn/v1"),
    "qwen": ("通义千问", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "custom": ("自定义", ""),
}


class OpenAICompatProvider(ModelProvider):
    """OpenAI 兼容协议 Provider：适用于 OpenAI / DeepSeek / GLM / Kimi / 通义等厂商。"""

    name = "openai_compat"
    DEFAULT_OPTIONS = {"max_tokens": 2048}
    # Ollama 专有参数不能发给 OpenAI 兼容接口（会 400）；num_predict 需要改名
    _OLLAMA_ONLY = {"num_predict", "num_ctx", "repeat_penalty", "repeat_last_n", "keep_alive", "top_k"}

    @classmethod
    def _sanitize_options(cls, options: dict) -> dict:
        clean = {k: v for k, v in (options or {}).items() if k not in cls._OLLAMA_ONLY}
        if "num_predict" in (options or {}):
            clean.setdefault("max_tokens", options["num_predict"])
        return clean

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 300.0,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.timeout = timeout
        self._transport = transport
        self.last_done_reason = ""  # "length" = 撞上输出上限被截断，据此判断要不要续写

    def _http(self) -> httpx.Client:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self._transport is not None:
            return httpx.Client(timeout=self.timeout, transport=self._transport, trust_env=False, headers=headers)
        key = ("api", self.base_url, self.api_key)
        client = _SHARED_CLIENTS.get(key)
        if client is None:
            # 复用连接（HTTP keep-alive），避免每次调用重新握手。
            client = httpx.Client(timeout=self.timeout, trust_env=False, headers=headers,
                                  limits=httpx.Limits(max_keepalive_connections=8))
            _SHARED_CLIENTS[key] = client
        return client

    @staticmethod
    def close_shared_clients():
        for client in _SHARED_CLIENTS.values():
            try:
                client.close()
            except Exception:
                pass
        _SHARED_CLIENTS.clear()

    @staticmethod
    def _error_message(exc: Exception):
        if isinstance(exc, httpx.ConnectError):
            return "无法连接 API 服务，请检查网络与服务地址。"
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            body = exc.response.text[:200]
            if code == 401:
                return "API Key 无效或未授权（401），请在模型中心检查密钥。"
            if code == 404:
                return f"接口不存在（404），请检查 Base URL 是否正确：{body}"
            if code == 429:
                return "请求过于频繁或额度不足（429）。"
            return f"API 返回错误：{code} {body}"
        return str(exc)

    def list_models(self) -> list[dict]:
        if not self.base_url:
            raise RuntimeError("请先填写 API 服务地址（Base URL）。")
        try:
            client = self._http()
            if True:
                response = client.get(f"{self.base_url}/models")
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise RuntimeError(self._error_message(exc)) from exc
        result = []
        for item in data.get("data") or []:
            model_id = item.get("id") or ""
            if model_id:
                result.append({"name": model_id, "size": 0, "family": item.get("owned_by") or "",
                               "parameter_size": "", "quantization": ""})
        return result

    def generate(self, prompt, model, system=None, options=None) -> str:
        if not self.base_url:
            raise RuntimeError("请先在模型中心配置 API 服务地址与密钥。")
        if not model:
            raise RuntimeError("未指定模型名，请先在模型中心设置默认模型。")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": model, "messages": messages,
                   **{k: v for k, v in {**self.DEFAULT_OPTIONS, **self._sanitize_options(options)}.items()}}
        try:
            client = self._http()
            response = client.post(f"{self.base_url}/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise RuntimeError(self._error_message(exc)) from exc
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("API 未返回生成结果。")
        self.last_done_reason = choices[0].get("finish_reason") or ""
        return (choices[0].get("message") or {}).get("content") or ""

    def generate_stream(self, prompt, model, system=None, options=None, on_chunk=None) -> str:
        if not self.base_url or not model:
            raise RuntimeError("请先在模型中心配置 API 服务地址与默认模型。")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": model, "messages": messages, "stream": True,
                   **{k: v for k, v in {**self.DEFAULT_OPTIONS, **self._sanitize_options(options)}.items()}}
        collected = []
        try:
            client = self._http()
            if True:
                with client.stream("POST", f"{self.base_url}/chat/completions", json=payload) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            item = json.loads(chunk)
                        except ValueError:
                            continue
                        delta = ((item.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                        reason = (item.get("choices") or [{}])[0].get("finish_reason") or ""
                        if reason:
                            self.last_done_reason = reason
                        if delta:
                            collected.append(delta)
                            if on_chunk:
                                on_chunk("".join(collected), delta)
        except Exception as exc:
            raise RuntimeError(self._error_message(exc)) from exc
        return "".join(collected)

    def vision(self, prompt, model, image_path, system=None, options=None) -> str:
        if not self.base_url or not model:
            raise RuntimeError("请先在模型中心配置 API 服务地址与默认模型。")
        import base64
        image_file = Path(image_path)
        if not image_file.exists():
            raise RuntimeError(f"图片不存在：{image_path}")
        data_url = "data:image/png;base64," + base64.b64encode(image_file.read_bytes()).decode("utf-8")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]})
        payload = {"model": model, "messages": messages, **self.DEFAULT_OPTIONS, **(options or {})}
        try:
            client = self._http()
            response = client.post(f"{self.base_url}/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise RuntimeError(self._error_message(exc)) from exc
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("API 未返回识别结果。")
        return (choices[0].get("message") or {}).get("content") or ""
