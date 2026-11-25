# Erster Auftrag an Claude Code

Kopiere diesen Text als erste Nachricht in Claude Code:

---

Lies zuerst README.md und CLAUDE.md. Schau dir dann die beiden CSV-Dateien in data/ an und beschreibe mir kurz, welche Spalten es gibt und was dir auffällt.

Erstelle danach einen Plan für Version 1, noch keinen Code:

1. CSV-Exporte einlesen und zu Wochenwerten zusammenfassen (Woche = Montag bis Sonntag).
2. Woche gegen Vorwoche berechnen: Ausgaben, ROAS, CPA, CTR, Bestellungen, Umsatz, AOV, jeweils gesamt und pro Kampagne.
3. Starke Veränderungen mit festen Regeln markieren und in Treiber zerlegen, zum Beispiel Umsatz = Bestellungen × AOV.
4. Den Unterschied zwischen Meta-Käufen und Shopify-Bestellungen mit utm_source facebook zeigen.
5. Ein LLM schreibt den Erklärtext nur aus einer Tabelle geprüfter Zahlen. Danach prüft der Code jede Zahl im Text.
6. Ausgabe als einseitiger HTML-Report für die letzte Woche.

Erkläre mir den Plan in einfacher Sprache. Wir setzen ihn danach Schritt für Schritt um, damit ich jeden Teil im Interview erklären kann.
