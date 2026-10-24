import json
import shutil
import subprocess

import pytest

from tripcore import webpage

SRC = webpage.TEMPLATE if hasattr(webpage, "TEMPLATE") else ""


def _js() -> str:
    a, b = SRC.index("function mdInline"), SRC.index("function setMsg")
    esc = "const esc = s => String(s).replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));\n"
    return esc + SRC[a:b]


def test_chat_uses_safe_markdown_for_assistant_only():
    assert "function md(" in SRC and "function setMsg(" in SRC
    assert "el.classList.contains('a')" in SRC            # 只有助手的回复走 md，用户的话仍是纯文本
    assert "d.textContent = text" not in SRC.split("function bubble")[1].split("\n")[0]


@pytest.mark.skipif(shutil.which("node") is None, reason="需要 node 来跑页面里的脚本")
def test_md_escapes_html_and_drops_images():
    prog = _js() + "\nconsole.log(JSON.stringify([md(%s), md(%s), md(%s)]));" % (
        json.dumps("<script>alert(1)</script> ![](https://evil.example/a.png)"),
        json.dumps("| a | b |\n|---|---|\n| **x** | <img src=x onerror=1> |"),
        json.dumps("- 一\n- 二"),
    )
    out = json.loads(subprocess.run(["node", "-e", prog], capture_output=True, text=True, check=True).stdout)
    assert "<script" not in out[0] and "&lt;script&gt;" in out[0] and "evil.example" not in out[0] and "<img" not in out[0]
    assert "<table>" in out[1] and "<b>x</b>" in out[1] and "<img" not in out[1] and "&lt;img" in out[1]
    assert out[2] == "<ul><li>一</li><li>二</li></ul>"
