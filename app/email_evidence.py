"""Compare line readings before asking the reviewer to resolve an email address."""
from difflib import SequenceMatcher
import re

from .parser import EMAIL, clean_email

DOMAIN_LINE = re.compile(r"(?:web(?:site)?\s*:\s*)?(?:https?://)?(?:www\.)?([\w-]+(?:\.[\w-]+)+)/?", re.I)


def _addresses(text):
    return {clean_email(m.group().casefold().strip(".")) for m in EMAIL.finditer(text)}


def _similar(a, b):
    return SequenceMatcher(None, a.casefold(), b.casefold(), autojunk=False).ratio()


def _boundary_addresses(reads):
    # One reader saw @ and its neighbors. Use the other reader's punctuation
    # only when both sides align, including a whole domain with a printed dot.
    candidates = set()
    for read in reads:
        if read.count("@") != 1:
            continue
        left, right = read.casefold().split("@")
        left = re.sub(r"[^a-z0-9]", "", left)
        right = re.sub(r"[^a-z0-9]", "", right)
        if len(left) < 3 or len(right) < 5:
            continue
        for other in reads:
            raw = other.strip().casefold()
            if "@" in raw or not re.fullmatch(r"[a-z0-9._+'-]+", raw):
                continue
            for pos in range(3, len(raw)-4):
                local, domain = raw[:pos], raw[pos+1:]
                if re.sub(r"[^a-z0-9]", "", local) != left or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}", domain):
                    continue
                if raw[pos] not in "aegos" or _similar(right, domain.replace(".", "")) < 0.80:
                    continue
                if not local.endswith(".") and EMAIL.fullmatch(local + "@" + domain):
                    candidates.add(local + "@" + domain)
    return candidates


def _groups(full, cropped):
    # Only full-frame coordinates refer to the original upload.
    groups = [{"reads": line["readings"][:], "box": line.get("box")}
              for line in full if line.get("readings")]
    originals = groups[:]
    used = set()
    for line in cropped:
        if not (reads := line.get("readings")):
            continue
        matches = [i for i, group in enumerate(originals)
                   if i not in used and max(_similar(a, b) for a in reads for b in group["reads"]) >= 0.92]
        if len(matches) == 1:
            i = matches[0]
            originals[i]["reads"].extend(reads)
            used.add(i)
        else:
            groups.append({"reads": reads[:], "box": None})
    return groups


def apply(fields, full, cropped, text):
    domains = {m.group(1).casefold() for line in text.splitlines()
               if (m := DOMAIN_LINE.fullmatch(line.strip()))}
    evidence = []
    groups = _groups(full or [], cropped or [])
    for group in groups:
        reads = group["reads"]
        sets = [_addresses(t) for t in reads]
        choices = set.union(*sets)
        if not choices and not any("@" in t for t in reads):
            continue
        if choices and all(values == choices for values in sets):
            continue
        if not choices and not fields.get("emails"):
            inferred = _boundary_addresses(reads)
            if len(inferred) == 1:
                fields["emails"] = sorted(inferred)
            elif inferred and len({s.replace(".", "") for s in inferred}) == 1:
                # Whitespace in the secondary transcription corroborates a printed local-part separator.
                with_dot = [s for s in inferred if "." in s.split("@")[0] and any(
                    re.sub(r"\s+", ".", t.casefold().split("@")[0].strip()) == s.split("@")[0] for t in reads if "@" in t)]
                if len(with_dot) == 1:
                    fields["emails"] = with_dot
        supported = []
        for addr in choices:
            local, domain = addr.rsplit("@", 1)
            others = [re.sub(r"\s+", "", t).casefold() for t, values in zip(reads, sets, strict=True) if addr not in values]
            boundary = any(re.fullmatch(re.escape(local) + r"[^@\s]?" + re.escape(domain), t) for t in others)
            if domain in domains and (sum(addr in values for values in sets) >= 2 or boundary):
                supported.append(addr)
        if len(supported) == 1 and supported[0] not in (fields.get("emails") or []):
            addr = supported[0]
            existing = fields.get("emails") or []
            # A card can carry both a personal and an office mailbox. Add an address
            # only if every address we would retain is printed on a separate line.
            elsewhere = {email for other in groups if other is not group
                         for read in other["reads"] for email in _addresses(read)}
            if not existing or (not choices.intersection(existing) and all(e in elsewhere for e in existing)):
                fields["emails"] = [*existing, addr]
            elif len(existing) == 1 and (fields.get("confidence", {}).get("emails") or 0) < 0.6 and _similar(existing[0], addr) >= 0.72:
                fields["emails"] = [addr]
        evidence.append({"readings": list(dict.fromkeys(reads)), "box": group["box"]})
    if evidence:
        fields["email_evidence"] = evidence
        mark_for_review(fields)


def mark_for_review(fields):
    confidence = fields.setdefault("confidence", {})
    confidence["emails"] = min(confidence.get("emails") or 0.5, 0.5)
    if "emails" not in fields.setdefault("needs_review", []):
        fields["needs_review"].append("emails")
    values = [v for v in confidence.values() if isinstance(v, (int, float))]
    fields["overall_confidence"] = round(min(sum(values)/len(values), min(values) + 0.25), 2)
