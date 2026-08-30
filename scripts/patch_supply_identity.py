from pathlib import Path

p = Path('src/hermes_ultra/skill_supply_chain.py')
s = p.read_text()

def r(old: str, new: str) -> None:
    global s
    if old not in s:
        raise SystemExit('patch context missing: ' + old[:60])
    s = s.replace(old, new, 1)

r('''    def codeload_url(self) -> str:\n        return (\n            f"https://codeload.github.com/{self.owner}/{self.repo}/tar.gz/"\n            f"{self.commit_sha}"\n        )\n\n    def to_dict(self) -> dict[str, str]:\n''', '''    def codeload_url(self) -> str:\n        return (\n            f"https://codeload.github.com/{self.owner}/{self.repo}/tar.gz/"\n            f"{self.commit_sha}"\n        )\n\n    def commit_api_url(self) -> str:\n        return (\n            f"https://api.github.com/repos/{self.owner}/{self.repo}/git/commits/"\n            f"{self.commit_sha}"\n        )\n\n    def to_dict(self) -> dict[str, str]:\n''')

r('''    def fetch(self, source: PinnedSkillSource) -> bytes:\n        data = self._fetcher(source.codeload_url(), self.max_archive_bytes)\n        if len(data) > self.max_archive_bytes:\n            raise SkillSupplyChainError("archive byte cap exceeded")\n        return bytes(data)\n''', '''    def fetch(self, source: PinnedSkillSource) -> bytes:\n        metadata_cap = 1024 * 1024\n        metadata = self._fetcher(source.commit_api_url(), metadata_cap)\n        if len(metadata) > metadata_cap:\n            raise SkillSupplyChainError("commit metadata byte cap exceeded")\n        try:\n            payload = json.loads(bytes(metadata).decode("utf-8"))\n            actual_tree = payload["tree"]["sha"]\n        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:\n            raise SkillSupplyChainError("invalid GitHub commit tree metadata") from exc\n        if not isinstance(actual_tree, str) or not _SHA40_RE.fullmatch(actual_tree):\n            raise SkillSupplyChainError("invalid GitHub commit tree SHA")\n        if actual_tree.lower() != source.tree_sha:\n            raise SkillSupplyChainError("commit tree SHA does not match pinned tree SHA")\n        data = self._fetcher(source.codeload_url(), self.max_archive_bytes)\n        if len(data) > self.max_archive_bytes:\n            raise SkillSupplyChainError("archive byte cap exceeded")\n        return bytes(data)\n''')

r('''    def to_dict(self) -> dict[str, str]:\n        return asdict(self)\n\n\n@dataclass(frozen=True)\nclass QuarantinedSkillArtifact:\n''', '''    def to_dict(self) -> dict[str, str]:\n        return asdict(self)\n\n    def identity_hash(self) -> str:\n        payload = self.to_dict()\n        payload.pop("staged_at", None)\n        return _canonical_hash(payload)\n\n\n@dataclass(frozen=True)\nclass QuarantinedSkillArtifact:\n''')

r('''        files: list[SkillFile] = []\n        regular_count = 0\n        declared_bytes = 0\n''', '''        files: list[SkillFile] = []\n        entry_count = 0\n        declared_bytes = 0\n''')

r('''                for member in archive:\n                    parts = _safe_archive_path(member.name)\n                    if member.isdir():\n                        continue\n                    if not member.isreg():\n                        raise SkillSupplyChainError(\n                            "archive contains unsupported non-regular entry: "\n                            f"{member.name}"\n                        )\n                    regular_count += 1\n                    if regular_count > self.max_files:\n                        raise SkillSupplyChainError("file count cap exceeded")\n''', '''                for member in archive:\n                    parts = _safe_archive_path(member.name)\n                    entry_count += 1\n                    if entry_count > self.max_files:\n                        raise SkillSupplyChainError("archive entry count cap exceeded")\n                    if member.isdir():\n                        continue\n                    if not member.isreg():\n                        raise SkillSupplyChainError(\n                            "archive contains unsupported non-regular entry: "\n                            f"{member.name}"\n                        )\n''')

p.write_text(s)
