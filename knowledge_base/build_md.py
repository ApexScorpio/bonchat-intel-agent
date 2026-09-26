import json
from pathlib import Path

kb_dir = Path(__file__).resolve().parent
entries_file = kb_dir / "intel_entries.json"
md_file = kb_dir / "AUTHORITY_INTEL.md"

with open(entries_file, "r", encoding="utf-8") as f:
    entries = json.load(f)

md_lines = [
    "# 🏛️ Base de Conhecimento Operacional TIMI — Comunicações Oficiais",
    "",
    "> **Repositório Oficial:** [ApexScorpio/bonchat-intel-agent](https://github.com/ApexScorpio/bonchat-intel-agent)  ",
    "> **Finalidade:** Registo histórico permanente, 100% inalterado e auditável de todas as mensagens, cartazes, diretivas e campanhas partilhadas pelas autoridades oficiais da TIMI (**Theodore**, **Jonathan / TIMI-Jonathan**, **Márcia** e canal oficial **TIMI--NO.08**).  ",
    "> **Uso:** Consulta interna para agentes em campo, pesquisa rápida de regras e histórico de incentivos sem necessidade de gastar quota de IA.",
    "",
    "---",
    "",
    "## 📑 Índice Rápido de Comunicações Oficiais",
    "",
    "| ID | Data / Hora | Grupo / Canal | Autoridade | Assunto Principal | Anexo Visual |",
    "|---|---|---|---|---|:---:|"
]

for e in sorted(entries, key=lambda x: x["timestamp_published"], reverse=True):
    entry_id = e["id"]
    anchor = entry_id.lower()
    anexo_md = f"[Ver Anexo](#{anchor})" if e.get("image_asset") else "—"
    md_lines.append(f"| `{entry_id}` | {e['date_str']} ({e['time_str']}) | `{e['channel']}` | {e['authority']} | {e['content_type']} | {anexo_md} |")

md_lines.extend([
    "",
    "---",
    "",
    "## 📌 Registos Integrais (100% Inalterados)",
    ""
])

for e in sorted(entries, key=lambda x: x["timestamp_published"], reverse=True):
    anchor = e["id"].lower()
    md_lines.extend([
        "---",
        "",
        f"### <a id=\"{anchor}\"></a>[{e['id']}] — {e['content_type']}",
        "",
        f"- **📅 Data de Publicação:** {e['date_str']}",
        f"- **⏰ Hora / Período:** {e['time_str']}",
        f"- **👥 Grupo / Canal:** `{e['channel']}`",
        f"- **👑 Autoridade / Emissor:** `{e['authority']}`",
        f"- **🏷️ Categoria:** {e['content_type']}"
    ])
    
    if e.get("image_asset"):
        md_lines.extend([
            "- **🖼️ Imagem Original Capturada:**",
            "",
            f"![{e['content_type']}]({e['image_asset']})",
            ""
        ])
    
    md_lines.extend([
        "#### 📝 Conteúdo Literal 100% Inalterado:",
        "```text",
        e["verbatim_text"],
        "```",
        "",
        "#### 💡 Pontos-Chave Operacionais:",
        ""
    ])
    for pt in e["key_takeaways"]:
        md_lines.append(f"- {pt}")
    md_lines.append("")

md_file.write_text("\n".join(md_lines), encoding="utf-8")
print(f"Updated AUTHORITY_INTEL.md successfully with {len(entries)} verified communications!")
