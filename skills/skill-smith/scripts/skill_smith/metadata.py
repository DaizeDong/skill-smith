"""The small frontmatter subset used by the existing metadata readers."""
import re


def parse_frontmatter(text):
    text = text.lstrip("\ufeff")
    if not text.startswith("---"):
        return None, None
    end = text.find("\n---", 3)
    if end == -1:
        return None, None
    fields = {}
    lines = text[3:end].splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(name|description):\s*(.*)$", line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip().strip('"\'')
        if key == "description":
            for following in lines[index + 1:]:
                if not following.startswith((" ", "\t")) or re.match(r"^\s*\w[\w-]*:\s", following):
                    break
                value += " " + following.strip()
        fields[key] = value
    return fields.get("name"), fields.get("description")
