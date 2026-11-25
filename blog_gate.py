"""
Blog Quality Gate - version 1 (free, runs on your own laptop)

What it does
1. Checks your blog against your format rules (headings, links, banned words, meta, etc.)
2. Compares the blog with competitor pages: copied text, same headings, missing topics
3. Checks if your real details (examples, observations) actually appear in the blog
4. Gives a verdict: DON'T PUBLISH / FIX FIRST / READY FOR HUMAN REVIEW
5. Builds one prompt you can paste into any free AI chat for a deeper review

Run:
    pip install -r requirements.txt
    streamlit run blog_gate.py

No paid tool or API key is needed.
"""
import re
import statistics
from collections import Counter
from urllib.parse import urlparse

# ----------------------------------------------------------------------------
# Settings you can edit
# ----------------------------------------------------------------------------
DEFAULT_DOMAIN = "vatstudio.in"

DEFAULT_ALLOWED_URLS = """https://vatstudio.in/services/website-development
https://vatstudio.in/services/digital-marketing
https://vatstudio.in/services/ui-ux-design
https://vatstudio.in/services/artificial-intelligence-solutions
https://vatstudio.in/services/business-automation
https://vatstudio.in/services/creative-content-production
https://vatstudio.in/services/cloud-technology-services
https://vatstudio.in/blog/website-development-cost
https://vatstudio.in/blog/website-development-company
https://vatstudio.in/blog/digital-marketing
https://vatstudio.in/blog/ai-chatbots
https://vatstudio.in/blog/mobile-app-development-cost
https://vatstudio.in/blog/custom-software-cost
https://vatstudio.in/blog/brand-identity
https://vatstudio.in/blog/ui-ux-design"""

BANNED_WORDS = [
    "delve", "unlock", "elevate", "seamless", "seamlessly", "robust", "game-changer",
    "game changer", "landscape", "realm", "tapestry", "navigate", "leverage",
    "in today's digital world", "in today's digital landscape", "it is important to note",
    "it's important to note", "furthermore", "moreover", "additionally", "in conclusion",
    "look no further", "let's dive in", "stuck", "turns out", "ping", "hit up",
    "nail it", "deep dive", "this is where", "whether you're a startup",
]

LABEL_LINES = ["quick answer:", "in short:", "key takeaways:", "tl;dr", "last updated"]

STOP = set(
    "a an the and or but of to in on for with at by from is are was were be been it this that "
    "these those you your we our they their as if not no can could should would will do does did "
    "how what why when which who whom into than then so such more most very also about over under "
    "up down out off any all each other some just".split()
)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
LINK_RE = re.compile(r"(\*\*)?\[(\*\*)?([^\]]+?)(\*\*)?\]\((https?://[^)\s]+)\)(\*\*)?")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2B06]")


# ----------------------------------------------------------------------------
# Parsing helpers
# ----------------------------------------------------------------------------
def strip_md(s):
    s = LINK_RE.sub(lambda m: m.group(3), s)
    return re.sub(r"[*`]+", "", s)


def split_meta(text):
    """Pull the meta title and meta description out of the text."""
    meta_title, meta_desc, body = "", "", []
    for line in text.splitlines():
        m1 = re.match(r"^\s*\**\s*meta title\s*\**\s*:\s*\**\s*(.+?)\s*$", line, re.I)
        m2 = re.match(r"^\s*\**\s*meta description\s*\**\s*:\s*\**\s*(.+?)\s*$", line, re.I)
        if m1:
            meta_title = m1.group(1).strip("* ")
        elif m2:
            meta_desc = m2.group(1).strip("* ")
        else:
            body.append(line)
    return meta_title, meta_desc, "\n".join(body)


def parse(body):
    """Return headings [(level, text, h2_index)] and paragraphs [(text, h2_index, kind)]."""
    headings, paras = [], []
    state = {"h2": 0}
    buf = []

    def flush():
        if buf:
            paras.append((" ".join(buf).strip(), state["h2"], "text"))
            buf.clear()

    for line in body.splitlines():
        s = line.strip()
        m = HEADING_RE.match(s)
        if m:
            flush()
            level, text = len(m.group(1)), m.group(2).strip()
            if level == 2:
                state["h2"] += 1
            headings.append((level, text, state["h2"]))
        elif not s:
            flush()
        elif s.startswith("|"):
            flush()
            if not re.match(r"^\|[\s\-:|]+\|?$", s):
                paras.append((s, state["h2"], "table"))
        elif re.match(r"^([-*+]|\d+[.)])\s+", s):
            flush()
            paras.append((re.sub(r"^([-*+]|\d+[.)])\s+", "", s), state["h2"], "list"))
        else:
            buf.append(s)
    flush()
    return headings, paras


def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", text)
    return [p.strip() for p in parts if len(p.split()) >= 3]


def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def shingles(tok, n=8):
    return {" ".join(tok[i:i + n]) for i in range(len(tok) - n + 1)}


def cwords(text):
    return {w for w in tokens(text) if w not in STOP and len(w) > 2}


def jacc(a, b):
    u = a | b
    return len(a & b) / len(u) if u else 0.0


def norm_url(u):
    p = urlparse(u.strip())
    return (p.netloc.lower().replace("www.", "") + p.path.rstrip("/")).lower()


# ----------------------------------------------------------------------------
# Part 1: rule checks
# ----------------------------------------------------------------------------
def run_rules(raw, keyword, domain, allowed_urls):
    meta_title, meta_desc, body = split_meta(raw)
    headings, paras = parse(body)
    checks = []

    def add(name, status, detail=""):
        checks.append({"Check": name, "Result": status, "Details": detail})

    text_paras = [strip_md(p) for p, h, k in paras if k == "text"]
    body_text = " ".join(strip_md(p) for p, h, k in paras if k in ("text", "list"))
    all_text = body_text + " " + " ".join(h[1] for h in headings)
    word_count = len(body_text.split())

    # Meta
    add("Meta title is 60 characters or less",
        "PASS" if meta_title and len(meta_title) <= 60 else "FAIL",
        f"{len(meta_title)} characters" if meta_title else "Meta title not found")
    add("Meta description is 155 characters or less",
        "PASS" if meta_desc and len(meta_desc) <= 155 else "FAIL",
        f"{len(meta_desc)} characters" if meta_desc else "Meta description not found")

    # Headings
    h1s = [h for h in headings if h[0] == 1]
    add("Exactly one H1", "PASS" if len(h1s) == 1 else "FAIL", f"{len(h1s)} H1 found")

    issues, prev = [], 0
    for lvl, t, _ in headings:
        if prev == 0 and lvl != 1:
            issues.append(f"First heading is H{lvl}, not H1")
        elif lvl > prev + 1:
            issues.append(f"'{t}' jumps from H{prev} to H{lvl}")
        prev = lvl
    add("Heading order has no skipped levels", "PASS" if not issues else "FAIL", "; ".join(issues))

    # Links
    links = []
    for pi, (p, h2, kind) in enumerate(paras):
        for m in LINK_RE.finditer(p):
            bold = bool((m.group(1) and m.group(6)) or (m.group(2) and m.group(4)))
            links.append({"anchor": m.group(3).strip(), "url": m.group(5),
                          "bold": bold, "para": pi, "h2": h2})
    dom = domain.lower().replace("www.", "").strip()
    internal = [l for l in links if urlparse(l["url"]).netloc.lower().replace("www.", "").endswith(dom)]
    allowed = {norm_url(u) for u in allowed_urls if u.strip()}

    add("3 to 4 internal links", "PASS" if 3 <= len(internal) <= 4 else "FAIL",
        f"{len(internal)} internal links found")
    unknown = [l["url"] for l in internal if norm_url(l["url"]) not in allowed]
    add("Every internal link is in your allowed URL list", "PASS" if not unknown else "FAIL",
        ", ".join(unknown))
    notbold = [l["anchor"] for l in internal if not l["bold"]]
    add("Internal links are bold", "PASS" if not notbold else "FAIL", ", ".join(notbold))
    longanchor = [l["anchor"] for l in internal if len(l["anchor"].split()) > 4]
    add("Link anchors are 4 words or less", "PASS" if not longanchor else "FAIL", "; ".join(longanchor))
    by_para = Counter(l["para"] for l in internal)
    add("No two links in the same paragraph", "PASS" if all(v == 1 for v in by_para.values()) else "FAIL")
    by_sec = Counter(l["h2"] for l in internal)
    secs = [str(k) for k, v in by_sec.items() if v > 1]
    add("No two links in the same section", "PASS" if not secs else "FAIL",
        "Section numbers with 2+ links: " + ", ".join(secs) if secs else "")
    first_sec = min((l["h2"] for l in internal), default=None)
    add("First link is in the first section",
        "PASS" if first_sec is not None and first_sec <= 1 else "FAIL",
        "No internal links" if first_sec is None else f"First link is in section {first_sec}")

    # Keyword
    k = keyword.lower().strip()
    if k:
        add("Keyword in H1", "PASS" if h1s and k in h1s[0][1].lower() else "FAIL")
        add("Keyword in meta title", "PASS" if k in meta_title.lower() else "FAIL")
        add("Keyword in meta description", "PASS" if k in meta_desc.lower() else "FAIL")
        first100 = " ".join(body_text.split()[:100]).lower()
        add("Keyword in first 100 words", "PASS" if k in first100 else "FAIL")
        add("Keyword in at least one H2",
            "PASS" if any(h[0] == 2 and k in h[1].lower() for h in headings) else "FAIL")
        h2s = [h for h in headings if h[0] == 2]
        conc_text = ""
        if h2s:
            idx = h2s[-1][2]
            conc_text = " ".join(strip_md(p) for p, h, kd in paras if h == idx).lower()
        add("Keyword in conclusion", "PASS" if k in conc_text else "WARN",
            "Check by eye, wording may differ slightly")
        count = body_text.lower().count(k)
        density = count * len(k.split()) / max(1, word_count) * 100
        add("Keyword density about 1% (under 2%)",
            "PASS" if 0 < count and density < 2 else "WARN",
            f"{count} times, {density:.1f}%")

    # Structure
    h2s = [h for h in headings if h[0] == 2]
    add("Last section is the Conclusion",
        "PASS" if h2s and h2s[-1][1].lower().startswith("conclusion") else "FAIL",
        f"Last H2 is '{h2s[-1][1]}'" if h2s else "No H2 found")
    faq = [h for h in h2s if "question" in h[1].lower() or "faq" in h[1].lower()]
    if faq:
        n = len([h for h in headings if h[0] == 3 and h[2] == faq[0][2]])
        add("FAQ has 3 or more questions", "PASS" if n >= 3 else "WARN", f"{n} questions")
    else:
        add("FAQ section exists", "WARN", "No FAQ section found")

    # Style
    low = all_text.lower()
    banned = [w for w in BANNED_WORDS if re.search(r"\b" + re.escape(w) + r"\b", low)]
    add("No banned AI words or phrases", "PASS" if not banned else "FAIL", ", ".join(banned))
    labels = [l for l in LABEL_LINES if l in low]
    add("No label lines (Quick answer, In short...)", "PASS" if not labels else "FAIL", ", ".join(labels))
    add("No em dashes", "PASS" if "\u2014" not in raw else "FAIL", f"{raw.count(chr(0x2014))} found")
    add("No emojis", "PASS" if not EMOJI_RE.search(raw) else "FAIL")

    sents = []
    for p in text_paras:
        sents.extend(sentences(p))
    if len(sents) >= 8:
        lens = [len(s.split()) for s in sents]
        sd = statistics.pstdev(lens)
        short = sum(1 for n in lens if n <= 8) / len(lens)
        add("Sentence rhythm varies (hint only, not proof)",
            "PASS" if sd >= 6 and short >= 0.08 else "WARN",
            f"Spread {sd:.1f} words, {short * 100:.0f}% short sentences. "
            "Low numbers mean the rhythm is very even, which reads as machine-written.")
        starts = [s.split()[0].lower() for s in sents]
        triples = sorted({starts[i] for i in range(len(starts) - 2)
                          if starts[i] == starts[i + 1] == starts[i + 2]})
        add("No 3 sentences in a row start with the same word",
            "PASS" if not triples else "WARN", ", ".join(triples))

    # Sources
    unsourced = []
    for p, h, kind in paras:
        if kind != "text":
            continue
        if "http" in p:
            continue
        for sent in sentences(strip_md(p)):
            if re.search(r"\d+(\.\d+)?\s?%|\bstudy\b|\bresearch\b|\bsurvey\b|according to", sent, re.I):
                unsourced.append(sent[:160])
    add("Statistics and studies have a source link", "PASS" if not unsourced else "WARN",
        " | ".join(unsourced[:5]))

    add("Word count", "INFO", f"{word_count} words")
    return checks, headings, body_text, links


# ----------------------------------------------------------------------------
# Part 2: competitor comparison
# ----------------------------------------------------------------------------
def fetch_page(url):
    import requests
    from bs4 import BeautifulSoup
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; BlogGate/1.0)"}, timeout=20)
        r.raise_for_status()
    except Exception as e:  # network errors, blocked pages, etc.
        return {"url": url, "error": str(e)}
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "form"]):
        tag.decompose()
    heads = [(int(h.name[1]), h.get_text(" ", strip=True))
             for h in soup.find_all(["h1", "h2", "h3"]) if h.get_text(strip=True)]
    text = " ".join(el.get_text(" ", strip=True) for el in soup.find_all(["p", "li"]))
    return {"url": url, "headings": heads, "text": text}


def from_pasted(text, label):
    heads = []
    for line in text.splitlines():
        m = HEADING_RE.match(line.strip())
        if m and len(m.group(1)) in (1, 2, 3):
            heads.append((len(m.group(1)), m.group(2).strip()))
    return {"url": label, "headings": heads, "text": text}


def overlap_report(blog_text, competitors, n=8):
    bsh = shingles(tokens(blog_text), n)
    per, union = {}, {}
    for c in competitors:
        hit = bsh & shingles(tokens(c["text"]), n)
        per[c["url"]] = len(hit) / max(1, len(bsh)) * 100
        for s in hit:
            union.setdefault(s, c["url"])
    overall = len(union) / max(1, len(bsh)) * 100
    flagged = []
    for sent in sentences(blog_text):
        ss = shingles(tokens(sent), n)
        if not ss:
            continue
        m = [s for s in ss if s in union]
        if m and len(m) / len(ss) >= 0.3:
            flagged.append({"Sentence": sent, "Matches": union[m[0]]})
    return overall, per, flagged


def heading_report(blog_headings, blog_text, competitors):
    skip = ("conclusion", "frequently asked", "common questions", "faq")
    skip_secs = {h2 for lvl, t, h2 in blog_headings if lvl == 2 and t.lower().startswith(skip)}
    mine = [t for lvl, t, h2 in blog_headings
            if lvl in (2, 3) and not t.lower().startswith(skip) and h2 not in skip_secs]
    theirs = []
    for c in competitors:
        for lvl, t in c.get("headings", []):
            if lvl in (2, 3) and len(cwords(t)) >= 2:
                theirs.append((t, c["url"]))
    similar, unique = [], []
    for m in mine:
        mw = cwords(m)
        best = max((jacc(mw, cwords(t)) for t, _ in theirs), default=0.0)
        if best >= 0.6:
            similar.append(m)
        elif best < 0.3:
            unique.append(m)
    clusters = []
    for t, u in theirs:
        w = cwords(t)
        for cl in clusters:
            if jacc(w, cl["w"]) >= 0.5:
                cl["urls"].add(u)
                break
        else:
            clusters.append({"rep": t, "w": w, "urls": {u}})
    blog_words = set(tokens(blog_text))
    missing = []
    for cl in clusters:
        if len(cl["urls"]) >= 2:
            covered = len(cl["w"] & blog_words) / len(cl["w"])
            if covered < 0.75:
                missing.append((cl["rep"], len(cl["urls"])))
    missing.sort(key=lambda x: -x[1])
    return similar, unique, missing[:12], len(mine)


# ----------------------------------------------------------------------------
# Part 3: do your real details appear in the blog?
# ----------------------------------------------------------------------------
def detail_report(details_text, blog_text):
    bw = set(tokens(blog_text))
    out = []
    for line in [l.strip() for l in details_text.splitlines() if l.strip()]:
        w = {x for x in cwords(line) if len(x) > 3}
        if w:
            out.append((line, len(w & bw) / len(w) >= 0.5))
    return out


# ----------------------------------------------------------------------------
# Verdict
# ----------------------------------------------------------------------------
def make_verdict(rules, overlap, similar, unique, n_mine, missing, details, flagged):
    hard, fixes = [], []
    if overlap >= 15:
        hard.append(f"{overlap:.0f}% of the blog's 8-word phrases match competitor pages. Too much copied text.")
    if n_mine >= 4 and len(similar) / n_mine >= 0.7 and not unique:
        hard.append("Most headings match competitor headings and none is new. The blog adds nothing new.")
    fails = [c for c in rules if c["Result"] == "FAIL"]
    if fails:
        fixes.append(f"{len(fails)} rule check(s) failed.")
    if 5 <= overlap < 15:
        fixes.append(f"{overlap:.0f}% phrase overlap with competitors. Rewrite the flagged sentences.")
    if len(details) < 2:
        fixes.append("Add at least 2 real details (an example, an observation, a number from your own work).")
    elif any(not used for _, used in details):
        fixes.append("Some of your real details are not used in the blog.")
    if len(missing) >= 3:
        fixes.append(f"{len(missing)} topics that several competitors cover are missing.")
    if hard:
        return "DON'T PUBLISH", hard + fixes
    if fixes:
        return "FIX FIRST", fixes
    return "READY FOR HUMAN REVIEW", ["All automatic checks passed. A person still has to read it and check the facts."]


# ----------------------------------------------------------------------------
# AI prompts: review and actual rewrite
# ----------------------------------------------------------------------------
def competitor_context(competitors, max_chars_each=5000, max_total=18000):
    """Include competitor headings and extracted text, within a safe prompt size."""
    chunks = []
    used = 0
    for c in competitors:
        heads = "\n".join(f"  - {t}" for lvl, t in c.get("headings", []) if lvl in (1, 2, 3))
        page_text = re.sub(r"\s+", " ", c.get("text", "")).strip()
        remaining = max_total - used
        if remaining <= 0:
            break
        page_text = page_text[:min(max_chars_each, remaining)]
        block = (
            f"\nCOMPETITOR PAGE: {c['url']}\n"
            f"HEADINGS:\n{heads or '(headings unavailable)'}\n"
            f"EXTRACTED PAGE TEXT (may be incomplete):\n{page_text or '(page text unavailable)'}\n"
        )
        chunks.append(block)
        used += len(block)
    return "\n".join(chunks) if chunks else "(No competitor page content was successfully collected.)"


def build_prompt(blog, keyword, goal, competitors, details):
    comp = competitor_context(competitors)
    return f"""You are a strict human editor and SEO reviewer. Do not be polite or generic.

TARGET KEYWORD: {keyword or '(not supplied)'}
BUSINESS GOAL: {goal}

REAL DETAILS SUPPLIED BY THE BUSINESS (do not invent additional details):
{details or '(none supplied)'}

COMPETITOR MATERIAL SUPPLIED FOR COMPARISON:
{comp}

ORIGINAL BLOG:
{blog}

Review the article and provide:
1. VERDICT: Publish, Fix first, or Don't publish. Explain in one sentence.
2. WHAT THIS BLOG ADDS compared with the supplied competitor material. Quote exact lines.
3. WHAT IS GENERIC, REPETITIVE, OR TOO SIMILAR. Quote exact lines.
4. WHAT TO REMOVE OR MERGE. Quote exact lines and explain why.
5. WHAT TO ADD. Identify specific missing information, useful examples, or sources.
6. CLAIMS WITHOUT EVIDENCE. Identify statistics, studies, product capabilities, and company claims that need checking.
7. SEARCH INTENT AND BUSINESS GOAL. Explain whether the article satisfies the target keyword's intent and stated goal.
8. A PRIORITIZED CORRECTION CHECKLIST. Make every action specific and traceable to the article.

Rules:
- Use the supplied competitor material only. Do not claim that a page ranks unless ranking evidence was supplied.
- Do not invent search volumes, rankings, client results, statistics, or sources.
- Distinguish verified observations from hypotheses.
- Quote the blog as evidence for every criticism.
- Do not rewrite the article in this review step.
"""


def build_rewrite_prompt(blog, keyword, goal, competitors, details,
                         rules, missing, similar, flagged, detail_rows):
    """Build a separate prompt that requires a full corrected article."""
    comp = competitor_context(competitors)
    failed = [f"- {r['Check']}: {r['Details']}" for r in rules if r["Result"] == "FAIL"]
    warnings = [f"- {r['Check']}: {r['Details']}" for r in rules if r["Result"] == "WARN"]
    missing_text = "\n".join(
        f"- {title} (appears in {count} supplied competitor page(s))"
        for title, count in missing
    ) or "- No repeated competitor topic gaps were detected by the automated heading comparison."
    similar_text = "\n".join(f"- {h}" for h in similar) or "- None detected."
    flagged_text = "\n".join(
        f"- {x['Sentence']} [matched page: {x['Matches']}]"
        for x in flagged
    ) or "- No matching sentences were flagged by the automated phrase check."
    details_text = "\n".join(
        f"- {line} [{'already appears in the blog' if used else 'NOT YET USED in the blog'}]"
        for line, used in detail_rows
    ) or "- No first-hand business details were supplied."
    return f"""ROLE
You are a senior human editor and SEO content strategist. Your job is to produce a corrected, publication-ready version of the complete article.

THIS IS A REWRITE TASK, NOT AN AUDIT TASK.
Do not return another review, a list of suggestions, or a lightly paraphrased copy. You must deliver the complete revised blog and apply the corrections below.

TARGET KEYWORD: {keyword or '(not supplied)'}
BUSINESS GOAL: {goal}

ORIGINAL BLOG (source of truth for existing facts):
<<<ORIGINAL BLOG
{blog}
END ORIGINAL BLOG>>>

REAL BUSINESS DETAILS SUPPLIED BY THE USER:
{details or '(No first-hand details supplied. Do not invent any.)'}

AUTOMATED QUALITY-GATE FINDINGS
Failed checks:
{chr(10).join(failed) or '- None'}

Warnings to review:
{chr(10).join(warnings) or '- None'}

Competitor topics the heading comparison suggests may be missing:
{missing_text}

Your headings that look similar to supplied competitor headings:
{similar_text}

Sentences flagged by the phrase-overlap check:
{flagged_text}

User-provided business details and whether they appear in the article:
{details_text}

SUPPLIED COMPETITOR MATERIAL
The following material is extracted from URLs supplied by the user. Extraction may be incomplete. Treat it as comparison material, not proof of ranking position:
{comp}

MANDATORY EDITING INSTRUCTIONS
1. Read the entire original blog and every finding before rewriting.
2. Preserve verified facts, intended meaning, and relevant business details. Do not change facts.
3. Correct every failed quality-gate rule that can be corrected from the information supplied.
4. Review every warning. Fix it where appropriate; do not force unnatural wording to satisfy a heuristic.
5. Make meaningful editorial changes where the report identifies generic, repetitive, or weak sections. Do not keep the same structure and merely swap synonyms.
6. Remove repeated explanations and combine sections that make the same point.
7. Add missing coverage only when it genuinely helps the reader and is supported by supplied material or reliable sources you can verify. Do not add a competitor topic just because it appears in a heading.
8. Do not copy competitor wording, structure, examples, or distinctive phrasing.
9. Do not invent client stories, company results, observations, statistics, search volumes, rankings, testimonials, or sources. If an example is needed but none was supplied, label it hypothetical or state that first-hand evidence is needed.
10. Do not claim competitors rank on page one unless ranking evidence is supplied.
11. Keep the article aligned with the target keyword's search intent and stated business goal. Use the keyword naturally; do not stuff it.
12. Keep useful, accurate sections even if a competitor covers the same broad subject. Improve the explanation rather than deleting necessary information.
13. Return the complete article, not only changed paragraphs.
14. Do not include an explanation of your edits before or after the article.

OUTPUT FORMAT
Return the complete article with meta title, meta description, one H1, properly ordered H2/H3 headings, article body, FAQs where appropriate, and a final Conclusion section.

FINAL SELF-CHECK
Check the new article against every failed rule and warning listed above. Correct every remaining fixable issue before returning it. After the article, include a short "Unresolved items" list only for things that cannot be fixed without additional facts, access, or user input.
"""


# ----------------------------------------------------------------------------
# Streamlit app
# ----------------------------------------------------------------------------
def main():
    import pandas as pd
    import streamlit as st

    st.set_page_config(page_title="Blog Quality Gate", layout="wide")
    st.title("Blog Quality Gate")
    st.caption("Audit your blog against your rules and supplied competitor pages, then generate a separate prompt that requires a complete corrected rewrite. It cannot predict rankings.")

    col1, col2 = st.columns([3, 2])
    with col1:
        blog = st.text_area("Paste the blog (markdown, with Meta title and Meta description lines at the top)",
                            height=420)
    with col2:
        keyword = st.text_input("Target keyword")
        goal = st.selectbox("Goal of this blog", ["Traffic", "Leads", "Authority"])
        details = st.text_area("Your real details, one per line (client observation, example, number from your work)",
                               height=120)
        comp_urls = st.text_area("Competitor URLs, one per line (3 to 5 pages that rank for this keyword)",
                                 height=110)
        comp_paste = st.text_area("Or paste competitor text here (separate pages with a line containing -----)",
                                  height=90)

    with st.expander("Settings: domain and allowed internal URLs"):
        domain = st.text_input("Your domain", DEFAULT_DOMAIN)
        allowed_text = st.text_area("Allowed internal URLs (one per line)", DEFAULT_ALLOWED_URLS, height=200)

    if not st.button("Check this blog", type="primary"):
        return
    if not blog.strip():
        st.warning("Paste a blog first.")
        return

    rules, headings, body_text, links = run_rules(
        blog, keyword, domain, [u for u in allowed_text.splitlines() if u.strip()])

    competitors, errors = [], []
    with st.spinner("Reading competitor pages..."):
        for u in [x.strip() for x in comp_urls.splitlines() if x.strip()]:
            page = fetch_page(u)
            (errors if "error" in page else competitors).append(page)
    for i, chunk in enumerate([c for c in re.split(r"\n\s*-----+\s*\n", comp_paste) if c.strip()], 1):
        competitors.append(from_pasted(chunk, f"Pasted text {i}"))

    if competitors:
        overlap, per_site, flagged = overlap_report(body_text, competitors)
        similar, unique, missing, n_mine = heading_report(headings, body_text, competitors)
    else:
        overlap, per_site, flagged, similar, unique, missing, n_mine = 0.0, {}, [], [], [], [], 0
    detail_rows = detail_report(details, body_text)

    label, reasons = make_verdict(rules, overlap, similar, unique, n_mine, missing, detail_rows, flagged)
    box = {"DON'T PUBLISH": st.error, "FIX FIRST": st.warning}.get(label, st.success)
    box(f"Verdict: {label}")
    for r in reasons:
        st.write("- " + r)
    if not competitors:
        st.info("No competitor pages were read, so the copy check and topic comparison were skipped. "
                "Add 3 to 5 competitor URLs for a real verdict.")
    for e in errors:
        st.caption(f"Could not read {e['url']}: {e['error']}. Paste its text in the box instead.")

    tabs = st.tabs(["Rules", "Copy check", "Competitors", "To-do list", "AI review prompt", "Corrected blog prompt"])

    with tabs[0]:
        st.dataframe(pd.DataFrame(rules), width="stretch", hide_index=True)

    with tabs[1]:
        st.metric("Phrase overlap with competitors", f"{overlap:.1f}%")
        if per_site:
            st.dataframe(pd.DataFrame([{"Page": u, "Overlap %": round(v, 1)} for u, v in per_site.items()]),
                         width="stretch", hide_index=True)
        if flagged:
            st.write("Sentences to rewrite:")
            st.dataframe(pd.DataFrame(flagged), width="stretch", hide_index=True)
        else:
            st.write("No matching sentences found in the pages you gave. Also run a plagiarism checker such as "
                     "Duplichecker for the rest of the web.")

    with tabs[2]:
        st.write("**Headings that look the same as a competitor's (not new):**")
        st.write(similar or "None")
        st.write("**Your headings that no competitor has (your angle):**")
        st.write(unique or "None")
        st.write("**Topics 2 or more competitors cover that your blog does not:**")
        st.write([f"{t} ({n} sites)" for t, n in missing] or "None found (use at least 3 competitor pages)")

    with tabs[3]:
        st.write("**Add**")
        for t, n in missing:
            st.write(f"- A section on: {t}")
        for line, used in detail_rows:
            if not used:
                st.write(f"- Use this real detail in the blog: {line}")
        if len(detail_rows) < 2:
            st.write("- Real details from your own work (at least 2)")
        st.write("**Remove or rewrite**")
        for f in flagged:
            st.write(f"- Copied phrase: {f['Sentence'][:150]}")
        for h in similar:
            st.write(f"- Heading same as competitors, give it your own angle: {h}")
        for c in rules:
            if c["Result"] == "FAIL":
                st.write(f"- Rule failed: {c['Check']}. {c['Details']}")
        warns = [c for c in rules if c["Result"] == "WARN"]
        if warns:
            st.write("**Check by hand**")
            for c in warns:
                st.write(f"- {c['Check']}. {c['Details']}")

    with tabs[4]:
        st.write("Use this prompt for an independent audit. It asks the AI to diagnose the article, not rewrite it.")
        st.code(build_prompt(blog, keyword, goal, competitors, details), language="text")

    with tabs[5]:
        st.subheader("Generate a corrected blog")
        st.write(
            "Copy this second prompt into your AI chat after the audit. "
            "It requires a complete rewritten article and includes the failed checks, warnings, "
            "competitor material, and supplied business details."
        )
        rewrite_prompt = build_rewrite_prompt(
            blog, keyword, goal, competitors, details,
            rules, missing, similar, flagged, detail_rows
        )
        st.code(rewrite_prompt, language="text")
        st.caption(
            "Competitor extraction can be incomplete or blocked. If a page could not be read, "
            "paste its relevant text into the competitor text box and run the check again."
        )


if __name__ == "__main__":
    main()
