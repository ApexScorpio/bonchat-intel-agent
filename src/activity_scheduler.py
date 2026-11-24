"""
TIMI BonChat Activity & Meeting Dynamic Scheduler (V2)
Deteta anúncios de reuniões, remarcações e cancelamentos em qualquer grupo do BonChat,
e gere dinamicamente as tarefas do Windows Task Scheduler para lançar o TIMI_GUARDIAN.py
15 minutos antes, já focado no grupo certo (--channel "<Grupo X>").
"""

import os
import re
import json
import logging
import datetime
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("ActivityScheduler")

PYTHON_EXE = r"S:\Users\lopes\AppData\Local\Programs\Python\Python310\pythonw.exe"
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = r"C:\Users\lopes\AppData\Local\Programs\Python\Python310\pythonw.exe"
GUARDIAN_SCRIPT = r"S:\Users\lopes\Documents\TIMI_FIELD_WORKSPACE\code\TIMI_GUARDIAN.py"
GUARDIAN_WORKDIR = r"S:\Users\lopes\Documents\TIMI_FIELD_WORKSPACE\code"
SCHEDULED_DB = Path(__file__).resolve().parent.parent / "data" / "scheduled_activities.json"

MONTH_MAP = {
    "janeiro": 1, "jan": 1,
    "fevereiro": 2, "fev": 2,
    "março": 3, "marco": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "maio": 5, "mai": 5,
    "junho": 6, "jun": 6,
    "julho": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "setembro": 9, "set": 9,
    "outubro": 10, "out": 10,
    "novembro": 11, "nov": 11,
    "dezembro": 12, "dez": 12,
}

WEEKDAY_MAP = {
    "segunda": 0, "segunda-feira": 0,
    "terça": 1, "terca": 1, "terça-feira": 1, "terca-feira": 1,
    "quarta": 2, "quarta-feira": 2,
    "quinta": 3, "quinta-feira": 3,
    "sexta": 4, "sexta-feira": 4,
    "sábado": 5, "sabado": 5,
    "domingo": 6,
}

KNOWN_GROUPS = [
    "TIMI--NO.08",
    "TIMI-68",
    "TIMI Mall",
    "TIMI-NeWs",
    "Grupo de reuniões",
    "Equipa de Agentes de Elite da TIMI",
    "Theodore.Grupo de Agentes20",
    "TIMI PORTUGAL DREAM TEAM",
    "Grupo de Recompensas por Objetivos",
]


def _extract_target_channel(text: str, default_channel: str = "TIMI--NO.08") -> str:
    """
    Identifica em que grupo/canal vai REALMENTE decorrer a reunião.
    Dá prioridade absoluta a menções explícitas de local ('no grupo X', 'em X', 'canal X', 'sala X')
    para não confundir o grupo onde o anúncio foi publicado ou menções a produtos (ex: 'produto TIMI Mall').
    """
    tl = text.lower()
    group_patterns = [
        ("TIMI-68", r'(?:timi[\s\-]*68|grupo\s*68|canal\s*68)'),
        ("TIMI--NO.08", r'(?:timi[\s\-]*no\.?\s*08|no\.?\s*08|no08|grupo\s*08|canal\s*08)'),
        ("Theodore.Grupo de Agentes20", r'(?:agentes\s*20|theodore\.?\s*grupo\s*de\s*agentes\s*20)'),
        ("Equipa de Agentes de Elite da TIMI", r'(?:agentes\s+de\s+elite|equipa\s+de\s+agentes)'),
        ("Grupo de reuniões", r'(?:grupo\s+de\s+reuni[oõ]es)'),
        ("TIMI PORTUGAL DREAM TEAM", r'(?:dream\s+team)'),
        ("Grupo de Recompensas por Objetivos", r'(?:recompensas\s+por\s+objetivos)'),
        ("TIMI Mall", r'(?:timi\s*mall|timimall)'),
    ]

    # 1. Prioridade máxima: contexto explícito de local ("no grupo ...", "no canal ...", "em ...", "sala ...")
    loc_prefix = r'(?:no\s+grupo|na\s+sala|no\s+canal|grupo\s*[:\-]|canal\s*[:\-]|local\s*[:\-]|em\s+(?:direto\s+no\s+)?(?:grupo\s+)?)\s*'
    for grp_name, pat in group_patterns:
        if re.search(loc_prefix + pat, tl):
            return grp_name

    # 2. Se disser explicitamente "neste grupo" / "aqui no grupo", usar o canal de origem
    if re.search(r'\b(neste\s+grupo|aqui\s+no\s+grupo|neste\s+canal)\b', tl):
        return default_channel or "TIMI--NO.08"

    # 3. Menção direta de grupo (evitando 'produto timi mall' / 'campanha timi mall')
    for grp_name, pat in group_patterns:
        if grp_name == "TIMI Mall" and re.search(r'(?:produto|campanha|loja|compra\w*)\s+(?:da\s+|do\s+)?timi\s*mall', tl):
            continue
        if re.search(pat, tl):
            return grp_name

    return default_channel or "TIMI--NO.08"


def parse_meeting_event(
    text: str,
    base_date: Optional[datetime.date] = None,
    source_channel: str = "TIMI--NO.08",
) -> Optional[Dict[str, Any]]:
    """
    Analisa texto em PT e extrai evento de reunião/atividade:
    Retorna dict:
      {
        "action": "schedule" | "reschedule" | "cancel",
        "meeting_dt": datetime.datetime,
        "channel": str,
        "reason": str,
      }
    ou None se não for anúncio/alteração de reunião.
    """
    if not text or len(text.strip()) < 10:
        return None

    now = datetime.datetime.now()
    if not base_date:
        base_date = now.date()

    text_lower = text.lower()

    # Ignorar mensagens de encerramento
    if any(k in text_lower for k in (
        "termina aqui", "terminou", "acabou", "obrigado pela reunião", "obrigado pela reuniao"
    )):
        return None

    # Verificar se há menção a reunião/atividade/live/sorteio
    is_meeting_mention = any(k in text_lower for k in (
        "reunião", "reuniao", "encontro", "live", "transmissão ao vivo", "transmissao ao vivo",
        "chamada", "presença", "presenca", "sorteio de usdt", "sorteio ao vivo", "sorteio da sorte",
        "sessão", "sessao", "formação", "formacao"
    ))
    if not is_meeting_mention:
        return None

    # Detetar ação: cancelar / remarcar / agendar
    action = "schedule"
    if any(k in text_lower for k in ("cancelad", "não haverá reunião", "nao havera reuniao", "sem reunião", "sem reuniao", "adiada sem data")):
        action = "cancel"
    elif any(k in text_lower for k in ("remarcad", "alterad", "mudou para", "passou para", "novo horário", "novo horario", "adiada para", "transferida para")):
        action = "reschedule"

    # Extrair Data
    target_date = base_date
    date_explicit = False

    if "depois de amanhã" in text_lower or "depois de amanha" in text_lower:
        target_date = base_date + datetime.timedelta(days=2)
        date_explicit = True
    elif "amanhã" in text_lower or "amanha" in text_lower:
        target_date = base_date + datetime.timedelta(days=1)
        date_explicit = True
    elif "hoje" in text_lower or "esta noite" in text_lower:
        target_date = base_date
        date_explicit = True
    else:
        # 1. dd/mm ou dd/mm/yyyy (ex: 25/11 ou 25/11/2026)
        slash_m = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b', text_lower)
        # 2. "dia 25" ou "25 de novembro"
        dm_match = re.search(r'(?:dia\s*)?(\d{1,2})\s*de\s*([a-zç]+)', text_lower)
        day_only = re.search(r'\bdia\s*(\d{1,2})\b', text_lower)

        if slash_m:
            d, m = int(slash_m.group(1)), int(slash_m.group(2))
            y = int(slash_m.group(3)) if slash_m.group(3) else base_date.year
            if y < 100:
                y += 2000
            try:
                target_date = datetime.date(y, m, d)
                if not slash_m.group(3) and target_date < base_date:
                    target_date = datetime.date(y + 1, m, d)
                date_explicit = True
            except ValueError:
                pass
        elif dm_match and dm_match.group(2) in MONTH_MAP:
            d = int(dm_match.group(1))
            m = MONTH_MAP[dm_match.group(2)]
            try:
                target_date = datetime.date(base_date.year, m, d)
                if target_date < base_date:
                    target_date = datetime.date(base_date.year + 1, m, d)
                date_explicit = True
            except ValueError:
                pass
        elif day_only:
            d = int(day_only.group(1))
            try:
                target_date = datetime.date(base_date.year, base_date.month, d)
                if target_date < base_date:
                    next_m = base_date.month + 1
                    next_y = base_date.year + (1 if next_m > 12 else 0)
                    next_m = 1 if next_m > 12 else next_m
                    target_date = datetime.date(next_y, next_m, d)
                date_explicit = True
            except ValueError:
                pass
        else:
            # 3. Dia da semana (ex: "quinta-feira", "domingo", "sábado")
            for wd_name, wd_idx in WEEKDAY_MAP.items():
                if re.search(rf'\b{re.escape(wd_name)}\b', text_lower):
                    delta = (wd_idx - base_date.weekday()) % 7
                    if delta == 0 and "próxim" in text_lower:
                        delta = 7
                    target_date = base_date + datetime.timedelta(days=delta)
                    date_explicit = True
                    break

    # Extrair Hora — EXIGE preposição ou formato explícito (às 20:00, pelas 20h, horário 20:00, 20h30, 20 horas)
    # para NUNCA confundir timestamps de balões de chat (ex: '16:24', '16:36', '16:54') com hora de reunião!
    explicit_colon = re.findall(
        r'(?:às|as|ás|pelas|pela|horário|horario|hora(?:\s+de\s+portugal)?|para\s+as|início|inicio)\s*[:\-]?\s*(\d{1,2}):(\d{2})\b',
        text_lower,
    )
    explicit_h = re.findall(
        r'(?:às|as|ás|pelas|pela|para\s+as)?\s*\b(\d{1,2})[hH](\d{2})?\b',
        text_lower,
    )
    valid_times = []
    for h_str, m_str in explicit_colon + explicit_h:
        h = int(h_str)
        m = int(m_str) if m_str else 0
        if 0 <= h <= 23 and 0 <= m <= 59:
            # Reuniões reais ocorrem em múltiplos de 5 min (ignora ruído OCR/timestamps aleatórios como 16:24/16:36/16:54)
            if m % 5 == 0:
                valid_times.append((h, m))

    hour = None
    minute = 0
    if valid_times:
        hour, minute = valid_times[-1] if action == "reschedule" else valid_times[0]
    else:
        h_match = re.findall(r'\b(\d{1,2})\s*horas\b', text_lower)
        if h_match:
            h = int(h_match[-1] if action == "reschedule" else h_match[0])
            if 0 <= h <= 23:
                hour, minute = h, 0

    if hour is None:
        if action == "cancel" and date_explicit:
            hour, minute = 20, 0
        elif any(k in text_lower for k in ("hoje à noite", "hoje a noite", "esta noite", "reunião noturna", "reuniao noturna")):
            hour, minute = 20, 0
        elif any(k in text_lower for k in ("live diária", "live diaria", "live das 16")):
            hour, minute = 16, 30
        else:
            return None

    meeting_dt = datetime.datetime.combine(target_date, datetime.time(hour, minute))
    channel = _extract_target_channel(text, default_channel=source_channel)

    reason = "Reunião Oficial BonChat"
    if "live" in text_lower:
        reason = "Live / Transmissão TIMI"
    elif "sorteio" in text_lower:
        reason = "Sorteio ao Vivo & Códigos"
    elif "presença" in text_lower or "presenca" in text_lower:
        reason = "Reunião Obrigatória com Chamada de Presença"
    elif "formação" in text_lower or "formacao" in text_lower:
        reason = "Sessão de Formação TIMI"

    return {
        "action": action,
        "meeting_dt": meeting_dt,
        "channel": channel,
        "reason": reason,
    }


def parse_meeting_datetime(text: str, base_date: Optional[datetime.date] = None) -> Optional[Tuple[datetime.datetime, str]]:
    """Compatibilidade retroativa: retorna (meeting_dt, reason) ou None."""
    ev = parse_meeting_event(text, base_date=base_date)
    if not ev or ev["action"] == "cancel":
        return None
    return ev["meeting_dt"], ev["reason"]


def _load_db() -> Dict[str, Dict[str, Any]]:
    if not SCHEDULED_DB.exists():
        return {}
    try:
        with open(SCHEDULED_DB, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {item.get("task_name", f"item_{i}"): item for i, item in enumerate(data) if isinstance(item, dict)}
    except Exception:
        pass
    return {}


def _save_db(records: Dict[str, Dict[str, Any]]):
    SCHEDULED_DB.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(SCHEDULED_DB, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Aviso ao guardar registo de agendamento: {e}")


def _ps_unregister_task(task_name: str) -> bool:
    ps = f"Unregister-ScheduledTask -TaskName '{task_name}' -Confirm:$false -ErrorAction SilentlyContinue"
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return res.returncode == 0
    except Exception:
        return False


def _ps_register_once_task(task_name: str, launch_dt: datetime.datetime, channel: str) -> bool:
    """Cria/atualiza tarefa Windows via PowerShell (100% independente do locale de data)."""
    iso_dt = launch_dt.strftime("%Y-%m-%dT%H:%M:00")
    safe_channel = channel.replace('"', "").replace("'", "")
    args = f'-u "{GUARDIAN_SCRIPT}" --channel "{safe_channel}"'
    ps = (
        f"$act = New-ScheduledTaskAction -Execute '{PYTHON_EXE}' -Argument '{args}' -WorkingDirectory '{GUARDIAN_WORKDIR}'; "
        f"$trig = New-ScheduledTaskTrigger -Once -At ([datetime]'{iso_dt}'); "
        f"$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        f"-ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew; "
        f"Register-ScheduledTask -TaskName '{task_name}' -Action $act -Trigger $trig -Settings $set -Force | Out-Null"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if res.returncode != 0:
            logger.error(f"Erro PowerShell ao registar '{task_name}': {res.stderr.strip()}")
            return False
        return True
    except Exception as e:
        logger.error(f"Exceção PowerShell ao registar '{task_name}': {e}")
        return False


def cleanup_expired_tasks() -> int:
    """Remove tarefas TIMI_AUTO_MEETING_* cuja hora já passou há mais de 3 horas."""
    now = datetime.datetime.now()
    records = _load_db()
    removed = 0
    for task_name in list(records.keys()):
        rec = records[task_name]
        dt_str = rec.get("meeting_datetime") or rec.get("meeting_time") or ""
        try:
            m_dt = datetime.datetime.fromisoformat(dt_str)
        except Exception:
            continue
        if m_dt < (now - datetime.timedelta(hours=3)):
            _ps_unregister_task(task_name)
            del records[task_name]
            removed += 1
    if removed:
        _save_db(records)
        logger.info(f"🧹 Removidas {removed} tarefa(s) automática(s) expirada(s).")
    return removed


def cancel_or_replace_for_day(target_date: datetime.date, channel: str) -> List[str]:
    """Remove tarefas TIMI_AUTO_MEETING_* existentes no mesmo dia/canal (para remarcações ou cancelamentos)."""
    records = _load_db()
    removed_names = []
    date_prefix = target_date.strftime("%Y-%m-%d")
    for task_name in list(records.keys()):
        rec = records[task_name]
        dt_str = str(rec.get("meeting_datetime") or rec.get("meeting_time") or "")
        rec_ch = str(rec.get("channel") or "")
        if dt_str.startswith(date_prefix) and (not rec_ch or rec_ch.lower() == channel.lower()):
            _ps_unregister_task(task_name)
            del records[task_name]
            removed_names.append(task_name)
    if removed_names:
        _save_db(records)
        logger.info(f"🔄 Removida(s) tarefa(s) anterior(es) de {date_prefix} ({channel}): {removed_names}")
    return removed_names


def schedule_activity_task(
    meeting_dt: datetime.datetime,
    reason: str,
    channel: str = "TIMI--NO.08",
    action: str = "schedule",
) -> Optional[str]:
    """
    Regista, remarca ou cancela uma tarefa no Windows Task Scheduler para arrancar o
    TIMI_GUARDIAN.py 15 minutos antes da reunião no grupo certo.
    """
    cleanup_expired_tasks()

    if action == "cancel":
        removed = cancel_or_replace_for_day(meeting_dt.date(), channel)
        return f"CANCELLED:{','.join(removed)}" if removed else None

    if action == "reschedule":
        cancel_or_replace_for_day(meeting_dt.date(), channel)

    now = datetime.datetime.now()
    launch_dt = meeting_dt - datetime.timedelta(minutes=15)

    # Se a reunião já começou há mais de 30 min, ignorar
    if meeting_dt < (now - datetime.timedelta(minutes=30)):
        logger.info(f"Reunião ({meeting_dt.strftime('%Y-%m-%d %H:%M')}) já no passado. Ignorando.")
        return None

    # Se estamos a menos de 15 min da reunião, arrancar daqui a 1 min
    if launch_dt <= now:
        launch_dt = now + datetime.timedelta(minutes=1)

    task_name = f"TIMI_AUTO_MEETING_{meeting_dt.strftime('%Y%m%d_%H%M')}"
    records = _load_db()
    if task_name in records and records[task_name].get("channel", "").lower() == channel.lower() and action == "schedule":
        logger.info(f"ℹ️ Tarefa '{task_name}' ({channel}) já está agendada.")
        return None

    if _ps_register_once_task(task_name, launch_dt, channel):
        iso_meet = meeting_dt.strftime("%Y-%m-%dT%H:%M:00")
        records[task_name] = {
            "task_name": task_name,
            "meeting_datetime": iso_meet,
            "meeting_time": meeting_dt.strftime("%Y-%m-%d %H:%M"),
            "launch_time": launch_dt.strftime("%Y-%m-%d %H:%M"),
            "channel": channel,
            "reason": reason,
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_db(records)
        logger.info(f"✅ TAREFA DINÂMICA AGENDADA: '{task_name}' | Canal: {channel} | Reunião: {meeting_dt.strftime('%d/%m/%Y %H:%M')} | Arranque: {launch_dt.strftime('%H:%M')}")
        return task_name
    return None


def scan_and_schedule_from_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Percorre registos extraídos pelo Intel Agent e agenda/remarca/cancela automaticamente
    quaisquer reuniões detetadas com o respetivo grupo/canal.
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

        src_ch = e.get("channel") or "TIMI--NO.08"
        ev = parse_meeting_event(text, base_date=base_d, source_channel=src_ch)
        if not ev:
            continue

        task = schedule_activity_task(
            ev["meeting_dt"],
            ev["reason"],
            channel=ev["channel"],
            action=ev["action"],
        )
        if task:
            scheduled.append({
                "task_name": task,
                "action": ev["action"],
                "channel": ev["channel"],
                "meeting_time": ev["meeting_dt"].strftime("%Y-%m-%d %H:%M"),
                "reason": ev["reason"],
            })

    return scheduled
