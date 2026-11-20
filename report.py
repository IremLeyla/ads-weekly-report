"""
Schritt 6: Einseitiger HTML-Report für die letzte vollständige Woche.

Ablauf: Daten laden -> analysieren -> Fakten bauen -> Text erzeugen (LLM, geprüft) -> HTML.

    python report.py                      letzte Woche, mit LLM-Text (Anbieter aus einstellungen.py)
    python report.py --ohne-llm           nur Ersatztext, kein API-Aufruf
    python report.py --woche 6            sechste vollständige Woche in den Daten
    python report.py --woche 2026-11-02   Woche, in der dieses Datum liegt
    python report.py --alle --ohne-llm    alle Wochen ab Woche 2 (Woche 1 hat keine Vorwoche)

Alle Zahlen in den Tabellen kommen direkt aus dem Code, nie vom LLM.
Nur der Erklärtext kommt vom LLM – und der ist geprüft (Zahlen-Check + Pflicht-Check).
"""

import argparse
import datetime
import html

import pandas as pd

import analyse
import daten
import einstellungen
import llm_text
from llm_text import FORMAT, NAMEN, formatiere


# ===============================================================
# Hilfen
# ===============================================================
def e(text) -> str:
    """HTML-sicher machen (z. B. '<' oder '&' in Texten)."""
    return html.escape(str(text))


def wert(kennzahl: str, x) -> str:
    """Wert einer Kennzahl im Report-Format, z. B. '1.484 €' oder '1,91 %'."""
    art, stellen = FORMAT[kennzahl]
    return formatiere(x, art, stellen)


def wert_basis(kennzahl: str, x) -> str:
    """Wie wert(), aber halbe Stückzahlen aus dem Median mit einer Nachkommastelle (z. B. 18,5)."""
    art, stellen = FORMAT[kennzahl]
    return formatiere(x, art, llm_text.stellen_fuer(x, art, stellen))


def aenderung(kennzahl: str, absolut, prozent) -> str:
    """Änderung als Text: absolut und in %. Bei CTR/CR die absolute Änderung in Prozentpunkten."""
    art, stellen = FORMAT[kennzahl]
    if art == "quote_prozent":
        abs_text = formatiere(absolut, "pp", 2, vorzeichen=True)
    else:
        abs_text = formatiere(absolut, art, stellen, vorzeichen=True)
    return f"{abs_text} ({formatiere(prozent, 'prozent', 0, vorzeichen=True)})"


def tabelle(kopf: list, zeilen: list, klasse: str = "") -> str:
    """Einfache HTML-Tabelle. Jede Zelle ist Text oder (Text, CSS-Klasse)."""
    th = "".join(f"<th>{e(k)}</th>" for k in kopf)
    trs = []
    for zeile in zeilen:
        tds = []
        for zelle in zeile:
            text, cls = zelle if isinstance(zelle, tuple) else (zelle, "")
            tds.append(f'<td class="{cls}">{text}</td>')
        trs.append(f"<tr>{''.join(tds)}</tr>")
    return f'<table class="{klasse}"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


# ===============================================================
# Abschnitte
# ===============================================================
def vergleich_beschreibung(a: dict) -> str:
    """Ein Satz, womit verglichen wird – für Kopf und Tabellen."""
    b = a["basis_wochen"]
    von, bis = b[0], b[-1] + pd.Timedelta(days=6)
    if a["vergleich_art"] == "typisch":
        return (f"Vergleich mit einer typischen Woche der letzten vier "
                f"(Median der Wochen {von:%d.%m.} bis {bis:%d.%m.%Y})")
    return (f"Vergleich mit der Vorwoche ({von:%d.%m.} bis {bis:%d.%m.%Y}). "
            f"Für eine typische Woche gibt es noch zu wenige frühere Wochen")


def abschnitt_kopf(ergebnis_text: dict, woche, a: dict) -> str:
    bis = woche + pd.Timedelta(days=6)
    kw = woche.isocalendar().week
    if ergebnis_text["quelle"] == "llm":
        herkunft = (f'<p class="herkunft ok">Erklärtext: {e(ergebnis_text["anbieter"])} / '
                    f'{e(ergebnis_text["modell"])}, Zahlen-Check und Pflicht-Check bestanden '
                    f'(Versuch {ergebnis_text["versuche"]}).</p>')
    elif ergebnis_text["quelle"] == "ersatztext (ohne LLM)":
        herkunft = '<p class="herkunft warnung">Erklärtext: Ersatztext aus festen Satzvorlagen (ohne LLM erzeugt).</p>'
    else:
        herkunft = ('<p class="herkunft warnung">Erklärtext: Ersatztext aus festen Satzvorlagen. '
                    'Der LLM-Text hat die Prüfung nicht bestanden (Details im Log).</p>')
    return (f"<header><h1>Ads Weekly Report KW {kw}</h1>"
            f"<p class=\"zeitraum\">{woche:%d.%m.%Y} bis {bis:%d.%m.%Y} · {e(vergleich_beschreibung(a))}</p>"
            f"{herkunft}</header>")


def abschnitt_text(ergebnis_text: dict, fakten: dict) -> str:
    absaetze = ergebnis_text["absaetze"]
    teile = [f"<section><h2>Was ist passiert?</h2><p>{e(absaetze['gesamtbild'])}</p>"]
    for b, info in zip(absaetze["befunde"], fakten["befunde"]):
        marke = ' <span class="marke">geringe Fallzahl</span>' if info["geringe_fallzahl"] else ""
        teile.append(f"<h3>{e(b['kampagne'])}{marke}</h3><p>{e(b['text'])}</p>")
    teile.append("</section>")
    return "".join(teile)


# Welche Gesamt-Kennzahlen in der Tabelle stehen (Reihenfolge = Anzeige)
TABELLE_GESAMT = ["ausgaben", "kaeufe_meta", "kaufwert_meta", "roas", "roas_shopify", "cpa", "ctr",
                  "bestellungen", "umsatz", "aov", "rabatt", "bestellungen_fb", "umsatz_fb"]


def abschnitt_gesamt(a: dict) -> str:
    g = a["vergleich_gesamt"].set_index("kennzahl")
    zeilen = []
    for k in TABELLE_GESAMT:
        z = g.loc[k]
        cls = "markiert" if z["markiert"] else ""
        status = "markiert" if z["markiert"] else z["status"]
        zeile = [e(NAMEN[k]), e(wert(k, z["vorwoche"]))]
        if a["vergleich_art"] == "typisch":
            zeile.append(e(wert_basis(k, z["basis"])))
        zeile += [(e(wert(k, z["diese_woche"])), cls),
                  (e(aenderung(k, z["aenderung_abs"], z["aenderung_prozent"])), cls), e(status)]
        zeilen.append(zeile)
    if a["vergleich_art"] == "typisch":
        kopf = ["Kennzahl", "Vorwoche", "Typische Woche", "Diese Woche", "Änderung zur typischen Woche", "Status"]
    else:
        kopf = ["Kennzahl", "Vorwoche", "Diese Woche", "Änderung zur Vorwoche", "Status"]
    return ("<section><h2>Kennzahlen gesamt</h2>"
            + f'<p class="klein">{e(vergleich_beschreibung(a))}. Markiert wird gegen diesen Maßstab; '
              "die Vorwoche steht nur zur Information da.</p>"
            + tabelle(kopf, zeilen)
            + '<p class="klein">Meta-Werte (Käufe, Kaufwert, ROAS, CPA, CTR) zählt Meta. '
              "Shopify-Bestellungen, -Umsatz, -AOV und Rabatte „alle Kanäle“: jede Bestellung im Shop, "
              "egal woher. „Nur Facebook“: nur Bestellungen mit utm_source facebook. "
              "Der Shopify-ROAS ist der Umsatz nur aus Facebook geteilt durch die Meta-Ausgaben. "
              "Der Umsatz ist bereits nach Abzug der Rabatte.</p>"
              "</section>")


TABELLE_KAMPAGNE = ["ausgaben", "kaeufe_meta", "kaufwert_meta", "roas", "cpa", "ctr"]


def abschnitt_kampagnen(a: dict) -> str:
    vk = a["vergleich_kampagnen"]
    zeilen = []
    for kampagne, teil in vk.groupby("kampagne", sort=False):
        teil = teil.set_index("kennzahl")
        zeile = [e(kampagne)]
        for k in TABELLE_KAMPAGNE:
            z = teil.loc[k]
            cls = "markiert" if z["markiert"] else ""
            text = (f"{e(wert(k, z['diese_woche']))}<br><span class=\"klein\">"
                    f"{e(formatiere(z['aenderung_prozent'], 'prozent', 0, vorzeichen=True))} "
                    f"({'typisch' if a['vergleich_art'] == 'typisch' else 'Vorwoche'} "
                    f"{e(wert_basis(k, z['basis']))})</span>")
            zeile.append((text, cls))
        fallzahl = "geringe Fallzahl" if (teil["hinweis"] == "geringe Fallzahl").any() else ""
        zeile.append(e(fallzahl))
        zeilen.append(zeile)
    kopf = ["Kampagne"] + [NAMEN[k] for k in TABELLE_KAMPAGNE] + ["Hinweis"]
    return ("<section><h2>Kampagnen</h2>" + tabelle(kopf, zeilen, "breit")
            + '<p class="klein">Pro Kampagne gibt es nur Meta-Zahlen. Shopify kennt keine Kampagne.</p></section>')


def abschnitt_befunde(a: dict) -> str:
    bf = a["befunde"]
    if bf.empty:
        return "<section><h2>Alle Befunde</h2><p>Keine markierten Änderungen in dieser Woche.</p></section>"
    zeilen = []
    for _, b in bf.iterrows():
        namen = ", ".join(NAMEN.get(k.strip(), k.strip()) for k in b["kennzahlen"].split(","))
        zeilen.append([
            e(b["rang"]), e(b["kampagne"]), e(b["bereich"]),
            e(formatiere(b["euro_wirkung"], "euro", 0, vorzeichen=True)),
            e(formatiere(b["budget_beitrag"], "euro", 0, vorzeichen=True)),
            e(formatiere(b["effizienz_beitrag"], "euro", 0, vorzeichen=True)),
            e(namen),
            e("ja" if b["geringe_fallzahl"] else ""),
            e("ja" if b["im_text"] else "nein"),
        ])
    return ("<section><h2>Alle Befunde</h2>"
            + tabelle(["Rang", "Kampagne", "Bereich", "Wirkung auf Kaufwert", "davon Budget",
                       "davon Effizienz", "markierte Kennzahlen", "geringe Fallzahl", "im Text"],
                      zeilen, "breit")
            + f'<p class="klein">Sortiert nach Wirkung auf den Meta-Kaufwert. Die ersten '
              f"{einstellungen.TOP_BEFUNDE_IM_TEXT} werden oben im Text erklärt. „Nicht berechenbar“ "
              f"steht als „kein Wert“, wenn ein Baustein 0 ist.</p></section>")


MOEGLICHE_GRUENDE = [
    "Meta zählt Käufe innerhalb eines Zeitfensters nach Klick oder Ansicht der Anzeige, "
    "Shopify zählt jede Bestellung genau einmal.",
    "Meta zählt auch Käufe nach reinem Ansehen einer Anzeige, ohne Klick.",
    "Bestellungen ohne oder mit veränderter utm_source landen bei Shopify nicht unter „facebook“.",
    "Meta ordnet einen Kauf meist dem Tag der Anzeigen-Interaktion zu, Shopify dem Bestelltag. "
    "An Wochengrenzen kann ein Kauf so in verschiedenen Wochen landen.",
]


def abschnitt_meta_shopify(a: dict, fakten: dict) -> str:
    mgs = a["meta_gegen_shopify"]
    t = mgs["tabelle"]
    sp = mgs["spanne"].set_index("kennzahl")
    markiert = {k: sp.loc[k, "markiert"] for k in sp.index}
    zeilen = []
    for woche, z in t.iterrows():
        aktuell = woche == a["woche"]
        def zelle(text, kennzahl=None):
            cls = "markiert" if (aktuell and kennzahl and markiert.get(kennzahl)) else ""
            return (e(text), cls)
        zeile = [
            zelle(f"{woche:%d.%m.%Y}" + (" (diese Woche)" if aktuell else "")),
            zelle(formatiere(z["kaeufe_meta"], "zahl")),
            zelle(formatiere(z["bestellungen_fb"], "zahl")),
            zelle(formatiere(z["verhaeltnis_stueck"], "zahl", 2), "verhaeltnis_stueck"),
            zelle(formatiere(z["kaufwert_meta"], "euro")),
            zelle(formatiere(z["umsatz_fb"], "euro")),
            zelle(formatiere(z["verhaeltnis_euro"], "zahl", 2), "verhaeltnis_euro"),
        ]
        zeilen.append(zeile)
    hinweise = "".join(f"<p>{e(h)}</p>" for h in fakten["feste_hinweise"])
    gruende = "".join(f"<li>{e(g)}</li>" for g in MOEGLICHE_GRUENDE)
    return ("<section><h2>Meta gegen Shopify (utm_source facebook)</h2>"
            + tabelle(["Woche ab", "Meta-Käufe", "Shopify-Bestellungen, nur Facebook", "Verhältnis",
                       "Meta-Kaufwert", "Shopify-Umsatz, nur Facebook", "Verhältnis"], zeilen, "breit")
            + f'<div class="kasten">{hinweise}</div>'
            + "<h3>Mögliche Gründe für Unterschiede</h3>"
            + '<p class="klein">Allgemeine Gründe. Für diese Woche nicht geprüft – die Ursache bleibt unklar.</p>'
            + f"<ul>{gruende}</ul></section>")


def abschnitt_werte(werte: pd.DataFrame) -> str:
    zeilen = [[e(r.id), e(r.bedeutung), e(r.text)] for r in werte.itertuples()]
    return ('<section><details><summary>Tabelle der geprüften Werte '
            f"({len(werte)} Zeilen) – jede Zahl im Erklärtext stammt von hier</summary>"
            + tabelle(["ID", "Bedeutung", "Wert"], zeilen) + "</details></section>")


def abschnitt_regeln() -> str:
    s = ", ".join(f"{NAMEN.get(k, k)} ±{v} %" for k, v in einstellungen.SCHWELLEN_PROZENT.items())
    return (f'<footer><p>Maßstab: eine typische Woche der letzten {einstellungen.VERGLEICH_WOCHEN} Wochen '
            f"(Median jeder Summe, Quoten daraus berechnet; die aktuelle Woche zählt nicht mit). Gibt es weniger "
            f"frühere Wochen, wird mit der Vorwoche verglichen.</p>"
            f'<p>Regeln: Markiert wird ab {e(s)} gegenüber dem Maßstab, wenn die Änderung groß genug ist '
            f"(z. B. mindestens {einstellungen.MINDEST_AENDERUNG['ausgaben']:.0f} € bzw. "
            f"{einstellungen.MINDEST_AENDERUNG['bestellungen']} Bestellungen). Pro Kampagne braucht es mindestens "
            f"{einstellungen.MINDEST_KAEUFE_KAMPAGNE} Meta-Käufe in einer der beiden Wochen; unter "
            f"{einstellungen.GERINGE_FALLZAHL_UNTER} gilt „geringe Fallzahl“. Meta gegen Shopify wird ab "
            f"{einstellungen.MINDEST_WOCHEN_GESCHICHTE} früheren Wochen bewertet.</p>"
            f"<p>Erstellt am {datetime.datetime.now():%d.%m.%Y %H:%M}. Alle Daten sind Beispieldaten.</p></footer>")


CSS = """
:root { --text:#1d2433; --gedaempft:#5b6475; --linie:#dde1e8; --hinter:#ffffff; --flaeche:#f5f6f8;
        --mark:#fff1d6; --mark-text:#7a4b00; --ok:#e6f4ea; --ok-text:#1e6b35; --warn:#fde8e8; --warn-text:#8a1c1c; }
@media (prefers-color-scheme: dark) {
  :root { --text:#e6e8ec; --gedaempft:#a3aab8; --linie:#363c48; --hinter:#16191f; --flaeche:#1f232b;
          --mark:#4a3712; --mark-text:#ffd99a; --ok:#173523; --ok-text:#9fe0b4; --warn:#4a1c1c; --warn-text:#ffb4b4; }
}
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px; background:var(--hinter); color:var(--text);
       font:15px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 980px; margin: 0 auto; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 19px; margin: 32px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--linie); }
h3 { font-size: 16px; margin: 20px 0 6px; }
.zeitraum, .klein { color: var(--gedaempft); }
.klein { font-size: 13px; }
.herkunft { display:inline-block; padding:6px 10px; border-radius:6px; font-size:13px; margin:8px 0 0; }
.ok { background:var(--ok); color:var(--ok-text); }
.warnung { background:var(--warn); color:var(--warn-text); }
.marke { font-size:12px; font-weight:500; padding:2px 8px; border-radius:10px;
         background:var(--mark); color:var(--mark-text); margin-left:6px; vertical-align:middle; }
table { border-collapse: collapse; width: 100%; font-size: 14px; margin: 8px 0; }
.breit { display:block; overflow-x:auto; }
th, td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--linie); vertical-align:top; }
th { background: var(--flaeche); font-weight:600; white-space:nowrap; }
td.markiert { background: var(--mark); color: var(--mark-text); font-weight:600; }
.kasten { background:var(--flaeche); border-left:4px solid var(--gedaempft); padding:4px 14px; margin:12px 0; }
details summary { cursor:pointer; font-weight:600; margin: 24px 0 8px; }
footer { margin-top: 36px; padding-top: 12px; border-top:1px solid var(--linie);
         color: var(--gedaempft); font-size: 13px; }
"""


# ===============================================================
# Alles zusammen
# ===============================================================
def wochen_liste(wochen: list) -> str:
    """Alle Wochen mit Nummer, z. B. für Fehlermeldungen."""
    return "\n".join(f"  {i}: ab {w:%d.%m.%Y} (KW {w.isocalendar().week})" for i, w in enumerate(wochen, 1))


def waehle_woche(wochen: list, angabe) -> pd.Timestamp:
    """Findet die gewünschte Woche.

    angabe: None -> letzte Woche
            "6"  -> sechste vollständige Woche in den Daten (gezählt ab 1)
            "2026-11-02" -> die Woche, in der dieses Datum liegt
    Woche 1 geht nicht: Sie hat keine Vorwoche zum Vergleichen.
    """
    if angabe is None:
        woche = wochen[-1]
    elif str(angabe).isdigit():
        nummer = int(angabe)
        if not 1 <= nummer <= len(wochen):
            raise SystemExit(f"Woche {nummer} gibt es nicht. Verfügbar:\n{wochen_liste(wochen)}")
        woche = wochen[nummer - 1]
    else:
        try:
            datum = pd.Timestamp(angabe)
        except ValueError:
            raise SystemExit(f"'{angabe}' ist weder eine Wochennummer noch ein Datum (JJJJ-MM-TT).")
        woche = datum.normalize() - pd.Timedelta(days=datum.day_of_week)   # Montag dieser Woche
        if woche not in wochen:
            raise SystemExit(f"Die Woche ab {woche:%d.%m.%Y} ist nicht in den Daten. "
                             f"Verfügbar:\n{wochen_liste(wochen)}")

    if woche == wochen[0]:
        raise SystemExit(f"Woche 1 (ab {woche:%d.%m.%Y}) hat keine Vorwoche in den Daten "
                         f"und kann nicht verglichen werden.")
    return woche


def baue_report(ohne_llm: bool = False, woche_angabe=None, d: dict = None) -> str:
    """Erzeugt den Report für eine Woche (Standard: die letzte) und gibt den Dateipfad zurück."""
    d = d or daten.lade_wochendaten()
    woche = waehle_woche(d["wochen"], woche_angabe)
    nummer = d["wochen"].index(woche) + 1
    print(f"Woche {nummer} (ab {woche:%d.%m.%Y}, KW {woche.isocalendar().week})")
    a = analyse.analysiere_woche(d, woche)
    werte, fakten = llm_text.baue_fakten(a)
    kampagnen = list(a["vergleich_kampagnen"]["kampagne"].unique())

    if ohne_llm:
        roh = llm_text.ersatztext(fakten, werte, kampagnen)
        ergebnis_text = {"quelle": "ersatztext (ohne LLM)", "absaetze": llm_text.ohne_ids(roh)}
    else:
        ergebnis_text = llm_text.erzeuge_text(fakten, werte, kampagnen, woche)

    seite = (f'<!doctype html><html lang="de"><head><meta charset="utf-8">'
             f'<meta name="viewport" content="width=device-width, initial-scale=1">'
             f"<title>Ads Weekly Report KW {woche.isocalendar().week}</title><style>{CSS}</style></head>"
             f"<body><main>"
             + abschnitt_kopf(ergebnis_text, woche, a)
             + abschnitt_text(ergebnis_text, fakten)
             + abschnitt_gesamt(a)
             + abschnitt_kampagnen(a)
             + abschnitt_befunde(a)
             + abschnitt_meta_shopify(a, fakten)
             + abschnitt_werte(werte)
             + abschnitt_regeln()
             + "</main></body></html>")

    einstellungen.REPORT_ORDNER.mkdir(exist_ok=True)
    # Eigener Name ohne LLM, damit ein Report mit LLM-Text nie überschrieben wird
    zusatz = "_ohne-llm" if ohne_llm else ""
    datei = einstellungen.REPORT_ORDNER / f"report_KW{woche.isocalendar().week}_{woche.date()}{zusatz}.html"
    datei.write_text(seite, encoding="utf-8")
    print(f"Erklärtext: {ergebnis_text['quelle']}")
    return str(datei)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ads Weekly Report als HTML erzeugen.")
    parser.add_argument("--woche", help="Wochennummer in den Daten (ab 1) oder ein Datum JJJJ-MM-TT. "
                                        "Ohne Angabe: die letzte vollständige Woche.")
    parser.add_argument("--alle", action="store_true", help="Reports für alle Wochen ab Woche 2.")
    parser.add_argument("--ohne-llm", action="store_true", help="Nur Ersatztext, kein API-Aufruf.")
    args = parser.parse_args()

    if args.alle:
        d = daten.lade_wochendaten()
        for nummer in range(2, len(d["wochen"]) + 1):
            pfad = baue_report(ohne_llm=args.ohne_llm, woche_angabe=nummer, d=d)
            print(f"  -> {pfad}\n")
    else:
        pfad = baue_report(ohne_llm=args.ohne_llm, woche_angabe=args.woche)
        print(f"Report gespeichert: {pfad}")
