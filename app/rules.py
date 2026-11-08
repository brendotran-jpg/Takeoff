"""Rules library: YAML files validated against rules/schema.json.

Load order: rules/*.yaml (shipped starter set), then rules/user/*.yaml (your
own, never overwritten by upgrades). A user rule with the same id replaces the
starter rule. Each rule gets a content hash so a measurement can record
exactly which version of a rule it was measured under.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent / "rules"
USER_FILE_NAME = "user_rules.yaml"


class RuleError(ValueError):
    pass


class RulesLibrary:
    def __init__(self, root: Path = ROOT, user_dir: Path | None = None):
        self.root = Path(root)
        # Bundled rules are read-only in a packaged app, so user rules live elsewhere.
        self.user_dir = Path(user_dir) if user_dir else self.root / "user"
        self.schema = json.loads((self.root / "schema.json").read_text())
        self.validator = jsonschema.Draft202012Validator(self.schema)
        self.rules: dict[str, dict] = {}
        self.origin: dict[str, str] = {}
        self.errors: list[str] = []
        self.reload()

    # ------------------------------------------------------------ loading --
    def reload(self) -> None:
        self.rules, self.origin, self.errors = {}, {}, []
        files = sorted(self.root.glob("*.yaml")) + sorted(self.user_dir.glob("*.yaml"))
        for f in files:
            try:
                data = yaml.safe_load(f.read_text()) or {}
            except yaml.YAMLError as e:
                self.errors.append(f"{f.name}: YAML error: {e}")
                continue
            for i, rule in enumerate(data.get("rules", [])):
                problems = self.validate(rule)
                if problems:
                    self.errors.append(f"{f.name} rule #{i + 1} ({rule.get('id', '?')}): " + "; ".join(problems))
                    continue
                self.rules[rule["id"]] = rule
                self.origin[rule["id"]] = ("user/" if f.parent == self.user_dir else "") + f.name

    def validate(self, rule: dict) -> list[str]:
        return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
                for e in self.validator.iter_errors(rule)]

    # ------------------------------------------------------------ access ---
    def get(self, rule_id: str) -> dict:
        if rule_id not in self.rules:
            raise RuleError(f"unknown rule id {rule_id!r}")
        return self.rules[rule_id]

    def list(self) -> list[dict]:
        return [{**r, "_origin": self.origin[r["id"]], "_hash": rule_hash(r)}
                for r in sorted(self.rules.values(), key=lambda r: (r["category"], r["id"]))]

    # ------------------------------------------------------------ editing --
    def save_user_rule(self, rule: dict) -> dict:
        """Create or override a rule in rules/user/user_rules.yaml."""
        problems = self.validate(rule)
        if problems:
            raise RuleError("; ".join(problems))
        path = self.user_dir / USER_FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        data = yaml.safe_load(path.read_text()) if path.exists() else None
        data = data or {"rules": []}
        existing = [r for r in data["rules"] if r.get("id") != rule["id"]]
        if rule["id"] in self.rules:
            rule = {**rule, "version": int(self.rules[rule["id"]].get("version", 1)) + 1}
        data["rules"] = existing + [rule]
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        self.reload()
        return self.get(rule["id"])


def rule_hash(rule: dict) -> str:
    canon = json.dumps({k: v for k, v in rule.items() if not k.startswith("_")},
                       sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode()).hexdigest()[:12]


def citation(rule: dict) -> str:
    """Human-readable citation string; makes unverified status impossible to miss."""
    s = rule["source"]
    parts = [s["document"]]
    if s.get("edition"):
        parts.append(f"ed. {s['edition']}")
    if s.get("clause"):
        parts.append(f"cl. {s['clause']}")
    elif s.get("section_hint"):
        parts.append(f"section: {s['section_hint']} (clause TBC)")
    text = ", ".join(parts)
    if not s.get("clause_verified") or rule["verification"]["status"] != "user_verified":
        text = "[UNVERIFIED] " + text
    return text
