from __future__ import annotations


class ModelProvider:
    """模型提供方接口。实现类负责发现模型、生成与向量化，UI 与业务层不得写死模型名。

    think 参数：是否允许模型输出"思考过程"。提示词成品类任务一律传 False——
    思考会吃掉输出额度（实测 qwen3.8 思考占满 num_predict 后正文为空），
    且这类任务不需要长推理。不支持的 provider 忽略该参数即可。
    """

    name = "base"
    SUPPORTS_THINK = False

    def list_models(self):
        raise NotImplementedError

    def generate(self, prompt, model, system=None, options=None, think=None):
        raise NotImplementedError

    def embeddings(self, text, model):
        raise NotImplementedError
