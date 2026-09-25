import os
import json
import logging
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger("AIIntelligence")

SYSTEM_PROMPT = """Tu és um Analista de Inteligência Operacional de Elite para a equipa TIMI.
A tua missão é analisar as transcrições das conversas do BonChat e extrair EXCLUSIVAMENTE o que é crítico e operacionalmente relevante para um agente em campo.

REGRAS RÍGIDAS DE FILTRAGEM:
1. FILTRA 100% DO LIXO:
   - Elimina cumprimentos banais ("bom dia", "boa tarde", "olá", "boa noite", etc.)
   - Elimina conversas casuais, piadas, memes, emojis soltos e agradecimentos.
   - Elimina perguntas repetitivas de utilizadores sem resposta oficial.

2. MÁXIMA ATENÇÃO AOS CONTACTOS-CHAVE:
   - Mensagens de: THEODORE, JOHNATHAN, MÁRCIA.
   - Mensagens do canal TIMI 08 / AVISOS 08 (tudo o que for comunicado neste canal tem prioridade máxima).

3. FOCA-TE APENAS EM:
   - 📢 AVISOS & REGRAS (alterações de horários, regras de conduta, procedimentos)
   - 🎯 CAMPANHAS & METAS (bónus, prémios, incentivos, objetivos diários/semanais)
   - ⚙️ NOVIDADES DE FUNCIONAMENTO (novos processos, rotas, ferramentas, orientações de chefia)
   - ⚠️ ALERTAS & INCIDENTES (problemas técnicos, falhas no site, bloqueios, fiscalização)

4. FORMATO DE SAÍDA:
   - Resumo executivo ultra-direto, profissional e pronto para leitura rápida no Telegram (Markdown).
   - Usa emojis para fácil identificação visual.
   - Se um canal não tiver nada relevante, omite-o ou resume em 1 linha.
   - Se não houver avisos de relevo no dia, diz claramente: "Sem novidades operacionais críticas no turno."
"""

class AIIntelligence:
    def __init__(self, gemini_keys: List[str], groq_key: Optional[str] = None):
        self.gemini_keys = [k.strip() for k in gemini_keys if k and k.strip()]
        self.groq_key = groq_key.strip() if groq_key else None
        self.current_key_idx = 0

    def _call_gemini(self, prompt: str) -> Optional[str]:
        """Tries calling Gemini 2.5 Flash rotating across available free keys."""
        if not self.gemini_keys:
            return None

        total_keys = len(self.gemini_keys)
        models_to_try = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite"]

        for attempt in range(total_keys):
            idx = (self.current_key_idx + attempt) % total_keys
            api_key = self.gemini_keys[idx]
            
            for model_name in models_to_try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                headers = {"Content-Type": "application/json"}
                payload = {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {"text": f"{SYSTEM_PROMPT}\n\nTRANSCRICÃO DOS CANAIS:\n{prompt}"}
                            ]
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 2048
                    }
                }

                try:
                    resp = requests.post(url, headers=headers, json=payload, timeout=45)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                self.current_key_idx = idx
                                return parts[0].get("text", "").strip()
                    elif resp.status_code == 429:
                        logger.warning(f"Gemini key #{idx+1} hit rate limit (429). Rotating to next key...")
                        break
                    else:
                        logger.warning(f"Gemini {model_name} key #{idx+1} error {resp.status_code}: {resp.text[:120]}")
                except Exception as e:
                    logger.error(f"Gemini request exception on key #{idx+1}: {e}")

        return None

    def _call_groq(self, prompt: str) -> Optional[str]:
        """Calls Groq as a high-speed free fallback."""
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
                {"role": "user", "content": f"TRANSCRICÃO DOS CANAIS:\n{prompt}"}
            ],
            "temperature": 0.2,
            "max_tokens": 2048
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=45)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
            else:
                logger.warning(f"Groq API error {resp.status_code}: {resp.text[:150]}")
        except Exception as e:
            logger.error(f"Groq request exception: {e}")

        return None

    def summarize_channels(self, channel_data: Dict[str, str], shift_label: str = "DIÁRIO") -> str:
        """
        Takes raw OCR text from monitored channels, filters noise, and returns executive brief.
        """
        combined_input = []
        for ch_name, raw_text in channel_data.items():
            if not raw_text or not raw_text.strip():
                continue
            combined_input.append(f"=== CANAL: {ch_name} ===\n{raw_text.strip()}\n")

        if not combined_input:
            return f"ℹ️ *Briefing Operacional BonChat ({shift_label})*\n\nNenhuma mensagem nova capturada nos canais monitorizados."

        full_prompt = "\n".join(combined_input)
        
        # 1. Try Gemini (Primary, free tier)
        summary = self._call_gemini(full_prompt)
        
        # 2. Try Groq (Fallback, free tier)
        if not summary:
            logger.info("Attempting Groq fallback for summarization...")
            summary = self._call_groq(full_prompt)

        if not summary:
            return f"⚠️ *Briefing BonChat ({shift_label})*\n\nFalha ao contactar serviços de IA (Gemini / Groq) para processamento."

        header = f"🚲 *RESUMO OPERACIONAL TIMI ({shift_label})*\n\n"
        return header + summary
