# Photocatalog

*[Read this README in English](README.md)*

Strumento locale per catalogare foto: scansiona una cartella, ed estrae per ogni immagine:

- **Tag descrittivi** generati da un modello vision locale via [Ollama](https://ollama.com)
- **Tutti i metadati EXIF**
- **Colore dominante** (analisi cromatica dei pixel)

I dati vengono salvati in un catalogo SQLite locale, consultabile tramite un piccolo viewer web.

I file RAW di Sony (`.ARW`), Canon (`.CR2`/`.CR3`), Nikon (`.NEF`) e Fujifilm (`.RAF`) sono supportati tramite il **JPEG di anteprima incorporato** (estratto con [rawpy](https://github.com/letmaik/rawpy)/LibRaw) — nessuna demosaicizzazione completa, quindi è veloce e non richiede setup aggiuntivo. L'EXIF viene letto dal file RAW stesso quando possibile, altrimenti dai metadati dell'anteprima; le dimensioni dell'immagine riflettono la vera risoluzione del sensore.

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

- Per i file RAW viene usata solo l'anteprima incorporata, non i dati reali del sensore — tag, colore dominante e thumbnail riflettono il JPEG generato dalla fotocamera, non uno sviluppo RAW completo.
- Altri formati RAW oltre ARW/CR2/CR3/NEF/RAF potrebbero funzionare se supportati da LibRaw, ma non sono testati.
- Foto HEIC richiedono l'extra `pillow-heif`.
- Il tagging via Ollama è sequenziale (nessuna concorrenza sulla singola istanza del modello locale).

## Sviluppi futuri

- Esportazione dei tag come keyword IPTC/XMP (via `exiftool`) per l'importazione in Adobe Lightroom.
