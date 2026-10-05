# Sicurezza

## La chiave API

- La chiave Gemini non va mai scritta nel codice, nei test, negli issue o nelle pull request.
- L'app la cerca in quest'ordine: variabile d'ambiente `GEMINI_API_KEY`, file `.env` accanto al programma, Gestione credenziali di Windows (dove la salva il pulsante *Chiave API…*).
- `.env` è escluso da git; il file `.env.example` contiene solo un segnaposto.
- Chi contribuisce attivi il controllo che blocca i commit con file `.env` o stringhe simili a una chiave Google:

  ```bash
  git config core.hooksPath .githooks
  ```

**Se una chiave finisce per errore in un commit**, considerala compromessa: revocala subito in [Google AI Studio](https://aistudio.google.com/apikey) e creane una nuova. Cancellarla con un commit successivo non basta, resta nella storia.

## Dati personali

Registrazioni, report, `errori.csv`, `report.json` e `sessions.jsonl` contengono dati personali e sono esclusi da git. Non allegarli agli issue: per segnalare un problema basta il messaggio d'errore della sezione *Dettagli*, senza percorsi o nomi.

## Segnalare una vulnerabilità

Non aprire un issue pubblico. Usa *Security → Report a vulnerability* nella pagina della repository: la segnalazione resta privata finché il problema non è risolto.
