"""
Schritt 1: CSV-Exporte einlesen und zu Wochenwerten zusammenfassen.

Eine Woche geht von Montag bis Sonntag.
Wir summieren hier nur Grundzahlen (Ausgaben, Klicks, Käufe, Umsatz ...).
Quoten wie ROAS oder CPA werden erst später aus diesen Summen berechnet,
denn ein Durchschnitt von Tages-Quoten wäre falsch.
"""

import pandas as pd

import einstellungen


# ---------------------------------------------------------------
# Hilfsfunktion: Montag der Woche
# ---------------------------------------------------------------
def montag_der_woche(datum: pd.Series) -> pd.Series:
    """Gibt für jedes Datum den Montag seiner Woche zurück.

    pandas zählt Wochentage so: Montag = 0, ..., Sonntag = 6.
    Datum minus Wochentag (in Tagen) ergibt also immer den Montag.
    .dt.normalize() schneidet vorher die Uhrzeit ab (wichtig für Shopify).
    """
    tag = datum.dt.normalize()
    return tag - pd.to_timedelta(tag.dt.day_of_week, unit="D")


# ---------------------------------------------------------------
# Einlesen
# ---------------------------------------------------------------
def lade_meta(pfad=einstellungen.META_DATEI) -> pd.DataFrame:
    """Liest den Meta-Export (eine Zeile pro Tag und Kampagne)."""
    df = pd.read_csv(pfad, encoding="utf-8")

    # Kurze, einheitliche Spaltennamen
    df = df.rename(columns={
        "ausgaben_eur": "ausgaben",
        "kaufwert_meta_eur": "kaufwert_meta",
    })

    df["datum"] = pd.to_datetime(df["datum"], format="%Y-%m-%d")
    df["woche"] = montag_der_woche(df["datum"])
    return df


def lade_shopify(pfad=einstellungen.SHOPIFY_DATEI) -> pd.DataFrame:
    """Liest den Shopify-Export (eine Zeile pro Bestellung).

    gesamtbetrag_eur ist bereits NACH Abzug des Rabatts (wie "Total" bei Shopify).
    Der Rabatt wird deshalb nur als eigene Spalte mitgeführt, nie nochmal abgezogen.
    """
    df = pd.read_csv(pfad, encoding="utf-8")

    df = df.rename(columns={
        "gesamtbetrag_eur": "umsatz",
        "rabatt_eur": "rabatt",
    })

    df["erstellt_am"] = pd.to_datetime(df["erstellt_am"], format="%Y-%m-%d %H:%M")
    df["woche"] = montag_der_woche(df["erstellt_am"])
    return df


# ---------------------------------------------------------------
# Wochenwerte
# ---------------------------------------------------------------
META_SUMMEN = ["ausgaben", "impressionen", "klicks", "kaeufe_meta", "kaufwert_meta"]


def meta_pro_woche(meta: pd.DataFrame) -> pd.DataFrame:
    """Meta gesamt: eine Zeile pro Woche."""
    return meta.groupby("woche")[META_SUMMEN].sum()


def meta_pro_woche_und_kampagne(meta: pd.DataFrame) -> pd.DataFrame:
    """Meta pro Kampagne: eine Zeile pro (Woche, Kampagne)."""
    return meta.groupby(["woche", "kampagne"])[META_SUMMEN].sum()


def shopify_pro_woche(shopify: pd.DataFrame) -> pd.DataFrame:
    """Shopify gesamt und nur facebook: eine Zeile pro Woche.

    Spalten:
      bestellungen, umsatz, rabatt          -> alle Bestellungen
      bestellungen_fb, umsatz_fb, rabatt_fb -> nur utm_source = facebook
    """
    alle = shopify.groupby("woche").agg(
        bestellungen=("bestellnummer", "count"),
        umsatz=("umsatz", "sum"),
        rabatt=("rabatt", "sum"),
    )

    nur_fb = shopify[shopify["utm_source"] == einstellungen.META_UTM_SOURCE]
    fb = nur_fb.groupby("woche").agg(
        bestellungen_fb=("bestellnummer", "count"),
        umsatz_fb=("umsatz", "sum"),
        rabatt_fb=("rabatt", "sum"),
    )

    # join: Wochen ohne Facebook-Bestellung bekommen 0 statt "leer"
    return alle.join(fb).fillna(0)


# ---------------------------------------------------------------
# Vollständigkeit
# ---------------------------------------------------------------
def vollstaendige_wochen(meta: pd.DataFrame) -> list:
    """Gibt die Wochen zurück, in denen Meta für JEDE Kampagne alle 7 Tage hat.

    Warum Meta als Maßstab? Bei Shopify sieht ein Tag ohne Bestellung genauso
    aus wie ein fehlender Tag. Bei Meta hat jede Kampagne jeden Tag eine Zeile.
    """
    tage = meta.groupby(["woche", "kampagne"])["datum"].nunique()
    # Pro Woche: die kleinste Tageszahl über alle Kampagnen
    min_tage_pro_woche = tage.groupby("woche").min()
    return sorted(min_tage_pro_woche[min_tage_pro_woche == 7].index)


# ---------------------------------------------------------------
# Alles zusammen
# ---------------------------------------------------------------
def lade_wochendaten() -> dict:
    """Liest beide Dateien und gibt alle Wochentabellen zurück.

    Es bleiben nur vollständige Wochen übrig.
    """
    meta = lade_meta()
    shopify = lade_shopify()
    wochen = vollstaendige_wochen(meta)

    gesamt = meta_pro_woche(meta).join(shopify_pro_woche(shopify))
    gesamt = gesamt.loc[gesamt.index.isin(wochen)]

    kampagnen = meta_pro_woche_und_kampagne(meta)
    kampagnen = kampagnen.loc[kampagnen.index.get_level_values("woche").isin(wochen)]

    return {"gesamt": gesamt, "kampagnen": kampagnen, "wochen": wochen}


# ---------------------------------------------------------------
# Kleiner Test: python daten.py
# ---------------------------------------------------------------
if __name__ == "__main__":
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)

    daten = lade_wochendaten()
    print(f"Vollständige Wochen: {len(daten['wochen'])}")
    print(f"Erste: {daten['wochen'][0].date()}  Letzte: {daten['wochen'][-1].date()}\n")

    print("=== Gesamt pro Woche ===")
    print(daten["gesamt"].round(2))

    print("\n=== Letzte Woche pro Kampagne ===")
    letzte = daten["wochen"][-1]
    print(daten["kampagnen"].loc[letzte].round(2))
