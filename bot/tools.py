import httpx
from smolagents import Tool


class HFModelLookupTool(Tool):
    name = "hf_model_lookup"
    description = (
        "Look up detailed metadata for a HuggingFace model by its model_id "
        "(e.g. 'meta-llama/Llama-3.1-8B-Instruct'). Returns parameter count, "
        "architecture, pipeline tag, quantization info, downloads, likes, "
        "last modified date, and a direct link."
    )
    inputs = {
        "model_id": {
            "type": "string",
            "description": "The HuggingFace model ID, e.g. 'meta-llama/Llama-3.1-8B-Instruct'.",
        }
    }
    output_type = "string"

    def forward(self, model_id: str) -> str:
        url = f"https://huggingface.co/api/models/{model_id}"
        resp = httpx.get(url, timeout=15.0)
        if resp.status_code == 404:
            return f"Model '{model_id}' not found on HuggingFace."
        resp.raise_for_status()
        data = resp.json()

        safetensors = data.get("safetensors")
        param_count = None
        if safetensors and isinstance(safetensors, dict):
            param_count = safetensors.get("total") or safetensors.get("parameters", {}).get("total")

        model_config = data.get("config") or {}
        architectures = model_config.get("architectures", [])
        quant_config = model_config.get("quantization_config", {})
        quant_method = quant_config.get("quant_method", "none")

        lines = [
            f"Model: {model_id}",
            f"URL: https://huggingface.co/{model_id}",
            f"Pipeline: {data.get('pipeline_tag', 'N/A')}",
            f"Architectures: {', '.join(architectures) if architectures else 'N/A'}",
            f"Parameters: {param_count if param_count else 'N/A'}",
            f"Quantization: {quant_method}",
            f"Likes: {data.get('likes', 0)}",
            f"Downloads: {data.get('downloads', 0)}",
            f"Last Modified: {data.get('lastModified', 'N/A')}",
        ]

        card_data = data.get("cardData") or {}
        if card_data.get("license"):
            lines.append(f"License: {card_data['license']}")

        tags = data.get("tags", [])
        if tags:
            lines.append(f"Tags: {', '.join(tags[:10])}")

        return "\n".join(lines)
