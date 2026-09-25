import sys
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from src.knowledge_base import KnowledgeBase

def main():
    parser = argparse.ArgumentParser(description="TIMI Authority Knowledge Base - Instant Local Search (Zero Quota)")
    parser.add_argument("query", nargs="?", default="", help="Keyword to search in messages, flyers or rules")
    parser.add_argument("--authority", "-a", type=str, default="", help="Filter by authority (Theodore, Jonathan, Marcia, etc.)")
    parser.add_argument("--channel", "-c", type=str, default="", help="Filter by channel/group name")
    parser.add_argument("--all", action="store_true", help="List all recorded communications")

    args = parser.parse_args()

    kb = KnowledgeBase()
    results = kb.search(query=args.query, authority=args.authority, channel=args.channel)

    if not results:
        print(f"\n🔍 Nenhuma comunicação oficial encontrada para: query='{args.query}', autoridade='{args.authority}', canal='{args.channel}'\n")
        return

    print(f"\n🏛️ Encontradas {len(results)} comunicação(ões) oficial(is) na Base de Conhecimento:\n" + "="*70)
    for r in results:
        print(f"[{r['id']}] {r['content_type']}")
        print(f"📅 Data/Hora: {r['date_str']} | {r['time_str']}")
        print(f"👥 Grupo: {r['channel']} | 👑 Autoridade: {r['authority']}")
        if r.get("image_asset"):
            print(f"🖼️ Imagem: knowledge_base/{r['image_asset']}")
        print("\n📝 Mensagem 100% Inalterada:")
        print(r['verbatim_text'])
        takeaways = r.get("key_takeaways", [])
        if takeaways:
            print("\n💡 Pontos-Chave:")
            for t in takeaways:
                print(f"  • {t}")
        print("="*70)

if __name__ == "__main__":
    main()
