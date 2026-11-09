"""When a snooze Oliver types in the chief thread ends: `<rank or name>: snooze <when>`
(D15). The page's presets are the same times: `1h`, `tomorrow 9`, `tomorrow 12`.

  <n> m|min|h|hours|d|days|w|weeks   from now; "in 2 h", "90m", "for 3 days" too
  tomorrow [at] <time>               the local day after; 09:00 without a time
  today [at] <time>, <time>          today; a bare time already past is tomorrow
  monday … sunday [at] <time>        the next such day, never today; 09:00 without a time
  2026-11-05 [14:00], ISO 8601       local unless it carries Z or an offset; 09:00 without a time

A <time> is 9, 09:30, 14, 2pm or 9.30am. Times are in Oliver's zone: CHIEF_TZ, else TZ,
else this machine's (/etc/localtime)."""
from __future__ import annotations

import os, re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MORNING = time(9, 0)
LONGEST = timedelta(days=60)
FORMS = ('"1h", "30m", "2 days", "tomorrow", "tomorrow 12", "today 15:30", "3pm", "monday 9", '
         '"2026-11-05 14:00"')
SPAN = re.compile(r"^(?:in\s+|for\s+)?(\d+(?:\.\d+)?)\s*(m|mins?|minutes?|h|hrs?|hours?|d|days?|w|weeks?)$")
UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
CLOCK = re.compile(r"^(?:at\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?$")
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ t](.+))?$")


class Unparsed(ValueError):
    pass


def zone() -> ZoneInfo:
    """Oliver's zone: CHIEF_TZ, TZ, or the zone /etc/localtime links to; UTC failing all."""
    names = [os.environ.get("CHIEF_TZ"), os.environ.get("TZ", "").lstrip(":")]
    try:
        names.append(str(Path("/etc/localtime").resolve()).split("zoneinfo/", 1)[1])
    except (OSError, IndexError):
        pass
    for name in names:
        if name:
            try:
                return ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                continue
    return ZoneInfo("UTC")


def clock(text: str) -> time:
    """09:30, 9, 14, 2pm, 9.30am as a time of day."""
    found = CLOCK.match(text.strip())
    if not found:
        raise Unparsed(f'"{text}" isn\'t a time of day')
    hour, minute, half = int(found.group(1)), int(found.group(2) or 0), found.group(3)
    if half:
        if not 1 <= hour <= 12:
            raise Unparsed(f'"{text}" isn\'t a time of day')
        hour = hour % 12 + (12 if half == "pm" else 0)
    if hour > 23 or minute > 59:
        raise Unparsed(f'"{text}" isn\'t a time of day')
    return time(hour, minute)


def day_word(word: str):
    """today, tomorrow, or a weekday (3 letters or more) as a function from today's date to
    that day; a weekday is the next one, never today. None for any other word."""
    if word == "today":
        return lambda today: today
    if word == "tomorrow":
        return lambda today: today + timedelta(days=1)
    for number, name in enumerate(DAYS):
        if len(word) >= 3 and name.startswith(word):
            return lambda today: today + timedelta(days=(number - today.weekday() - 1) % 7 + 1)
    return None


def on(day: date, at: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, at, tzinfo=tz)


def until(text: str, now: datetime, tz: ZoneInfo | None = None) -> datetime:
    """The end of a snooze Oliver wrote, as an aware time. Raises Unparsed when the words
    aren't one of FORMS, or the time is past or more than 60 days out."""
    tz = tz or zone()
    words = re.sub(r"\s+", " ", text.strip().lower())
    words = re.sub(r"^(until|next) ", "", words).strip()
    local = now.astimezone(tz)
    found = SPAN.match(words)
    if found:
        unit = UNITS[found.group(2)[0]]
        end = now + timedelta(**{unit: float(found.group(1))})
    elif day_word(words.partition(" ")[0]) is not None:
        head, _, rest = words.partition(" ")
        at = clock(rest) if rest else None
        if head == "today" and at is None:
            raise Unparsed('"today" needs a time, such as "today 15:30"')
        end = on(day_word(head)(local.date()), at or MORNING, tz)
    elif DATE.match(words):
        day_text, rest = DATE.match(words).groups()
        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            raise Unparsed(f'"{day_text}" isn\'t a date') from None
        if rest and re.search(r"(z|[+-]\d{2}:?\d{2})$", rest):
            try:
                end = datetime.fromisoformat(f"{day_text}T{rest.upper().replace('Z', '+00:00')}")
            except ValueError:
                raise Unparsed(f'"{text}" isn\'t a time') from None
        else:
            end = on(day, clock(rest) if rest else MORNING, tz)
    else:
        try:
            at = clock(words)
        except Unparsed:
            raise Unparsed(f'"{text}" isn\'t a time I know; write one of {FORMS}') from None
        end = on(local.date(), at, tz)
        if end <= now:
            end = on(local.date() + timedelta(days=1), at, tz)
    if end <= now + timedelta(minutes=1):
        raise Unparsed(f"{end.astimezone(tz):%a %H:%M} is past; pick a later time")
    if end > now + LONGEST:
        raise Unparsed("snooze for 60 days at most; settle the thread instead")
    return end.astimezone(timezone.utc)


def command(text: str) -> tuple[str, str] | None:
    """("snooze", "<when>") or ("unsnooze", "") when Oliver's answer is one, else None."""
    words = text.strip()
    if words.lower() == "unsnooze":
        return "unsnooze", ""
    found = re.match(r"^snooze\b\s*(.*)$", words, re.I | re.S)
    return ("snooze", found.group(1).strip()) if found else None
