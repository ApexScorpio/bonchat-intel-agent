import os
import sys
import json
import hashlib
import logging
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from PIL import Image

logger = logging.getLogger("KnowledgeBase")

BASE_DIR = Path(__file__).resolve().parent.parent
KB_DIR = BASE_DIR / "knowledge_base"
ASSETS_DIR = KB_DIR / "assets"
ENTRIES_FILE = KB_DIR / "intel_entries.json"
MARKDOWN_FILE = KB_DIR / "AUTHORITY_INTEL.md"

class KnowledgeBase:
    def __init__(self):
        KB_DIR.mkdir(parents=True, exist_ok=True)
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        self.entries: List[Dict[str, Any]] = self._load_entries()

    def _load_entries(self) -> List[Dict[str, Any]]:
        if ENTRIES_FILE.exists():
            try:
                with open(ENTRIES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading {ENTRIES_FILE}: {e}")
        return []

    def _save_entries(self):
        with open(ENTRIES_FILE, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=2)

    @staticmethod
    def compute_image_hash(img: Image.Image) -> str:
        """Computes a SHA256 hash of resized image pixels for fast deduplication."""
        small = img.convert("L").resize((64, 64))
        return hashlib.sha256(small.tobytes()).hexdigest()

    def is_known_hash(self, sha256_hash: str) -> bool:
        """Checks if an image has already been recorded in the knowledge base."""
        for e in self.entries:
            if e.get("image_sha256") == sha256_hash:
                return True
        return False

    def add_entry(
        self,
        date_str: str,
        time_str: str,
        channel: str,
        authority: str,
        content_type: str,
        verbatim_text: str,
        image: Optional[Image.Image] = None,
        key_takeaways: Optional[List[str]] = None,
        asset_filename: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Appends a new official authority communication to the knowledge base without duplicates.
        """
        img_hash = ""
        saved_rel_path = ""

        if image:
            img_hash = self.compute_image_hash(image)
            if self.is_known_hash(img_hash):
                logger.info(f"Duplicate image hash detected ({img_hash[:8]}). Skipping duplicate entry.")
                return None

            if not asset_filename:
                clean_auth = "".join(c for c in authority if c.isalnum())
                clean_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                asset_filename = f"{clean_auth}_{clean_time}.jpg"

            dest_path = ASSETS_DIR / asset_filename
            image.convert("RGB").save(str(dest_path), "JPEG", quality=90)
            saved_rel_path = f"assets/{asset_filename}"

        today_stamp = datetime.datetime.now().strftime("%Y%m%d")
        new_id = f"INTEL-{today_stamp}-{len(self.entries) + 1:03d}"

        entry = {
            "id": new_id,
            "timestamp_published": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "date_str": date_str,
            "time_str": time_str,
            "channel": channel,
            "authority": authority,
            "content_type": content_type,
            "image_asset": saved_rel_path,
            "image_sha256": img_hash,
            "verbatim_text": verbatim_text.strip(),
            "key_takeaways": key_takeaways or []
        }

        # Insert at the beginning (reverse chronological)
        self.entries.insert(0, entry)
        self._save_entries()
        self.render_markdown()
        logger.info(f"Recorded new knowledge base entry: {new_id} ({authority} in {channel})")
        return entry

    def search(self, query: str = "", authority: str = "", channel: str = "") -> List[Dict[str, Any]]:
        """
        Performs 100% free local search across all recorded intel entries without calling AI APIs.
        """
        q = query.lower().strip()
        auth = authority.lower().strip()
        ch = channel.lower().strip()

        results = []
        for e in self.entries:
            if auth and auth not in e.get("authority", "").lower():
                continue
            if ch and ch not in e.get("channel", "").lower():
                continue
            if q:
                v_text = e.get("verbatim_text", "").lower()
                c_type = e.get("content_type", "").lower()
                if q not in v_text and q not in c_type:
                    continue
            results.append(e)
        return results

    def render_markdown(self):
        """Regenerates AUTHORITY_INTEL.md from structured entries."""
        lines = [
            "# 🏛️ Base de Conhecimento Operacional TIMI — Comunicações Oficiais\n",
            "> **Repositório Oficial:** [ApexScorpio/bonchat-intel-agent](https://github.com/ApexScorpio/bonchat-intel-agent)  ",
            "> **Finalidade:** Registo histórico permanente, 100% inalterado e auditável de todas as mensagens, cartazes, diretivas e campanhas partilhadas pelas autoridades oficiais da TIMI (**Theodore**, **Jonathan / TIMI-Jonathan**, **Márcia** e canal oficial **TIMI--NO.08**).  ",
            "> **Uso:** Consulta interna para agentes em campo, pesquisa rápida de regras e histórico de incentivos sem necessidade de gastar quota de IA.\n",
            "---\n",
            "## 📑 Índice Rápido de Comunicações\n",
            "| ID | Data / Hora | Grupo / Canal | Autoridade | Assunto Principal | Anexo Visual |",
            "|---|---|---|---|---|:---:|"
        ]

        for e in self.entries:
            e_id = e.get("id", "N/A")
            dt = f"{e.get('date_str', '')} {e.get('time_str', '')}".strip()
            ch = e.get("channel", "")
            auth = e.get("authority", "")
            ctype = e.get("content_type", "")
            lines.append(f"| `{e_id}` | {dt} | `{ch}` | {auth} | {ctype} | [Ver Anexo](#{e_id.lower()}) |")

        lines.append("\n---\n\n## 📌 Registos Integrais (100% Inalterados)\n")

        for e in self.entries:
            e_id = e.get("id", "N/A")
            lines.append(f"---\n\n### <a id=\"{e_id.lower()}\"></a>[{e_id}] — {e.get('content_type', 'Aviso')}\n")
            lines.append(f"- **📅 Data de Publicação:** {e.get('date_str', 'N/A')}")
            lines.append(f"- **⏰ Hora:** {e.get('time_str', 'N/A')}")
            lines.append(f"- **👥 Grupo / Canal:** `{e.get('channel', 'N/A')}`")
            lines.append(f"- **👑 Autoridade / Emissor:** `{e.get('authority', 'N/A')}`")
            lines.append(f"- **🏷️ Categoria:** {e.get('content_type', 'N/A')}")

            if e.get("image_asset"):
                lines.append(f"- **🖼️ Imagem Original Capturada:**\n\n![{e.get('content_type', 'Asset')}]({e.get('image_asset')})\n")

            lines.append("#### 📝 Conteúdo Literal 100% Inalterado:\n```text")
            lines.append(e.get("verbatim_text", "").strip())
            lines.append("```\n")

            takeaways = e.get("key_takeaways", [])
            if takeaways:
                lines.append("#### 💡 Pontos-Chave:")
                for t in takeaways:
                    lines.append(f"- {t}")
                lines.append("")

        MARKDOWN_FILE.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Updated {MARKDOWN_FILE} successfully.")
