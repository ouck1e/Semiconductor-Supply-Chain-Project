"""
Pass handoffs along for automated runs of the AI agent team: fill the next agent's prompt with the handoff blocks
from the replies already saved in each run folder. (In manual runs you paste them yourself.)

  python agent_handoff.py <stage> <run_id> [<run_id> ...]      stage = 2, 3, 5 or 6

Replies are saved in the run folder as reply_1.txt (Researcher), reply_2.txt (News Analyst), reply_3.txt
(Strategist) and reply_5.txt (Risk Manager). Each handoff is everything from the reply's last "AGENT:" line to the
end, so the Strategist's PLAN block travels with its handoff. Each prompt gets exactly the handoffs its own
[PASTE ...] placeholders ask for, so older prompt versions are filled the way they were written.
Writes filled_<prompt>.txt in each run folder. Never reads data/agents/keys/.
"""
import re
import sys

import agent_sim as sim

PROMPT = {2: "2_news_analyst.txt", 3: "3_strategist.txt", 5: "5_risk_manager.txt", 6: "6_boss.txt"}
LABEL = {1: "RESEARCHER", 2: "NEWS ANALYST", 3: "STRATEGIST", 5: "RISK MANAGER"}
SLOTS = {   # placeholder text -> which replies' handoffs go there
    "[PASTE THE RESEARCHER'S HANDOFF BLOCK HERE]": [1],
    "[PASTE THE NEWS ANALYST'S HANDOFF BLOCK HERE]": [2],
    "[PASTE THE STRATEGIST'S HANDOFF BLOCK HERE]": [3],
    "[PASTE THE STRATEGIST'S HANDOFF AND PLAN BLOCKS HERE]": [3],
    "[PASTE THE RESEARCHER, NEWS ANALYST, STRATEGIST AND RISK MANAGER HANDOFF BLOCKS HERE]": [1, 2, 3, 5],
}


def handoff(run_dir, n):
    text = (run_dir / f"reply_{n}.txt").read_text(encoding="utf-8")
    starts = [m.start() for m in re.finditer(r"^\**AGENT:", text, re.M)]
    if not starts:
        raise SystemExit(f"{run_dir.name}: reply_{n}.txt has no handoff block")
    return text[starts[-1]:].strip()


def fill(stage, run_dir):
    text = (run_dir / PROMPT[stage]).read_text(encoding="utf-8")
    for ph in re.findall(r"\[PASTE [^\]]*HERE\]", text):
        if ph not in SLOTS:
            raise SystemExit(f"{run_dir.name}: unknown placeholder {ph}")
        ns = SLOTS[ph]
        block = handoff(run_dir, ns[0]) if len(ns) == 1 else \
            "\n\n".join(f"--- {LABEL[n]} ---\n{handoff(run_dir, n)}" for n in ns)
        text = text.replace(ph, block, 1)
    out = run_dir / f"filled_{PROMPT[stage]}"
    out.write_text(text, encoding="utf-8")
    return out


if __name__ == "__main__":
    stage = int(sys.argv[1])
    for rid in sys.argv[2:]:
        print(fill(stage, sim.OUT / "runs" / rid))
