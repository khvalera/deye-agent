#! /usr/bin/python3

import yaml

registers_file = "/etc/deye-agent/registers.yaml"
po_file = "deye-agent-registers.po"

with open(registers_file, "r", encoding="utf-8") as f:
    data = yaml.safe_load(f)

names = [reg["name"] for reg in data.get("registers", []) if "name" in reg]

with open(po_file, "w", encoding="utf-8") as f:
    f.write('# SOME DESCRIPTIVE TITLE.\n')
    f.write('# Copyright (C) YEAR THE PACKAGE\'S COPYRIGHT HOLDER\n')
    f.write('# This file is distributed under the same license as the deye-agent package.\n')
    f.write('# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.\n')
    f.write('#\n')
    f.write('msgid ""\nmsgstr ""\n')
    f.write('"Content-Type: text/plain; charset=UTF-8\\n"\n\n')

    for name in names:
        f.write(f'msgid "{name}"\n')
        f.write('msgstr ""\n\n')

print(f"Generated {po_file} with {len(names)} entries.")
