"""Turn the raw transcript into numbered speaker turns, check quotes, and flag callback candidates."""

import re

TURN_LABEL = re.compile(r"^(Agent|Customer|Caller|User):[ \t]*(.*)$", re.I)
WORD_ALIASES = {"ok": "okay", "k": "okay", "alright": "all right", "haa": "haan", "ha": "haan"}

TIMING = re.compile(
    r"\b(?:in (?:\d+|a few|few|half an?) ?(?:min(?:ute)?s?|hours?|hrs?)|\d+ ?(?:min(?:ute)?s?|hours?|hrs?)|"
    r"half an hour|tomorrow|today|tonight|day after|parso|next (?:week|month)|this week|weekend|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|morning|afternoon|evening|"
    r"\d{1,2}(?::\d{2})? ?(?:am|pm|a\.m\.|p\.m\.|o'clock)|after (?:diwali|holi|eid|christmas))\b", re.I)
CONTACT = re.compile(r"\b(?:call|ring|contact|talk|speak|get back|update|inform|tell you|connect|reach|ping|message)\b",
                     re.I)


def dialogue_turns(transcript):
    """Every nonblank line, numbered by its line in the transcript, with the last seen speaker label."""
    turns, speaker = [], "unknown"
    for number, line in enumerate(transcript.splitlines(), 1):
        if not line.strip():
            continue
        if match := TURN_LABEL.match(line.lstrip()):
            speaker = "agent" if match[1].lower() == "agent" else "customer"
            line = match[2]
        turns.append({"id": number, "speaker": speaker, "text": line})
    return turns


def turns_by_id(call):
    """Turn ID -> turn, for checking cited quotes."""
    return {turn["id"]: turn for turn in dialogue_turns(call["transcript"])}


def format_turns(turns, keep=None):
    """Compact 'ID speaker: text' lines. With keep, only those turn IDs, and '...' where turns are skipped."""
    lines, skipped = [], False
    for turn in turns:
        if keep is not None and turn["id"] not in keep:
            skipped = True
            continue
        if skipped and lines:
            lines.append("...")
        skipped = False
        lines.append(f"{turn['id']} {turn['speaker']}: {turn['text']}")
    return "\n".join(lines)


def normalized(text):
    return " ".join(text.casefold().replace("’", "'").split())


def words(text):
    return [WORD_ALIASES.get(word, word) for word in re.findall(r"[a-z0-9']+", normalized(text))]


def quoted_in(quote, text):
    """True when the quote matches the turn, tolerating punctuation, 'ok'/'okay' and small slips."""
    quote_words, text_words = words(quote or ""), words(text or "")
    if not quote_words:
        return False
    if " ".join(quote_words) in " ".join(text_words):
        return True
    available = set(text_words)
    return len(quote_words) >= 3 and sum(word in available for word in quote_words) >= 0.85 * len(quote_words)


def grounded_turn(by_id, turn_id, quote, not_from=None):
    """The cited turn when it exists, its quote matches, and it is not from the excluded speaker."""
    turn = by_id.get(turn_id)
    if turn and quoted_in(quote, turn["text"]) and turn["speaker"] != not_from:
        return turn
    return None


def callback_candidates(turns):
    """Up to eight timed contact proposals answered by the other speaker within two turns: hints for the model."""
    found = []
    for index, turn in enumerate(turns):
        if not (TIMING.search(turn["text"]) and CONTACT.search(turn["text"])):
            continue
        reply = next((later for later in turns[index + 1:index + 3]
                      if later["speaker"] not in (turn["speaker"], "unknown")), None)
        if reply:
            found.append((turn["id"], reply["id"]))
    return found[-8:]
