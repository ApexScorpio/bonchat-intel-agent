import os
import io
import json
import base64
import logging
from typing import Dict, Any, List, Optional
import requests
from PIL import Image

logger = logging.getLogger("AIIntelligence")

SYSTEM_PROMPT = """Tu és o Analista de Inteligência Operacional de Elite para a equipa TIMI.
A tua missão é olhar diretamente para as capturas de ecrã dos canais do BonChat e extrair EXCLUSIVAMENTE o que é crítico e operacionalmente relevante para um agente em campo.

REGRAS RÍGIDAS DE FILTRAGEM:
1. FILTRA 100% DO LIXO:
   - Elimina cumprimentos banais ("bom dia", "boa tarde", "olá", "boa noite", etc.).
   - Elimina conversas casuais, piadas, memes, emojis soltos e agradecimentos.
   - Elimina perguntas repetitivas de utilizadores sem resposta oficial.

2. MÁXIMA ATENÇÃO AOS CONTACTOS-CHAVE E CANAIS OFICIAIS:
   - Theodore (e canal Teodoro.Grupo de Agentes20)
   - Jonathan / TIMI-Jonathan (Gerente Geral da TIMI)
   - Márcia
   - Joana (avisos importantes de reuniões)
   - Rui Santos (diretivas do Theodore e subidas de nível)
   - Canal TIMI--NO.08 (tudo o que for comunicado neste canal tem prioridade máxima)

3. FOCA-TE NO CONTEÚDO REAL DE CARTAZES, IMAGENS E MENSAGENS FIXADAS:
   - 📢 AVISOS & REUNIÕES (datas, horários obrigatórios, penalizações de pontos)
   - 🎯 CAMPANHAS, EMPRÉSTIMOS & BÓNUS (valores em USDT, vagas, condições de adesão)
   - ⚙️ NOVIDADES DE FUNCIONAMENTO (regras, rotas, ferramentas, orientações de chefia)
   - 🏆 RECONHECIMENTOS & SUBIDAS DE NÍVEL (promoções oficiais de agentes)

4. FORMATO DE SAÍDA:
   - Resumo executivo ultra-direto, profissional e pronto para leitura rápida no Telegram (Markdown).
   - Usa emojis para fácil identificação visual.
   - Se um canal não tiver nada relevante, omite-o.
   - Se não houver avisos de relevo no dia, diz: "Sem novidades operacionais críticas no turno."
"""

class AIIntelligence:
    def __init__(self, gemini_keys: List[str], groq_key: Optional[str] = None):
        self.gemini_keys = [k.strip() for k in gemini_keys if k and k.strip()]
        self.groq_key = groq_key.strip() if groq_key else None
        self.current_key_idx = 0

    def _call_gemini_multimodal(self, prompt_text: str, images: List[Image.Image]) -> Optional[str]:
        """
        Sends chat images and prompt directly to Gemini 2.5 Flash for true multimodal visual inspection.
        """
        if not self.gemini_keys:
            return None

        # Prepare parts: text prompt + base64 images
        parts = [{"text": f"{SYSTEM_PROMPT}\n\n{prompt_text}"}]
        for img in images[:4]:  # send up to 4 images per call
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=85)
            img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": img_b64
                }
            })

        total_keys = len(self.gemini_keys)
        models_to_try = ["gemini-2.5-flash", "gemini-flash-latest"]

        for attempt in range(total_keys):
            idx = (self.current_key_idx + attempt) % total_keys
            api_key = self.gemini_keys[idx]

            for model_name in models_to_try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                headers = {"Content-Type": "application/json"}
                payload = {
                    "contents": [{"role": "user", "parts": parts}],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 2048
                    }
                }

                try:
                    resp = requests.post(url, headers=headers, json=payload, timeout=60)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            resp_parts = candidates[0].get("content", {}).get("parts", [])
                            if resp_parts:
                                self.current_key_idx = idx
                                return resp_parts[0].get("text", "").strip()
                    elif resp.status_code == 429:
                        logger.warning(f"Gemini key #{idx+1} hit rate limit (429). Rotating to next key...")
                        break
                    else:
                        logger.warning(f"Gemini error {resp.status_code}: {resp.text[:120]}")
                except Exception as e:
                    logger.error(f"Gemini multimodal request exception: {e}")

        return None

    def _call_groq_text(self, text_prompt: str) -> Optional[str]:
        """High-speed free fallback for textual summarization."""
        if not self.groq_key:
            return None

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "qwen/qwen3.8-27b",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text_prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 2048
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=45)
            if resp.status_code == 200:
                choices = resp.json().get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.error(f"Groq exception: {e}")

        return None

    def analyze_channel_capture(self, channel_name: str, images: List[Image.Image]) -> str:
        """
        Analyzes captures of a channel visually using multimodal AI.
        """
        if not images:
            return ""

        prompt = (
            f"Analisa as capturas do canal '{channel_name}'. "
            f"Observa com atenção mensagens fixadas no topo, cartazes, folhetos gráficos, campanhas e mensagens dos contactos-chave. "
            f"Filtra todo o lixo e extrai apenas informação operacional útil."
        )

        return self._call_gemini_multimodal(prompt, images) or ""

    def generate_full_briefing(self, channel_summaries: Dict[str, str], shift_label: str = "DIÁRIO") -> str:
        """
        Combines per-channel visual findings into an executive Telegram briefing.
        """
        valid_items = [f"### {ch}\n{text}" for ch, text in channel_summaries.items() if text and "sem novidades" not in text.lower()]
        
        if not valid_items:
            return f"🚲 *RESUMO OPERACIONAL TIMI ({shift_label})*\n\n✅ Sem novos avisos ou novidades críticas registadas neste turno."

        header = f"🚲 *RESUMO OPERACIONAL TIMI ({shift_label})*\n\n"
        body = "\n\n".join(valid_items)
        return header + body
