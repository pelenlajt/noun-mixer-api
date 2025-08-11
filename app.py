import re
import hashlib
import random
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
import morfeusz2

# --- Konfiguracja CORS (możesz podać swoją domenę WP zamiast "*")
ALLOWED_ORIGINS = ["*"]

app = FastAPI(title="Noun Mixer (PL) API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Morfeusz – jeden globalny obiekt
morf = morfeusz2.Morfeusz()

# Tokenizacja: ZACHOWUJEMY białe znaki jako tokeny
WORD_RX = re.compile(r"(\s+|[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+|[0-9]+|[^\sA-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż0-9])")

def is_whitespace(t: str) -> bool:
    return bool(t) and t.isspace()

def is_word(t: str) -> bool:
    return bool(t) and not t.isspace() and t.isalpha()

def stable_seed(*parts: str) -> int:
    h = hashlib.md5(("||".join(parts)).encode("utf-8")).hexdigest()
    # weź 8 bajtów, zamień na int
    return int(h[:16], 16)

class MixIn(BaseModel):
    recipient: str = Field(..., description="Tekst biorcy (do 2000 znaków)")
    donor: str = Field(..., description="Tekst dawcy (do 2000 znaków)")
    strength: float = Field(1.0, ge=0.0, le=1.0, description="0..1 – jaki odsetek rzeczowników podmienić")

    @validator("recipient", "donor", pre=True)
    def trim_len(cls, v: str) -> str:
        v = v or ""
        return v[:2000]

class MixOut(BaseModel):
    result: str

def analyze_token_word(tok: str):
    """
    Zwraca (is_noun, lemma, tag_str, feats_dict)
    tag_str w stylu 'subst:sg:gen:m2'
    feats_dict: {'pos':'subst','number':'sg','case':'gen','gender':'m2'...}
    """
    analyses = morf.analyse(tok)
    # analyses: lista krotek (start, end, (form, lemma, tag))
    for _, _, (form, lemma, tag) in analyses:
        # Morfeusz – rzeczownik to 'subst'
        if tag.startswith("subst"):
            feats = parse_tag(tag)
            return True, lemma, tag, feats
    return False, None, None, {}

def parse_tag(tag: str):
    """
    Morfeuszowe tagi są dwukropkowe, np:
      subst:sg:gen:m2
    Niektóre wersje dodają dodatkowe cechy – bierzemy kluczowe.
    """
    parts = tag.split(":")
    feats = {"pos": parts[0] if parts else ""}
    # heurystycznie wyciągamy number, case, gender
    for p in parts[1:]:
        if p in {"sg", "pl"}:
            feats["number"] = p
        elif p in {"nom","gen","dat","acc","inst","loc","voc"}:
            feats["case"] = p
        elif p in {"m1","m2","m3","f","n"}:
            feats["gender"] = p
    return feats

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
    """
    Używamy dokładnie TEGO SAMEGO tagu, który miał biorca,
    tylko z inną lemą. morfeusz.generate(lemma, tag)
    zwraca listę (form, lemma, tag) – bierzemy pierwszą pasującą.
    """
    variants = morf.generate(lemma, tag)
    if variants:
        return variants[0][0]  # surface form
    return lemma

def match_casing(src: str, dst: str) -> str:
    return dst.capitalize() if src[:1].isupper() else dst

@app.get("/")
def root():
    return {"ok": True, "name": "Noun Mixer (PL) API", "version": 1}

@app.post("/mix", response_model=MixOut)
def mix(payload: MixIn):
    rtxt = payload.recipient
    dtxt = payload.donor
    strength = float(payload.strength)

    # Tokeny z biorcy (ze spacjami włącznie)
    tokens = WORD_RX.findall(rtxt)
    donors = donor_lemmas(dtxt)

    if not tokens:
        return {"result": ""}
    if not donors:
        # brak rzeczowników w dawcy -> zwracamy oryginał
        return {"result": rtxt}

    rng = random.Random(stable_seed(rtxt, dtxt, f"{strength:.4f}"))

    out: List[str] = []
    for t in tokens:
        if not is_word(t):
            out.append(t)
            continue
        is_n, lemma_b, tag_b, feats_b = analyze_token_word(t)
        if not is_n:
            out.append(t)
            continue
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
