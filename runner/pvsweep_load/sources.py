"""Public datasets used by Pharmacovigilance Sweep, pinned to exact revisions.

Nothing here is committed to the repository: files are read at load time straight from the
Hugging Face Hub. Licences are recorded in REF.DATA_SOURCE with every load.
"""

from __future__ import annotations

from dataclasses import dataclass

HF = "https://huggingface.co/datasets"


@dataclass(frozen=True)
class Source:
    key: str
    repo: str
    revision: str
    licence: str
    attribution: str

    def url(self, path: str) -> str:
        return f"{HF}/{self.repo}/resolve/{self.revision}/{path}"


FAERS = Source(
    key="faers",
    repo="alexcpn/fda-faers-parquet",
    revision="616858a29efe3ffe3b42526f23513ee45d1397d0",
    licence="CC0-1.0",
    attribution="US FDA Adverse Event Reporting System (FAERS) quarterly files, Parquet copy by alexcpn",
)

VAERS_NARRATIVES = Source(
    key="vaers_narratives",
    repo="chrisvoncsefalvay/vaers-narrative-generation",
    revision="29aeb0b96763dbff46fd2d2115f89e9221e58869",
    licence="CC0-1.0",
    attribution="US CDC/FDA Vaccine Adverse Event Reporting System (VAERS), prepared by Chris von Csefalvay",
)

VAERS_OUTCOMES = Source(
    key="vaers_outcomes",
    repo="chrisvoncsefalvay/vaers-outcomes",
    revision="cd4d8d23e222c04f8d76e8328cadfd72451711fa",
    licence="Apache-2.0",
    attribution="US CDC/FDA Vaccine Adverse Event Reporting System (VAERS), prepared by Chris von Csefalvay",
)

# EU and EEA countries as FAERS occurrence country codes.
EU_EEA = (
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "IE", "IT", "LV", "LT",
    "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO",
)

# The fictional MAH's portfolio: FAERS active-ingredient strings that count as each substance.
# Salts are included; desvenlafaxine is a different substance and is excluded on purpose.
PORTFOLIO: dict[str, tuple[str, ...]] = {
    "sertraline": ("SERTRALINE", "SERTRALINE HYDROCHLORIDE"),
    "escitalopram": ("ESCITALOPRAM", "ESCITALOPRAM OXALATE"),
    "duloxetine": ("DULOXETINE", "DULOXETINE HYDROCHLORIDE"),
    "venlafaxine": ("VENLAFAXINE", "VENLAFAXINE HYDROCHLORIDE", "VENLAFAXINE BESYLATE"),
}
