# Contribuire

Grazie per l'interesse. Qualche regola per mantenere il progetto semplice e sicuro.

## Preparare l'ambiente

```bash
git clone https://github.com/f-estero/english-assessment-engine.git
cd english-assessment-engine
pip install -r requirements-dev.txt
git config core.hooksPath .githooks
python -m pytest
```

## Regole

- **Nessuna chiamata di rete nei test.** Gemini ed edge-tts vanno sostituiti con oggetti finti (vedi `tests/test_pipeline_modes.py`).
- **Nessun dato reale.** Nei test e negli esempi usa frasi e nomi inventati, mai registrazioni o report di persone reali.
- **Prima il test.** Per un bug, scrivi un test che lo riproduce e fallisce, poi correggi.
- **L'app non scrive mai nella propria cartella**: tutto l'output va nella cartella dei report scelta dall'utente.
- Testi dell'interfaccia e dei report in italiano, semplici, con la sola iniziale maiuscola.

## Pull request

Descrivi cosa cambia e perché, e allega l'output di `python -m pytest`. Per modifiche al report o alla finestra aggiungi uno screenshot fatto con dati inventati.
