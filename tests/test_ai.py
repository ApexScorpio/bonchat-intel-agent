import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from src.config import load_config
from src.ai_intelligence import AIIntelligence

def test_ai_pipeline():
    print("=== Testing AI Intelligence Pipeline (Noise Filtering & Extraction) ===")
    cfg = load_config()
    
    ai = AIIntelligence(
        gemini_keys=cfg.get("gemini_keys", []),
        groq_key=cfg.get("groq_key")
    )

    sample_data = {
        "timi 08": """
[09:15] Rui: bom dia pessoal
[09:16] Carlos: bom dia bom trabalho
[09:30] Theodore: ATENÇÃO EQUIPA: Hoje às 19:00 há reunião obrigatória de alinhamento sobre as novas regras de ativação das bicicletas.
[10:00] Maria: Ok entendido!
[10:05] João: 👍👍
[10:30] Johnathan: Campanha do fim de semana ativa: cada agente com mais de 3 ativações bem sucedidas recebe bónus extra de 20€.
[11:00] Pedro: onde vejo o saldo?
[11:02] Marcia: O site estará em manutenção rápida entre as 14:00 e 14:15. Não tentem submeter vouchers nesse intervalo.
""",
        "equipa de agentes de elite de timi": """
[10:15] Lucas: Olá malta
[10:20] Theodore: Pessoal de elite, novo incentivo para a zona de Portimão e Faro hoje. Confirmem quem está ativo no turno da noite.
"""
    }

    summary = ai.summarize_channels(sample_data, shift_label="TESTE")
    print("\n--- RESULTADO GERADO PELA IA ---")
    print(summary)
    print("--------------------------------\n")
    assert "Theodore" in summary or "THEODORE" in summary or "bónus" in summary.lower() or "manutenção" in summary.lower()
    print("✅ Teste de IA passou com sucesso!")

if __name__ == "__main__":
    test_ai_pipeline()
