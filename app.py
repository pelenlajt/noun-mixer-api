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
ALLOW_CREDENTIALS = False  # dla "*" musi być False

app = FastAPI(title="Noun Mixer (PL) API")

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

STOP_LEMMAS = {"co", "kto", "który", "jaki", "t_
