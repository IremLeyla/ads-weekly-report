"""
Schritt 2 und 3: Kennzahlen, Woche gegen Vorwoche, Regeln und Treiber.

(Schritt 4 – Meta gegen Shopify – kommt später in diese Datei.)

Grundsätze:
- Alle Quoten werden aus Wochen-SUMMEN berechnet, nie aus Tageswerten.
- Es wird hier nicht gerundet. Gerundet wird erst bei der Anzeige.
- Die Zerlegung sagt, WELCHER Baustein sich bewegt hat, nicht WARUM.
"""

import math

import numpy as np
import pandas as pd

import einstellungen


# ===============================================================
# Hilfsfunktion: sicher teilen
# ===============================================================
def teile(zaehler, nenner):
    """Teilt zwei Spalten. Ist der Nenner 0, kommt NaN (= "kein Wert") heraus.

    Beispiel: CPA bei 0 Käufen gibt es nicht. 0 oder "unendlich" wären
    erfundene Zahlen, deshalb bleibt der Wert leer.
    """
    return zaehler / nenner.replace(0, np.nan)


# ===============================================================
# Schritt 2a: Kennzahlen
# ===============================================================
def meta_quoten(df: pd.DataFrame) -> pd.DataFrame:
    """Quoten, die nur Meta-Zahlen brauchen (gesamt und pro Kampagne gleich)."""
    df["ctr"] = teile(df["klicks"], df["impressionen"])
    df["cpm"] = teile(df["ausgaben"], df["impressionen"]) * 1000  # Preis pro 1.000 Impressionen
    df["cr"] = teile(df["kaeufe_meta"], df["klicks"])             # Conversion-Rate: Käufe je Klick
    df["cpa"] = teile(df["ausgaben"], df["kaeufe_meta"])
    df["roas"] = teile(df["kaufwert_meta"], df["ausgaben"])
    df["aov_meta"] = teile(df["kaufwert_meta"], df["kaeufe_meta"])
    return df


def kennzahlen_gesamt(gesamt: pd.DataFrame) -> pd.DataFrame:
    """Gesamt-Wochentabelle plus Quoten (Meta- und Shopify-Seite)."""
    df = meta_quoten(gesamt.copy())
    df["aov"] = teile(df["umsatz"], df["bestellungen"])             # Shopify, alle Bestellungen
    df["roas_shopify"] = teile(df["umsatz_fb"], df["ausgaben"])     # Shopify, nur facebook
    return df


def kennzahlen_kampagnen(kampagnen: pd.DataFrame) -> pd.DataFrame:
    """Kampagnen-Tabelle plus Quoten (nur Meta – Shopify kennt keine Kampagne)."""
    return meta_quoten(kampagnen.copy())


# Welche Kennzahlen im Vergleich auftauchen (Reihenfolge = Reihenfolge im Report)
KENNZAHLEN_GESAMT = [
    "ausgaben", "impressionen", "cpm", "klicks", "ctr", "cr",
    "kaeufe_meta", "kaufwert_meta", "aov_meta", "cpa", "roas", "roas_shopify",
    "bestellungen", "umsatz", "aov", "rabatt",
    "bestellungen_fb", "umsatz_fb",
]

KENNZAHLEN_KAMPAGNE = [
    "ausgaben", "impressionen", "cpm", "klicks", "ctr", "cr",
    "kaeufe_meta", "kaufwert_meta", "aov_meta", "cpa", "roas",
]


# ===============================================================
# Schritt 2b: Woche gegen Vorwoche
# ===============================================================
def vergleiche(diese: pd.Series, basis: pd.Series, vorwoche: pd.Series, kennzahlen: list) -> pd.DataFrame:
    """Lange Tabelle: eine Zeile pro Kennzahl.

    basis:    der Maßstab für Änderung und Markierung (typische Woche oder Vorwoche)
    vorwoche: nur zur Anzeige im Report

    Spalten: kennzahl, diese_woche, basis, vorwoche, aenderung_abs, aenderung_prozent
    """
    tabelle = pd.DataFrame({
        "kennzahl": kennzahlen,
        "diese_woche": [diese[k] for k in kennzahlen],
        "basis": [basis[k] for k in kennzahlen],
        "vorwoche": [vorwoche[k] for k in kennzahlen],
    })
    tabelle["aenderung_abs"] = tabelle["diese_woche"] - tabelle["basis"]
    # Prozent: Änderung im Verhältnis zur Basis. Basis 0 -> NaN.
    tabelle["aenderung_prozent"] = teile(tabelle["aenderung_abs"], tabelle["basis"]) * 100
    return tabelle


# ===============================================================
# Schritt 2c: Die Vergleichsbasis – typische Woche oder Vorwoche
# ===============================================================
# Meta-Summen, die es pro Kampagne gibt (gesamt = Summe der Kampagnen)
META_SUMMEN_GESAMT = ["ausgaben", "impressionen", "klicks", "kaeufe_meta", "kaufwert_meta"]


def basis_wochen(alle_wochen: list, woche: pd.Timestamp) -> tuple:
    """Welche Wochen bilden die Vergleichsbasis?

    Gibt es mindestens einstellungen.VERGLEICH_WOCHEN frühere Wochen:
        -> ("typisch", die letzten N Wochen davor). Die aktuelle Woche ist NIE dabei.
    Sonst:
        -> ("vorwoche", [Vorwoche])
    """
    n = einstellungen.VERGLEICH_WOCHEN
    frueher = [w for w in alle_wochen if w < woche]
    if len(frueher) >= n:
        return "typisch", frueher[-n:]
    return "vorwoche", [woche - pd.Timedelta(days=7)]


def basis_summen(tabelle: pd.DataFrame, art: str, wochen: list) -> pd.Series:
    """Summen der Vergleichsbasis aus einer Wochentabelle (Index = Woche).

    typisch:  Median JEDER Summe über die Basiswochen. Quoten werden später
              aus diesen Summen berechnet (nicht als Median der Quoten).
              Der Median ist robust: Eine einzelne Ausnahmewoche (Black Friday,
              Rabattaktion) verzerrt ihn kaum.
    vorwoche: einfach die Summen der Vorwoche.
    """
    teil = tabelle.loc[tabelle.index.isin(wochen)]
    if teil.empty:
        return pd.Series(np.nan, index=tabelle.columns)
    return teil.median() if art == "typisch" else teil.iloc[0]


# ===============================================================
# Schritt 3a: Regeln – welche Änderung ist "stark"?
# ===============================================================

# Welche Schwelle aus einstellungen.py gilt für welche Kennzahl?
# Kennzahlen, die hier fehlen (z. B. impressionen, cpm, rabatt), werden nicht markiert.
SCHWELLEN_GRUPPE = {
    "ausgaben": "ausgaben",
    "klicks": "klicks",
    "bestellungen": "bestellungen",
    "bestellungen_fb": "bestellungen",
    "kaeufe_meta": "kaeufe_meta",
    "umsatz": "umsatz",
    "umsatz_fb": "umsatz",
    "kaufwert_meta": "umsatz",
    "aov": "aov",
    "aov_meta": "aov",
    "roas": "roas",
    "roas_shopify": "roas",
    "cpa": "cpa",
    "ctr": "ctr",
}

# Der Meta-AOV stützt sich auf Meta-Käufe, nicht auf Shopify-Bestellungen.
# Für ihn wird die Mindestgröße deshalb an den Meta-Käufen geprüft.
BASIS_ABWEICHEND = {"aov_meta": "kaeufe_meta"}

# Kennzahlen, die auf Meta-Käufen beruhen. Pro Kampagne gilt für sie
# die Käufe-Mindestgröße aus einstellungen.MINDEST_KAEUFE_KAMPAGNE.
KAEUFE_BASIERT = {"kaeufe_meta", "kaufwert_meta", "aov_meta", "cpa", "roas"}


def ist_kaeufe_regel(kennzahl: str, gruppe: str) -> bool:
    """Ist die normale Mindestgröße dieser Kennzahl eine Käufe-Regel?

    Pro Kampagne werden genau diese Regeln durch die neue Käufe-Regel ersetzt.
    """
    if gruppe in einstellungen.MINDEST_AENDERUNG:
        return gruppe == "kaeufe_meta"
    if gruppe in einstellungen.MINDEST_BASIS:
        spalte = BASIS_ABWEICHEND.get(kennzahl, einstellungen.MINDEST_BASIS[gruppe][0])
        return spalte == "kaeufe_meta"
    return False


def gross_genug(kennzahl: str, gruppe: str, zeile: pd.Series, werte: pd.DataFrame) -> bool:
    """Prüft die normale Mindestgröße (siehe einstellungen.py).

    Mengen: Die absolute Änderung muss groß genug sein.
    Quoten: Die Grundlage muss in BEIDEN Wochen groß genug sein.
    """
    if gruppe in einstellungen.MINDEST_AENDERUNG:
        return abs(zeile["aenderung_abs"]) >= einstellungen.MINDEST_AENDERUNG[gruppe]

    if gruppe in einstellungen.MINDEST_BASIS:
        spalte, minimum = einstellungen.MINDEST_BASIS[gruppe]
        spalte = BASIS_ABWEICHEND.get(kennzahl, spalte)
        return (werte.loc[spalte, "diese_woche"] >= minimum
                and werte.loc[spalte, "basis"] >= minimum)

    return True  # keine Mindestgröße festgelegt


def markiere(tabelle: pd.DataFrame, ist_kampagne: bool = False) -> pd.DataFrame:
    """Wendet die Regeln auf eine Vergleichstabelle an (gesamt ODER eine Kampagne).

    Neue Spalten:
      schwelle_prozent  welche Schwelle galt
      markiert          True / False
      status            Begründung in Worten
      hinweis           z. B. "geringe Fallzahl" (sonst leer)
    """
    werte = tabelle.set_index("kennzahl")  # zum Nachschlagen der Grundlage

    # Pro Kampagne: der größere Käufe-Wert der beiden Wochen
    if ist_kampagne:
        kaeufe_max = max(werte.loc["kaeufe_meta", "diese_woche"],
                         werte.loc["kaeufe_meta", "basis"])

    schwellen, markiert, status, hinweise = [], [], [], []

    for _, zeile in tabelle.iterrows():
        kennzahl = zeile["kennzahl"]
        gruppe = SCHWELLEN_GRUPPE.get(kennzahl)
        hinweis = ""

        if gruppe is None:
            schwellen.append(np.nan)
            markiert.append(False)
            status.append("keine Regel")
            hinweise.append("")
            continue

        schwelle = einstellungen.SCHWELLEN_PROZENT[gruppe]
        schwellen.append(schwelle)

        # Gilt pro Kampagne die Käufe-Regel für diese Kennzahl?
        kaeufe_regel = ist_kampagne and kennzahl in KAEUFE_BASIERT

        if pd.isna(zeile["aenderung_prozent"]):
            ergebnis = "kein Vergleich möglich"
        elif abs(zeile["aenderung_prozent"]) < schwelle:
            ergebnis = "unter Schwelle"
        elif kaeufe_regel and kaeufe_max < einstellungen.MINDEST_KAEUFE_KAMPAGNE:
            ergebnis = "Mindestgröße nicht erreicht"
        # Normale Mindestgröße – außer sie ist eine Käufe-Regel, die pro Kampagne ersetzt wurde
        elif not (kaeufe_regel and ist_kaeufe_regel(kennzahl, gruppe)) \
                and not gross_genug(kennzahl, gruppe, zeile, werte):
            ergebnis = "Mindestgröße nicht erreicht"
        else:
            ergebnis = "markiert"
            if kaeufe_regel and kaeufe_max < einstellungen.GERINGE_FALLZAHL_UNTER:
                hinweis = "geringe Fallzahl"

        markiert.append(ergebnis == "markiert")
        status.append(ergebnis)
        hinweise.append(hinweis)

    tabelle = tabelle.copy()
    tabelle["schwelle_prozent"] = schwellen
    tabelle["markiert"] = markiert
    tabelle["status"] = status
    tabelle["hinweis"] = hinweise
    return tabelle


# ===============================================================
# Schritt 3b: Zerlegung in Treiber (Log-Methode)
# ===============================================================

# Kennzahl -> Liste von (Baustein, Richtung)
# Richtung +1: Baustein steht im Zähler (mehr davon = mehr Ergebnis)
# Richtung -1: Baustein steht im Nenner (mehr davon = weniger Ergebnis)
ZERLEGUNGEN = {
    # Umsatz = Bestellungen × AOV                     (nur gesamt, Shopify)
    "umsatz": [("bestellungen", +1), ("aov", +1)],
    # Meta-Kaufwert = Meta-Käufe × Meta-AOV
    "kaufwert_meta": [("kaeufe_meta", +1), ("aov_meta", +1)],
    # Meta-Käufe = Ausgaben ÷ CPM × 1000 × CTR × Conversion-Rate
    # (die 1000 ist eine Konstante und kürzt sich beim Wochenvergleich weg)
    "kaeufe_meta": [("ausgaben", +1), ("cpm", -1), ("ctr", +1), ("cr", +1)],
    # ROAS = Kaufwert ÷ Ausgaben
    "roas": [("kaufwert_meta", +1), ("ausgaben", -1)],
    # CPA = Ausgaben ÷ Käufe
    "cpa": [("ausgaben", +1), ("kaeufe_meta", -1)],
}


# Grundzahlen (Summen), aus denen alle Quoten entstehen
GRUNDZAHLEN = ["ausgaben", "impressionen", "klicks", "kaeufe_meta", "kaufwert_meta",
               "bestellungen", "umsatz"]


def nullgrund(diese: pd.Series, basis: pd.Series, namen: list) -> str:
    """Nennt alle Werte aus `namen`, die 0 sind oder fehlen. Leer, wenn alles okay ist.

    Beispiel: "kaeufe_meta ist 0 (diese Woche)"
    """
    gruende = []
    for name in namen:
        for wert, wann in [(basis.get(name), "Vergleichswert"), (diese.get(name), "diese Woche")]:
            if pd.isna(wert):
                gruende.append(f"{name} fehlt ({wann})")
            elif wert <= 0:
                gruende.append(f"{name} ist 0 ({wann})")
    return "; ".join(gruende)


# Die lange Kette für den Kaufwert. Sie wird nicht im Report als Zerlegung gezeigt,
# sondern dient zur Messung der Euro-Wirkung (siehe EURO_AUS_KETTE weiter unten).
# Kaufwert = Ausgaben ÷ CPM × 1000 × CTR × Conversion-Rate × Meta-AOV
KAUFWERT_KETTE = [("ausgaben", +1), ("cpm", -1), ("ctr", +1), ("cr", +1), ("aov_meta", +1)]


def zerlege(kennzahl: str, diese: pd.Series, basis: pd.Series, bausteine=None):
    """Zerlegt die Änderung einer Kennzahl in die Beiträge ihrer Bausteine.

    Idee: ln(a × b) = ln(a) + ln(b). Im Log-Raum addieren sich die
    Änderungen der Bausteine also GENAU zur Gesamtänderung, ohne Rest.
    Danach wird die echte Änderung (in € oder Stück) nach diesen Anteilen verteilt.

    bausteine: optional eine eigene Liste (z. B. KAUFWERT_KETTE),
               sonst die Formel aus ZERLEGUNGEN.

    Rückgabe: (status, tabelle)
      status  "ok" oder "nicht berechenbar: <Grund>"
      tabelle eine Zeile pro Baustein (bei "nicht berechenbar": None)
    """
    if bausteine is None:
        bausteine = ZERLEGUNGEN[kennzahl]
    ziel_neu, ziel_alt = diese[kennzahl], basis[kennzahl]

    # 1) Nullwerte abfangen: ln(0) gibt es nicht
    namen = [kennzahl] + [baustein for baustein, _ in bausteine]
    if nullgrund(diese, basis, namen):
        # Grund möglichst an der GRUNDZAHL festmachen (z. B. "kaeufe_meta ist 0"),
        # nicht an einer abgeleiteten Quote (z. B. "cr ist 0").
        grund = nullgrund(diese, basis, [s for s in GRUNDZAHLEN if s in diese.index]) \
            or nullgrund(diese, basis, namen)
        return f"nicht berechenbar: {grund}", None

    # 2) Keine Änderung -> nichts aufzuteilen
    log_gesamt = math.log(ziel_neu / ziel_alt)
    if log_gesamt == 0:
        return "nicht berechenbar: keine Änderung", None

    # 3) Anteil jedes Bausteins
    aenderung_gesamt = ziel_neu - ziel_alt
    zeilen = []
    for baustein, richtung in bausteine:
        alt, neu = basis[baustein], diese[baustein]
        log_teil = richtung * math.log(neu / alt)
        anteil = log_teil / log_gesamt
        zeilen.append({
            "baustein": baustein,
            "richtung": richtung,
            "basis": alt,
            "diese_woche": neu,
            "aenderung_prozent": (neu / alt - 1) * 100,
            "beitrag": aenderung_gesamt * anteil,   # in Einheit der Kennzahl (€, Stück, ...)
            "anteil_prozent": anteil * 100,          # Anteil an der Gesamtänderung
            "_log_teil": log_teil,                   # nur für die Kontrolle unten
        })
    tabelle = pd.DataFrame(zeilen)

    # 4) Kontrolle: Die Teile müssen genau die Gesamtänderung ergeben
    assert math.isclose(tabelle["_log_teil"].sum(), log_gesamt, rel_tol=1e-9), \
        f"Zerlegung von {kennzahl} geht nicht auf"
    return "ok", tabelle.drop(columns="_log_teil")


def zerlege_markierte(vergleich: pd.DataFrame, diese: pd.Series, basis: pd.Series,
                      ebene: str) -> pd.DataFrame:
    """Zerlegt alle markierten Kennzahlen einer Ebene (gesamt oder eine Kampagne).

    Ergebnis: lange Tabelle mit Spalten ebene, kennzahl, status, baustein, ...
    Für Kennzahlen ohne Formel (z. B. Ausgaben) gibt es keine Zerlegung.
    """
    teile_liste = []
    for kennzahl in vergleich.loc[vergleich["markiert"], "kennzahl"]:
        if kennzahl not in ZERLEGUNGEN:
            continue
        status, tabelle = zerlege(kennzahl, diese, basis)
        if tabelle is None:
            tabelle = pd.DataFrame([{}])  # eine leere Zeile, damit der Status sichtbar bleibt
        tabelle.insert(0, "status", status)
        tabelle.insert(0, "kennzahl", kennzahl)
        tabelle.insert(0, "ebene", ebene)
        teile_liste.append(tabelle)

    if not teile_liste:
        return pd.DataFrame(columns=["ebene", "kennzahl", "status"])
    return pd.concat(teile_liste, ignore_index=True)


# ===============================================================
# Schritt 3c: Euro-Wirkung jeder Kennzahl (über ihren Beitrag zum Kaufwert)
# ===============================================================

# Jede Kennzahl besteht aus Bausteinen der Kaufwert-Kette.
# Ihre Euro-Wirkung = Summe der Euro-Beiträge dieser Bausteine.
EURO_AUS_KETTE = {
    "ausgaben":      ["ausgaben"],
    "ctr":           ["ctr"],
    "aov_meta":      ["aov_meta"],
    "klicks":        ["ausgaben", "cpm", "ctr"],              # Klicks = Ausgaben ÷ CPM × CTR
    "kaeufe_meta":   ["ausgaben", "cpm", "ctr", "cr"],        # Käufe  = Klicks × CR
    "cpa":           ["cpm", "ctr", "cr"],                    # CPA    = CPM ÷ (CTR × CR)
    "roas":          ["cpm", "ctr", "cr", "aov_meta"],        # ROAS   = Kaufwert ÷ Ausgaben
    "kaufwert_meta": ["ausgaben", "cpm", "ctr", "cr", "aov_meta"],
}


def euro_wirkung(kennzahl: str, kette) -> float:
    """Euro-Wirkung einer Kennzahl auf den Kaufwert.

    kette: Ergebnis der Kaufwert-Zerlegung (oder None, wenn nicht berechenbar).
    Gibt NaN zurück, wenn die Kennzahl nicht in der Kette steckt
    (z. B. Shopify-Werte) oder die Kette nicht berechenbar war.
    """
    if kette is None or kennzahl not in EURO_AUS_KETTE:
        return np.nan
    teile_der_kette = kette[kette["baustein"].isin(EURO_AUS_KETTE[kennzahl])]
    return teile_der_kette["beitrag"].sum()


# ===============================================================
# Schritt 3d: Markierungen zu Befunden bündeln und nach Euro sortieren
# ===============================================================

# Bereiche einer Kampagne
ERGEBNIS_KENNZAHLEN = {"kaeufe_meta", "kaufwert_meta", "aov_meta", "cpa", "roas"}
BUDGET_KENNZAHLEN = {"ausgaben", "klicks", "ctr"}


def bilde_befunde(vergleich_kampagnen: pd.DataFrame, kaufwert_ketten: pd.DataFrame) -> pd.DataFrame:
    """Bündelt die markierten Kennzahlen jeder Kampagne zu EINEM Befund.

    Bündeln:
    - Ist eine Ergebnis-Kennzahl markiert -> Befund "Meta-Ergebnis".
      Markierte Budget-Kennzahlen derselben Kampagne gehören mit dazu
      (sie werden im Text als Treiber genannt, nicht eigen gerankt).
    - Ist nur Budget markiert -> Befund "Budget und Reichweite".

    Euro-Wirkung des Befunds (danach wird sortiert):
    - Kaufwert markiert ODER Treiber nicht berechenbar -> echte Änderung des Kaufwerts.
      (Ein Absturz auf 0 wird so normal gerankt, oft ist er der wichtigste Befund.)
    - sonst -> größte Euro-Wirkung seiner markierten Kennzahlen.

    Zusätzlich für den Text:
      budget_beitrag     Euro-Beitrag der Ausgaben zum Kaufwert
      effizienz_beitrag  Euro-Wirkung des ROAS (alles außer Budget)
      treiber_status     "ok" oder "nicht berechenbar: <Grund>"
    """
    markiert = vergleich_kampagnen[vergleich_kampagnen["markiert"]]
    befunde = []

    for kampagne, zeilen in markiert.groupby("kampagne", sort=False):
        ergebnis = zeilen[zeilen["kennzahl"].isin(ERGEBNIS_KENNZAHLEN)]
        budget = zeilen[zeilen["kennzahl"].isin(BUDGET_KENNZAHLEN)]

        if len(ergebnis) > 0:
            bereich, massgeblich = "Meta-Ergebnis", ergebnis
        elif len(budget) > 0:
            bereich, massgeblich = "Budget und Reichweite", budget
        else:
            continue  # sollte nicht vorkommen: jede Kampagnen-Kennzahl mit Regel ist in einem Bereich

        # Alle Werte dieser Kampagne (auch unmarkierte) und ihre Kaufwert-Kette
        alle = vergleich_kampagnen[vergleich_kampagnen["kampagne"] == kampagne].set_index("kennzahl")
        kette = kaufwert_ketten[kaufwert_ketten["ebene"] == kampagne]
        treiber_status = kette["status"].iloc[0]
        kaufwert_aenderung = alle.loc["kaufwert_meta", "aenderung_abs"]

        if treiber_status == "ok":
            budget_beitrag = kette.loc[kette["baustein"] == "ausgaben", "beitrag"].sum()
            effizienz_beitrag = alle.loc["roas", "euro_wirkung"]
        else:
            budget_beitrag = effizienz_beitrag = np.nan

        # Euro-Wirkung (Variante b)
        if "kaufwert_meta" in zeilen["kennzahl"].values or treiber_status != "ok":
            wirkung, quelle = kaufwert_aenderung, "Kaufwert-Änderung"
        else:
            wirkungen = massgeblich["euro_wirkung"].dropna()
            wirkung = wirkungen.loc[wirkungen.abs().idxmax()]   # Vorzeichen bleibt erhalten
            quelle = "größte Einzelwirkung"

        befunde.append({
            "kampagne": kampagne,
            "bereich": bereich,
            "euro_wirkung": wirkung,
            "wirkung_quelle": quelle,
            "kaufwert_aenderung": kaufwert_aenderung,
            "budget_beitrag": budget_beitrag,
            "effizienz_beitrag": effizienz_beitrag,
            "treiber_status": treiber_status,
            "kennzahlen": ", ".join(zeilen["kennzahl"]),   # alle Markierungen inkl. Budget
            "geringe_fallzahl": (zeilen["hinweis"] == "geringe Fallzahl").any(),
        })

    spalten = ["kampagne", "bereich", "euro_wirkung", "wirkung_quelle", "kaufwert_aenderung",
               "budget_beitrag", "effizienz_beitrag", "treiber_status", "kennzahlen",
               "geringe_fallzahl"]
    tabelle = pd.DataFrame(befunde, columns=spalten)
    tabelle["_sortierung"] = tabelle["euro_wirkung"].abs()
    # NaN gibt es nur noch, wenn die Kampagne in der Vorwoche fehlte -> ans Ende
    tabelle = tabelle.sort_values("_sortierung", ascending=False, na_position="last")
    tabelle = tabelle.drop(columns="_sortierung").reset_index(drop=True)

    tabelle.insert(0, "rang", range(1, len(tabelle) + 1))
    tabelle["im_text"] = tabelle["rang"] <= einstellungen.TOP_BEFUNDE_IM_TEXT
    return tabelle


# ===============================================================
# Schritt 3e: Welche Kampagne hat wie viel zur Gesamtänderung beigetragen?
# ===============================================================

# Nur Summen: Die addieren sich über Kampagnen. Quoten (ROAS, CPA ...) nicht.
SUMMEN_FUER_BEITRAG = ["ausgaben", "impressionen", "klicks", "kaeufe_meta", "kaufwert_meta"]


def kampagnen_beitraege(vergleich_kampagnen: pd.DataFrame,
                        vergleich_gesamt: pd.DataFrame) -> pd.DataFrame:
    """Anteil jeder Kampagne an der Gesamtänderung einer Summe.

    Beispiel: Ausgaben gesamt −100 €, Kampagne A −80 € -> Anteil 80 %.
    Laufen Kampagnen gegeneinander, kann ein Anteil negativ oder über 100 % sein.
    """
    teil = vergleich_kampagnen[vergleich_kampagnen["kennzahl"].isin(SUMMEN_FUER_BEITRAG)]
    teil = teil[["kampagne", "kennzahl", "basis", "diese_woche", "aenderung_abs"]].copy()

    summe = teil.groupby("kennzahl")["aenderung_abs"].sum()

    # Kontrolle: Summe der Kampagnen = Gesamtwert aus der Gesamt-Tabelle
    gesamt = vergleich_gesamt.set_index("kennzahl")["aenderung_abs"]
    for kennzahl in SUMMEN_FUER_BEITRAG:
        assert math.isclose(summe[kennzahl], gesamt[kennzahl], abs_tol=1e-6), \
            f"Kampagnen ergeben nicht den Gesamtwert bei {kennzahl}"

    teil["aenderung_gesamt"] = teil["kennzahl"].map(summe)
    teil["anteil_prozent"] = teile(teil["aenderung_abs"], teil["aenderung_gesamt"]) * 100
    return teil.reset_index(drop=True)


# ===============================================================
# Schritt 4: Meta-Käufe gegen Shopify-Bestellungen (utm_source = facebook)
# ===============================================================
def meta_gegen_shopify(gesamt: pd.DataFrame, woche: pd.Timestamp) -> dict:
    """Stellt Meta-Zahlen und Shopify-Facebook-Zahlen nebeneinander.

    Keine der beiden Zahlen ist "die richtige". Der Code zeigt nur den Unterschied.

    Rückgabe:
      tabelle    alle Wochen bis einschließlich `woche`
      vergleich  diese Woche gegen Vorwoche (lange Tabelle wie bei den Kennzahlen)
      spanne     Verhältnis Meta ÷ Shopify in den Wochen DAVOR: min, mittel, max,
                 und ob diese Woche außerhalb dieser Spanne liegt

    Feste Regel: markiert, wenn das Verhältnis außerhalb der Spanne aller
    früheren Wochen liegt, aber erst ab einstellungen.MINDEST_WOCHEN_GESCHICHTE
    früheren Wochen. Die Richtung ("ungewöhnlich klein/groß") ist neutral
    formuliert, eine Ursache nennt der Code nicht.
    """
    vorwoche = woche - pd.Timedelta(days=7)

    t = pd.DataFrame(index=gesamt.index)
    # Stückzahl
    t["kaeufe_meta"] = gesamt["kaeufe_meta"]
    t["bestellungen_fb"] = gesamt["bestellungen_fb"]
    t["differenz_stueck"] = t["kaeufe_meta"] - t["bestellungen_fb"]
    t["verhaeltnis_stueck"] = teile(t["kaeufe_meta"], t["bestellungen_fb"])
    # Wert
    t["kaufwert_meta"] = gesamt["kaufwert_meta"]
    t["umsatz_fb"] = gesamt["umsatz_fb"]
    t["differenz_euro"] = t["kaufwert_meta"] - t["umsatz_fb"]
    t["verhaeltnis_euro"] = teile(t["kaufwert_meta"], t["umsatz_fb"])
    t = t.loc[:woche]

    # Hier bleibt der Maßstab die Vorwoche (dazu kommt die Spanne aller früheren Wochen)
    vergleich = vergleiche(t.loc[woche], t.loc[vorwoche], t.loc[vorwoche], list(t.columns))

    # Spanne der früheren Wochen (alle vor `woche`)
    frueher = t.loc[t.index < woche]
    zeilen = []
    genug_geschichte = len(frueher) >= einstellungen.MINDEST_WOCHEN_GESCHICHTE

    for spalte in ["verhaeltnis_stueck", "verhaeltnis_euro"]:
        jetzt = t.loc[woche, spalte]
        minimum, maximum = frueher[spalte].min(), frueher[spalte].max()

        if not genug_geschichte:
            status, richtung = "zu wenig Geschichte", ""
        elif jetzt < minimum:
            status, richtung = "markiert", "ungewöhnlich klein"
        elif jetzt > maximum:
            status, richtung = "markiert", "ungewöhnlich groß"
        else:
            status, richtung = "innerhalb der Spanne", ""

        zeilen.append({
            "kennzahl": spalte,
            "diese_woche": jetzt,
            "frueher_min": minimum,
            "frueher_mittel": frueher[spalte].mean(),
            "frueher_max": maximum,
            "wochen_frueher": len(frueher),
            "markiert": status == "markiert",
            "status": status,
            "richtung": richtung,
        })

    return {"tabelle": t, "vergleich": vergleich, "spanne": pd.DataFrame(zeilen)}


# ===============================================================
# Alles für eine Woche
# ===============================================================
def analysiere_woche(daten: dict, woche: pd.Timestamp) -> dict:
    """Führt Schritt 2 und 3 für eine Woche aus.

    Rückgabe (alles pandas-Tabellen):
      vergleich_gesamt      Kennzahlen gesamt, mit Markierung und Euro-Wirkung
      vergleich_kampagnen   Kennzahlen pro Kampagne, mit Markierung und Euro-Wirkung
      zerlegungen           Treiber aller markierten Kennzahlen
      kaufwert_ketten       Euro-Beitrag jedes Bausteins zum Kaufwert (gesamt + Kampagnen)
      befunde               gebündelte Markierungen, nach Euro-Wirkung sortiert
      kampagnen_beitraege   Anteil jeder Kampagne an der Gesamtänderung
    """
    vorwoche = woche - pd.Timedelta(days=7)
    gesamt = kennzahlen_gesamt(daten["gesamt"])
    kampagnen = kennzahlen_kampagnen(daten["kampagnen"])
    ketten = []

    # --- Vergleichsbasis: typische Woche (Median der letzten N) oder Vorwoche ---
    art, b_wochen = basis_wochen(daten["wochen"], woche)
    roh_k = daten["kampagnen"]
    namen_kampagnen = list(kampagnen.loc[woche].index)

    k_basis_summen = {}
    for kampagne in namen_kampagnen:
        if kampagne in roh_k.index.get_level_values("kampagne"):
            k_basis_summen[kampagne] = basis_summen(roh_k.xs(kampagne, level="kampagne"), art, b_wochen)

    g_summen = basis_summen(daten["gesamt"], art, b_wochen)
    if art == "typisch":
        # Meta gesamt = Summe der typischen Wochen der Kampagnen.
        # So bleibt "gesamt = Summe der Kampagnen" wahr (wichtig für die Anteile pro Kampagne).
        # Shopify hat keine Kampagnen -> dort gilt der Median der Gesamtwerte.
        g_summen[META_SUMMEN_GESAMT] = sum(s[META_SUMMEN_GESAMT] for s in k_basis_summen.values())

    def mit_quoten(summen: pd.Series, fuer_gesamt: bool) -> pd.Series:
        """Quoten (ROAS, CPA ...) aus den Summen der Basis berechnen."""
        zeile = summen.to_frame().T.astype(float)
        return (kennzahlen_gesamt(zeile) if fuer_gesamt else kennzahlen_kampagnen(zeile)).iloc[0]

    def kaufwert_kette(diese, basis, ebene):
        """Kaufwert-Kette zerlegen und für die Ausgabe merken."""
        status, kette = zerlege("kaufwert_meta", diese, basis, bausteine=KAUFWERT_KETTE)
        if kette is not None:
            ketten.append(kette.assign(ebene=ebene, status=status))
        else:
            ketten.append(pd.DataFrame([{"ebene": ebene, "status": status}]))
        return kette

    # --- Gesamt ---
    g_diese, g_vor = gesamt.loc[woche], gesamt.loc[vorwoche]
    g_basis = mit_quoten(g_summen, fuer_gesamt=True)
    v_gesamt = markiere(vergleiche(g_diese, g_basis, g_vor, KENNZAHLEN_GESAMT))
    g_kette = kaufwert_kette(g_diese, g_basis, "Gesamt")
    v_gesamt["euro_wirkung"] = v_gesamt["kennzahl"].map(lambda k: euro_wirkung(k, g_kette))
    zerlegungen = [zerlege_markierte(v_gesamt, g_diese, g_basis, "Gesamt")]

    # --- Pro Kampagne ---
    k_diese_tab, k_vor_tab = kampagnen.loc[woche], kampagnen.loc[vorwoche]
    leer = pd.Series(np.nan, index=kampagnen.columns)
    v_kampagnen = []
    for kampagne in namen_kampagnen:
        k_diese = k_diese_tab.loc[kampagne]
        # Fehlt die Kampagne in der Vorwoche bzw. Basis, ist dort alles NaN (kein Wert)
        k_vor = k_vor_tab.loc[kampagne] if kampagne in k_vor_tab.index else leer
        k_basis = mit_quoten(k_basis_summen[kampagne], fuer_gesamt=False) \
            if kampagne in k_basis_summen else leer

        v = markiere(vergleiche(k_diese, k_basis, k_vor, KENNZAHLEN_KAMPAGNE), ist_kampagne=True)
        k_kette = kaufwert_kette(k_diese, k_basis, kampagne)
        v["euro_wirkung"] = v["kennzahl"].map(lambda k: euro_wirkung(k, k_kette))
        v.insert(0, "kampagne", kampagne)
        v_kampagnen.append(v)
        zerlegungen.append(zerlege_markierte(v, k_diese, k_basis, kampagne))

    v_kampagnen = pd.concat(v_kampagnen, ignore_index=True)
    ketten = pd.concat(ketten, ignore_index=True)

    return {
        "woche": woche,
        "vorwoche": vorwoche,
        "vergleich_art": art,          # "typisch" oder "vorwoche"
        "basis_wochen": b_wochen,      # welche Wochen den Maßstab bilden
        "vergleich_gesamt": v_gesamt,
        "vergleich_kampagnen": v_kampagnen,
        "zerlegungen": pd.concat(zerlegungen, ignore_index=True),
        "kaufwert_ketten": ketten,
        "befunde": bilde_befunde(v_kampagnen, ketten),
        "kampagnen_beitraege": kampagnen_beitraege(v_kampagnen, v_gesamt),
        "meta_gegen_shopify": meta_gegen_shopify(gesamt, woche),
    }


# ===============================================================
# Kleiner Test: python analyse.py
# ===============================================================
if __name__ == "__main__":
    import daten

    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 200)
    pd.set_option("display.max_columns", 20)

    d = daten.lade_wochendaten()
    e = analysiere_woche(d, d["wochen"][-1])
    print(f"Woche {e['woche'].date()} | Maßstab: {e['vergleich_art']} | Basiswochen: "
          f"{[w.date().isoformat() for w in e['basis_wochen']]}\n")

    spalten = ["kennzahl", "vorwoche", "basis", "diese_woche", "aenderung_prozent", "schwelle_prozent",
               "status", "hinweis"]
    print("=== Gesamt ===")
    print(e["vergleich_gesamt"][spalten].round(3).to_string(index=False))

    print("\n=== Kampagnen: nur markierte ===")
    vk = e["vergleich_kampagnen"]
    print(vk.loc[vk["markiert"], ["kampagne"] + spalten].round(3).to_string(index=False))

    print("\n=== Kampagnen: wegen Mindestgröße NICHT markiert ===")
    print(vk.loc[vk["status"] == "Mindestgröße nicht erreicht", ["kampagne"] + spalten].round(3).to_string(index=False))

    print("\n=== Zerlegungen ===")
    print(e["zerlegungen"].round(2).to_string(index=False))

    print("\n=== Kaufwert-Kette (Euro-Beitrag je Baustein) ===")
    kette_spalten = ["ebene", "status", "baustein", "aenderung_prozent", "beitrag", "anteil_prozent"]
    print(e["kaufwert_ketten"][kette_spalten].round(1).to_string(index=False))

    print("\n=== Euro-Wirkung der markierten Kampagnen-Kennzahlen ===")
    print(vk.loc[vk["markiert"], ["kampagne", "kennzahl", "aenderung_prozent", "euro_wirkung", "hinweis"]]
          .round(1).to_string(index=False))

    print("\n=== Befunde ===")
    print(e["befunde"].round(1).to_string(index=False))

    mgs = e["meta_gegen_shopify"]
    print("\n=== Meta gegen Shopify (facebook): alle Wochen ===")
    print(mgs["tabelle"].round(2).to_string())
    print("\n=== Meta gegen Shopify: diese Woche gegen Vorwoche ===")
    print(mgs["vergleich"].round(2).to_string(index=False))
    print("\n=== Meta gegen Shopify: Spanne der früheren Wochen ===")
    print(mgs["spanne"].round(2).to_string(index=False))

    print("\n=== Beitrag der Kampagnen ===")
    print(e["kampagnen_beitraege"].round(1).to_string(index=False))
