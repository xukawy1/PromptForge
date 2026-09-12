from __future__ import annotations


class ModelProvider:
    """模型提供方接口。实现类负责发现模型、生成与向量化，UI 与业务层不得写死模型名。"""

    name = "base"

    def list_models(self):
        raise NotImplementedError

    def generate(self, prompt, model, system=None, options=None):
        raise NotImplementedError

    def embeddings(self, text, model):
        raise NotImplementedError
