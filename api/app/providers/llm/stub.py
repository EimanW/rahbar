"""A provider with no model and no network.

Use it for every unit test and for CI (section 6): your tests must never call a
real model. It is deterministic: the same input always gives the same output.

It reads the numbered <evidence> blocks that services/generation.py puts in the
prompt, so it also exercises the real prompt builder: it cites the first block, or
declines when there is none.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .base import Completion

_EVIDENCE = re.compile(
    r'<evidence id="(\d+)" source="([^"]*)" section="([^"]*)" page="([^"]*)">\n(.*?)\n</evidence>',
    re.S)


class StubProvider:
    name = "stub"

    def complete(self, messages: list[dict[str, str]], schema: dict[str, Any],
                 temperature: float) -> Completion:
        prompt = messages[-1]["content"]
        blocks = _EVIDENCE.findall(prompt)
        reply: dict[str, Any]
        if not blocks:
            reply = {"reasoning": "stub: nothing was retrieved",
                     "answer": "(stub) No passages were retrieved for this question.",
                     "citations": [], "answered_from_context": False, "confidence": "low"}
        else:
            n, source, section, page, text = blocks[0]
            body = text.split("\n", 1)[-1] if text.startswith("[") else text
            reply = {
                "reasoning": "stub: cites the first retrieved passage",
                "answer": f"(stub) A model would answer here from {len(blocks)} passages. "
                          f"The first one says: {body} [{source} / {section}]",
                "citations": [{"source": source, "section": section,
                               "page": int(page) if page.isdigit() else None}],
                "answered_from_context": True, "confidence": "low",
            }
        return Completion(text=json.dumps(reply), tokens_in=len(prompt.split()),
                          tokens_out=len(str(reply["answer"]).split()))
