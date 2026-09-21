from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.services.providers.base import ModelProvider


_SHARED_CLIENTS: dict = {}


class OllamaProvider(ModelProvider):
    """本地 Ollama 服务提供方：动态发现模型，不预设任何模型清单。

    加速策略：① 同一地址复用 HTTP 连接（避免每次新建连接握手）；
    ② 请求携带 keep_alive 让模型常驻显存，后续调用无需重新加载。
    """

    name = "ollama"
    KEEP_ALIVE = "30m"

    def __init__(self, endpoint: str, timeout: float = 300.0, transport: httpx.BaseTransport | None = None):
        self.endpoint = (endpoint or "").rstrip("/") or "http://127.0.0.1:11434"
        self.timeout = timeout
        self._transport = transport
        self.last_done_reason = ""  # "length" = 撞上输出上限被截断，据此判断要不要续写

    def _http(self) -> httpx.Client:
        # 本地服务不走系统代理，避免环境代理变量拦截 127.0.0.1 请求。
        if self._transport is not None:
            return httpx.Client(timeout=self.timeout, transport=self._transport, trust_env=False)
        key = ("ollama", self.endpoint)
        client = _SHARED_CLIENTS.get(key)
        if client is None:
            client = httpx.Client(timeout=self.timeout, trust_env=False)
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

    def _post(self, path: str, payload: dict) -> dict:
        try:
            client = self._http()
            response = client.post(f"{self.endpoint}{path}", json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as exc:
            raise RuntimeError(f"无法连接 Ollama 服务（{self.endpoint}），请确认 Ollama 已启动。") from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Ollama 返回错误：{exc.response.status_code} {exc.response.text[:200]}") from exc

    def list_models(self) -> list[dict]:
        try:
            client = self._http()
            response = client.get(f"{self.endpoint}/api/tags")
            response.raise_for_status()
            data = response.json()
        except httpx.ConnectError as exc:
            raise RuntimeError(f"无法连接 Ollama 服务（{self.endpoint}），请确认 Ollama 已启动。") from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Ollama 返回错误：{exc.response.status_code} {exc.response.text[:200]}") from exc
        result = []
        for item in data.get("models") or []:
            details = item.get("details") or {}
            result.append({
                "name": item.get("name") or item.get("model") or "",
                "size": item.get("size") or 0,
                "family": details.get("family") or "",
                "parameter_size": details.get("parameter_size") or "",
                "quantization": details.get("quantization_level") or "",
            })
        return result

    DEFAULT_OPTIONS = {"num_predict": 2048}

    def generate(self, prompt, model, system=None, options=None) -> str:
        if not model:
            raise RuntimeError("未指定生成模型，请先在模型中心设置默认 LLM。")
        payload = {"model": model, "prompt": prompt, "stream": False,
                   "keep_alive": self.KEEP_ALIVE,
                   "options": {**self.DEFAULT_OPTIONS, **(options or {})}}
        if system:
            payload["system"] = system
        data = self._post("/api/generate", payload)
        self.last_done_reason = data.get("done_reason") or ""
        return data.get("response") or ""

    def generate_stream(self, prompt, model, system=None, options=None, on_chunk=None) -> str:
        """流式生成：每收到一段文本就回调 on_chunk(累计文本, 新增文本)，返回完整文本。"""
        if not model:
            raise RuntimeError("未指定生成模型，请先在模型中心设置默认 LLM。")
        payload = {"model": model, "prompt": prompt, "stream": True,
                   "keep_alive": self.KEEP_ALIVE,
                   "options": {**self.DEFAULT_OPTIONS, **(options or {})}}
        if system:
            payload["system"] = system
        collected = []
        try:
            client = self._http()
            if True:
                with client.stream("POST", f"{self.endpoint}/api/generate", json=payload) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                        except ValueError:
                            continue
                        piece = item.get("response") or ""
                        if piece:
                            collected.append(piece)
                            if on_chunk:
                                on_chunk("".join(collected), piece)
                        if item.get("done"):
                            self.last_done_reason = item.get("done_reason") or ""
                            break
        except httpx.ConnectError as exc:
            if not collected:
                raise RuntimeError(f"无法连接 Ollama 服务（{self.endpoint}），请确认 Ollama 已启动。") from exc
            self.last_done_reason = "aborted"
        except httpx.HTTPStatusError as exc:
            # 已收到内容后再报错（如"token repeat limit reached"中途中止）→ 保留已生成的部分，
            # 交给上层续写，而不是把整段结果丢空退化成兜底骨架。
            if not collected:
                raise RuntimeError(f"Ollama 返回错误：{exc.response.status_code} {exc.response.text[:200]}") from exc
            self.last_done_reason = "aborted"
        return "".join(collected)

    def vision(self, prompt, model, image_path, system=None, options=None) -> str:
        """视觉反推：把本地图片以 base64 发给多模态模型（参照 TE 工作流的 图像→VLM→提示词 原理）。"""
        if not model:
            raise RuntimeError("未指定视觉模型，请先在模型中心设置默认 Vision 模型。")
        import base64
        image_file = Path(image_path)
        if not image_file.exists():
            raise RuntimeError(f"图片不存在：{image_path}")
        payload = {
            "model": model, "prompt": prompt, "stream": False,
            "keep_alive": self.KEEP_ALIVE,
            "options": {**self.DEFAULT_OPTIONS, **(options or {})},
            "images": [base64.b64encode(image_file.read_bytes()).decode("utf-8")],
        }
        if system:
            payload["system"] = system
        data = self._post("/api/generate", payload)
        return data.get("response") or ""

    def embeddings(self, text, model) -> list[float]:
        if not model:
            raise RuntimeError("未指定向量化模型，请先在模型中心设置默认 Embedding。")
        data = self._post("/api/embeddings", {"model": model, "prompt": text})
        vector = data.get("embedding")
        if not isinstance(vector, list):
            raise RuntimeError("Ollama 未返回有效的向量数据")
        return vector
