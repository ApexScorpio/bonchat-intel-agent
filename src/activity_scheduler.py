"""
TIMI BonChat Activity & Meeting Dynamic Scheduler
Deteta anúncios de reuniões e atividades no BonChat e cria agendamentos automáticos
no Windows Task Scheduler para lançar o TIMI_GUARDIAN.py 15 minutos antes.
"""

import os
import re
import sys
import json
import logging
import datetime
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("ActivityScheduler")

PYTHON_EXE = r"C:\Users\lopes\AppData\Local\Programs\Python\Python310\python.exe"
GUARDIAN_SCRIPT = r"S:\Users\lopes\Documents\TIMI_FIELD_WORKSPACE\code\TIMI_GUARDIAN.py"
SCHEDULED_DB = Path(__file__).resolve().parent.parent / "data" / "scheduled_activities.json"

MONTH_MAP = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12
}


def parse_meeting_datetime(text: str, base_date: Optional[datetime.date] = None) -> Optional[Tuple[datetime.datetime, str]]:
    """
    Extrai a data e hora de uma reunião ou atividade a partir de texto em português.
    Retorna (data_hora_reunião, motivo) ou None.
    """
    now = datetime.datetime.now()
    if not base_date:
        base_date = now.date()

    text_lower = text.lower()

    # Ignorar mensagens de encerramento
    if any(k in text_lower for k in ("termina aqui", "terminou", "acabou", "boa noite pessoal", "obrigado pela reunião")):
        return None

    # Verificar se há menção a reunião/atividade/live
    is_meeting_mention = any(k in text_lower for k in (
        "reunião", "reuniao", "encontro", "live", "transmissão ao vivo", "transmissao ao vivo",
        "chamada", "presença", "presenca", "sorteio de usdt", "sorteio ao vivo"
    ))
    if not is_meeting_mention:
        return None

    # Extrair Hora
    # Ex: '20:00', '20h00', '20h', 'às 20 horas', 'às 19:30'
    time_match = re.search(r'(?:às|as|pelas|pela|hora|horário|horario|ás)?\s*(\d{1,2})[:hH](\d{2})?\b', text_lower)
    hour = None
    minute = 0
    if time_match:
        h_str = time_match.group(1)
        m_str = time_match.group(2)
        h = int(h_str)
        if 0 <= h <= 23:
            hour = h
            minute = int(m_str) if m_str else 0
    else:
        # Menção genérica a "à noite" / "20 horas"
        h_match = re.search(r'(\d{1,2})\s*horas\b', text_lower)
        if h_match:
            h = int(h_match.group(1))
            if 0 <= h <= 23:
                hour = h
                minute = 0

    if hour is None:
        # Se for menção a reunião noturna sem hora explícita, o padrão oficial TIMI é 20:00
        if any(k in text_lower for k in ("hoje à noite", "hoje a noite", "esta noite", "reunião noturna", "reuniao noturna")):
            hour = 20
            minute = 0
        elif any(k in text_lower for k in ("live diária", "live diaria", "live das 16")):
            hour = 16
            minute = 30
        else:
            return None

    # Extrair Data
    target_date = base_date

    # 1. "Amanhã" / "Amanha"
    if "amanhã" in text_lower or "amanha" in text_lower:
        target_date = base_date + datetime.timedelta(days=1)
    # 2. "Hoje"
    elif "hoje" in text_lower:
        target_date = base_date
    # 3. Data específica: "dia 11", "12 de novembro", "15/11"
    else:
        dm_match = re.search(r'dia\s*(\d{1,2})(?:\s*de\s*([a-zç]+))?', text_lower)
        if dm_match:
            d = int(dm_match.group(1))
            m_name = dm_match.group(2)
            m = MONTH_MAP.get(m_name, base_date.month) if m_name else base_date.month
            try:
                target_date = datetime.date(base_date.year, m, d)
                if target_date < base_date:
                    target_date = datetime.date(base_date.year + 1, m, d)
            except ValueError:
                target_date = base_date

    meeting_dt = datetime.datetime.combine(target_date, datetime.time(hour, minute))
    
    # Determinar tipo/motivo
    reason = "Reunião Oficial BonChat"
    if "live" in text_lower:
        reason = "Live / Transmissão TIMI"
    elif "sorteio" in text_lower:
        reason = "Sorteio ao Vivo & Códigos"
    elif "presença" in text_lower or "presenca" in text_lower:
        reason = "Reunião Obrigatória com Chamada de Presença"

    return meeting_dt, reason


def schedule_activity_task(meeting_dt: datetime.datetime, reason: str) -> Optional[str]:
    """
    Regista uma tarefa no Windows Task Scheduler para arrancar o TIMI_GUARDIAN.py
    15 minutos antes da reunião. Retorna o nome da tarefa se agendada com sucesso.
    """
    now = datetime.datetime.now()
    
    # Arrancar 15 minutos antes da hora marcada da reunião
    launch_dt = meeting_dt - datetime.timedelta(minutes=15)
    
    # Se o momento de arranque já passou há mais de 10 minutos, ignorar
    if launch_dt < (now - datetime.timedelta(minutes=10)):
        logger.info(f"Horário de arranque ({launch_dt.strftime('%Y-%m-%d %H:%M')}) já no passado. Ignorando agendamento.")
        return None

    # Se estiver a menos de 15 minutos da reunião (ou em cima da hora), arrancar imediatamente (daqui a 1 min)
    if launch_dt <= now:
        launch_dt = now + datetime.timedelta(minutes=1)

    task_name = f"TIMI_AUTO_MEETING_{meeting_dt.strftime('%Y%m%d_%H%M')}"
    time_str = launch_dt.strftime("%H:%M")
    date_str = launch_dt.strftime("%d/%m/%Y") # Formato dd/MM/yyyy do Windows local

    # Comando a executar
    cmd_run = f'"{PYTHON_EXE}" "{GUARDIAN_SCRIPT}"'

    # Criar a tarefa no Task Scheduler
    cmd_schtasks = [
        "schtasks", "/create",
        "/tn", task_name,
        "/tr", cmd_run,
        "/sc", "once",
        "/st", time_str,
        "/sd", date_str,
        "/f"
    ]

    try:
        res = subprocess.run(cmd_schtasks, capture_output=True, text=True, check=False)
        if res.returncode == 0:
            logger.info(f"✅ TAREFA WINDOWS AGENDADA: '{task_name}' para {date_str} às {time_str} ({reason})")
            save_scheduled_record(task_name, meeting_dt, launch_dt, reason)
            return task_name
        else:
            logger.error(f"Erro ao criar tarefa agendada ({res.returncode}): {res.stderr}")
            return None
    except Exception as e:
        logger.error(f"Exceção ao agendar tarefa: {e}")
        return None


def save_scheduled_record(task_name: str, meeting_dt: datetime.datetime, launch_dt: datetime.datetime, reason: str):
    """Guarda registo histórico das reuniões agendadas para evitar tarefas duplicadas."""
    SCHEDULED_DB.parent.mkdir(parents=True, exist_ok=True)
    records = {}
    if SCHEDULED_DB.exists():
        try:
            with open(SCHEDULED_DB, "r", encoding="utf-8") as f:
                records = json.load(f)
        except Exception:
            records = {}

    records[task_name] = {
        "meeting_time": meeting_dt.strftime("%Y-%m-%d %H:%M"),
        "launch_time": launch_dt.strftime("%Y-%m-%d %H:%M"),
        "reason": reason,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        with open(SCHEDULED_DB, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Aviso ao guardar registo de agendamento: {e}")


def scan_and_schedule_from_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Percorre registos extraídos pelo Intel Agent e agenda automaticamente
    quaisquer reuniões detetadas para o próprio dia ou dias seguintes.
    """
    scheduled = []
    for e in entries:
        text = e.get("verbatim_text") or " ".join(e.get("key_takeaways", []))
        if not text:
            continue

        base_d = None
        date_str = e.get("date_str")
        if date_str and date_str != "N/A":
            try:
                base_d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            except Exception:
                pass

        parsed = parse_meeting_datetime(text, base_date=base_d)
        if parsed:
            m_dt, reason = parsed
            task = schedule_activity_task(m_dt, reason)
            if task:
                scheduled.append({
                    "task_name": task,
                    "meeting_time": m_dt.strftime("%Y-%m-%d %H:%M"),
                    "reason": reason
                })

    return scheduled

