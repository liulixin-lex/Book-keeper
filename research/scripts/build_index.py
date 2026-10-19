"""Build research/INDEX.md from manifest.tsv and review headers."""
import csv
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
rows = list(csv.reader(open(root / "manifest.tsv", encoding="utf-8"), delimiter="\t"))[1:]

CATS = {
    "01-plaintext-accounting": "纯文本复式记账",
    "02-ledger-engines": "账本引擎 / 核心库",
    "03-accounting-libraries": "会计库 / 框架",
    "04-smb-accounting": "中小企业记账",
    "05-erp-accounting": "ERP 会计模块",
    "06-personal-finance": "个人 / 家庭财务",
    "07-import-reconciliation": "导入、分类与对账",
    "08-mcp-ai-access": "MCP / 外部 AI 接入",
    "09-api-specs-standards": "API 规范与标准",
}

out = ["# 记账项目调研索引", "",
       f"共 {len(rows)} 个项目，按 9 个类别存放于 `repos/<类别>/<owner>__<repo>`，逐个审查结果在 `reviews/<类别>/<owner>__<repo>.md`。", "",
       "仓库只读审查，未执行其中任何脚本。", ""]
by_cat = {}
for r in rows:
    by_cat.setdefault(r[0], []).append(r)

for cat, items in by_cat.items():
    out += [f"## {cat} {CATS.get(cat, '')}（{len(items)}）", "",
            "| 项目 | 语言 / 许可证 / 最近提交 | 关注点 | 审查 |",
            "|---|---|---|---|"]
    for r in items:
        repo, focus = r[1], r[3]
        name = repo.replace("/", "__")
        review = root / "reviews" / cat / f"{name}.md"
        meta = ""
        if review.exists():
            m = re.search(r"语言 / 许可证 / 最近提交[：:]\s*(.+)", review.read_text(encoding="utf-8"))
            if m:
                meta = m.group(1).strip()
        meta = meta.replace("|", "/")
        focus = focus.replace("|", "/")
        out.append(f"| [{repo}](https://github.com/{repo}) | {meta} | {focus} | [review](reviews/{cat}/{name}.md) |")
    out.append("")

(root / "INDEX.md").write_text("\n".join(out), encoding="utf-8")
print("rows", len(rows))
