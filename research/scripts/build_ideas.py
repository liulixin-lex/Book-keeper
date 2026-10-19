"""Build research/IDEAS.md: every adoptable idea ID -> project -> text."""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = ["# 可借鉴要点总表", "",
       "从 81 份审查的“可借鉴”一节自动汇总。重构方案文档中的 `[ID]` 引用均指向此表。", "",
       "| ID | 项目 | 要点 |", "|---|---|---|"]
count = 0
for p in sorted((root / "reviews").glob("*/*.md")):
    if p.name.startswith("_"):
        continue
    m = re.search(r"## 可借鉴\n(.*?)(\n## |\Z)", p.read_text(encoding="utf-8"), re.S)
    if not m:
        continue
    repo = p.stem.replace("__", "/", 1)
    rel = p.relative_to(root)
    for idea_id, text in re.findall(r"^- \[([A-Za-z0-9-]+)\]\s*(.+)$", m.group(1), re.M):
        text = text.replace("|", "/").replace("**", "")
        out.append(f"| {idea_id} | [{repo}]({rel}) | {text} |")
        count += 1
(root / "IDEAS.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print("ideas", count)
