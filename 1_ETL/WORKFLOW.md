# Workflow: ETL für Gebäudedaten bis Heizwärmebedarf

Die ETL-Prozesse sind ein notwendiger Vorbereitungsschritt, um die spätere Berechnung der Heizwärmebedarfe zu ermöglichen. Diese Anleitung betrachtet die ETL-Kette ganzheitlich: von der Rohdatenaufbereitung über die fünf ETL-Schritte bis zur Übergabe der aufbereiteten Gebäudedaten für `2_COMPUTE`.

Die genauen Produktnamen und Downloadpfade auf [Geodaten Sachsen](https://www.geodaten.sachsen.de/) können sich ändern; dort die aktuellen Liegenschafts- bzw. Gebäudedaten und die passenden LOD1-GML-Kacheln für den Untersuchungsraum auswählen.

## Überblick: Preprocessing und Hauptpipeline

**Zwei Preprocessing-Schritte** können (oder sollten) die Eingaben vorbereiten, **bevor** die **fünf ETL-Hauptschritte** laufen. Sie sind thematisch getrennt:

| Vorbereitung | Skript | Zweck |
|--------------|--------|--------|
| **1 – Gemeinde / AGS** | `input/grundkarte_liegenschaftskataster/preprocess_filter_gemeinde.py` | Gebäudeanzahl auf die gewählte Gemeinde bzw. den gewählten Ort in Sachsen beschränken (Filter über **AGS**). Ausgabe z. B. nach `input/gpkg_filtered/` oder `input/grundkarte_liegenschaftskataster/gpkg_filtered/`. |
| **2 – Zensus Baualter** | `input/zensus_baualtersklassen/preprocess_zensus_baualter.py` | Zensusdaten so aufbereiten, dass sie in **ETL-Schritt 4** zur Ermittlung der Baujahre genutzt werden können (CSV → GPKG mit Gitter-Polygonen). |

**Hauptpipeline** (Gebäude-GPKG weiterverarbeiten, in der Regel der Reihe nach):

| ETL | Skript | Kurzbeschreibung |
|-----|--------|------------------|
| **1** | `etl_schritt1_spatial_join.py` | Spatial Join, um Informationen aus dem 3D-Modell mit der 2D-Grundkarte zu verknüpfen. |
| **2** | `etl_schritt2_filter_gebaeudefunktion.py` | Filterung der Gebäude auf Wohngebäude. |
| **3** | `etl_schritt3_hoehe_flaeche_geschosse.py` | Ermittlung von Dach- und Traufhöhe sowie Geschossanzahl und Bezugsfläche. |
| **4** | `etl_schritt4_baujahr.py` | Gebäudescharfe Approximation des Baujahres. |
| **5** | `etl_schritt5_gebaeudetyp.py` | Approximation des jeweiligen Gebäudetyps. |

Preprocessing 1 ist für eine fokussierte Region **empfohlen** (sonst sehr große GPKG). Preprocessing 2 ist für Schritt 4 **nötig**, wenn Baujahre aus dem Zensus-Gitter kommen sollen (Flächendenkmal allein reicht nicht für alle Gebäude).

## Voraussetzungen

- Python 3.10+ (empfohlen)
- Abhängigkeiten installieren:

```bash
pip install -r requirements.txt
```

## Rohdaten beschaffen und ablegen

1. Auf **Geodaten Sachsen** die **Liegenschafts-/Gebäude-Vektordatei** (typischerweise GeoPackage) beziehen → nach `input/gpkg_raw/` legen.
2. Die **LOD1-CityGML**-Datei(en) für den Ausschnitt herunterladen → nach `input/lod1/` legen (nur die `.gml` direkt in diesem Ordner; Unterordner mit Zusatzdateien werden nicht automatisch mitgelesen).

## Vorbereitung 1: Gebäude nach AGS filtern (Preprocessing)

Skript: **`input/grundkarte_liegenschaftskataster/preprocess_filter_gemeinde.py`**

Ausgabe nach **`input/gpkg_filtered/`** oder **`input/grundkarte_liegenschaftskataster/gpkg_filtered/`** — **ETL-Schritt 1** sucht automatisch zuerst in beiden Filter-Ordnern (in dieser Reihenfolge), dann in `input/gpkg_raw/`.

Beispiele (vom **Projektroot** aus; Pfade anpassen):

```bash
python input/grundkarte_liegenschaftskataster/preprocess_filter_gemeinde.py input/gpkg_raw/hu_sn_gebaeude.gpkg --ags 14713000 -o input/gpkg_filtered/gebaeude_leipzig.gpkg

python input/grundkarte_liegenschaftskataster/preprocess_filter_gemeinde.py input/gpkg_raw/hu_sn_gebaeude.gpkg --ags 14713000 14523380 -o input/gpkg_filtered/gebaeude_auswahl.gpkg

python input/grundkarte_liegenschaftskataster/preprocess_filter_gemeinde.py input/gpkg_raw/hu_sn_gebaeude.gpkg --prefix 14713 -o input/grundkarte_liegenschaftskataster/gpkg_filtered/region_14713.gpkg
```

## Vorbereitung 2: Zensus Baualtersklassen (Preprocessing, für ETL-Schritt 4)

Skript: **`input/zensus_baualtersklassen/preprocess_zensus_baualter.py`**

Destatis-CSV (Baualtersklassen, Gittermittelpunkte) → **GeoPackage** mit Polygon-Geometrie, typisch `zensus_baualter.gpkg` im gleichen Ordner. **ETL-Schritt 4** liest standardmäßig `input/zensus_baualtersklassen/zensus_baualter.gpkg` (oder das erste passende `*.gpkg` dort).

```bash
python input/zensus_baualtersklassen/preprocess_zensus_baualter.py
```

Details (CRS EPSG:3035, `--bbox`, `--boundary`) siehe Docstring im Skript.

## ETL-Schritt 1: Räumlichen Join ausführen

Skript: **`etl_schritt1_spatial_join.py`**

- **Standard:** LEFT JOIN; Zuordnung des LOD1-Gebäudes mit der **größten Schnittfläche** zum GPKG-Polygon.
- **Eingabe-GPKG:** Ohne `--gpkg` wird zuerst eine `*.gpkg` unter **`input/gpkg_filtered/`** verwendet. Ist dort keine vorhanden, folgt **`input/grundkarte_liegenschaftskataster/gpkg_filtered/`**, danach **`input/gpkg_raw/`**. Bei mehreren Dateien wird alphabetisch die erste gewählt — besser `--gpkg` setzen.
- **LOD1-GML:** Standard sind **alle** `input/lod1/*.gml`. Optional können einzelne Dateien als Positionsargumente übergeben werden.
- **Hauptausgabe:** **GeoPackage** unter `output/output_step1/<NameDerEingabeGPKG>_schritt1.gpkg` (Layer-Standard: `lod1_join`). Der **Basisname** leitet sich vom **Dateinamen der Eingabe-GPKG** ab.
- **CSV:** nur mit `--csv` (optionaler Pfad; ohne Pfad: gleicher Basisname wie die GPKG-Ausgabe, Endung `.csv`).
- Nur CSV, kein GPKG: `--no-gpkg --csv` (selten nötig).

```bash
python etl_schritt1_spatial_join.py

python etl_schritt1_spatial_join.py --gpkg input/gpkg_filtered/gebaeude_leipzig.gpkg -o output/output_step1/gebaeude_leipzig_schritt1.gpkg

python etl_schritt1_spatial_join.py --csv
```

Aus den LOD1-Attributen entstehen u. a. Spalten mit Präfix `lod1_` (z. B. `lod1_measuredHeight_m`, `lod1_roofType`); Gebäudefunktion bleibt über **GFK** in der GPKG-Eingabe. Außerdem `lod1_intersection_area_m2`.

## ETL-Schritt 2: Optional nach GFK filtern (z. B. nur Wohngebäude)

Skript: **`etl_schritt2_filter_gebaeudefunktion.py`**

- Filtert nach der Spalte **GFK** (Gebäudefunktionskatalog), Standard in den sächsischen Hausumringen.
- **Ohne Zusatzargumente:** Auswahl **Wohngebäude** über die Standardcodes `31001_1000` und `31001_1100` (bei abweichendem Datenbestand `--codes` nutzen).
- **Eingabe:** Standard ist die erste `*_schritt1.gpkg` unter `output/output_step1/`, alternativ Pfad angeben.
- **Ausgabe:** Standard `output/output_step2/<Basis>_schritt2.gpkg`.

```bash
python etl_schritt2_filter_gebaeudefunktion.py

python etl_schritt2_filter_gebaeudefunktion.py output/output_step1/gebaeude_leipzig_schritt1.gpkg
```

## ETL-Schritt 3: Dachhöhe und Traufhöhe schätzen

Skript: **`etl_schritt3_hoehe_flaeche_geschosse.py`**

- **Eingaben:** `lod1_measuredHeight_m`, `lod1_Dachneigung`, optional `lod1_roofType`; plus **Gebäudegeometrie** (Fußabdruck, für Trauf-/Dachmodell und Flächen).
- **Neue Spalten:**
  - **`dach_hoehe_m`**, **`trauf_hoehe_m`** — vereinfachtes Satteldach bzw. Flachdach (siehe Docstring im Skript).
  - **`anzahl_geschosse`** — geschätzte **Anzahl oberirdischer Geschosse** aus `trauf_hoehe_m` (Annahme ~3 m Geschosshöhe, siehe Docstring); wird in **ETL-Schritt 5** für die Gebäudetyp-Regeln genutzt.
  - **`bezugsflaeche`** — **größtes Polygon** der Geometrie (Fußabdruckfläche in m² im CRS) × **`anzahl_geschosse`** × **0.85** (Kenngröße); dient als einheitliche Bezugsgröße für spätere Auswertungen.
- **Eingabe-Datei:** Standard: erste `*_schritt2.gpkg` unter `output/output_step2/` (alternativ Pfad als Argument).
- **Ausgabe:** `output/output_step3/<Basis>_schritt3.gpkg`.

```bash
python etl_schritt3_hoehe_flaeche_geschosse.py

python etl_schritt3_hoehe_flaeche_geschosse.py output/output_step2/gebaeude_leipzig_schritt2.gpkg
```

## ETL-Schritt 4: Baujahr und Denkmalschutz

Skript: **`etl_schritt4_baujahr.py`**

- **Priorität:** Zuerst **Flächendenkmal** (Spalte `ext_dat` → Jahr, `denkmalschutz`), danach **Zensus-Gitter** (Baualtersklassen-Häufigkeiten pro Zelle). Gebäude ohne Treffer behalten leeres `baujahr`.
- **Flächendenkmal:** erstes `*.gpkg` unter `input/flaechendenkmal/` — **fehlt der Ordner oder eine Datei, wird dieser Teil übersprungen** (ohne Abbruch).
- **Zensus:** Standard `input/zensus_baualtersklassen/zensus_baualter.gpkg` (oder erstes `*.gpkg` dort; siehe Vorbereitung 2). Mit **`--no-gitter`** entfällt die Zensus-Schätzung.
- **Eingabe:** Standard: erste `*_schritt3.gpkg` unter `output/output_step3/`.
- **Ausgabe:** `output/output_step4/<Basis>_schritt4.gpkg` (u. a. Spalten `baujahr`, `denkmalschutz`).

```bash
python etl_schritt4_baujahr.py

python etl_schritt4_baujahr.py --no-gitter
```

## ETL-Schritt 5: Gebäudetyp

Skript: **`etl_schritt5_gebaeudetyp.py`**

- **Eingabe:** Standard: erste `*_schritt4.gpkg` unter `output/output_step4/` (alternativ Pfad als Argument).
- **Voraussetzungen:** Die in **Schritt 3** angelegten Spalten **`trauf_hoehe_m`**, **`dach_hoehe_m`**, **`bezugsflaeche`**, **`anzahl_geschosse`** (über Schritt 4 unverändert in der Eingabe-GPKG). Es werden **keine** ALKIS-Felder wie `anzahlDOberirdischenGeschosse` / `objekthoehe` verwendet. **Geschosszahl** kommt aus **`anzahl_geschosse`**; die HH-Abgrenzung nutzt aktuell **`lod1_measuredHeight_m`** und nicht `trauf_hoehe_m + dach_hoehe_m`.
- **Inhalt:** Keine Auswahl nach übergeordneter Gebäudefunktion — die typische Eingrenzung auf Wohngebäude erfolgt in **Schritt 2 (GFK)**. Klassifikation u. a. EFH, RH, MFH, GMH, HH: **EFH/RH** u. a. über **Fußabdruckfläche** (größtes Polygon, m²) ≤ 400 und **`anzahl_geschosse`** unter 3; RH, wenn ein berührendes Nachbargebäude mit ähnlicher Fläche existiert.
- **Ausgabe:** `output/output_step5/<Basis>_schritt5.gpkg` mit Spalte **`gebaeudetyp`**.

```bash
python etl_schritt5_gebaeudetyp.py

python etl_schritt5_gebaeudetyp.py output/output_step4/gebaeude_leipzig_schritt4.gpkg
```

## Ergebnis nutzen

Nach den ETL-Schritten kann das Ergebnis direkt in `2_COMPUTE` verwendet werden, um die Wärmebedarfe zu berechnen.

Standardfall: die vollständige Datei aus `output/output_step5/` (inklusive `gebaeudetyp`). Im aktuellen Schritt-5-Skript wird diese Ausgabe zusätzlich automatisch nach `2_COMPUTE/computing_inputs/` kopiert und steht damit direkt für die Berechnung bereit.
