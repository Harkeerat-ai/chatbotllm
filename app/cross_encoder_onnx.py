import logging
import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from transformers import AutoTokenizer

logger = logging.getLogger(__name__)

_MODEL_REPO = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_ONNX_FILENAME = "onnx/model.onnx"


class CrossEncoderONNX:
    def __init__(self, model_repo: str = _MODEL_REPO, onnx_filename: str = _ONNX_FILENAME):
        model_path = hf_hub_download(repo_id=model_repo, filename=onnx_filename)
        self.tokenizer = AutoTokenizer.from_pretrained(model_repo)

        providers = [
            "DmlExecutionProvider",
            "CPUExecutionProvider",
        ]
        available = ort.get_available_providers()
        effective = [p for p in providers if p in available]
        logger.info("ONNX providers: available=%s effective=%s", available, effective)

        if not effective:
            effective = ["CPUExecutionProvider"]

        self.session = ort.InferenceSession(model_path, providers=effective)
        self.model_inputs = {inp.name for inp in self.session.get_inputs()}

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        texts = [f"{q} [SEP] {d}" for q, d in pairs]
        inputs = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="np",
        )

        feed = {
            "input_ids": inputs["input_ids"].astype(np.int64),
            "attention_mask": inputs["attention_mask"].astype(np.int64),
        }
        if "token_type_ids" in self.model_inputs:
            feed["token_type_ids"] = inputs.get("token_type_ids", np.zeros_like(inputs["input_ids"])).astype(np.int64)

        outputs = self.session.run(["logits"], feed)
        return outputs[0][:, 0].tolist()

    def __call__(self, pairs: list[tuple[str, str]]) -> list[float]:
        return self.predict(pairs)
