# Photocatalog

*[Read this README in English](README.md)*

Strumento locale per catalogare foto: scansiona una cartella, ed estrae per ogni immagine:

- **Tag descrittivi** generati da un modello vision locale via [Ollama](https://ollama.com)
- **Tutti i metadati EXIF**
- **Colore dominante** (analisi cromatica dei pixel)

I dati vengono salvati in un catalogo SQLite locale, consultabile tramite un piccolo viewer web.

## Screenshot

| Griglia del catalogo con filtri | Vista di dettaglio con tag, colore ed EXIF |
| --- | --- |
| ![Griglia del catalogo](docs/screenshot-grid.png) | ![Dettaglio immagine](docs/screenshot-detail.png) |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .              # oppure: pip install -e ".[heic]" per le foto iPhone HEIC
ollama pull qwen3-vl:8b       # modello vision di default
```

## Uso

```bash
photocatalog scan ~/Pictures/Vacanze     # scansiona una cartella e aggiorna il catalogo
photocatalog serve                        # avvia il viewer su http://127.0.0.1:5000
photocatalog stats                        # statistiche sul catalogo
photocatalog prune                        # rimuove le voci di file non più esistenti
```

Il catalogo (`~/.photocatalog/catalog.db`) e le thumbnail (`~/.photocatalog/thumbnails/`) vivono fuori dal repository. Lo scan è incrementale e ripartibile: ri-lanciare `scan` sulla stessa cartella salta i file invariati e riprende il tagging da dove interrotto.

## Sviluppo

```bash
pip install -e ".[dev]"
pytest
```

## Limiti noti (v1)

- Formati RAW (.CR2, .NEF, .ARW, ...) non supportati (Pillow non li apre).
- Foto HEIC richiedono l'extra `pillow-heif`.
- Il tagging via Ollama è sequenziale (nessuna concorrenza sulla singola istanza del modello locale).

## Sviluppi futuri

- Esportazione dei tag come keyword IPTC/XMP (via `exiftool`) per l'importazione in Adobe Lightroom.
