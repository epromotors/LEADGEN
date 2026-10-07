import random
import re


# Variable placeholder pattern — these must NOT be resolved as spintax
# They will be injected AFTER spintax resolution.
_VARIABLE_PATTERN = re.compile(r"^\w+$")  # single word, no pipes = variable name


def resolve_spintax(text: str, variables: dict | None = None) -> str:
    """
    Recursively resolve all {option1|option2|option3} blocks in a string.
    Supports nested spintax.

    IMPORTANT: Single-word tokens like {business_name} are treated as variable
    placeholders and are NOT resolved as spintax — they are left intact so that
    inject_variables() can replace them correctly afterwards.

    Example:
        "{Hi|Hey|Hello} {business_name}!" → "Hey {business_name}!"
        (then inject_variables replaces {business_name} → "Acme Corp")
    """
    known_vars = set(variables.keys()) if variables else set()

    pattern = re.compile(r"\{([^{}]+)\}")
    while "{" in text:
        match = pattern.search(text)
        if not match:
            break
        inner = match.group(1)

        # If it's a known variable name (no pipes, just a plain word), skip it
        # by temporarily replacing with a sentinel so the loop doesn't re-process it
        if "|" not in inner and _VARIABLE_PATTERN.match(inner.strip()):
            # This is a variable placeholder — stop trying to resolve it as spintax
            # We'll only continue if there are other { } blocks left
            # Mark it as "done" by checking the rest of the string
            remaining = text[match.end():]
            if "{" not in remaining:
                break  # nothing else to process, leave variable intact
            # There are more groups — skip this one and advance past it
            # We do this by processing the string in two halves
            prefix = text[:match.end()]
            suffix = resolve_spintax(remaining, variables)
            return prefix + suffix

        options = inner.split("|")
        chosen = random.choice(options)
        text = text[: match.start()] + chosen + text[match.end():]

    return text


def inject_variables(text: str, variables: dict) -> str:
    """
    Replace {variable_name} placeholders (after spintax resolution).
    Variables dict: {"business_name": "Acme Corp", "audit_summary": "...", ...}
    """
    for key, value in variables.items():
        text = text.replace(f"{{{key}}}", str(value))
    return text


def process_template(template: str, variables: dict) -> str:
    """Full pipeline: inject variables first, then resolve spintax.

    Order matters: inject variables BEFORE spintax so that when a subject
    template like '{Quick audit on {domain}|Found gaps on {domain}}' is
    processed, the inner {domain} is already replaced with the real domain
    string before the outer spintax picker runs. This avoids the nested-brace
    issue where the regex (which forbids braces inside a match) would fail to
    pick from the outer options and print the raw template.
    """
    after_vars = inject_variables(template, variables)
    return resolve_spintax(after_vars, variables)
