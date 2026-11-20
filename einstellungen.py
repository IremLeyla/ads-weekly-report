"""
Alle Einstellungen an einer Stelle.

Hier stehen nur Zahlen und Pfade, keine Logik.
Wenn du eine Schwelle ändern willst, änderst du sie nur hier.
"""

from pathlib import Path

# ---------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------
PROJEKT_ORDNER = Path(__file__).parent
DATEN_ORDNER = PROJEKT_ORDNER / "data"
META_DATEI = DATEN_ORDNER / "meta_ads_export.csv"
SHOPIFY_DATEI = DATEN_ORDNER / "shopify_orders_export.csv"

REPORT_ORDNER = PROJEKT_ORDNER / "reports"          # wird nicht committet
LOG_DATEI = REPORT_ORDNER / "zahlencheck_fehler.log"  # jeder fehlgeschlagene Zahlen-Check
LAEUFE_ORDNER = REPORT_ORDNER / "laeufe"              # jeder LLM-Lauf als lesbare Datei

# Diese utm_source zählt als "kommt von Meta" in den Shopify-Daten
META_UTM_SOURCE = "facebook"

# ---------------------------------------------------------------
# Maßstab: Verglichen wird mit einer "typischen Woche der letzten N".
# Typische Woche = Median jeder Summe (Ausgaben, Klicks, Käufe ...) über die
# N Wochen VOR der aktuellen Woche. Gibt es weniger als N frühere Wochen,
# wird mit der Vorwoche verglichen (der Report vermerkt das).
# ---------------------------------------------------------------
VERGLEICH_WOCHEN = 4

# ---------------------------------------------------------------
# Schwellen: Ab welcher Veränderung zum Maßstab wird markiert?
# Angaben in Prozent (20 bedeutet ±20 %).
# ---------------------------------------------------------------
SCHWELLEN_PROZENT = {
    # Mengen: ±20 %
    "ausgaben": 20,
    "klicks": 20,
    "bestellungen": 20,   # Shopify-Bestellungen
    "kaeufe_meta": 20,    # Meta-Käufe (wie Bestellungen behandelt)
    "umsatz": 20,
    # Quoten
    "aov": 10,
    "roas": 10,
    "cpa": 20,            # bewusst höher: schwankt bei kleinen Shops stark
    "ctr": 10,
}

# ---------------------------------------------------------------
# Mindestgröße: Damit Zufall nicht als "starke Änderung" zählt.
# ---------------------------------------------------------------

# Für Mengen: Die Änderung muss auch absolut mindestens so groß sein.
# Beispiel: 2 statt 1 Kauf wäre +100 %, aber nur +1 -> nicht markiert.
MINDEST_AENDERUNG = {
    "ausgaben": 50.0,     # Euro
    "umsatz": 50.0,       # Euro
    "bestellungen": 5,    # Stück
    "kaeufe_meta": 5,     # Stück
    "klicks": 50,         # Stück
}

# Für Quoten: Die Grundlage muss in BEIDEN Wochen groß genug sein.
# Beispiel: Ein CPA aus nur 2 Käufen ist zu wackelig, um ihn zu bewerten.
# Format: Kennzahl -> (Spalte der Grundlage, Mindestwert)
MINDEST_BASIS = {
    "roas": ("ausgaben", 50.0),
    "cpa": ("kaeufe_meta", 5),
    "aov": ("bestellungen", 5),
    "ctr": ("klicks", 50),
}

# Nur PRO KAMPAGNE: Kennzahlen, die auf Meta-Käufen beruhen
# (Käufe, Kaufwert, Meta-AOV, CPA, ROAS), brauchen genug Käufe.
# Gemessen am GRÖSSEREN Wert der beiden Wochen.
# Ersetzt auf Kampagnenebene die Käufe-Regeln oben (5 Stück).
MINDEST_KAEUFE_KAMPAGNE = 10

# Liegt der größere Käufe-Wert unter dieser Grenze (aber über der Mindestgröße),
# bekommt die Markierung den Hinweis "geringe Fallzahl".
GERINGE_FALLZAHL_UNTER = 20

# ---------------------------------------------------------------
# Meta gegen Shopify: Das Verhältnis Meta ÷ Shopify wird markiert,
# wenn es außerhalb der Spanne aller früheren Wochen liegt.
# Erst ab so vielen früheren Wochen. Davor werden nur die Werte gezeigt.
# ---------------------------------------------------------------
MINDEST_WOCHEN_GESCHICHTE = 6

# ---------------------------------------------------------------
# Text: Wie viele Befunde werden im Erklärtext erklärt?
# Der Rest steht nur in der Tabelle darunter.
# ---------------------------------------------------------------
TOP_BEFUNDE_IM_TEXT = 5

# ---------------------------------------------------------------
# LLM: Wer schreibt den Erklärtext?
# Anbieter: "groq" oder "anthropic". Zum Vergleichen hier umstellen.
# Der Schlüssel steht NUR in .env (GROQ_API_KEY bzw. ANTHROPIC_API_KEY).
# ---------------------------------------------------------------
LLM_ANBIETER = "groq"

LLM_MODELLE = {
    "anthropic": "claude-sonnet-5-5",
    # Geprüft am 18.11.2026 mit "python llm_text.py --modelle".
    # Alternative zum Vergleichen: "qwen/qwen3.8-27b"
    "groq": "openai/gpt-oss-120b",
}

SCHLUESSEL_NAME = {
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
}

# Sekunden Pause vor dem zweiten Versuch.
# Groq (Gratis-Stufe) erlaubt nur 8.000 Tokens pro Minute -> eine neue Minute abwarten.
WARTEN_VOR_ZWEITEM_VERSUCH = {
    "anthropic": 0,
    "groq": 60,
}
