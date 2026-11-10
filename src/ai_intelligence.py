import os
import io
import re
import json
import base64
import time
import datetime
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import requests
from PIL import Image

from .date_pill_detector import DatePillDetector
from .telemetry_bridge import LiveViewBridge

logger = logging.getLogger("AIIntelligence")

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "data" / "cache"

SYSTEM_PROMPT = """Tu és o Analista de Inteligência Operacional de Elite para a equipa TIMI.
A tua missão é olhar diretamente para as capturas de ecrã dos canais do BonChat e extrair o conteúdo das mensagens, anúncios e discussões relevantes de TODOS os autores e participantes em campo.

REGRAS DE FILTRAGEM:
1. FILTRA APENAS RUÍDO TRIVIAL:
   - Elimina cumprimentos banais isolados sem conteúdo adicional ("bom dia", "olá", "obrigado", emojis soltos).
   - Mantém todas as mensagens informativas, diretivas, questões operacionais, respostas e discussões de TODOS os autores (liderança e membros).

2. ATENÇÃO A TODOS OS PARTICIPANTES:
   - Theodore, Jonathan / TIMI-Jonathan, Márcia, TIMI--NO.08.
   - Líderes de equipa, formadores, agentes de campo e membros participantes.

3. FOCA-TE NO CONTEÚDO REAL DE CARTAZES, IMAGENS E MENSAGENS FIXADAS:
   - 📢 AVISOS & REUNIÕES (datas, horários obrigatórios, penalizações de pontos)
   - 🎯 CAMPANHAS, EMPRÉSTIMOS & BÓNUS (valores em USDT, vagas, condições de adesão)
   - ⚙️ NOVIDADES DE FUNCIONAMENTO (regras, rotas, ferramentas, orientações de chefia)

4. IDENTIFICAÇÃO RIGOROSA DA DATA DE CADA MENSAGEM:
   - Identifica o dia a que cada mensagem pertence observando as pílulas de data centrais do BonChat (ex: "9/17", "9/18", "9/26", "Hoje", "Ontem").
   - Todas as mensagens situadas por baixo de uma pílula de data pertencem a esse dia, até surgir uma nova pílula.
   - ATENÇÃO: Nunca confundas datas impressas dentro de capturas de ecrã/fotos enviadas por membros (ex: prints de depósitos, transações) com a pílula de data nativa do chat do BonChat.

5. FORMATO DE SAÍDA:
   - Resumo executivo ultra-direto, profissional e pronto para leitura rápida no Telegram (Markdown).
   - Usa emojis para fácil identificação visual.
   - Bloco estruturado JSON no fim com todas as entradas de inteligência das autoridades identificadas.
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
        for img in images[:8]:
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

        for retry_round in range(4):
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
                            "maxOutputTokens": 4096
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

            if retry_round < 3:
                logger.info(f"All Gemini keys hit rate limit (round {retry_round+1}/4). Waiting 15s for RPM quota window to reset...")
                time.sleep(15)

        return None

    def analyze_channel_capture(self, channel_name: str, images: List[Image.Image]) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Analyzes captures of a channel visually using multimodal AI and DatePillDetector.
        Returns:
            clean_summary (str): Formatted executive briefing for Telegram
            extracted_entries (List[Dict[str, Any]]): Structured intel records for the Knowledge Base
        """
        if not images:
            return "", []

        # Process frames in batches of up to 6 frames so deep scroll history is fully analyzed
        batch_size = 6
        all_entries = []
        all_summaries = []

        detector = DatePillDetector()
        latest_known_date = datetime.datetime.now().strftime("%Y-%m-%d")

        for b_idx in range(0, len(images), batch_size):
            chunk_imgs = images[b_idx : b_idx + batch_size]
            chunk_num = (b_idx // batch_size) + 1
            total_chunks = (len(images) + batch_size - 1) // batch_size

            msg_chunk = f"[{channel_name}] IA Vision: a analisar lote {chunk_num}/{total_chunks} ({len(chunk_imgs)} frames)..."
            logger.info(msg_chunk)
            LiveViewBridge.get_instance().emit_event(msg_chunk)

            # Detect date pills in this chunk
            detected_pills_info = []
            for idx_local, img in enumerate(chunk_imgs):
                pills = detector.detect_date_pills(img)
                for p in pills:
                    latest_known_date = p['date_str']
                    detected_pills_info.append(
                        f"- Frame {b_idx + idx_local + 1}: Pílula de data '{p['raw_text']}' -> {p['date_str']} em Y={p['y']}"
                    )

            if detected_pills_info:
                pill_ctx_str = (
                    "📌 PÍLULAS DE DATA CENTRAIS DO BONCHAT DETETADAS NESTE LOTE (GROUND TRUTH):\n"
                    + "\n".join(detected_pills_info)
                    + "\n👉 REGRA TEMPORAL: As pílulas de data centrais do BonChat marcam o início do dia.\n"
                    + "   - Mensagens abaixo de uma pílula pertencem à data dessa pílula.\n"
                    + "   - Mensagens acima da pílula pertencem ao dia anterior.\n"
                    + "   - NUNCA uses datas de prints/comprovativos partilhados por membros; usa APENAS a data da interface do BonChat."
                )
            else:
                pill_ctx_str = (
                    f"📌 PÍLULAS DE DATA: Nenhuma pílula visível neste lote de mensagens. "
                    f"Atribui as mensagens a {latest_known_date} salvo evidência clara de transição de dia."
                )

            # Check cache per chunk
            primary = chunk_imgs[0]
            small = primary.convert("L").resize((64, 64))
            chunk_hash = hashlib.sha256(small.tobytes()).hexdigest()

            cached = self._get_cached_hash_analysis(chunk_hash)
            if cached:
                json_m = re.search(r'```json\s*(\[.*?\])\s*```', cached, re.DOTALL)
                if json_m:
                    try: all_entries.extend(json.loads(json_m.group(1)))
                    except Exception: pass
                clean_text = re.sub(r'```json\s*\[.*?\]\s*```', '', cached, flags=re.DOTALL).strip()
                if clean_text and "sem novidades" not in clean_text.lower():
                    all_summaries.append(clean_text)
                continue

            now_month_str = datetime.datetime.now().strftime("%B de %Y")
            prompt = (
                f"Analisa as capturas do canal '{channel_name}' (Lote {chunk_num}/{total_chunks}).\n\n"
                f"{pill_ctx_str}\n\n"
                f"INSTRUÇÃO OPERACIONAL:\n"
                f"Filtra e IGNORA 100% de cumprimentos banais ('bom dia', 'olá', 'obrigado'), emojis soltos e conversas paralelas entre membros comuns.\n"
                f"Foca-te EXCLUSIVAMENTE em diretivas da chefia (Theodore, Jonathan, Márcia), comunicados do canal 08, horários de reuniões obrigatórias, chamadas de presença, novos sorteios e campanhas de bónus.\n"
                f"- Data: identifica a data de publicação com base nas pílulas de data centrais do BonChat (formato YYYY-MM-DD).\n"
                f"- Hora: extrai a hora exata (HH:MM) junto ao autor ou cabeçalho da mensagem (ex: '11:42', '19:30'). Se não estiver visível, coloca 'N/A'.\n\n"
                f"PRODUZ OBRIGATORIAMENTE um bloco ```json com as mensagens críticas extraídas:\n"
                f"```json\n"
                f"[\n"
                f"  {{\n"
                f"    \"date_str\": \"YYYY-MM-DD\",\n"
                f"    \"time_str\": \"HH:MM\",\n"
                f"    \"authority\": \"Nome do Autor / Remetente\",\n"
                f"    \"content_type\": \"Aviso / Reunião / Diretiva / Campanha / Sorteio\",\n"
                f"    \"verbatim_text\": \"Texto literal integral da mensagem...\",\n"
                f"    \"key_takeaways\": [\"Ponto chave 1\", \"Ponto chave 2\"]\n"
                f"  }}\n"
                f"]\n"
                f"```"
            )

            analysis = self._call_gemini_multimodal(prompt, chunk_imgs)
            if analysis:
                self._save_cached_hash_analysis(chunk_hash, analysis)
                json_m = re.search(r'```json\s*(\[.*?\])\s*```', analysis, re.DOTALL)
                if json_m:
                    try:
                        all_entries.extend(json.loads(json_m.group(1)))
                    except Exception:
                        pass
                clean_text = re.sub(r'```(?:json)?[\s\S]*?```', '', analysis).strip()
                if clean_text and "sem novidades" not in clean_text.lower():
                    all_summaries.append(clean_text)

            time.sleep(1.5)

        combined_summary = "\n\n".join(all_summaries).strip() if all_summaries else "Sem novidades operacionais críticas no turno."
        return combined_summary, all_entries

    def generate_full_briefing(
        self,
        channel_summaries: Dict[str, str],
        shift_label: str = "DIÁRIO",
        all_entries: Optional[List[Dict[str, Any]]] = None,
        scheduled_tasks: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        Gera um Resumo Executivo conciso, limpo e profissional para o Telegram,
        eliminando 100% de repetições, lixo/conversas banais e resquícios de código.
        """
        def sanitize_intel_text(t: str) -> str:
            if not t: return ""
            t = re.sub(r'```(?:json|python)?[\s\S]*?```', '', t)
            t = re.sub(r'\{[^{}]*"date_str"[^{}]*\}', '', t)
            t = re.sub(r'\[\s*\{[\s\S]*?\}\s*\]', '', t)
            t = re.sub(r'["\']?(?:date_str|time_str|verbatim_text|key_takeaways|content_type|authority)["\']?\s*:\s*["\']?[^,\n\}]*["\']?', '', t)
            t = re.sub(r'[\{\}\[\]]', '', t)
            t = re.sub(r'\n{3,}', '\n\n', t)
            return t.strip()

        today_str = datetime.datetime.now().strftime("%d/%m/%Y")
        lines = [
            f"🚲 *RESUMO EXECUTIVO TIMI* | {today_str} ({shift_label})",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ]

        # A. Atividades Agendadas Dinamicamente
        if scheduled_tasks:
            lines.append("\n📅 *ATIVIDADES & REUNIÕES AGENDADAS NO SISTEMA:*")
            for task in scheduled_tasks:
                lines.append(f"• ⏰ *{task['meeting_time']}* — {task['reason']}")
                lines.append(f"  └─ 🤖 *Gatilho Automático:* O `TIMI_GUARDIAN` arranca 15 min antes (Tarefa: `{task['task_name']}`).")

        # B. Extrair e desduplicar avisos e diretivas
        seen_takeaways = set()
        meetings = []
        authorities_notices = []
        campaigns_bonuses = []
        vouchers_codes = []

        if all_entries:
            for e in all_entries:
                c_type = (e.get("content_type") or "").lower()
                text = (e.get("verbatim_text") or " ".join(e.get("key_takeaways", []))).strip()
                auth = (e.get("authority") or "Oficial").strip()

                t_lower = text.lower()
                if any(k in t_lower for k in ("bom dia", "boa tarde", "boa noite pessoal", "obrigado", "consegui", "parabéns")):
                    if not any(k in t_lower for k in ("reunião", "reuniao", "sorteio", "código", "codigo", "bónus", "bonus", "usdt")):
                        continue

                norm_key = re.sub(r'\W+', '', text[:50].lower())
                if norm_key in seen_takeaways:
                    continue
                seen_takeaways.add(norm_key)

                if any(k in t_lower or k in c_type for k in ("reunião", "reuniao", "presença", "presenca", "live", "encontro")):
                    time_info = f" ({e.get('time_str')})" if e.get('time_str') and e.get('time_str') != 'N/A' else ""
                    meetings.append(f"• *[{auth}]{time_info}:* {text[:140]}...")
                elif any(k in t_lower or k in c_type for k in ("bónus", "bonus", "campanha", "usdt", "meta", "comissão")):
                    campaigns_bonuses.append(f"• *[{auth}]:* {text[:140]}...")
                elif any(k in t_lower or k in c_type for k in ("chave", "voucher", "código", "codigo", "sorteio")):
                    vouchers_codes.append(f"• *[{auth}]:* {text[:140]}...")
                elif auth in ("Theodore", "Jonathan", "Johnathan", "Marcia", "Márcia", "TIMI") or "diretiva" in c_type or "aviso" in c_type:
                    authorities_notices.append(f"• *[{auth}]:* {text[:140]}...")

        has_content = False

        if meetings and not scheduled_tasks:
            lines.append("\n📢 *REUNIÕES & EVENTOS:*")
            for m in meetings[:3]:
                lines.append(m)
            has_content = True

        if authorities_notices:
            lines.append("\n👑 *DIRETIVAS DA CHEFIA (Theodore / Jonathan):*")
            for an in authorities_notices[:4]:
                lines.append(an)
            has_content = True

        if campaigns_bonuses:
            lines.append("\n💰 *BÓNUS & CAMPANHAS ATIVAS:*")
            for cb in campaigns_bonuses[:3]:
                lines.append(cb)
            has_content = True

        if vouchers_codes:
            lines.append("\n⚡ *VOUCHERS & CHAVES DINÂMICAS:*")
            for vc in vouchers_codes[:2]:
                lines.append(vc)
            has_content = True

        if not has_content and not scheduled_tasks:
            cleaned_summaries = []
            for ch, s in channel_summaries.items():
                clean_s = sanitize_intel_text(s)
                if clean_s and "sem novidades" not in clean_s.lower() and len(clean_s) > 20:
                    cleaned_summaries.append(f"• *{ch}:* {clean_s[:140]}...")
            if cleaned_summaries:
                lines.append("\n📋 *DESTAQUES DOS CANAIS:*")
                lines.extend(cleaned_summaries[:4])
            else:
                lines.append("\n✅ *Sem novos comunicados críticos da chefia neste turno.*")
                lines.append("Operação regular a decorrer nas 3 contas TIMI.")

        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("🛡️ *Sistema Operacional 3/3 Contas Ativas*")

        return sanitize_intel_text("\n".join(lines))
