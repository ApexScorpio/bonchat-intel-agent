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

SYSTEM_PROMPT = """Tu és um Analista Executivo de Inteligência ultra-objetivo para a operação TIMI.
A tua única função é extrair NOVIDADES ACIONÁVEIS das capturas de ecrã do BonChat, eliminando 100% do ruído.

FILTRAGEM RIGOROSA — INCLUIR APENAS O QUE INTERESSA:
1. 📅 REUNIÕES, LIVES & CHAMADAS OBRIGATÓRIAS:
   - Data, hora exata, grupo (ex: TIMI--NO.08, TIMI Mall, TIMI-68) e se há chamada de presença ou código da sorte.
2. 💰 NOVAS CAMPANHAS, BÓNUS & RECOMPENSAS:
   - Valores exatos em USDT, condições, vagas e datas limite (ignorar campanhas antigas já repetidas).
3. ⚠️ ALTERAÇÕES REAIS DE REGRAS OU AVISOS URGENTES DA CHEFIA (Theodore, Jonathan, Márcia, TIMI oficial):
   - Mudanças de horários, manutenção do site, novas regras de levantamento/ativação, alertas de segurança.

LIXO A IGNORAR 100% (PROIBIDO INCLUIR NO RESUMO):
- Cumprimentos, saudações, "presente", "1", emojis, agradecimentos, "parabéns ao parceiro X".
- Capturas de depósitos, levantamentos ou transações individuais de membros ("depositei X USDC", "levantamento TIMI Mall").
- Discursos motivacionais, reflexões genéricas ("capacidade de execução", "sucesso", "foco") sem nenhuma ação prática nova.
- Vouchers/códigos de viagem rotineiros das 11:00 e 19:00 (já são tratados automaticamente pelo Maestro).
- Repetições do mesmo aviso noutros grupos.

IDENTIFICAÇÃO DA DATA:
- Usa apenas as pílulas de data nativas do BonChat ("Hoje", "Ontem", "11/20"). Nunca confundas datas dentro de prints de transações.

FORMATO DE SAÍDA:
- Máximo 3 a 5 bullets curtos (1 linha por facto concreto, zero enchimento).
- Bloco JSON no fim apenas com entradas verdadeiramente acionáveis.
- Se não houver NADA concreto que cumpra os critérios 1, 2 ou 3, responde EXATAMENTE: "Sem novidades operacionais críticas no turno."
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
                f"Filtra e IGNORA 100% de:\n"
                f"- Cumprimentos banais ('bom dia', 'olá', 'obrigado'), emojis soltos e conversas entre membros comuns;\n"
                f"- Aberturas de lojas/mercearias/supermercados/drogarias no Brasil ('Região: Brasil', links Google Maps) e endereços de centros de experiência;\n"
                f"- Convites pessoais de membros ('X convida cordialmente você...') e textos puramente motivacionais sem ação prática.\n"
                f"Foca-te EXCLUSIVAMENTE em informação acionável para Portugal: horários e grupos de reuniões/lives futuras, chamadas de presença, novos sorteios/códigos, campanhas de bónus com valores e prazos, alterações de regras/levantamentos/taxas e manutenção do site.\n"
                f"- Data: identifica a data de publicação com base nas pílulas de data centrais do BonChat (formato YYYY-MM-DD).\n"
                f"- Hora: extrai a hora exata (HH:MM) junto ao autor ou cabeçalho da mensagem (ex: '11:42', '19:30'). Se não estiver visível, coloca 'N/A'.\n"
                f"- Em 'key_takeaways', escreve 1 a 3 frases curtas, completas e diretas em PT-PT com o essencial (datas, horas, grupos, valores, prazos) — nunca frases cortadas.\n\n"
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

        def format_clean_summary(entry: Dict[str, Any], max_len: int = 420) -> str:
            """Usa os key_takeaways (completos e objetivos) ou o texto limpo sem cortar a meio de palavras."""
            takeaways = [
                re.sub(r'\s+', ' ', str(k).strip()).rstrip('.')
                for k in (entry.get("key_takeaways") or [])
                if str(k).strip()
            ]
            if takeaways:
                body = ". ".join(takeaways[:3]) + "."
            else:
                body = re.sub(r'https?://\S+', '', str(entry.get("verbatim_text") or "")).strip()
                body = re.sub(r'\s+', ' ', body)
            if len(body) <= max_len:
                return body
            # Cortar na última frase completa dentro do limite, ou na última palavra inteira
            cut = body[:max_len]
            last_dot = max(cut.rfind('. '), cut.rfind('! '), cut.rfind('? '))
            if last_dot >= int(max_len * 0.55):
                return cut[:last_dot + 1].strip()
            last_space = cut.rfind(' ')
            return (cut[:last_space].rstrip(' ,;:-') + "…") if last_space > 0 else (cut + "…")

        # B. Extrair, filtrar ruído irrelevante e desduplicar avisos acionáveis
        seen_takeaways = set()
        meetings = []
        authorities_notices = []
        campaigns_bonuses = []
        vouchers_codes = []

        if all_entries:
            for e in all_entries:
                c_type = (e.get("content_type") or "").lower()
                raw_verbatim = (e.get("verbatim_text") or "").strip()
                takeaways_joined = " ".join(str(k) for k in (e.get("key_takeaways") or []))
                text_for_filter = f"{raw_verbatim} {takeaways_joined}".strip()
                auth = (e.get("authority") or "Oficial").strip()
                channel = (e.get("channel") or "").strip()

                t_lower = text_for_filter.lower()
                # 1. Bloquear ruído sem utilidade prática (lojas do Brasil, spam de convites, conversa banal)
                hard_irrelevant = (
                    "região: brasil", "regiao: brasil", "mercado brasileiro",
                    "mercearia n.", "supermercado n.", "drogaria ", "maps.app.goo.gl",
                    "convida cordialmente", "quim barreiros",
                    "código de viagem", "codigo de viagem", "pedale com um clique",
                    "centro de experiência", "centro de experiencia", "carnaxide",
                    "já se avisaram uns aos outros", "ja se avisaram uns aos outros",
                    "resumo da reunião de hoje", "resumo da reuniao de hoje",
                )
                if any(k in t_lower for k in hard_irrelevant):
                    continue

                noise_terms = (
                    "bom dia", "boa tarde", "boa noite", "obrigado", "obrigada", "consegui",
                    "parabéns", "parabens", "depositou", "depositei", "chegou na conta",
                    "capacidade de execução", "capacidade de execucao", "presente!"
                )
                important_terms = (
                    "reunião", "reuniao", "sorteio", "bónus", "bonus", "campanha",
                    "manutenção", "manutencao", "regra", "prazo", "live", "taxa", "levantamento"
                )
                if any(k in t_lower for k in noise_terms) and not any(k in t_lower for k in important_terms):
                    continue

                # 2. Desduplicação robusta por conjunto de palavras significativas
                sig_words = sorted({w for w in re.findall(r'[a-zà-ú0-9]{4,}', t_lower)})
                norm_key = "|".join(sig_words[:10]) if sig_words else re.sub(r'\W+', '', t_lower[:50])
                if norm_key in seen_takeaways:
                    continue
                seen_takeaways.add(norm_key)

                summary_str = format_clean_summary(e, max_len=420)
                if not summary_str or len(summary_str) < 12:
                    continue
                ch_tag = f" [{channel}]" if channel else ""
                time_info = f" ({e.get('time_str')})" if e.get('time_str') and e.get('time_str') != 'N/A' else ""

                if any(k in t_lower or k in c_type for k in ("reunião", "reuniao", "presença", "presenca", "live", "encontro")):
                    meetings.append(f"• *{auth}{ch_tag}{time_info}:* {summary_str}")
                elif any(k in t_lower or k in c_type for k in ("bónus", "bonus", "campanha", "usdt", "meta", "comissão", "sorteio", "prémio", "premio")):
                    campaigns_bonuses.append(f"• *{auth}{ch_tag}:* {summary_str}")
                elif any(k in t_lower or k in c_type for k in ("manutenção", "manutencao", "regra", "taxa", "levantamento", "penalização", "penalizacao", "aviso urgente", "diretiva")):
                    authorities_notices.append(f"• *{auth}{ch_tag}:* {summary_str}")
                elif auth in ("Theodore", "Jonathan", "Johnathan", "Marcia", "Márcia") and any(k in t_lower for k in ("obrigatóri", "obrigatori", "altera", "novo", "nova", "atenção", "atencao", "importante")):
                    authorities_notices.append(f"• *{auth}{ch_tag}:* {summary_str}")

        has_content = False

        if meetings and not scheduled_tasks:
            lines.append("\n📢 *REUNIÕES & EVENTOS:*")
            for m in meetings[:4]:
                lines.append(m)
            has_content = True

        if authorities_notices:
            lines.append("\n⚠️ *REGRAS, AVISOS & DIRETIVAS CRÍTICAS:*")
            for an in authorities_notices[:4]:
                lines.append(an)
            has_content = True

        if campaigns_bonuses:
            lines.append("\n💰 *BÓNUS, CAMPANHAS & SORTEIOS:*")
            for cb in campaigns_bonuses[:4]:
                lines.append(cb)
            has_content = True

        if vouchers_codes:
            lines.append("\n⚡ *VOUCHERS & CHAVES DINÂMICAS:*")
            for vc in vouchers_codes[:2]:
                lines.append(vc)
            has_content = True

        if not has_content and not scheduled_tasks:
            lines.append("\n✅ *Sem novidades críticas ou acionáveis neste turno.*")
            lines.append("Operação regular a decorrer nas 3 contas TIMI.")

        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("🛡️ *Sistema Operacional 3/3 Contas Ativas*")

        return sanitize_intel_text("\n".join(lines))
