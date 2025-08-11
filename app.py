import re
import hashlib
import random
from typing import List, Tuple, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import morfeusz2

# =========================
# CORS
# =========================
ALLOWED_ORIGINS = ["*"]
ALLOW_CREDENTIALS = False

app = FastAPI(title="Noun Mixer (PL) API – safe mode")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Morfeusz – global
# =========================
morf = morfeusz2.Morfeusz()

# =========================
# Pomocnicze
# =========================
WORD_RX = re.compile(r"(\s+|[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+|[0-9]+|[^\sA-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż0-9])")

SAFE_SKIP_WORDS = {"co", "kto", "nic", "niczego", "nikt", "to", "tamto"}
RISKY_PREPS = {"do", "na", "w", "o", "u", "po", "za"}

def is_whitespace(t: str) -> bool:
    return bool(t) and t.isspace()

def is_word(t: str) -> bool:
    return bool(t) and not t.isspace() and t.isalpha()

def stable_seed(*parts: str) -> int:
    h = hashlib.md5(("||".join(parts)).encode("utf-8")).hexdigest()
    return int(h[:16], 16)

def clean_colon_suffix(s: str) -> str:
    if not isinstance(s, str):
        s = str(s) if s is not None else ""
    return s.split(":", 1)[0]

# =========================
# Schematy wej./wyj.
# =========================
class MixIn(BaseModel):
    recipient: str = Field(..., description="Tekst biorcy (do 2000 znaków)")
    donor: str = Field(..., description="Tekst dawcy (do 2000 znaków)")
    strength: float = Field(1.0, ge=0.0, le=1.0)

    @validator("recipient", "donor", pre=True)
    def trim_len(cls, v: str) -> str:
        v = v or ""
        return v[:2000]

class MixOut(BaseModel):
    result: str

# =========================
# Morf: tagi i analiza
# =========================
def parse_tag(tag: str) -> Dict[str, str]:
    if isinstance(tag, bytes):
        tag = tag.decode("utf-8", "ignore")
    parts = str(tag).split(":")
    feats: Dict[str, str] = {"pos": parts[0] if parts else ""}
    for p in parts[1:]:
        if p in {"sg", "pl"}:
            feats["number"] = p
        elif p in {"nom", "gen", "dat", "acc", "inst", "loc", "voc"}:
            feats["case"] = p
        elif p in {"m1", "m2", "m3", "f", "n"}:
            feats["gender"] = p
    return feats

def analyze_token_word(tok: str) -> Tuple[bool, str, str, Dict[str, str]]:
    analyses = morf.analyse(tok)
    for a in analyses:
        if len(a) < 3:
            continue
        info = a[2]
        form  = info[0] if len(info) > 0 else tok
        lemma = info[1] if len(info) > 1 else None
        tag   = info[2] if len(info) > 2 else ""

        if isinstance(lemma, bytes):
            lemma = lemma.decode("utf-8", "ignore")
        if isinstance(tag, bytes):
            tag = tag.decode("utf-8", "ignore")

        lemma_clean = clean_colon_suffix(lemma) if lemma else None

        if isinstance(tag, str) and tag.startswith("subst") and lemma_clean:
            feats = parse_tag(tag)
            return True, lemma_clean, tag, feats
    return False, None, None, {}

def donor_lemmas(text: str) -> List[str]:
    toks = WORD_RX.findall(text)
    out: List[str] = []
    for t in toks:
        if not is_word(t):
            continue
        is_n, lemma, tag, feats = analyze_token_word(t)
        if is_n and lemma:
            out.append(lemma)
    return out

def generate_form(lemma: str, tag: str) -> str:
    variants = morf.generate(lemma, tag)
    if variants:
        v = variants[0]
        if isinstance(v, (list, tuple)) and len(v) > 0:
            return clean_colon_suffix(v[0])
        return clean_colon_suffix(v)
    return clean_colon_suffix(lemma)

def match_casing(src: str, dst: str) -> str:
    return dst.capitalize() if src[:1].isupper() else dst

# =========================
# Endpointy
# =========================
@app.get("/")
def root():
    return {"ok": True, "name": "Noun Mixer (PL) API – safe mode", "version": 1}

@app.post("/mix", response_model=MixOut)
def mix(payload: MixIn):
    rtxt = payload.recipient
    dtxt = payload.donor
    strength = float(payload.strength)

    tokens = WORD_RX.findall(rtxt)
    donors = donor_lemmas(dtxt)

    if not tokens:
        return {"result": ""}
    if not donors:
        return {"result": rtxt}

    rng = random.Random(stable_seed(rtxt, dtxt, f"{strength:.4f}"))

    out: List[str] = []
    for i, t in enumerate(tokens):
        if not is_word(t):
            out.append(t)
            continue

        is_n, lemma_b, tag_b, feats_b = analyze_token_word(t)
        prev_token = tokens[i - 1].lower() if i > 0 else ""

        # Kryteria "bezpiecznej" zamiany:
        if not is_n:
            out.append(t)
            continue
        if feats_b.get("case") != "nom":
            out.append(t)
            continue
        if lemma_b.lower() in SAFE_SKIP_WORDS:
            out.append(t)
            continue
        if prev_token in RISKY_PREPS:
            out.append(t)
            continue

        # losowanie
        if rng.random() > strength:
            out.append(t)
            continue

        donor_lemma = rng.choice(donors)
        try:
            new_form = generate_form(donor_lemma, tag_b) or donor_lemma
        except Exception:
            new_form = donor_lemma
        out.append(match_casing(t, new_form))

    return {"result": "".join(out)}
