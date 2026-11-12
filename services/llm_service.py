from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger("orbe.llm")

SYSTEM_PROMPT = (
    "Você resume resultados de visão computacional para operadores rodoviários. "
    "Use SOMENTE os dados fornecidos. Não invente detecções, números ou causas. "
    "Não afirme que houve acidente: diga que é uma possível situação a ser verificada. "
    "Responda em português, em no máximo 3 frases."
)


def template_summary(analysis):
    res = analysis["result"]
    n = len(analysis.get("detections", []))
    tri = analysis.get("triage") or {}
    ind = tri.get("indicators", {})
    aviso = ""
    if analysis.get("model_mode") == "generic" and res != "none":
        aviso = "Atenção: o modelo em uso é genérico e não foi treinado para reconhecer acidentes. "
    if res == "possible":
        partes = [str(ind.get("vehicles", 0)) + " veículo(s)"]
        if ind.get("people"):
            partes.append(str(ind["people"]) + " pessoa(s)")
        if ind.get("two_wheelers"):
            partes.append(str(ind["two_wheelers"]) + " moto(s)/bicicleta(s)")
        return (aviso + "Possível ocorrência na imagem: " + ", ".join(partes) + " detectado(s). "
                + (tri.get("priority_label", "") + ". ") +
                "Confirme a imagem antes de acionar a equipe APH.")
    if res == "inconclusive":
        return aviso + "Resultado inconclusivo: " + analysis["situation_type"] + ". Uma pessoa precisa olhar a imagem."
    return "Nenhum indício de ocorrência foi encontrado (" + str(n) + " detecção(ões)). Isso não garante que não haja ocorrência."


class LLMService:
    def __init__(self, provider: str = "none", base_url: str = "", api_key: str = "", model: str = ""):
        self.provider, self.base_url, self.api_key, self.model = provider, base_url.rstrip("/"), api_key, model

    @property
    def enabled(self) -> bool:
        return self.provider == "openai_compatible" and bool(self.base_url and self.model)

    def summarize(self, analysis: dict) -> dict:
        if self.enabled:
            try:
                return {"text": self._call(analysis), "source": "llm"}
            except Exception as exc:
                log.warning("LLM indisponível, usando resumo padrão: %s", type(exc).__name__)
        return {"text": template_summary(analysis), "source": "template"}

    def _call(self, analysis: dict) -> str:
        payload = {k: analysis.get(k) for k in
                   ("result", "situation_type", "confidence", "detections", "model_mode", "reasons")}
        body = json.dumps({
            "model": self.model, "temperature": 0.2,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        }).encode()
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        return data["choices"][0]["message"]["content"].strip()
