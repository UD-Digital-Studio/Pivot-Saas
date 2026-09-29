import ast
import struct
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


def read_catalog(path):
    messages = {}
    current_id = None
    current_value = None
    active = None

    def commit():
        nonlocal current_id, current_value
        if current_id is not None and current_value is not None:
            messages[current_id] = current_value
        current_id = current_value = None

    for raw_line in path.read_text(encoding="utf-8").splitlines() + [""]:
        line = raw_line.strip()
        if line.startswith("msgid "):
            commit()
            current_id = ast.literal_eval(line[6:])
            current_value = ""
            active = "id"
        elif line.startswith("msgstr "):
            current_value = ast.literal_eval(line[7:])
            active = "value"
        elif line.startswith('"'):
            text = ast.literal_eval(line)
            if active == "id":
                current_id += text
            elif active == "value":
                current_value += text
        elif not line:
            commit()
            active = None
    return messages


def write_mo(messages, destination):
    keys = sorted(messages)
    ids = [key.encode("utf-8") for key in keys]
    values = [messages[key].encode("utf-8") for key in keys]
    count = len(keys)
    key_offset = 28 + count * 16
    value_offset = key_offset + sum(len(item) + 1 for item in ids)
    key_positions = []
    value_positions = []
    cursor = key_offset
    for item in ids:
        key_positions.append((len(item), cursor))
        cursor += len(item) + 1
    cursor = value_offset
    for item in values:
        value_positions.append((len(item), cursor))
        cursor += len(item) + 1
    output = [struct.pack("<7I", 0x950412DE, 0, count, 28, 28 + count * 8, 0, 0)]
    output.extend(struct.pack("<2I", *position) for position in key_positions)
    output.extend(struct.pack("<2I", *position) for position in value_positions)
    output.append(b"\0".join(ids) + b"\0")
    output.append(b"\0".join(values) + b"\0")
    destination.write_bytes(b"".join(output))


class Command(BaseCommand):
    help = "Compile les catalogues gettext sans dépendance système msgfmt."

    def handle(self, *args, **options):
        for locale_root in settings.LOCALE_PATHS:
            for source in Path(locale_root).glob("*/LC_MESSAGES/django.po"):
                destination = source.with_suffix(".mo")
                write_mo(read_catalog(source), destination)
                self.stdout.write(self.style.SUCCESS(f"Compiled {destination}"))
