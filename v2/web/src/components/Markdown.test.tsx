import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { Markdown } from "./Markdown";

describe("Markdown", () => {
  it("formats an AI answer: bold, lists and tables", () => {
    const text = "**9月收入 ¥54,396.40**\n\n| 指标 | 8月 | 9月 |\n|---|---:|---:|\n| 收入 | ¥8,056.07 | ¥54,396.40 |\n\n- 第一条\n- 第二条";
    const { container } = render(<Markdown>{text}</Markdown>);
    expect(container.querySelector("strong")).toHaveTextContent("9月收入 ¥54,396.40");
    expect(container.querySelectorAll("tbody tr")).toHaveLength(1);
    expect(container.querySelector("td:last-child")).toHaveStyle({ textAlign: "right" });
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.textContent).not.toContain("**");
    expect(container.textContent).not.toContain("|---");
  });

  it("never renders raw HTML or images", () => {
    const { container } = render(<Markdown>{'<img src="https://x.example/a.png">\n\n![x](https://x.example/b.png)\n\n<script>alert(1)</script>'}</Markdown>);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });
});
