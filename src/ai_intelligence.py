import os
import io
import json
import base64
import time
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
from PIL import Image

logger = logging.getLogger("AIIntelligence")

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "data" / "cache"

SYSTEM_PROMPT = """Tu és o Analista de Inteligência Operacional de Elite para a equipa TIMI.
A tua missão é olhar diretamente para as capturas de ecrã dos canais do BonChat e extrair EXCLUSIVAMENTE o que é crítico e operacionalmente relevante para um agente em campo.

REGRAS RÍGIDAS DE FILTRAGEM:
1. FILTRA 100% DO LIXO:
   - Elimina cumprimentos banais ("bom dia", "boa tarde", "olá", "boa noite", etc.).
   - Elimina conversas casuais, piadas, memes, emojis soltos e agradecimentos.
   - Elimina mensagens de membros comuns, conversas da Joana e do Rui Santos (foca-te apenas nas autoridades).

2. MÁXIMA ATENÇÃO EXCLUSIVA ÀS AUTORIDADES:
   - Theodore (diretivas, vídeos, promoções)
   - Jonathan / TIMI-Jonathan (Gerente Geral da TIMI - convocações, penalizações, regras)
   - Márcia (avisos operacionais)
   - Canal oficial TIMI--NO.08 (sorteios oficiais, avisos de sistema)

3. FOCA-TE NO CONTEÚDO REAL DE CARTAZES, IMAGENS E MENSAGENS FIXADAS:
   - 📢 AVISOS & REUNIÕES (datas, horários obrigatórios, penalizações de pontos)
   - 🎯 CAMPANHAS, EMPRÉSTIMOS & BÓNUS (valores em USDT, vagas, condições de adesão)
   - ⚙️ NOVIDADES DE FUNCIONAMENTO (regras, rotas, ferramentas, orientações de chefia)

4. FORMATO DE SAÍDA:
   - Resumo executivo ultra-direto, profissional e pronto para leitura rápida no Telegram (Markdown).
   - Usa emojis para fácil identificação visual.
   - Se não houver avisos de relevo no dia, responde exatamente: "Sem novidades operacionais críticas no turno."
"""

class AIIntelligence:
    def __init__(self, gemini_keys: List[str], groq_key: Optional[str] = None, quota_cfg: Optional[Dict[str, Any]] = None):
        self.gemini_keys = [k.strip() for k in gemini_keys if k and k.strip()]
        self.groq_key = groq_key.strip() if groq_key else None
        self.current_key_idx = 0
        
        self.quota_cfg = quota_cfg or {}
        self.max_calls_per_hour = self.quota_cfg.get("max_gemini_calls_per_hour", 15)
        self.enable_hash_caching = self.quota_cfg.get("enable_hash_caching", True)
        
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.call_history_file = CACHE_DIR / "api_calls_history.json"
        self.hash_cache_file = CACHE_DIR / "analyzed_hashes.json"

    def _can_call_gemini(self) -> bool:
        """Enforces a strict hourly call quota to ensure keys never exhaust."""
        now = time.time()
        one_hour_ago = now - 3600
        history = []
        if self.call_history_file.exists():
            try:
                with open(self.call_history_file, "r") as f:
                    history = json.load(f)
            except Exception:
                history = []

        recent_calls = [t for t in history if t > one_hour_ago]
        if len(recent_calls) >= self.max_calls_per_hour:
            logger.warning(f"Hourly Gemini quota budget reached ({len(recent_calls)}/{self.max_calls_per_hour}). Throttling API call.")
            return False
        return True

    def _record_gemini_call(self):
        now = time.time()
        one_hour_ago = now - 3600
        history = []
        if self.call_history_file.exists():
            try:
                with open(self.call_history_file, "r") as f:
                    history = json.load(f)
            except Exception:
                history = []
        history = [t for t in history if t > one_hour_ago]
        history.append(now)
        with open(self.call_history_file, "w") as f:
            json.dump(history, f)

    def _get_cached_hash_analysis(self, img_hash: str) -> Optional[str]:
        if not self.enable_hash_caching or not self.hash_cache_file.exists():
            return None
        try:
            with open(self.hash_cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
                return cache.get(img_hash)
        except Exception:
            return None

    def _save_cached_hash_analysis(self, img_hash: str, analysis: str):
        if not self.enable_hash_caching:
            return
        cache = {}
        if self.hash_cache_file.exists():
            try:
                with open(self.hash_cache_file, "r", encoding="utf-8") as f:
                    cache = json.load(f)
            except Exception:
                cache = {}
        cache[img_hash] = analysis
        with open(self.hash_cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)

    def _call_gemini_multimodal(self, prompt_text: str, images: List[Image.Image]) -> Optional[str]:
        """
        Sends chat images and prompt directly to Gemini 2.5 Flash with strict quota protection.
        """
        if not self.gemini_keys or not self._can_call_gemini():
            return None

        parts = [{"text": f"{SYSTEM_PROMPT}\n\n{prompt_text}"}]
        for img in images[:3]:
            # Resize image if large to save bandwidth & token quota
            w, h = img.size
            if w > 1200 or h > 1200:
                img = img.resize((w // 2, h // 2))

            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=82)
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
                        "maxOutputTokens": 1024
                    }
                }

                try:
                    resp = requests.post(url, headers=headers, json=payload, timeout=45)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            resp_parts = candidates[0].get("content", {}).get("parts", [])
                            if resp_parts:
                                self.current_key_idx = idx
                                self._record_gemini_call()
                                return resp_parts[0].get("text", "").strip()
                    elif resp.status_code == 429:
                        logger.warning(f"Gemini key #{idx+1} hit rate limit (429). Rotating key...")
                        break
                    else:
                        logger.warning(f"Gemini error {resp.status_code}: {resp.text[:120]}")
                except Exception as e:
                    logger.error(f"Gemini multimodal request exception: {e}")

        return None

    def analyze_channel_capture(self, channel_name: str, images: List[Image.Image]) -> str:
        """
        Analyzes captures of a channel visually using multimodal AI with local hash caching.
        """
        if not images:
            return ""

        # Compute hash of primary chat crop to check if screen changed
        primary = images[0]
        small = primary.convert("L").resize((64, 64))
        img_hash = hashlib.sha256(small.tobytes()).hexdigest()

        cached_analysis = self._get_cached_hash_analysis(img_hash)
        if cached_analysis:
            logger.info(f"Using cached analysis for '{channel_name}' (Hash: {img_hash[:8]}) - 0 API tokens spent.")
            return cached_analysis

        prompt = (
            f"Analisa as capturas do canal '{channel_name}'. "
            f"Observa com atenção mensagens fixadas no topo, cartazes, folhetos gráficos, campanhas e comunicados das autoridades (Theodore, Jonathan, Márcia, TIMI Oficial). "
            f"Ignora completamente mensagens de utilizadores comuns, Joana ou Rui Santos. "
            f"Extrai apenas o que for diretiva oficial, convocatória, sorteio ou campanha."
        )

        analysis = self._call_gemini_multimodal(prompt, images)
        if analysis:
            self._save_cached_hash_analysis(img_hash, analysis)
            return analysis
        return ""

    def generate_full_briefing(self, channel_summaries: Dict[str, str], shift_label: str = "DIÁRIO") -> str:
        """Combines per-channel visual findings into an executive Telegram briefing."""
        valid_items = [
            f"### {ch}\n{text}" for ch, text in channel_summaries.items() 
            if text and "sem novidades" not in text.lower()
        ]

        if not valid_items:
            return f"🚲 *RESUMO OPERACIONAL TIMI ({shift_label})*\n\n✅ Sem novos avisos ou novidades críticas das autoridades registadas neste turno."

        header = f"🚲 *RESUMO OPERACIONAL TIMI ({shift_label})*\n\n"
        body = "\n\n".join(valid_items)
        return header + body
