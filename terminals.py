import re
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 760
CARD, BAR = "#141821", "#1C2230"
COLORS = {
    "w": "#FFFFFF",
    "m": "#5CE1B1",
    "c": "#FF6B5E",
    "a": "#FFC857",
    "b": "#7FA2FF",
    "u": "#8A93A6",
}
FONT_DIR = Path.home() / "Library/Fonts"
MONO = str(FONT_DIR / "JetBrainsMono[wght].ttf")

TERMINALS = {
    "t-fork": ("fork.c", [
        "{u}// one call. two returns.",
        "{w}pid_t pid = fork();",
        "{w}if (pid == 0)  {u}// I am the child",
        "{w}    printf(\"child got %d\\n\", pid);",
        "{w}else           {u}// I am the parent",
        "{w}    printf(\"parent got %d\\n\", pid);",
        "",
        "{m}$ {w}./fork",
        "{a}parent got 48213",
        "{a}child got 0",
    ]),
    "t-phantom": ("inside sandbox-7f3a", [
        "{m}$ {w}echo $GITHUB_TOKEN",
        "{a}islo_phantom_7f3a_github",
        "{u}# a fake. worthless if it leaks.",
        "",
        "{m}$ {w}git push origin fix-login",
        "{b}gateway {u}(outside the VM){w}: phantom -> real token",
        "{m}To github.com:acme/app.git   pushed",
        "",
        "{m}$ {w}aws s3 ls",
        "{b}gateway{w}: per-sandbox STS session, short-lived",
    ]),
    "t-scoreboard": ("RewardHackBench / Claude Opus 4.7 / cheat hint", [
        "{u}network policy          cheat    fair",
        "{u}---------------------------------------",
        "{c}open network            24/24      -",
        "{w}host blocklist           0.38   0.50",
        "{w}content filter           0.50   0.38",
        "{w}layered                  0.08   0.58",
        "{m}LLM judge on the wire    0.00   0.58",
        "",
        "{u}# lower cheat is better. higher fair is better.",
    ]),
    "t-zenn": ("egress gateway log", [
        "{c}DENY   github.com       {u}blocklist",
        "{c}DENY   *.jina.ai        {u}blocklist",
        "{c}DENY   *.github.io      {u}blocklist",
        "{c}DENY   ctftime.org      {u}blocklist",
        "{a}ALLOW  zenn.dev         {u}# nobody listed it",
        "",
        "{w}agent: found a writeup with the answer",
        "",
        "{u}# a blocklist names the hosts you thought of.",
    ]),
    "t-stale": ("epoch fence / 88-line driver", [
        "{u}# machine A took epoch 1, then froze",
        "{u}# machine B took over with epoch 2",
        "",
        "{w}A wakes up: append(event, epoch=1)",
        "{c}StaleEpoch: cell_...: epoch 1 is no longer current.",
        "",
        "{u}# check and write are ONE SQL statement:",
        "{b}INSERT ... SELECT ... WHERE EXISTS (epoch matches)",
        "{m}# the old machine cannot write. no zombie edits.",
    ]),
    "t-capacity": ("restore fan-out / 141 MB disk snapshot", [
        "{u}concurrency  fan-out   result      p50",
        "{u}--------------------------------------------",
        "{w}12           256       {m}255/256 ok  {a}6.87s",
        "{w}12           64        {m}64/64 ok    {a}7.06s",
        "{w}32           64        {c}3/64 ok",
        "",
        "{u}# above 12 we hit our capacity wall.",
        "{u}# measure your wall before you plan a fleet.",
    ]),
    "t-gitlog": ("SWE-bench #465 / restored task repo", [
        "{m}$ {w}git log --all --oneline",
        "{a}9e1c0f7 {w}Fix the bug you were asked to fix  {c}<- the future",
        "{w}3b2a5d1 {w}the task starts here (HEAD)",
        "{w}...",
        "",
        "{u}# Claude 4 Sonnet and Qwen3-Coder both looked.",
        "{u}# 5 matches in 10,000 trajectories.",
        "{m}# fix: remove future history (swebench 4.1.0)",
    ]),
    "t-pytest": ("Airflow CI / run_unit_tests.sh, before PR #74172", [
        "{m}$ {w}pytest providers ... ; echo $?",
        "{c}=========== 1 failed ===========",
        "{a}1",
        "{w}No DB tests were collected ... treating as success",
        "{m}job: green",
        "",
        "{u}# pytest exit 1 = tests FAILED",
        "{u}# pytest exit 5 = no tests collected",
        "{c}# 192 days. 29 green jobs with a real failing test.",
    ]),
    "t-gate": ("SELFHOST-2 / gate log", [
        "{w}plan gate      9.8 KB plan   opened",
        "{a}+8.1 s         {w}approved by {c}\"human\"",
        "{u}# a script that answers every gate as admin",
        "",
        "{w}harness        {m}1,972 cases, 0 failed",
        "{w}diff           {c}no test for the new code path",
        "",
        "{u}# every agent was honest. the suite was green.",
        "{u}# the branch had no test.",
    ]),
    "t-logs": ("trace kept outside the sandbox", [
        "{m}$ {w}islo logs sandbox-7f3a --type agent",
        "{u}# one audit record per exec, written by the host",
        "",
        "{b}exec  {w}pytest -q",
        "{b}exec  {w}git diff --stat",
        "{b}egress {w}github.com  {m}allowed by gateway",
        "",
        "{u}# the child cannot edit this file.",
    ]),
    "t-boat": ("boat.dev live, 26 Oct 2026, small VM", [
        "{m}$ {w}POST /sandboxes",
        "{a}202 bx_6umwwzxe     {u}ready in 0.29s",
        "{m}$ {w}POST .../fork",
        "{c}409 fork_failed     {u}needs a snapshot",
        "{m}$ {w}POST .../stop",
        "{a}archived in 9.49s   {u}the stop wrote it",
        "{m}$ {w}POST .../fork  ->  cat ~/llmday.txt",
        "{a}202 bx_xnny3tga     {m}the pledge",
        "{m}$ {w}same Idempotency-Key",
        "{a}202 bx_xnny3tga     {u}same id, not a second machine",
    ]),
    "t-basement": ("islo resume fault matrix, run locally", [
        "{u}# the bug: a lost reply on resume",
        "{u}# could leave TWO live VMs for one sandbox",
        "",
        "{u}# invariant, verbatim from the test file:",
        "{w}\"at most one generation is ever serving, and every",
        "{w} generation that stopped short leaves no live",
        "{w} resources behind.\"",
        "",
        "{m}25 passed, 0 failed   {u}(18 fault rows)",
    ]),
}

SEG = re.compile(r"\{([wmcabu])\}")


def segments(line):
    parts = SEG.split(line)
    color = "w"
    out = []
    if parts[0]:
        out.append((color, parts[0]))
    for key, text in zip(parts[1::2], parts[2::2]):
        if text:
            out.append((key, text))
    return out


def render(name, title, lines, out_dir):
    longest = max((sum(len(t) for _, t in segments(l)) for l in lines), default=1)
    body_h = H - 140
    size = min(46, int((W - 120) / (longest * 0.6)), int(body_h / (len(lines) * 1.45)))
    font = ImageFont.truetype(MONO, size)
    title_font = ImageFont.truetype(MONO, 30)
    try:
        font.set_variation_by_axes([500])
        title_font.set_variation_by_axes([600])
    except Exception:
        pass

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=28, fill=CARD)
    d.rounded_rectangle([0, 0, W - 1, 76], radius=28, fill=BAR)
    d.rectangle([0, 48, W - 1, 76], fill=BAR)
    for i, dot in enumerate(["#FF5F57", "#FEBC2E", "#28C840"]):
        cx = 44 + i * 40
        d.ellipse([cx - 12, 26, cx + 12, 50], fill=dot)
    tw = d.textlength(title, font=title_font)
    d.text(((W - tw) / 2, 20), title, font=title_font, fill=COLORS["u"])

    y = 76 + 40
    step = int(size * 1.45)
    for line in lines:
        x = 60
        for key, text in segments(line):
            d.text((x, y), text, font=font, fill=COLORS[key])
            x += d.textlength(text, font=font)
        y += step
    path = out_dir / f"{name}.png"
    img.save(path)
    return path, size


if __name__ == "__main__":
    out = Path(__file__).parent / "img"
    names = sys.argv[1:] or list(TERMINALS)
    for n in names:
        title, lines = TERMINALS[n]
        p, s = render(n, title, lines, out)
        print(f"{p.name} font={s}")
