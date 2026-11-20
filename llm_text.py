"""
Schritt 5: Erklärtext nur aus geprüften Zahlen.

5a  Tabelle der geprüften Werte: jede Zahl, die im Text stehen darf,
    fertig formatiert (deutsches Format) und mit kurzer ID (z. B. B2.3).
5b  Zahlen-Check: Hinter jeder Zahl im Text steht ihre ID in eckigen Klammern.
    Der Code prüft, dass die Zahl genau zu dieser ID passt.
5c  Fakten und Ersatztext: feste Satzvorlagen, gebaut aus den Tabellentexten.
5d  LLM-Aufruf (Groq oder Anthropic), zweiter Versuch, Log, sonst Ersatztext.

Wichtig: Die Fakten-Sätze benutzen GENAU die Texte aus der Tabelle,
inklusive ID. Dadurch können Sätze und Tabelle nie auseinanderlaufen.
"""

import datetime
import json
import os
import re
import time

import numpy as np
import pandas as pd
from dotenv import load_dotenv

import einstellungen


# ===============================================================
# 5a: Zahlen deutsch formatieren
# ===============================================================
MINUS = "−"  # echtes Minuszeichen, nicht der Bindestrich

EINHEIT = {
    "euro": " €",
    "prozent": " %",          # Wert ist schon in Prozent (z. B. -22.06)
    "quote_prozent": " %",    # Wert ist ein Anteil (z. B. 0.0191) -> wird ×100 angezeigt
    "pp": " Prozentpunkte",   # Differenz zweier Anteile -> ×100
    "zahl": "",
}


def zahl_de(wert: float, stellen: int) -> str:
    """1234.5 -> '1.234,50' (bei stellen=2). Ohne Vorzeichen."""
    text = f"{abs(wert):,.{stellen}f}"                       # '1,234.50'
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def formatiere(wert, art: str, stellen: int = 0, vorzeichen: bool = False) -> str:
    """Formatiert einen Wert für Tabelle und Text.

    vorzeichen=True: positive Werte bekommen ein '+' (für Änderungen).
    Negative Werte bekommen immer ein '−'. Gerundet 0 bekommt kein Vorzeichen.
    """
    if wert is None or pd.isna(wert):
        return "kein Wert"
    if art in ("quote_prozent", "pp"):
        wert = wert * 100
    text = zahl_de(wert, stellen)
    if set(text) <= set("0.,"):          # z. B. '0' oder '0,00'
        return text + EINHEIT[art]
    if wert < 0:
        text = MINUS + text
    elif vorzeichen:
        text = "+" + text
    return text + EINHEIT[art]


# Wie wird welche Kennzahl angezeigt? (Art, Nachkommastellen)
FORMAT = {
    "ausgaben": ("euro", 0), "kaufwert_meta": ("euro", 0), "umsatz": ("euro", 0),
    "umsatz_fb": ("euro", 0), "rabatt": ("euro", 0),
    "aov": ("euro", 2), "aov_meta": ("euro", 2), "cpa": ("euro", 2), "cpm": ("euro", 2),
    "roas": ("zahl", 2), "roas_shopify": ("zahl", 2),
    "ctr": ("quote_prozent", 2), "cr": ("quote_prozent", 2),
    "impressionen": ("zahl", 0), "klicks": ("zahl", 0), "kaeufe_meta": ("zahl", 0),
    "bestellungen": ("zahl", 0), "bestellungen_fb": ("zahl", 0),
}

# Lesbare Namen für Text und Tabelle (ohne Ziffern, sonst stören sie den Check)
# Shopify-Namen sagen immer dazu, welche Bestellungen gemeint sind:
#   "alle Kanäle"   = jede Bestellung im Shop
#   "nur Facebook"  = nur Bestellungen mit utm_source = facebook
NAMEN = {
    "ausgaben": "Ausgaben", "kaufwert_meta": "Meta-Kaufwert", "umsatz": "Shopify-Umsatz (alle Kanäle)",
    "umsatz_fb": "Shopify-Umsatz, nur Facebook", "rabatt": "Rabatte (Shopify, alle Kanäle)",
    "aov": "Shopify-AOV (alle Kanäle)", "aov_meta": "Meta-AOV", "cpa": "CPA", "cpm": "CPM",
    "roas": "ROAS", "roas_shopify": "Shopify-ROAS (nur Facebook)", "ctr": "CTR", "cr": "Conversion-Rate",
    "impressionen": "Impressionen", "klicks": "Klicks", "kaeufe_meta": "Meta-Käufe",
    "bestellungen": "Shopify-Bestellungen (alle Kanäle)",
    "bestellungen_fb": "Shopify-Bestellungen, nur Facebook",
}

# Gesamt-Kennzahlen, die in die Tabelle kommen:
# die sieben aus dem V1-Plan plus das, was die Sätze zu Meta und Shopify brauchen.
GESAMT_IM_TEXT = [
    "ausgaben", "roas", "cpa", "ctr", "bestellungen", "umsatz", "aov",   # V1-Plan
    "kaeufe_meta", "kaufwert_meta", "roas_shopify", "rabatt",            # Gesamtbild
    "bestellungen_fb", "umsatz_fb",                                      # Meta gegen Shopify
]

# Namen der Effizienz-Bausteine im Text
BAUSTEIN_NAMEN = {
    "cpm": "CPM (Preis für Reichweite)",
    "ctr": "CTR",
    "cr": "Conversion-Rate",
    "aov_meta": "Meta-AOV",
}


# ===============================================================
# 5a: Die Tabelle der geprüften Werte (mit kurzen IDs)
# ===============================================================
class WerteTabelle:
    """Sammelt alle Zahlen, die im Text vorkommen dürfen.

    Jede Zeile bekommt eine KURZE ID, die das LLM leicht abschreiben kann:
      Z1, Z2 ...   Zeitraum
      G1, G2 ...   Gesamtbild
      M1, M2 ...   Meta gegen Shopify
      B2.1 ...     Befund auf Rang 2
      N1           die Zahl 0
    Die lange ID (lang_id) und die Bedeutung stehen daneben.

    neu(...) gibt "Text [ID]" zurück, z. B. "−618 € [B2.3]".
    Die Fakten-Sätze benutzen genau diesen Rückgabewert.

    Spalte "richtung": "+" oder "−" bei Zahlen MIT Vorzeichen (Änderungen, Beiträge),
    sonst leer (z. B. "965 €" diese Woche oder ein Anteil). Damit prüft der
    Richtungs-Check, ob "stieg"/"sank" im Text zum Vorzeichen passt.
    """

    def __init__(self):
        self.zeilen = []
        self.zaehler = {}
        self.bereich = "N"
        self.basis_name = "Vorwoche"   # wird in baue_fakten gesetzt ("typische Woche" oder "Vorwoche")
        self.null = self.neu("null", "die Zahl Null (z. B. 'auf 0 gefallen')", 0, "zahl")

    def _kurze_id(self) -> str:
        nummer = self.zaehler.get(self.bereich, 0) + 1
        self.zaehler[self.bereich] = nummer
        trenner = "." if self.bereich.startswith("B") else ""
        return f"{self.bereich}{trenner}{nummer}"

    def eintragen(self, lang_id: str, bedeutung: str, wert, text: str, richtung: str = "") -> str:
        """Trägt einen fertig formatierten Text ein und gibt 'Text [ID]' zurück."""
        if any(z["lang_id"] == lang_id for z in self.zeilen):
            raise ValueError(f"lang_id doppelt in der Werte-Tabelle: {lang_id}")
        kurz = self._kurze_id()
        self.zeilen.append({"id": kurz, "lang_id": lang_id, "bedeutung": bedeutung,
                            "wert": wert, "text": text, "richtung": richtung})
        return f"{text} [{kurz}]"

    def neu(self, lang_id: str, bedeutung: str, wert, art: str,
            stellen: int = 0, vorzeichen: bool = False) -> str:
        """Formatiert einen Wert, trägt ihn ein und gibt 'Text [ID]' zurück.

        Nur Werte mit Vorzeichen (vorzeichen=True) bekommen eine Richtung.
        Eine Änderung von genau 0 hat keine Richtung.
        """
        richtung = ""
        if vorzeichen and pd.notna(wert) and float(wert) != 0:
            richtung = "+" if float(wert) > 0 else MINUS
        return self.eintragen(lang_id, bedeutung, wert, formatiere(wert, art, stellen, vorzeichen), richtung)

    def als_tabelle(self) -> pd.DataFrame:
        return pd.DataFrame(self.zeilen)


def stellen_fuer(wert, art: str, stellen: int) -> int:
    """Stückzahlen im Median können halb sein (z. B. 18,5 Käufe). Dann 1 Nachkommastelle zeigen,
    sonst sähe '18 → 12 (−35 %)' falsch gerechnet aus."""
    if art == "zahl" and stellen == 0 and pd.notna(wert) and float(wert) != round(float(wert)):
        return 1
    return stellen


def kennzahl_werte(t: WerteTabelle, praefix: str, ebene: str, zeile: pd.Series) -> dict:
    """Legt für eine Kennzahl vier Zeilen an: diese Woche, Vergleichswert, Änderung, Änderung in %.

    Vergleichswert = typische Woche (Median) oder Vorwoche, siehe t.basis_name.
    Bei Quoten in Prozent (CTR, CR) ist die Änderung in Prozentpunkten angegeben,
    die relative Änderung in % zusätzlich.
    """
    k = zeile["kennzahl"]
    art, stellen = FORMAT[k]
    name = f"{NAMEN[k]} ({ebene})"
    w = {"name": NAMEN[k], "art": art}
    w["diese"] = t.neu(f"{praefix}.{k}.diese_woche", f"{name}, diese Woche",
                       zeile["diese_woche"], art, stellen)
    w["basis"] = t.neu(f"{praefix}.{k}.basis", f"{name}, {t.basis_name}",
                       zeile["basis"], art, stellen_fuer(zeile["basis"], art, stellen))
    if art == "quote_prozent":
        w["abs"] = t.neu(f"{praefix}.{k}.aenderung_pp", f"{name}, Änderung in Prozentpunkten",
                         zeile["aenderung_abs"], "pp", 2, vorzeichen=True)
    else:
        w["abs"] = t.neu(f"{praefix}.{k}.aenderung", f"{name}, Änderung",
                         zeile["aenderung_abs"], art, stellen_fuer(zeile["aenderung_abs"], art, stellen),
                         vorzeichen=True)
    w["prozent"] = t.neu(f"{praefix}.{k}.aenderung_prozent", f"{name}, Änderung in % (relativ)",
                         zeile["aenderung_prozent"], "prozent", 0, vorzeichen=True)
    return w


def kurz_name(name: str) -> str:
    """'Retargeting – Warenkorb' -> 'retargeting_warenkorb' (für lange IDs)."""
    return re.sub(r"[^a-z0-9äöüß]+", "_", name.lower()).strip("_")


# ===============================================================
# 5c: Hilfen für Sätze
# ===============================================================
def verbinde(teile: list) -> str:
    """['a', 'b', 'c'] -> 'a, b und c'"""
    if len(teile) <= 1:
        return "".join(teile)
    return ", ".join(teile[:-1]) + " und " + teile[-1]


def richtung(wert: float, plus: str, minus: str) -> str:
    """Wählt das Wort passend zur Richtung, z. B. 'mehr Budget' / 'weniger Budget'."""
    return plus if wert > 0 else minus


def treiber_satz(gesamt_wert: float, teile: list) -> str:
    """Satz über die Treiber einer Änderung.

    teile: Liste von (wort, beitrag_wert, beitrag_text, anteil_text)

    Zeigen alle Teile in dieselbe Richtung wie die Gesamtänderung:
        -> Prozent-Anteile ("Davon entfallen 63 % (−871 €) auf weniger Bestellungen ...")
    Laufen Teile gegeneinander:
        -> keine Anteile, sondern wer getrieben und wer entgegengewirkt hat.
    """
    vorzeichen_gesamt = np.sign(gesamt_wert)
    gleich = all(np.sign(b) == vorzeichen_gesamt for _, b, _, _ in teile if b != 0)

    if gleich:
        stuecke = [f"{anteil} ({beitrag}) auf {wort}" for wort, _, beitrag, anteil in teile]
        return f"Davon entfallen {verbinde(stuecke)}."

    treibend = [f"{wort} ({beitrag})" for wort, b, beitrag, _ in teile if np.sign(b) == vorzeichen_gesamt]
    gegen = [f"{wort} ({beitrag})" for wort, b, beitrag, _ in teile if np.sign(b) == -vorzeichen_gesamt]
    return f"Getrieben wurde das durch {verbinde(treibend)}; entgegen wirkte {verbinde(gegen)}."


def nullgrund_lesbar(werte: pd.DataFrame, null: str) -> str:
    """Begründung in Worten, warum die Treiber nicht berechenbar sind.

    werte: Vergleichstabelle einer Kampagne, Index = kennzahl
    null:  der Tabellentext für die Zahl 0, z. B. "0 [N1]"
    """
    grundzahlen = ["ausgaben", "impressionen", "klicks", "kaeufe_meta", "kaufwert_meta"]
    diese = [NAMEN[k] for k in grundzahlen if werte.loc[k, "diese_woche"] == 0]
    basis = [NAMEN[k] for k in grundzahlen if werte.loc[k, "basis"] == 0]
    if diese:
        return f"weil in dieser Woche {verbinde(diese)} auf {null} gefallen sind"
    if basis:
        return f"weil im Vergleichswert {verbinde(basis)} bei {null} lagen"
    return "weil ein Wert fehlt"


# ===============================================================
# 5a + 5c: Werte-Tabelle und Fakten für eine Woche bauen
# ===============================================================
def baue_fakten(e: dict):
    """Baut aus dem Analyse-Ergebnis (analyse.analysiere_woche) zwei Dinge:

    werte   Tabelle der geprüften Werte (id, lang_id, bedeutung, wert, text)
    fakten  {"gesamtbild": [Sätze], "befunde": [{"kampagne", "rang", "geringe_fallzahl", "saetze"}]}

    Alle Zahlen in den Sätzen tragen ihre ID, z. B. "−618 € [B2.3]".
    Die Fakten sind zugleich der Ersatztext und das Material für das LLM.
    """
    t = WerteTabelle()
    woche, vorwoche = e["woche"], e["vorwoche"]
    typisch = e["vergleich_art"] == "typisch"
    # So heißt der Vergleichswert in Tabelle und Sätzen
    t.basis_name = "typische Woche" if typisch else "Vorwoche"
    vgl = "typisch" if typisch else "Vorwoche"           # Kurzform in Klammern: "(typisch 1.594 €)"
    g = e["vergleich_gesamt"].set_index("kennzahl", drop=False)

    # --- Zeitraum ---
    t.bereich = "Z"
    b_wochen = e["basis_wochen"]
    zeit = {}
    for lang_id, bedeutung, datum in [
        ("zeit.woche_von", "erster Tag der Woche", woche),
        ("zeit.woche_bis", "letzter Tag der Woche", woche + pd.Timedelta(days=6)),
        ("zeit.basis_von", f"erster Tag der Vergleichszeit ({t.basis_name})", b_wochen[0]),
        ("zeit.basis_bis", f"letzter Tag der Vergleichszeit ({t.basis_name})", b_wochen[-1] + pd.Timedelta(days=6)),
    ]:
        zeit[lang_id] = t.eintragen(lang_id, bedeutung, datum, datum.strftime("%d.%m.%Y"))
    kw = t.neu("zeit.kw", "Kalenderwoche", woche.isocalendar().week, "zahl")

    if typisch:
        n = t.neu("zeit.anzahl_basiswochen", "Anzahl Wochen für die typische Woche", len(b_wochen), "zahl")
        vergleich_satz = (f"verglichen mit einer typischen Woche der letzten {n} Wochen (Median der Wochen "
                          f"vom {zeit['zeit.basis_von']} bis {zeit['zeit.basis_bis']}). "
                          f"„typisch“ heißt im Folgenden: Wert dieser typischen Woche.")
    else:
        vergleich_satz = (f"verglichen mit der Vorwoche ({zeit['zeit.basis_von']} bis {zeit['zeit.basis_bis']}), "
                          f"weil es für eine typische Woche noch zu wenige frühere Wochen gibt.")

    # --- Gesamt-Kennzahlen: nur die, die ein Satz benutzt (kleine Tabelle) ---
    t.bereich = "G"
    gw = {k: kennzahl_werte(t, "gesamt", "gesamt", g.loc[k]) for k in GESAMT_IM_TEXT}

    gesamtbild = [
        f"Woche vom {zeit['zeit.woche_von']} bis {zeit['zeit.woche_bis']} (KW {kw}), {vergleich_satz}",

        f"Meta: Ausgaben {gw['ausgaben']['diese']} ({vgl} {gw['ausgaben']['basis']}, "
        f"{gw['ausgaben']['prozent']}). Meta-Kaufwert {gw['kaufwert_meta']['diese']} ({vgl} "
        f"{gw['kaufwert_meta']['basis']}, {gw['kaufwert_meta']['abs']}, {gw['kaufwert_meta']['prozent']}). "
        f"ROAS {gw['roas']['diese']} ({vgl} {gw['roas']['basis']}), Shopify-ROAS nur aus Facebook-Bestellungen "
        f"{gw['roas_shopify']['diese']} "
        f"({vgl} {gw['roas_shopify']['basis']}). CPA {gw['cpa']['diese']} ({vgl} {gw['cpa']['basis']}), "
        f"CTR {gw['ctr']['diese']} ({vgl} {gw['ctr']['basis']}, {gw['ctr']['abs']}).",
    ]

    # Budget gegen Effizienz (gesamt)
    budget = g.loc["ausgaben", "euro_wirkung"]
    effizienz = g.loc["roas", "euro_wirkung"]
    kaufwert_delta = g.loc["kaufwert_meta", "aenderung_abs"]
    if pd.notna(budget) and pd.notna(effizienz):
        gesamtbild.append("Beim Meta-Kaufwert insgesamt: " + budget_effizienz_satz(
            t, "gesamt", kaufwert_delta, budget, effizienz))
    else:
        gesamtbild.append("Die Treiber des Meta-Kaufwerts insgesamt sind nicht berechenbar, "
                          "weil ein Wert fehlt oder auf null gefallen ist.".replace("null", t.null))

    gesamtbild.append(
        f"Shopify gesamt, alle Kanäle: Umsatz {gw['umsatz']['diese']} ({vgl} {gw['umsatz']['basis']}, "
        f"{gw['umsatz']['prozent']}), {gw['bestellungen']['diese']} Bestellungen ({vgl} "
        f"{gw['bestellungen']['basis']}), AOV {gw['aov']['diese']} ({vgl} {gw['aov']['basis']}, "
        f"{gw['aov']['prozent']}). Rabatte: {gw['rabatt']['diese']} ({vgl} {gw['rabatt']['basis']})."
    )

    # Rabatt-Regel: AOV markiert UND Rabatte in dieser Woche -> nur als zeitliches
    # Zusammentreffen nennen, nie als Ursache (die Daten zeigen keinen Zusammenhang).
    pflicht_rabatt = []
    if g.loc["aov", "markiert"] and g.loc["rabatt", "diese_woche"] > 0:
        wort = richtung(g.loc["aov", "aenderung_abs"], "Der Anstieg", "Der Rückgang")
        gesamtbild.append(
            f"{wort} des Shopify-AOV aller Kanäle ({gw['aov']['prozent']}) fällt zeitlich zusammen mit Rabatten von "
            f"{gw['rabatt']['diese']} in dieser Woche ({vgl} {gw['rabatt']['basis']}). Ob die Rabatte "
            f"die Ursache sind, zeigen die Daten nicht: Ursache unklar."
        )
        pflicht_rabatt = ["Rabatt", "zeitlich zusammen", "unklar"]   # genau, sonst zählt "setzte sich zusammen"

    # Umsatz-Zerlegung, falls markiert und berechenbar
    z = e["zerlegungen"]
    uz = z[(z["ebene"] == "Gesamt") & (z["kennzahl"] == "umsatz")]
    if len(uz) and uz["status"].iloc[0] == "ok":
        woerter = {"bestellungen": ("mehr Bestellungen", "weniger Bestellungen"),
                   "aov": ("größere Warenkörbe (AOV)", "kleinere Warenkörbe (AOV)")}
        teile = []
        for _, r in uz.iterrows():
            b = r["baustein"]
            teile.append((richtung(r["beitrag"], *woerter[b]), r["beitrag"],
                          t.neu(f"gesamt.umsatz.treiber.{b}.beitrag", f"Beitrag {b} zur Umsatz-Änderung",
                                r["beitrag"], "euro", 0, vorzeichen=True),
                          t.neu(f"gesamt.umsatz.treiber.{b}.anteil", f"Anteil {b} an der Umsatz-Änderung",
                                r["anteil_prozent"], "prozent", 0)))
        gesamtbild.append("Beim Shopify-Umsatz aller Kanäle: " + treiber_satz(g.loc["umsatz", "aenderung_abs"], teile))
    elif len(uz):
        gesamtbild.append(f"Die Treiber des Shopify-Umsatzes sind nicht berechenbar, "
                          f"weil ein Wert bei {t.null} liegt.")

    t.bereich = "M"
    ms_saetze, feste_hinweise, pflicht_ms = meta_shopify_saetze(t, e["meta_gegen_shopify"], gw)
    gesamtbild += ms_saetze
    pflicht_gesamtbild = sorted(set(pflicht_ms + pflicht_rabatt))

    # --- Befunde (nur die im Text) ---
    befunde = []
    vk = e["vergleich_kampagnen"]
    ketten = e["kaufwert_ketten"]
    beitraege = e["kampagnen_beitraege"]

    for _, bef in e["befunde"][e["befunde"]["im_text"]].iterrows():
        kampagne = bef["kampagne"]
        t.bereich = f"B{int(bef['rang'])}"
        p = f"kampagne.{kurz_name(kampagne)}"
        werte = vk[vk["kampagne"] == kampagne].set_index("kennzahl", drop=False)

        # Kennzahlen dieser Kampagne in die Tabelle: Kaufwert, Käufe und alle markierten
        noetig = ["kaufwert_meta", "kaeufe_meta"] + \
            [k for k in werte.index[werte["markiert"]] if k not in ("kaufwert_meta", "kaeufe_meta")]
        kw_ = {k: kennzahl_werte(t, p, kampagne, werte.loc[k]) for k in noetig}

        saetze = [f"{kampagne}: Meta-Kaufwert {kw_['kaufwert_meta']['diese']} ({vgl} "
                  f"{kw_['kaufwert_meta']['basis']}, {kw_['kaufwert_meta']['abs']}, "
                  f"{kw_['kaufwert_meta']['prozent']})."]

        if bef["geringe_fallzahl"]:
            saetze.append(f"Achtung, geringe Fallzahl: {kw_['kaeufe_meta']['diese']} Meta-Käufe in dieser "
                          f"Woche ({vgl} {kw_['kaeufe_meta']['basis']}).")

        if bef["treiber_status"] == "ok":
            saetze.append(budget_effizienz_satz(t, p, bef["kaufwert_aenderung"],
                                                bef["budget_beitrag"], bef["effizienz_beitrag"]))
            kette = ketten[(ketten["ebene"] == kampagne) & (ketten["baustein"] != "ausgaben")]
            kette = kette.reindex(kette["beitrag"].abs().sort_values(ascending=False).index)
            einzeln = []
            for _, r in kette.iterrows():
                b = r["baustein"]
                aend = t.neu(f"{p}.effizienz.{b}.aenderung_prozent",
                             f"Änderung {BAUSTEIN_NAMEN[b]} in % ({kampagne})",
                             r["aenderung_prozent"], "prozent", 0, vorzeichen=True)
                beitr = t.neu(f"{p}.effizienz.{b}.beitrag",
                              f"Euro-Beitrag {BAUSTEIN_NAMEN[b]} zum Kaufwert ({kampagne})",
                              r["beitrag"], "euro", 0, vorzeichen=True)
                einzeln.append(f"{BAUSTEIN_NAMEN[b]} {aend} ({beitr})")
            saetze.append(f"Effizienz im Einzelnen: {', '.join(einzeln)}.")

            # Ursache: die zwei größten Bausteine (inkl. Budget) – die Daten zeigen das Warum nicht
            gross = ketten[ketten["ebene"] == kampagne]
            gross = gross.reindex(gross["beitrag"].abs().sort_values(ascending=False).index).head(2)
            namen = ["das Budget" if b == "ausgaben" else BAUSTEIN_NAMEN[b] for b in gross["baustein"]]
            saetze.append(f"Warum sich {verbinde(namen)} verändert haben, zeigen die Daten nicht: Ursache unklar.")
        else:
            saetze.append(f"Die Treiber sind nicht berechenbar, {nullgrund_lesbar(werte, t.null)}. "
                          f"Ursache unklar.")

        # Weitere markierte Kennzahlen kurz nennen
        weitere = []
        for k in noetig:
            if k == "kaufwert_meta" or not werte.loc[k, "markiert"]:
                continue
            w = kw_[k]
            zusatz = f", {w['abs']}" if w["art"] == "quote_prozent" else ""
            weitere.append(f"{w['name']} {w['diese']} ({vgl} {w['basis']}, {w['prozent']}{zusatz})")
        if weitere:
            saetze.append(f"Weitere markierte Kennzahlen: {'; '.join(weitere)}.")

        # Anteil an der Gesamtänderung aller Kampagnen
        zeile = beitraege[(beitraege["kampagne"] == kampagne) & (beitraege["kennzahl"] == "kaufwert_meta")]
        if len(zeile) and pd.notna(zeile["anteil_prozent"].iloc[0]):
            anteil = zeile["anteil_prozent"].iloc[0]
            anteil_text = t.neu(f"{p}.anteil_an_gesamt",
                                f"Anteil an der Kaufwert-Änderung aller Kampagnen ({kampagne})",
                                anteil, "prozent", 0)
            if anteil >= 0:
                saetze.append(f"Die Kampagne macht {anteil_text} der Änderung des Meta-Kaufwerts "
                              f"aller Kampagnen aus.")
            else:
                saetze.append(f"Die Kampagne lief gegen die Gesamtentwicklung (Anteil {anteil_text}).")

        # Pflichtwörter, die im Absatz stehen müssen (Pflicht-Check, siehe pruefe_pflicht)
        pflicht = ["unklar" if bef["treiber_status"] == "ok" else "nicht berechenbar"]
        if bef["geringe_fallzahl"]:
            pflicht.append("geringe Fallzahl")

        befunde.append({"kampagne": kampagne, "rang": int(bef["rang"]),
                        "geringe_fallzahl": bool(bef["geringe_fallzahl"]),
                        "saetze": saetze, "pflicht": pflicht})

    return t.als_tabelle(), {"gesamtbild": gesamtbild, "pflicht_gesamtbild": pflicht_gesamtbild,
                             "befunde": befunde, "feste_hinweise": feste_hinweise}


def budget_effizienz_satz(t: WerteTabelle, p: str, kaufwert_delta, budget, effizienz) -> str:
    """Satz: Wie viel der Kaufwert-Änderung kam vom Budget, wie viel von der Effizienz?"""
    teile = []
    for name, wert, plus, minus in [("budget", budget, "mehr Budget", "weniger Budget"),
                                    ("effizienz", effizienz, "höhere Effizienz", "geringere Effizienz")]:
        beitrag = t.neu(f"{p}.{name}.beitrag", f"Euro-Beitrag {name} zur Kaufwert-Änderung ({p})",
                        wert, "euro", 0, vorzeichen=True)
        anteil_wert = wert / kaufwert_delta * 100 if kaufwert_delta else np.nan
        anteil = t.neu(f"{p}.{name}.anteil", f"Anteil {name} an der Kaufwert-Änderung ({p})",
                       anteil_wert, "prozent", 0)
        teile.append((richtung(wert, plus, minus), wert, beitrag, anteil))
    return treiber_satz(kaufwert_delta, teile)


def meta_shopify_saetze(t: WerteTabelle, mgs: dict, gw: dict) -> list:
    """Sätze zum Unterschied Meta gegen Shopify (utm_source facebook). Nie eine Zahl als "richtig"."""
    v = mgs["vergleich"].set_index("kennzahl")
    sp = mgs["spanne"].set_index("kennzahl")

    def verhaeltnis(lang_id, bedeutung, wert):
        return t.neu(f"meta_shopify.{lang_id}", bedeutung, wert, "zahl", 2)

    vs = verhaeltnis("verhaeltnis_stueck.diese_woche",
                     "Verhältnis Meta-Käufe ÷ Shopify-Bestellungen (facebook), diese Woche",
                     v.loc["verhaeltnis_stueck", "diese_woche"])
    vs_vor = verhaeltnis("verhaeltnis_stueck.vorwoche",
                         "Verhältnis Meta-Käufe ÷ Shopify-Bestellungen (facebook), Vorwoche",
                         v.loc["verhaeltnis_stueck", "vorwoche"])
    ve = verhaeltnis("verhaeltnis_euro.diese_woche",
                     "Verhältnis Meta-Kaufwert ÷ Shopify-Umsatz (facebook), diese Woche",
                     v.loc["verhaeltnis_euro", "diese_woche"])
    ve_vor = verhaeltnis("verhaeltnis_euro.vorwoche",
                         "Verhältnis Meta-Kaufwert ÷ Shopify-Umsatz (facebook), Vorwoche",
                         v.loc["verhaeltnis_euro", "vorwoche"])

    saetze = [
        f"Meta gegen Shopify: Meta zählt {gw['kaeufe_meta']['diese']} Käufe, Shopify "
        f"{gw['bestellungen_fb']['diese']} Bestellungen mit utm_source facebook "
        f"(Verhältnis {vs}, Vorwoche {vs_vor}). Beim Wert: Meta-Kaufwert {gw['kaufwert_meta']['diese']}, "
        f"Shopify-Umsatz aus Facebook {gw['umsatz_fb']['diese']} (Verhältnis {ve}, Vorwoche {ve_vor})."
    ]
    # Feste Hinweise: schreibt der Code, nicht das LLM (immer gleich, dürfen nie fehlen)
    feste_hinweise = ["Meta-Käufe und Shopify-Bestellungen sind verschiedene Zahlen. "
                      "Welche der beiden stimmt, lässt sich aus den Daten nicht sagen."]
    pflicht = []

    for kennzahl, wort in [("verhaeltnis_stueck", "bei der Stückzahl"), ("verhaeltnis_euro", "beim Wert")]:
        zeile = sp.loc[kennzahl]
        if zeile["status"] == "markiert":
            wochen = t.neu(f"meta_shopify.{kennzahl}.wochen_frueher", "Anzahl früherer Wochen",
                           zeile["wochen_frueher"], "zahl")
            mn = verhaeltnis(f"{kennzahl}.frueher_min", f"kleinstes Verhältnis {wort} in früheren Wochen",
                             zeile["frueher_min"])
            mx = verhaeltnis(f"{kennzahl}.frueher_max", f"größtes Verhältnis {wort} in früheren Wochen",
                             zeile["frueher_max"])
            saetze.append(
                f"Das Verhältnis {wort} ist {zeile['richtung']}: In den {wochen} Wochen davor lag es "
                f"zwischen {mn} und {mx}. Die Ursache ist unklar."
            )
            # "Verhältnis" zusätzlich: "unklar" allein könnte auch aus einem anderen Satz
            # stammen (z. B. Rabatt-Satz), dann fiele ein weggelassener Meta-Shopify-Teil nicht auf.
            pflicht += ["unklar", "Verhältnis"]
            if kennzahl == "verhaeltnis_euro":
                feste_hinweise.append("Ob Meta den Kaufwert vor oder nach Rabatt meldet, hängt von der "
                                      "Einrichtung des Meta-Pixels ab. Das lässt sich aus den Daten nicht prüfen.")
        elif zeile["status"] == "zu wenig Geschichte":
            wochen = t.neu(f"meta_shopify.{kennzahl}.wochen_frueher", "Anzahl früherer Wochen",
                           zeile["wochen_frueher"], "zahl")
            saetze.append(f"Für eine Bewertung des Verhältnisses {wort} gibt es erst {wochen} frühere Wochen.")
    return saetze, feste_hinweise, sorted(set(pflicht))


# ===============================================================
# 5b: Zahlen-Check mit IDs
# ===============================================================

# Einheiten, wie sie im Text stehen können. "Prozentpunkte" vor "Prozent", sonst passt nur der Anfang.
EINHEIT_MUSTER = r"(?:€|Euro|EUR|%|Prozentpunkten|Prozentpunkte|Prozentpunkt|Prozent)(?![A-Za-zäöüß])"
EINHEIT_NORMAL = {
    "": "", "€": "€", "Euro": "€", "EUR": "€",
    "%": "%", "Prozent": "%",
    "Prozentpunkte": "pp", "Prozentpunkten": "pp", "Prozentpunkt": "pp",
}

# Eine Zahl: Ziffern, optional mit Tausenderpunkten, Komma oder Datumspunkten.
# Vorzeichen gehören NICHT dazu -> Vergleich ohne Vorzeichen.
ZAHL = r"\d+(?:[.,]\d+)*"

# Eine ID in eckigen Klammern, z. B. [B2.3], [G14], [Z1]
ID_IN_KLAMMERN = re.compile(r"\[([A-Za-z]\d+(?:\.\d+)?)\]")

# Trick: Vor dem Suchen werden alle [ID] durch Platzhalter OHNE Ziffern ersetzt.
# Sonst würde die Zahlensuche die 2.3 in [B2.3] für eine Zahl im Text halten.
# Platzhalter = Zeichen aus dem "privaten" Unicode-Bereich, die nie in echtem Text vorkommen.
P_START, P_ENDE, P_BASIS = "", "", 0xE100

PRUEF_MUSTER = re.compile(
    rf"({ZAHL})"                                       # 1: die Zahl
    rf"(?:\s*({EINHEIT_MUSTER}))?"                     # 2: Einheit vor der ID (618 € [B2.3])
    rf"(?:\s*{P_START}(.){P_ENDE})?"                   # 3: Platzhalter der ID
    rf"(?:\s*({EINHEIT_MUSTER}))?"                     # 4: Einheit nach der ID (618 [B2.3] €)
)

# Zahlwörter, die der Ziffern-Check nicht sehen würde -> verboten
ZAHLWOERTER = [
    "null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn",
    "elf", "zwölf", "zwanzig", "dreißig", "vierzig", "fünfzig", "hundert", "tausend", "dutzend",
    "hälfte", "halb", "halbiert", "halbierte", "drittel", "viertel",
    "doppelt", "doppelte", "doppelten", "verdoppelt", "verdoppelte",
    "zweifach", "dreifach", "vierfach",
]
ZAHLWORT_MUSTER = re.compile(r"\b(" + "|".join(ZAHLWOERTER) + r")\b", re.IGNORECASE)

# Richtungswörter: Welches Wort sagt "rauf", welches "runter"?
# Nur reine Richtungen, keine Bewertungen wie "besser"/"schlechter"
# (ein steigender CPA ist schlecht, ein steigender ROAS gut – das wäre zu unsicher).
# Bewusst NICHT "geringe" (steht in "geringe Fallzahl"), nur die Steigerung "geringer...".
WOERTER_PLUS = [
    "stieg", "stiegen", "gestiegen", "steigt", "steigen", "anstieg", "anstiegs",
    "erhöht", "erhöhte", "erhöhten", "höher", "höhere", "höheren", "höherer", "höheres",
    "mehr", "größer", "größere", "größeren", "größerer", "größeres",
    "wuchs", "wuchsen", "gewachsen", "zugenommen", "zunahme", "plus",
    "zulegte", "zulegten", "zugelegt",
    # Hauptwörter, auch in Zusammensetzungen wie "CTR-Steigerung"
    "steigerung", "erhöhung", "zuwachs", "wachstum",
]
WOERTER_MINUS = [
    "sank", "sanken", "gesunken", "sinkt", "sinken", "rückgang", "rückgangs",
    "fiel", "fielen", "gefallen",   # NICHT "fällt": steht in "fällt zusammen mit" (Rabatt-Satz)
    "niedriger", "niedrigere", "niedrigeren", "niedrigerer", "niedrigeres",
    "weniger", "geringer", "geringere", "geringeren", "geringerer", "geringeres",
    "kleiner", "kleinere", "kleineren", "kleinerer", "kleineres",
    "verringert", "verringerte", "verringerten", "abgenommen", "abnahme", "minus",
    "zurück", "zurückging", "zurückgingen", "zurückgegangen", "nachgelassen", "nachließ",
    "reduziert", "reduzierte", "reduzierten", "eingebrochen",
    # Hauptwörter, auch in Zusammensetzungen wie "Conversion-Rate-Verringerung"
    "verringerung", "senkung", "reduzierung", "reduktion", "einbruch",
]
RICHTUNG_VON_WORT = {**{w: "+" for w in WOERTER_PLUS}, **{w: MINUS for w in WOERTER_MINUS}}
# Gruppe 1 = Wort aus der Liste, danach optional eine deutsche Endung:
# "erhöht" findet so auch "erhöhtes Budget", "gesunken" auch "gesunkene Rate".
RICHTUNG_MUSTER = re.compile(r"(?<![A-Za-zäöüßÄÖÜ])(" + "|".join(RICHTUNG_VON_WORT) + r")"
                             r"(?:e|en|er|es|em)?(?![A-Za-zäöüß])", re.IGNORECASE)

# Satzende: Punkt, Ausrufe- oder Fragezeichen mit Leerzeichen danach, oder neuer Absatz.
# (Punkte IN Zahlen wie "1.894" oder "16.11.2026" haben kein Leerzeichen danach.)
SATZ_ENDE = re.compile(r"[.!?](?=\s)|\n")


def satz_um(text: str, position: int) -> tuple:
    """Anfang und Ende des Satzes, in dem die Position liegt."""
    anfang = max([m.end() for m in SATZ_ENDE.finditer(text, 0, position)], default=0)
    ende = SATZ_ENDE.search(text, position)
    return anfang, (ende.start() if ende else len(text))


# Teilsatz-Grenze: Komma (aber nicht in "6,39"), Semikolon, "und", "sowie", "oder", "aber", "während"
TEILSATZ_GRENZE = re.compile(r",(?!\d)|;|(?<![A-Za-zäöüß])(?:und|sowie|oder|aber|während)(?![A-Za-zäöüß])")


def klammer_gruppen(text: str) -> list:
    """Für jedes Zeichen: In welcher Klammer steht es? (Position der öffnenden Klammer, -1 = keine)"""
    gruppen, offen = [], []
    for i, zeichen in enumerate(text):
        if zeichen == "(":
            offen.append(i)
        gruppen.append(offen[-1] if offen else -1)
        if zeichen == ")" and offen:
            offen.pop()
    return gruppen


def richtungswort_fuer(text: str, gruppen: list, start: int, ende: int):
    """Welches Richtungswort gehört zu der Zahl an Stelle start..ende?

    1. Satz in Teilsätze zerlegen (Komma, Semikolon, "und", "sowie" ...).
    2. Hat der Teilsatz ein Richtungswort in derselben Klammer-Ebene wie die Zahl -> das nächste davon.
       ("einer CTR, die um 2 % fiel", "(typisch 6,39 €, 31 % mehr)")
       Zahlen in Klammern sind Zusatz-Infos: Ein Wort AUSSERHALB der Klammer gilt nicht für sie.
       ("der CPM stieg um 6 % (−40 €)": "stieg" gilt für die 6 %, nicht für den Beitrag −40 €)
    3. Hat der Teilsatz gar kein Richtungswort: Aufzählung -> das letzte Wort davor im Satz gilt,
       auch für Zahlen in Klammern. ("Die Effizienz sank bei ..., beim CPM um 5 % (+70 €)")
    Rückgabe: (wort, richtung) oder None (nichts zu prüfen).
    """
    s_anfang, s_ende = satz_um(text, start)
    t_anfang = max([m.end() for m in TEILSATZ_GRENZE.finditer(text, s_anfang, start)], default=s_anfang)
    grenze = TEILSATZ_GRENZE.search(text, ende, s_ende)
    t_ende = grenze.start() if grenze else s_ende

    im_teilsatz = list(RICHTUNG_MUSTER.finditer(text, t_anfang, t_ende))
    gleiche_ebene = [w for w in im_teilsatz if gruppen[w.start()] == gruppen[start]]

    if gleiche_ebene:
        wort = min(gleiche_ebene, key=lambda w: start - w.end() if w.end() <= start else w.start() - ende)
    elif im_teilsatz:
        return None          # Wort gehört zu einer anderen Zahl im Teilsatz (z. B. Klammer-Zusatz)
    else:
        davor = [w for w in RICHTUNG_MUSTER.finditer(text, s_anfang, t_anfang) if gruppen[w.start()] == -1]
        if not davor:
            return None
        wort = davor[-1]
    return wort.group(0), RICHTUNG_VON_WORT[wort.group(1).lower()]


def zahl_und_einheit(text: str):
    """Erste Zahl samt Einheit aus einem Tabellentext: '−618 €' -> ('618', '€'). Ohne Zahl: None."""
    treffer = re.search(rf"({ZAHL})(?:\s*({EINHEIT_MUSTER}))?", text)
    if not treffer:
        return None
    return treffer.group(1), EINHEIT_NORMAL[treffer.group(2) or ""]


def pruefe_text(text: str, werte: pd.DataFrame, kampagnen: list) -> dict:
    """Prüft jede Zahl im Text gegen die ID dahinter.

    Fehlerarten (stehen so im Log):
      "ID fehlt"                hinter der Zahl steht keine [ID]
      "ID unbekannt"            die ID gibt es in der Tabelle nicht
      "Zahl passt nicht zur ID" Zahl (ohne Vorzeichen) oder Einheit weicht vom Tabellentext ab
      "Zahlwort"                z. B. "Hälfte", "doppelt"
      "Richtungswort passt nicht"  das Richtungswort zur Zahl (siehe richtungswort_fuer) sagt
                                "rauf", die ID ist aber negativ (oder umgekehrt)

    Eine fehlende Einheit ist erlaubt (die ID legt die Bedeutung fest),
    eine FALSCHE Einheit nicht.

    Richtungs-Check: Nur IDs mit Vorzeichen werden geprüft. Steht im Satz kein
    Richtungswort, gibt es nichts zu prüfen. Grenze: Der Check sieht nur Wörter
    und ihre Reihenfolge, nicht die Grammatik. Bewusst streng: Lieber ein
    zusätzlicher Versuch als ein falsches "sank" im Report.

    Rückgabe: {"ok": bool, "fehler": [ {art, zahl, id, erwartet} ], "anzahl_zahlen": int}
    """
    # 1. Kampagnennamen entfernen (z. B. die 30 in "Besucher 30 Tage")
    bereinigt = text
    for name in sorted(kampagnen, key=len, reverse=True):  # lange Namen zuerst
        bereinigt = bereinigt.replace(name, " ")

    # 2. IDs durch Platzhalter ohne Ziffern ersetzen und merken
    ids = []

    def ersetze(treffer):
        ids.append(treffer.group(1))
        return P_START + chr(P_BASIS + len(ids) - 1) + P_ENDE

    bereinigt = ID_IN_KLAMMERN.sub(ersetze, bereinigt)

    def stelle(start: int, ende: int) -> str:
        """Textstelle um einen Fund herum, Platzhalter wieder als [ID] lesbar."""
        ausschnitt = bereinigt[max(0, start - 40):ende + 30]
        return re.sub(f"{P_START}(.){P_ENDE}", lambda m: f"[{ids[ord(m.group(1)) - P_BASIS]}]",
                      ausschnitt).replace("\n", " ")

    # 3. Jede Zahl prüfen
    tabelle = dict(zip(werte["id"], werte["text"]))
    richtungen = dict(zip(werte["id"], werte["richtung"])) if "richtung" in werte else {}
    gruppen = klammer_gruppen(bereinigt)
    fehler, anzahl = [], 0
    for treffer in PRUEF_MUSTER.finditer(bereinigt):
        anzahl += 1
        zahl = treffer.group(1)
        einheit = EINHEIT_NORMAL[treffer.group(2) or treffer.group(4) or ""]
        geschrieben = f"{zahl} {einheit}".strip()
        wo = stelle(treffer.start(), treffer.end())

        if treffer.group(3) is None:
            fehler.append({"art": "ID fehlt", "zahl": geschrieben, "id": None, "erwartet": None, "stelle": wo})
            continue

        id_ = ids[ord(treffer.group(3)) - P_BASIS]
        if id_ not in tabelle:
            fehler.append({"art": "ID unbekannt", "zahl": geschrieben, "id": id_, "erwartet": None, "stelle": wo})
            continue

        erwartet = zahl_und_einheit(tabelle[id_])
        passt = (erwartet is not None and zahl == erwartet[0]
                 and einheit in ("", erwartet[1]))
        if not passt:
            fehler.append({"art": "Zahl passt nicht zur ID", "zahl": geschrieben, "id": id_,
                           "erwartet": tabelle[id_], "stelle": wo})
            continue

        # Richtung: passt das nächste Richtungswort im Satz zum Vorzeichen der ID?
        soll = richtungen.get(id_, "")
        wort = richtungswort_fuer(bereinigt, gruppen, treffer.start(), treffer.end()) if soll else None
        if wort and wort[1] != soll:
            klartext = "positiv (rauf)" if soll == "+" else "negativ (runter)"
            fehler.append({"art": "Richtungswort passt nicht",
                           "zahl": f"'{wort[0]}' bei {geschrieben}", "id": id_,
                           "erwartet": f"{tabelle[id_]} ist {klartext}", "stelle": wo})

    # 4. Zahlwörter
    for treffer in ZAHLWORT_MUSTER.finditer(bereinigt):
        fehler.append({"art": "Zahlwort", "zahl": treffer.group(1), "id": None, "erwartet": None,
                       "stelle": stelle(treffer.start(), treffer.end())})

    return {"ok": not fehler, "fehler": fehler, "anzahl_zahlen": anzahl}


def normiere(text: str) -> str:
    """Bindestriche/Minus vom LLM vereinheitlichen.

    '‑629 €' (geschützter Bindestrich vor Ziffer) -> '−629 €' (echtes Minus)
    'Meta‑Kaufwert' (geschützter Bindestrich im Wort) -> 'Meta-Kaufwert'
    Der Halbgeviertstrich '–' in Kampagnennamen bleibt unverändert.
    """
    text = re.sub(r"[‑‐-](?=\d)", MINUS, text)       # vor einer Ziffer: Minus
    return text.replace("‑", "-").replace("‐", "-")  # sonst: normaler Bindestrich


def pruefe_pflicht(absaetze: dict, fakten: dict) -> list:
    """Prüft, dass jeder Absatz seine Pflichtwörter enthält (z. B. 'unklar', 'geringe Fallzahl').

    Der Zahlen-Check sieht keine weggelassenen Sätze. Dieser Check schon – zumindest
    für die Aussagen, die nie fehlen dürfen. Groß-/Kleinschreibung egal.
    Rückgabe: Liste von Fehlern mit Art "Pflichtaussage fehlt".
    """
    fehler = []
    paare = [("Gesamtbild", absaetze["gesamtbild"], fakten["pflicht_gesamtbild"])]
    paare += [(b["kampagne"], a["text"], b["pflicht"])
              for b, a in zip(fakten["befunde"], absaetze["befunde"])]
    for wo, text, woerter in paare:
        for wort in woerter:
            if wort.lower() not in normiere(text).lower():
                fehler.append({"art": "Pflichtaussage fehlt", "zahl": f"'{wort}' fehlt im Absatz {wo}",
                               "id": None, "erwartet": None})
    return fehler


def entferne_ids(text: str) -> str:
    """'sank um 618 € [B2.3].' -> 'sank um 618 €.' (für die Ausgabe im Report)"""
    return ID_IN_KLAMMERN.sub("", text).replace("  ", " ").replace(" .", ".").replace(" ,", ",") \
        .replace(" )", ")").replace(" ;", ";")


# ===============================================================
# 5c: Ersatztext
# ===============================================================
def fakten_als_text(fakten: dict) -> dict:
    """Macht aus den Fakten-Sätzen Absätze: {"gesamtbild": str, "befunde": [{"kampagne", "text"}]}."""
    return {
        "gesamtbild": " ".join(fakten["gesamtbild"]),
        "befunde": [{"kampagne": b["kampagne"], "text": " ".join(b["saetze"])} for b in fakten["befunde"]],
    }


def alles_als_ein_text(absaetze: dict) -> str:
    """Alle Absätze zusammen, z. B. für den Zahlen-Check."""
    return "\n\n".join([absaetze["gesamtbild"]] + [b["text"] for b in absaetze["befunde"]])


def ohne_ids(absaetze: dict) -> dict:
    """Entfernt die [IDs] aus allen Absätzen (für die Ausgabe)."""
    return {
        "gesamtbild": entferne_ids(absaetze["gesamtbild"]),
        "befunde": [{"kampagne": b["kampagne"], "text": entferne_ids(b["text"])} for b in absaetze["befunde"]],
    }


def ersatztext(fakten: dict, werte: pd.DataFrame, kampagnen: list) -> dict:
    """Ersatztext aus festen Satzvorlagen (mit IDs). Wird selbst auch geprüft.

    Fällt er durch, ist das ein Fehler in UNSEREM Code -> Programm bricht ab.
    """
    absaetze = fakten_als_text(fakten)
    ergebnis = pruefe_text(alles_als_ein_text(absaetze), werte, kampagnen)
    pflicht = pruefe_pflicht(absaetze, fakten)
    if not ergebnis["ok"] or pflicht:
        raise RuntimeError(f"Ersatztext besteht die Prüfung nicht (Fehler im Code): "
                           f"{ergebnis['fehler'] + pflicht}")
    return absaetze


# ===============================================================
# 5d: LLM-Aufruf
# ===============================================================
SYSTEM_PROMPT = """Du schreibst den Erklärtext eines Wochenreports für die Betreiberin oder den Betreiber eines kleinen Online-Shops. Schreibe in einfachem, klarem Deutsch.

Regeln für Zahlen (werden automatisch geprüft, sonst wird dein Text verworfen):
1. Verwende nur Zahlen aus den Fakten. Rechne nichts aus, runde nichts, erfinde keine Zahl.
2. Schreibe hinter JEDE Zahl ihre ID in eckigen Klammern, genau wie in den Fakten. Die ID steht DIREKT hinter der Zahl bzw. ihrer Einheit (€, %), vor jedem weiteren Wort.
   Richtig: "Der Kaufwert sank um 618 € [B2.3]."  Richtig: "Meta zählt 68 [G29] Käufe."
   Falsch:  "Meta zählt 68 Käufe [G29]."  Falsch: "18 Meta-Käufe in der Vorwoche [B3.6]"
3. Schreibe die Zahl genau so wie in den Fakten. Das Vorzeichen darfst du weglassen, wenn ein Wort wie "sank" oder "stieg" die Richtung sagt.
4. Keine Zahlwörter (zum Beispiel "Hälfte", "doppelt", "zwei", "drei"). Keine nummerierten Listen.
5. Schreibe Kampagnennamen genau so wie in den Fakten.

Regeln für den Inhalt:
6. Erfinde keine Ursachen. Wo die Fakten "unklar" sagen, schreibe, dass die Ursache unklar ist.
7. Meta-Zahlen und Shopify-Zahlen sind verschiedene Zahlen. Stelle keine davon als "die richtige" dar.
8. Wenn bei einem Befund "geringe Fallzahl" steht, erwähne das.
9. Lass keine Fakten-Aussage weg, die "unklar", "nicht berechenbar", "geringe Fallzahl" oder "zeitlich zusammen" enthält. Ein zeitliches Zusammentreffen (z. B. mit Rabatten) ist keine Ursache, schreibe es nicht als Ursache.
10. Verglichen wird mit dem Wert, der in den Fakten in Klammern steht ("typisch" = eine typische Woche der letzten Wochen, sonst die Vorwoche). Schreibe nicht "Vorwoche", wenn in den Fakten "typisch" steht.
11. Richtungswörter (stieg, sank, mehr, weniger, höher, geringer, Plus, Minus ...) werden geprüft und müssen zum Vorzeichen der Zahl passen. Achtung beim CPM: Ein gesunkener CPM bringt einen POSITIVEN Euro-Beitrag, ein gestiegener CPM einen negativen. Nenne den CPM deshalb in einem eigenen Satz mit eigenem Verb.
   Richtig: "Der CPM sank um 5 % [B1.29]; das brachte ein Plus von 70 € [B1.30]."
   Falsch:  "Die Effizienz sank bei der CTR um 2 % [B1.31] und beim CPM um 5 % [B1.29] (+70 € [B1.30])."

Antworte nur mit JSON in genau dieser Form:
{"gesamtbild": "Absatz zum Gesamtbild", "befunde": [{"kampagne": "Name genau wie in den Fakten", "text": "Absatz zu diesem Befund"}]}
Die Befunde in derselben Reihenfolge wie in den Fakten."""


def baue_anfrage(fakten: dict) -> str:
    """Nachricht an das LLM: nur die Fakten (mit IDs).

    Die Tabelle der geprüften Werte geht bewusst NICHT mit: Jede ID, die der Text
    braucht, steht schon in den Fakten. Das halbiert die Anfrage (Token-Limit bei Groq).
    """
    teile = ["FAKTEN ZUM GESAMTBILD:"]
    teile += [f"- {s}" for s in fakten["gesamtbild"]]
    for b in fakten["befunde"]:
        teile.append(f"\nFAKTEN ZUM BEFUND \"{b['kampagne']}\""
                     + (" (geringe Fallzahl)" if b["geringe_fallzahl"] else "") + ":")
        teile += [f"- {s}" for s in b["saetze"]]
    teile.append("\nSchreibe jetzt den Erklärtext als JSON.")
    return "\n".join(teile)


def lies_schluessel(anbieter: str) -> str:
    """Liest den API-Schlüssel aus .env. Der Schlüssel wird nirgends ausgegeben."""
    load_dotenv(einstellungen.PROJEKT_ORDNER / ".env")
    name = einstellungen.SCHLUESSEL_NAME[anbieter]
    schluessel = os.getenv(name)
    if not schluessel or schluessel == "dein-schluessel-hier":
        raise RuntimeError(f"{name} fehlt in .env")
    return schluessel


def rufe_llm(system: str, nachrichten: list) -> str:
    """Schickt die Nachrichten an den eingestellten Anbieter und gibt den Antworttext zurück."""
    anbieter = einstellungen.LLM_ANBIETER
    modell = einstellungen.LLM_MODELLE[anbieter]
    schluessel = lies_schluessel(anbieter)

    if anbieter == "groq":
        from groq import Groq
        client = Groq(api_key=schluessel)
        antwort = client.chat.completions.create(
            model=modell,
            messages=[{"role": "system", "content": system}] + nachrichten,
            temperature=0.2,              # wenig Zufall: wir wollen genaues Abschreiben
            max_completion_tokens=16000,  # Platz für internes Nachdenken UND die lange Antwort
            reasoning_effort="low",       # Aufgabe ist Umformulieren, kein schweres Nachdenken
            # Bewusst KEIN response_format: Unser lies_json prüft die Form selbst.
            # So landet ein Formatfehler mit dem echten Antworttext in unserem Log.
        )
        return antwort.choices[0].message.content or ""

    if anbieter == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=schluessel)
        antwort = client.beta.messages.create(
            model=modell,
            max_tokens=16000,
            system=system,
            messages=nachrichten,
            # Lehnt das Modell ab, springt automatisch ein anderes Modell ein
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if antwort.stop_reason == "refusal":
            raise RuntimeError("Anfrage vom Modell abgelehnt")
        return "".join(b.text for b in antwort.content if b.type == "text")

    raise ValueError(f"Unbekannter Anbieter: {anbieter}")


def lies_json(antwort: str, fakten: dict) -> dict:
    """Liest die JSON-Antwort und prüft die Form. Bei Problemen: ValueError."""
    start, ende = antwort.find("{"), antwort.rfind("}")   # falls um das JSON noch Text steht
    if start < 0 or ende < 0:
        raise ValueError("keine JSON-Antwort")
    daten = json.loads(antwort[start:ende + 1])

    erwartet = [b["kampagne"] for b in fakten["befunde"]]
    befunde = daten.get("befunde", [])
    if not isinstance(daten.get("gesamtbild"), str) or not isinstance(befunde, list):
        raise ValueError("Felder 'gesamtbild' oder 'befunde' fehlen")
    erhalten = [b.get("kampagne") for b in befunde]
    if erhalten != erwartet:
        raise ValueError(f"Befunde passen nicht: erwartet {erwartet}, erhalten {erhalten}")
    return {"gesamtbild": normiere(daten["gesamtbild"]),
            "befunde": [{"kampagne": b["kampagne"], "text": normiere(str(b.get("text", "")))}
                        for b in befunde]}


def schreibe_log(eintrag: dict, log_datei) -> None:
    """Hängt eine Zeile (JSON) an die Log-Datei an. Eine Zeile pro Fehlschlag."""
    log_datei.parent.mkdir(parents=True, exist_ok=True)
    with open(log_datei, "a", encoding="utf-8") as f:
        f.write(json.dumps(eintrag, ensure_ascii=False, default=str) + "\n")


def speichere_lauf(ergebnis: dict, woche, ordner) -> str:
    """Speichert einen Lauf als lesbare Markdown-Datei, z. B. für Beispiele im README."""
    ordner.mkdir(parents=True, exist_ok=True)
    jetzt = datetime.datetime.now()
    modell_kurz = re.sub(r"[^A-Za-z0-9.]+", "-", ergebnis["modell"])
    name = f"{jetzt:%Y-%m-%d_%H%M%S}_woche-{pd.Timestamp(woche).date()}_{modell_kurz}"
    datei, nummer = ordner / f"{name}.md", 2
    while datei.exists():                      # nie eine alte Datei überschreiben
        datei, nummer = ordner / f"{name}_{nummer}.md", nummer + 1

    def abschnitt(absaetze):
        teile = [f"### Gesamtbild\n\n{absaetze['gesamtbild']}"]
        teile += [f"### {b['kampagne']}\n\n{b['text']}" for b in absaetze["befunde"]]
        return "\n\n".join(teile)

    datei.write_text(
        f"# Lauf vom {jetzt:%d.%m.%Y %H:%M:%S}\n\n"
        f"- Woche: {pd.Timestamp(woche).date()}\n"
        f"- Anbieter / Modell: {ergebnis['anbieter']} / {ergebnis['modell']}\n"
        f"- Quelle des Textes: {ergebnis['quelle']}\n"
        f"- Versuche: {ergebnis['versuche']}\n\n"
        f"## Text für den Report\n\n{abschnitt(ergebnis['absaetze'])}\n\n"
        f"## Text mit IDs (zum Nachprüfen)\n\n{abschnitt(ergebnis['absaetze_roh'])}\n",
        encoding="utf-8")
    return str(datei)


def erzeuge_text(fakten: dict, werte: pd.DataFrame, kampagnen: list, woche,
                 llm=rufe_llm, log_datei=einstellungen.LOG_DATEI, max_versuche: int = 2,
                 wartezeit=None, laeufe_ordner=einstellungen.LAEUFE_ORDNER) -> dict:
    """Erklärtext vom LLM holen und prüfen. Höchstens zwei Versuche, sonst Ersatztext.

    Geprüft wird zweierlei: der Zahlen-Check (jede Zahl passt zu ihrer ID) und der
    Pflicht-Check (Aussagen wie "unklar" oder "geringe Fallzahl" fehlen nicht).

    llm:           Funktion (system, nachrichten) -> Antworttext. Für Tests austauschbar.
    wartezeit:     Sekunden Pause vor dem zweiten Versuch (Standard: aus einstellungen.py).
    laeufe_ordner: hier wird jeder Lauf gespeichert (None = nicht speichern).

    Rückgabe:
      quelle         "llm" oder "ersatztext"
      absaetze       Text für den Report (ohne IDs)
      absaetze_roh   Text mit IDs (zum Nachprüfen)
      versuche       Anzahl LLM-Versuche
    """
    anbieter = einstellungen.LLM_ANBIETER
    modell = einstellungen.LLM_MODELLE[anbieter]
    if wartezeit is None:
        wartezeit = einstellungen.WARTEN_VOR_ZWEITEM_VERSUCH[anbieter]
    nachrichten = [{"role": "user", "content": baue_anfrage(fakten)}]

    for versuch in range(1, max_versuche + 1):
        if versuch > 1 and wartezeit:
            print(f"Warte {wartezeit} Sekunden vor Versuch {versuch} (Token-Limit pro Minute) ...")
            time.sleep(wartezeit)
        antwort, fehler = "", []
        try:
            antwort = llm(SYSTEM_PROMPT, nachrichten)
            absaetze = lies_json(antwort, fakten)
            ergebnis = pruefe_text(alles_als_ein_text(absaetze), werte, kampagnen)
            fehler = ergebnis["fehler"] + pruefe_pflicht(absaetze, fakten)
            if not fehler:
                fertig = {"quelle": "llm", "absaetze": ohne_ids(absaetze), "absaetze_roh": absaetze,
                          "versuche": versuch, "anbieter": anbieter, "modell": modell}
                if laeufe_ordner:
                    fertig["datei"] = speichere_lauf(fertig, woche, laeufe_ordner)
                return fertig
        except (ValueError, json.JSONDecodeError) as fehlermeldung:
            fehler = [{"art": "Format ungültig", "meldung": str(fehlermeldung)}]
        except Exception as fehlermeldung:   # Netzwerk, Schlüssel fehlt, Ablehnung ...
            fehler = [{"art": "API-Fehler", "meldung": f"{type(fehlermeldung).__name__}: {fehlermeldung}"}]

        schreibe_log({
            "zeitpunkt": datetime.datetime.now().isoformat(timespec="seconds"),
            "woche": str(pd.Timestamp(woche).date()),
            "anbieter": anbieter, "modell": modell, "versuch": versuch,
            "fehler": fehler, "text": antwort,
        }, log_datei)

        # Für den zweiten Versuch: dem LLM sagen, was falsch war
        if antwort:
            nachrichten.append({"role": "assistant", "content": antwort})
        hinweise = "\n".join(
            f"- {f['art']}: {f.get('zahl') or f.get('meldung')}"
            + (f" (ID {f['id']}, richtig wäre: {f['erwartet']})" if f.get("erwartet") else "")
            + (f" | Stelle: \"…{f['stelle']}…\"" if f.get("stelle") else "")
            for f in fehler[:20])
        nachrichten.append({"role": "user", "content":
                            "Der automatische Zahlen-Check ist fehlgeschlagen:\n" + hinweise +
                            "\nSchreibe den Text neu und halte dich genau an die Regeln. "
                            "Jede Zahl braucht ihre ID in eckigen Klammern."})

    # Kein Versuch hat bestanden -> Ersatztext
    roh = ersatztext(fakten, werte, kampagnen)
    fertig = {"quelle": "ersatztext", "absaetze": ohne_ids(roh), "absaetze_roh": roh,
              "versuche": max_versuche, "anbieter": anbieter, "modell": modell}
    if laeufe_ordner:
        fertig["datei"] = speichere_lauf(fertig, woche, laeufe_ordner)
    return fertig


# ===============================================================
# Tests ohne API:   python llm_text.py
# Echter Aufruf:    python llm_text.py --echt
# Modelle anzeigen: python llm_text.py --modelle
# ===============================================================
if __name__ == "__main__":
    import sys
    import tempfile
    from pathlib import Path

    import daten
    import analyse

    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 70)

    d = daten.lade_wochendaten()
    e = analyse.analysiere_woche(d, d["wochen"][-1])
    werte, fakten = baue_fakten(e)
    kampagnen = list(e["vergleich_kampagnen"]["kampagne"].unique())

    if "--modelle" in sys.argv:
        # Zeigt die Modelle, die der eingestellte Anbieter gerade anbietet (kostenlos)
        anbieter = einstellungen.LLM_ANBIETER
        if anbieter == "groq":
            from groq import Groq
            namen = [m.id for m in Groq(api_key=lies_schluessel("groq")).models.list().data]
        else:
            import anthropic
            namen = [m.id for m in anthropic.Anthropic(api_key=lies_schluessel("anthropic")).models.list()]
        print(f"Modelle bei {anbieter}:")
        for n in sorted(namen):
            print(("  * " if n == einstellungen.LLM_MODELLE[anbieter] else "    ") + n)
        sys.exit()

    if "--echt" in sys.argv:
        ergebnis = erzeuge_text(fakten, werte, kampagnen, e["woche"])
        print(f"Quelle: {ergebnis['quelle']}  |  Versuche: {ergebnis['versuche']}  |  "
              f"{ergebnis['anbieter']} / {ergebnis['modell']}")
        print(f"Gespeichert: {ergebnis['datei']}\n")
        print("=== Text mit IDs ===")
        print(alles_als_ein_text(ergebnis["absaetze_roh"]))
        print("\n=== Text für den Report ===")
        print(alles_als_ein_text(ergebnis["absaetze"]))
        sys.exit()

    # ---------- Tests ohne API ----------
    def kurz(lang_id):
        """Kurze ID zu einer langen ID (für die Testtexte)."""
        return werte.loc[werte["lang_id"] == lang_id, "id"].iloc[0]

    # Testwerte aus der Tabelle holen (nicht fest eintippen – sie hängen von den Daten ab)
    erster = fakten["befunde"][0]["kampagne"]
    p = f"kampagne.{kurz_name(erster)}"
    kaufwert = kurz(f"{p}.kaufwert_meta.aenderung")
    kw_zahl, _ = zahl_und_einheit(werte.set_index("id").loc[kaufwert, "text"])     # z. B. "618"
    # Eine Prozentzahl, die es in der Tabelle gibt, aber NICHT bei dieser ID (die alte Lücke)
    pz_id = kurz(f"{p}.kaufwert_meta.aenderung_prozent")
    pz_richtig, _ = zahl_und_einheit(werte.set_index("id").loc[pz_id, "text"])
    pz_falsch = next(z for z, e_ in (zahl_und_einheit(tx) or ("", "") for tx in werte["text"])
                     if e_ == "%" and z != pz_richtig)

    print(f"=== Tabelle: {len(werte)} Zeilen. Beispiele ({erster}) ===")
    print(werte[werte["lang_id"].str.startswith(p)][["id", "lang_id", "text"]].head(6).to_string(index=False))

    print("\n=== Ersatztext mit IDs (Ausschnitt) ===")
    absaetze = ersatztext(fakten, werte, kampagnen)
    print(absaetze["befunde"][0]["text"][:300] + " ...")
    print("\n=== Derselbe Ausschnitt ohne IDs ===")
    print(entferne_ids(absaetze["befunde"][0]["text"])[:250] + " ...")

    print("\n=== Zahlen-Check mit Testtexten ===")
    tests = [
        (f"Der Kaufwert änderte sich um {kw_zahl} € [{kaufwert}].", True),
        (f"Der Kaufwert änderte sich um {kw_zahl} [{kaufwert}] €.", True),              # Einheit nach der ID
        (f"Der Kaufwert änderte sich um {kw_zahl} [{kaufwert}].", True),                # Einheit fehlt: ok
        (f"Retargeting – Besucher 30 Tage: {kw_zahl} € [{kaufwert}].", True),           # 30 im Namen
        (f"Der Kaufwert änderte sich um {kw_zahl} €.", "ID fehlt"),
        (f"Der Kaufwert änderte sich um {kw_zahl} € [B9.99].", "ID unbekannt"),
        (f"Der Kaufwert änderte sich um {pz_falsch} % [{pz_id}].", "Zahl passt nicht zur ID"),  # alte Lücke
        (f"Der Kaufwert änderte sich um {kw_zahl} % [{kaufwert}].", "Zahl passt nicht zur ID"),  # falsche Einheit
        (f"Der Kaufwert hat sich fast halbiert, {kw_zahl} € [{kaufwert}].", "Zahlwort"),
    ]
    alle_ok = True
    for text, erwartet in tests:
        r = pruefe_text(text, werte, kampagnen)
        arten = sorted({f["art"] for f in r["fehler"]})
        passt = (r["ok"] if erwartet is True else arten == [erwartet])
        alle_ok &= passt
        print(f"{'✓' if passt else '✗ FALSCH'}  {('ok' if r['ok'] else ', '.join(arten)):24}  {text}")
    assert alle_ok, "Mindestens ein Test hat ein unerwartetes Ergebnis"

    print("\n=== Richtungs-Check (CPM-Fall aus dem Lauf vom 20.11.2026) ===")
    # Kleine feste Tabelle mit den echten Werten aus dem Lauf (KW47, Befund 1 und 3)
    mini = pd.DataFrame([
        {"id": "B1.25", "text": "−32 %", "richtung": MINUS},   # Meta-AOV, Änderung
        {"id": "B1.26", "text": "−522 €", "richtung": MINUS},  # Meta-AOV, Euro-Beitrag
        {"id": "B1.29", "text": "−5 %", "richtung": MINUS},    # CPM gesunken ...
        {"id": "B1.30", "text": "+70 €", "richtung": "+"},     # ... also positiver Beitrag
        {"id": "B3.23", "text": "+11 %", "richtung": "+"},     # CPM gestiegen ...
        {"id": "B3.24", "text": "−38 €", "richtung": MINUS},   # ... also negativer Beitrag
        {"id": "B1.22", "text": "4 %", "richtung": ""},        # Anteil: keine Richtung
    ])
    richtungs_tests = [
        # die zwei echten Fehler aus dem Lauf
        ("Die Effizienz sank bei Meta-AOV um 32 % [B1.25] (−522 € [B1.26]) und beim CPM "
         "um 5 % [B1.29] (+70 € [B1.30]).", "Richtungswort passt nicht"),
        ("Die Effizienz sank beim CPM um 11 % [B3.23] (−38 € [B3.24]).", "Richtungswort passt nicht"),
        # inhaltlich richtig, aber mehrdeutig gebaut -> bewusst streng: fällt durch
        # (das nächste Richtungswort zur +70 € ist "sank"; der Check versteht "brachte dadurch" nicht)
        ("Der CPM sank um 5 % [B1.29] und brachte dadurch +70 € [B1.30].", "Richtungswort passt nicht"),
        # richtig und eindeutig: jede Zahl hat ihr eigenes, passendes Richtungswort
        ("Der CPM sank um 5 % [B1.29] und brachte dadurch ein Plus von 70 € [B1.30].", True),
        ("Der CPM stieg um 11 % [B3.23]; das bedeutete ein Minus von 38 € [B3.24].", True),
        ("Meta-AOV −32 % [B1.25] (−522 € [B1.26]), CPM −5 % [B1.29] (+70 € [B1.30]).", True),  # ohne Wort
        # beide Richtungen in einem Satz (so schreibt es unser Ersatztext)
        ("Getrieben durch geringere Effizienz (−522 € [B1.26]); entgegen wirkte mehr Budget "
         "(+70 € [B1.30]).", True),
        ("Davon entfallen 4 % [B1.22] auf weniger Budget.", True),          # Anteil wird nicht geprüft
        ("Der CPM sank um 5 % [B1.29]. Der Beitrag war +70 € [B1.30].", True),  # anderer Satz
        # Formulierungen aus dem echten Lauf vom 20.11.2026 (Fehlalarme der ersten Version)
        ("Die Effizienz sank bei Meta-AOV um 32 % [B1.25] (−522 € [B1.26]) und der CPM stieg "
         "um 11 % [B3.23].", True),                                    # "stieg" gehört zum CPM-Teilsatz
        ("Hinzu kam ein CPM, der um 11 % [B3.23] stieg (−38 € [B3.24]).", True),   # Verb am Ende
        ("Dazu eine Meta-AOV, die um 32 % [B1.25] (−522 € [B1.26]) zurückging.", True),
        ("Der CPM lag über dem typischen Wert (11 % [B3.23] mehr).", True),  # Wort in derselben Klammer
        # Wortendung (echter Lauf KW45, 20.11.2026): "erhöhtes" gehört zu "erhöht"
        ("Getrieben durch geringere Effizienz (−522 € [B1.26]) und ein leicht erhöhtes "
         "Budget von +70 € [B1.30].", True),
        # Hauptwörter in Zusammensetzungen (echter Lauf KW46, 20.11.2026)
        ("Das ergab eine CPM-Senkung von −5 % [B1.29] (+70 € [B1.30]), eine CPM-Steigerung von "
         "+11 % [B3.23] (−38 € [B3.24]) und eine Meta-AOV-Verringerung von −32 % [B1.25].", True),
        # BEKANNTE GRENZE: ein einziger Teilsatz, "sank" passt zur −5 %, der Beitrag in Klammern
        # wird dann nicht geprüft. Der Fehler (Effizienz sank, obwohl +70 €) bleibt unentdeckt.
        ("Die Effizienz sank beim CPM um 5 % [B1.29] (+70 € [B1.30]).", True),
    ]
    for text, erwartet in richtungs_tests:
        r = pruefe_text(text, mini, [])
        arten = sorted({f["art"] for f in r["fehler"]})
        passt = (r["ok"] if erwartet is True else arten == [erwartet])
        alle_ok &= passt
        print(f"{'✓' if passt else '✗ FALSCH'}  {('ok' if r['ok'] else ', '.join(arten)):26}  {text}")
        for f in r["fehler"]:
            print(f"      -> {f['zahl']} [{f['id']}]: {f['erwartet']}")
    assert alle_ok, "Mindestens ein Richtungs-Test hat ein unerwartetes Ergebnis"

    print("\n=== Minuszeichen vereinheitlichen ===")
    roh_llm = "Meta‑Kaufwert sank (‑629 € [G53]); Retargeting – Warenkorb"
    print(f"vorher:  {roh_llm}\nnachher: {normiere(roh_llm)}")
    assert normiere(roh_llm) == "Meta-Kaufwert sank (−629 € [G53]); Retargeting – Warenkorb"

    print("\n=== Pflicht-Check ===")
    print(f"Pflicht Gesamtbild: {fakten['pflicht_gesamtbild']}")
    for b in fakten["befunde"]:
        print(f"Pflicht {b['kampagne']}: {b['pflicht']}")
    print(f"Feste Hinweise (schreibt der Code): {fakten['feste_hinweise']}")
    ohne_fallzahl = {**absaetze, "befunde": [
        {**b, "text": b["text"].replace("Achtung, geringe Fallzahl:", "Achtung:")} for b in absaetze["befunde"]]}
    fehlend = pruefe_pflicht(ohne_fallzahl, fakten)
    print("Test 'geringe Fallzahl' entfernt ->", [f["zahl"] for f in fehlend])
    assert len(fehlend) == sum(b["geringe_fallzahl"] for b in fakten["befunde"])

    if "zeitlich zusammen" in fakten["pflicht_gesamtbild"]:
        # Rabatt-Satz weglassen -> Pflicht-Check muss es merken
        ohne_rabatt = {**absaetze, "gesamtbild": " ".join(
            s for s in fakten["gesamtbild"] if "zeitlich zusammen" not in s)}
        fehlend = [f["zahl"] for f in pruefe_pflicht(ohne_rabatt, fakten)]
        print("Test Rabatt-Satz entfernt ->", fehlend)
        assert any("zusammen" in f for f in fehlend)

    print("\n=== Ablauf mit simuliertem LLM (ohne API, Log und Läufe in Testordner) ===")
    gut = json.dumps(absaetze, ensure_ascii=False)   # der Ersatztext als "perfekte" LLM-Antwort
    schlecht = json.dumps({**absaetze, "gesamtbild": "Der Umsatz sank um rund 600 €."}, ensure_ascii=False)
    ohne_pflicht = json.dumps(ohne_fallzahl, ensure_ascii=False)

    with tempfile.TemporaryDirectory() as ordner:
        log = Path(ordner) / "test.log"
        laeufe = Path(ordner) / "laeufe"
        faelle = [
            ("1. Versuch gut", [gut]),
            ("1. schlecht, 2. gut", [schlecht, gut]),
            ("beide schlecht", [schlecht, schlecht]),
            ("kein JSON, dann gut", ["Hier ist der Text: ...", gut]),
            ("Pflicht fehlt, dann gut", [ohne_pflicht, gut]),
        ]
        for name, antworten in faelle:
            antworten = list(antworten)
            ergebnis = erzeuge_text(fakten, werte, kampagnen, e["woche"], llm=lambda s, n: antworten.pop(0),
                                    log_datei=log, wartezeit=0, laeufe_ordner=laeufe)
            print(f"{name:24} -> Quelle: {ergebnis['quelle']:10}  Versuche: {ergebnis['versuche']}")

        def kaputt(s, n):
            raise RuntimeError("GROQ_API_KEY fehlt in .env")
        ergebnis = erzeuge_text(fakten, werte, kampagnen, e["woche"], llm=kaputt, log_datei=log,
                                wartezeit=0, laeufe_ordner=laeufe)
        print(f"{'API-Fehler':24} -> Quelle: {ergebnis['quelle']:10}  Versuche: {ergebnis['versuche']}")
        print(f"Gespeicherte Läufe: {len(list(laeufe.glob('*.md')))}")

        print("\nLog-Einträge (Art des Fehlschlags):")
        for zeile in log.read_text(encoding="utf-8").splitlines():
            eintrag = json.loads(zeile)
            print(f"  Versuch {eintrag['versuch']}: {[f['art'] for f in eintrag['fehler']]}")
