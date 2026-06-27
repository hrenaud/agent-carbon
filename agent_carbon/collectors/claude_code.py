import glob
import json
import os
from collections.abc import Iterator

from agent_carbon.collectors.base import Collector
from agent_carbon.models import InferenceEvent


def _project_from_cwd(cwd: str) -> str:
    return os.path.basename(cwd.rstrip("/")) or "unknown"


class ClaudeCodeCollector(Collector):
    provider = "anthropic"

    def __init__(self, root: str):
        self.root = os.path.expanduser(root)

    def collect(self) -> Iterator[InferenceEvent]:
        pattern = os.path.join(self.root, "**", "*.jsonl")
        for path in glob.glob(pattern, recursive=True):
            yield from self._parse_file(path)

    def _parse_file(self, path: str) -> Iterator[InferenceEvent]:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message") or {}
                usage = msg.get("usage")
                if not usage:
                    continue
                yield InferenceEvent(
                    provider=self.provider,
                    model=msg.get("model", ""),
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                    cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                    timestamp=obj.get("timestamp", ""),
                    project=_project_from_cwd(obj.get("cwd", "")),
                    session_id=obj.get("sessionId", ""),
                    msg_id=obj.get("uuid", ""),
                )
