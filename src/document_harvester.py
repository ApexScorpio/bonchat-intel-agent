import os
import sys
import re
import shutil
import hashlib
import logging
import datetime
from pathlib import Path
from typing import List, Dict, Any
import requests

logger = logging.getLogger("DocumentHarvester")

BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "knowledge_base" / "documents"
PPT_DIR = DOCS_DIR / "ppt_slides"
DOCS_INDEX_FILE = BASE_DIR / "knowledge_base" / "DOCUMENTS_INDEX.md"

class DocumentHarvester:
    def __init__(self):
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        PPT_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def sha256_file(filepath: Path) -> str:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()

    FORBIDDEN_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v", ".3gp"}
    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".png", ".jpg", ".jpeg", ".webp"}

    def harvest_local_downloads(self) -> List[Dict[str, Any]]:
        """Harvests known TIMI PDF documents from Downloads folder, strictly rejecting videos."""
        harvested = []
        downloads_dir = Path(r"S:\Users\lopes\Downloads")
        
        target_patterns = [
            ("TIMI ..pdf", "TIMI_Apresentacao_Oficial.pdf", "Apresentação Oficial da Empresa e Modelo de Mobilidade (enviada pelo Theodore)"),
            ("TIMI.PDF", "TIMI_Manual_Operacional_V1.pdf", "Manual e Apresentação Operacional TIMI"),
            ("Guia Levantamento TIMI.pdf", "Guia_Levantamento_TIMI.pdf", "Guia Oficial de Levantamentos e Regras de Liquidação"),
            ("guia_completo_registo_levantamentos_v7_timi_atualizado.pdf", "Guia_Completo_Registo_Levantamentos_v7.pdf", "Guia Completo de Registo de Levantamentos TIMI Atualizado"),
            ("guia_completo_CORRIGIDO_fluxos_deposito_v2.pdf", "Guia_Fluxos_Deposito_v2.pdf", "Guia Oficial Corrigido de Fluxos de Depósito"),
            ("guia_completo_FINAL_com_passos_timi_7_a_10.pdf", "Guia_Passos_7_a_10.pdf", "Guia Completo com Passos TIMI 7 a 10")
        ]

        for src_name, dest_name, desc in target_patterns:
            src_file = downloads_dir / src_name
            # Strict safety check: Never harvest videos
            if src_file.suffix.lower() in self.FORBIDDEN_EXTENSIONS:
                logger.warning(f"Skipping video file per policy: {src_file.name}")
                continue

            if src_file.exists():
                dest_file = DOCS_DIR / dest_name
                if not dest_file.exists() or src_file.stat().st_size != dest_file.stat().st_size:
                    shutil.copy2(src_file, dest_file)
                    logger.info(f"Harvested document: {dest_name} ({dest_file.stat().st_size} bytes)")
                
                size_mb = dest_file.stat().st_size / (1024 * 1024)
                harvested.append({
                    "filename": dest_name,
                    "rel_path": f"documents/{dest_name}",
                    "size_mb": round(size_mb, 2),
                    "sha256": self.sha256_file(dest_file),
                    "description": desc,
                    "source": "BonChat Direct (Theodore / Equipa)"
                })
        return harvested

    def harvest_online_ppt_slides(self) -> List[Dict[str, Any]]:
        """Downloads all PPT presentation slides from https://2794109.top/"""
        harvested = []
        url = "https://2794109.top/"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                img_sources = re.findall(r'src=["\']([^"\']+)["\']', r.text)
                for src in img_sources:
                    clean_src = src.split("?")[0]
                    slide_name = os.path.basename(clean_src)
                    img_url = f"https://2794109.top/{clean_src}" if not clean_src.startswith("http") else clean_src
                    dest_file = PPT_DIR / slide_name
                    
                    if not dest_file.exists():
                        img_resp = requests.get(img_url, timeout=15)
                        if img_resp.status_code == 200:
                            dest_file.write_bytes(img_resp.content)
                            logger.info(f"Downloaded PPT slide: {slide_name}")
                    
                    if dest_file.exists():
                        harvested.append({
                            "filename": f"ppt_slides/{slide_name}",
                            "rel_path": f"documents/ppt_slides/{slide_name}",
                            "size_kb": round(dest_file.stat().st_size / 1024, 1),
                            "sha256": self.sha256_file(dest_file),
                            "description": f"Slide oficial de formação PPT ({slide_name})",
                            "source": url
                        })
        except Exception as e:
            logger.warning(f"Could not harvest online PPT slides: {e}")
        return harvested

    def generate_index_markdown(self, docs: List[Dict[str, Any]], slides: List[Dict[str, Any]]):
        """Generates comprehensive DOCUMENTS_INDEX.md documentation."""
        lines = [
            "# 📁 Acervo de Documentos e Materiais Oficiais TIMI\n",
            "> **Repositório:** [ApexScorpio/bonchat-intel-agent](https://github.com/ApexScorpio/bonchat-intel-agent)  ",
            f"> **Última Atualização:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
            "> **Finalidade:** Todos os ficheiros PDF, guias operacionais e diapositivos partilhados pelas chefias oficiais descarregados e arquivados localmente.\n",
            "---\n",
            "## 📄 Documentos Principais (PDF)\n",
            "| Ficheiro | Descrição | Tamanho | SHA256 Checksum | Origem |",
            "|---|---|:---:|---|:---:|"
        ]

        for d in docs:
            lines.append(f"| [{d['filename']}]({d['rel_path']}) | {d['description']} | {d['size_mb']} MB | `{d['sha256'][:16]}...` | {d['source']} |")

        lines.append("\n---\n\n## 🖼️ Slides da Apresentação Oficial (PPT Online — 2794109.top)\n")
        lines.append("| Slide | Ficheiro | Tamanho | Checksum |",)
        lines.append("|---|---|:---:|---|")
        for s in slides:
            lines.append(f"| [{s['filename']}]({s['rel_path']}) | `{s['filename']}` | {s['size_kb']} KB | `{s['sha256'][:12]}...` |")

        lines.append("\n---\n\n### 🔗 Hiperligações Oficiais de Apoio Mencionadas pelo Theodore:\n")
        lines.append("- **Portal Oficial da Empresa:** [https://timiexhibit.com](https://timiexhibit.com)")
        lines.append("- **Voz da TIMI:** [http://timiuss.com](http://timiuss.com)")
        lines.append("- **Lojas Parceiras e Notícias:** [https://timiexhibit.com/#/news/newss](https://timiexhibit.com/#/news/newss)")
        lines.append("- **Apresentação PPT Online:** [https://2794109.top/](https://2794109.top/)")

        DOCS_INDEX_FILE.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Updated {DOCS_INDEX_FILE} successfully.")

    def run_harvest(self) -> Dict[str, Any]:
        """Runs complete document harvesting pipeline."""
        logger.info("Starting autonomous document harvesting...")
        docs = self.harvest_local_downloads()
        slides = self.harvest_online_ppt_slides()
        self.generate_index_markdown(docs, slides)
        logger.info(f"Harvest complete: {len(docs)} PDF documents, {len(slides)} PPT slides cataloged.")
        return {"documents": docs, "slides": slides}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    harvester = DocumentHarvester()
    harvester.run_harvest()
