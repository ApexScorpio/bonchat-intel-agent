# 🛰️ BonChat Operational Intelligence & Daily Briefing Agent

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![AI](https://img.shields.io/badge/AI-Gemini%202.5%20%7C%20Groq-purple.svg)]()
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)]()

Agente autónomo de extração, análise e resumo diário de comunicações operacionais do **BonChat**. Desenvolvido para agentes TIMI com foco exclusivo no que é crítico e acionável em campo, eliminando 100% do ruído e conversas triviais.

---

## 🎯 Objetivo e Funcionalidades

1. **Navegação & Leitura Automatizada do BonChat**:
   - Deteta a janela do BonChat ativa ou em desktop isolado (`WinSta0\TIMI_GHOST`) sem interferir no rato ou ecrã do utilizador.
   - Navega e lê automaticamente os 7 canais operacionais:
     * `timi 08` (Avisos prioritários)
     * `timi 64`
     * `grupo de agentes 20`
     * `equipa de agentes de elite de timi`
     * `grupo dde agentes portimao`
     * `timi new`
     * `Grupo de reunioes`
   - Realiza scroll automático para recuperar o histórico de mensagens do turno/dia.

2. **Filtro Rigoroso & Foco em Contactos-Chave**:
   - Monitoriza prioritariamente mensagens de:
     * 👤 **Theodore**
     * 👤 **Johnathan**
     * 👤 **Márcia**
     * 📢 **Canal TIMI 08** (todos os comunicados têm máxima prioridade)
   - Elimina cumprimentos banais ("bom dia", "olá", etc.), emojis soltos, memes e conversas paralelas.

3. **Inteligência Artificial (100% Gratuita com Máxima Quota)**:
   - **Motor Primário**: **Google Gemini 2.5 Flash** com rotação automática de múltiplas chaves de API para garantir disponibilidade contínua sem custos.
   - **Motor Secundário (Fallback)**: **Groq Llama 3 / Qwen** para redundância ultra-rápida.
   - Categorização automática em:
     * 📢 **Avisos & Regras Operacionais**
     * 🎯 **Campanhas, Bónus & Metas**
     * ⚙️ **Novidades de Funcionamento**
     * ⚠️ **Alertas & Incidentes Técnicos**

4. **Notificação Executiva no Telegram**:
   - Envio de briefing formatado diretamente para o Telegram do agente.
   - Agendamento automático a cada fim de turno: **13:30** e **21:30**.
   - Possibilidade de execução manual imediata a qualquer momento.

---

## 🏗️ Estrutura do Projeto

```
bonchat-intel-agent/
├── .gitignore               # Proteção estrita de credenciais e ficheiros locais
├── README.md                # Documentação completa
├── requirements.txt         # Dependências Python
├── config.example.json      # Modelo de configuração (sem segredos)
├── run_intel_agent.bat      # Lançador rápido 1-clique (Manual)
├── run_scheduled.bat        # Lançador de serviço agendado (13:30 e 21:30)
├── src/
│   ├── __init__.py
│   ├── config.py            # Carregamento seguro de configurações
│   ├── desktop_isolation.py # Gestão de sessões Windows e desktop TIMI_GHOST
│   ├── bonchat_reader.py    # Leitor OCR, navegação de canais e scroll
│   ├── ai_intelligence.py   # Rotação Gemini + Groq e filtragem de ruído
│   ├── telegram_bot.py      # Despacho de mensagens Telegram com chunking
│   ├── scheduler.py         # Agendador de turnos (13:30 / 21:30)
│   └── main.py              # CLI principal
└── tests/
    └── test_ai.py           # Teste de validação da pipeline de IA
```

---

## 🚀 Instalação e Configuração

### 1. Instalar Dependências
```bash
pip install -r requirements.txt
```

### 2. Configurar Chaves e Credenciais
Copia o ficheiro de exemplo para `config.local.json` (este ficheiro está no `.gitignore` e nunca é enviado para o GitHub):
```json
{
  "telegram_bot_token": "O_TEU_BOT_TOKEN",
  "telegram_chat_id": "O_TEU_CHAT_ID",
  "gemini_keys": [
    "CHAVE_GEMINI_1",
    "CHAVE_GEMINI_2",
    "CHAVE_GEMINI_3"
  ],
  "groq_key": "CHAVE_GROQ_OPCIONAL",
  "tesseract_cmd": "C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
  "channels_to_monitor": [
    "timi 08",
    "timi 64",
    "grupo de agentes 20",
    "equipa de agentes de elite de timi",
    "grupo dde agentes portimao",
    "timi new",
    "Grupo de reunioes"
  ],
  "vip_senders": ["Theodore", "Johnathan", "Marcia"],
  "priority_channels": ["timi 08", "Aviso 08"],
  "schedule_times": ["13:30", "21:30"]
}
```

---

## 💻 Como Usar

### Execução Imediata (Manual)
Dá duplo clique em `run_intel_agent.bat` ou executa via terminal:
```bash
python src/main.py --now
```

### Executar em Modo Agendado (Turnos das 13:30 e 21:30)
Dá duplo clique em `run_scheduled.bat` ou executa:
```bash
python src/main.py --schedule
```

### Testar a IA Localmente
```bash
python tests/test_ai.py
```

### Opções da Linha de Comandos
- `--now`: Corre a extração e envio imediatamente.
- `--shift <NOME>`: Atribui um rótulo personalizado ao resumo (ex: `MANHÃ`, `NOITE`).
- `--channel <NOME>`: Varrimento rápido de apenas um canal específico.
- `--dry-run`: Executa a leitura e análise de IA sem enviar para o Telegram (imprime na consola).
- `--schedule`: Ativa o agendador contínuo em segundo plano.

---

## 🔒 Segurança e Privacidade
- **0% Credenciais no Git**: Todos os tokens, chats e dados locais ficam armazenados em ficheiros ignorados pelo Git (`.gitignore`).
- **Isolamento de Ecrã**: O agente pode operar em segundo plano ou em desktop virtual sem expor dados nem interromper o trabalho diário.
