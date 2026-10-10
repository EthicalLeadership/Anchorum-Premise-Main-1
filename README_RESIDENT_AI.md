# Resident AI — IA résidente déterministe (DOSSIER-PIPELINE)

CLI interactive qui exécute un modèle de langage **local** (Blackstar) sur les preuves du dossier DOSSIER-PIPELINE, avec traçabilité et garde-fous déterministes.

## Architecture

- **Modèle :** `qwen2.5-7b-instruct` via Blackstar `/v1/chat/completions`
- **Embeddings :** `all-MiniLM-L6-v2` via Blackstar `/v1/embeddings` (fallback local sentence-transformers)
- **Vector store :** ChromaDB persistant dans `Red dart/resident_ai/vector_store/`
- **Audit :** journal JSONL immutable dans `Red dart/resident_ai/audit/`
- **Sorties :** analyses, lettres et alertes dans `Red dart/resident_ai/generated/`

## Prérequis

- Le service `blackstar-dashboard` doit être actif sur `https://localhost:8443`.
- Une clé API Blackstar valide doit être définie dans `BLACKSTAR_API_KEY`.

## Démarrage rapide

```bash
# 1. Vérifier que Blackstar est actif
systemctl status blackstar-dashboard.service

# 2. Exporter la clé API
export BLACKSTAR_API_KEY=$(cat /mnt/blackstar/vol-hdd-a/home_data_blackstar/blackstar/secrets/api_key.hex)

# 3. Indexer les documents configurés (une seule fois, ou après ajout de documents)
cd dossier_pipeline_v1.1
source ../.venv/bin/activate
python -m dossier_pipeline.resident_ai --index --no-repl

# 4. Lancer le REPL interactif
python -m dossier_pipeline.resident_ai
```

## Commandes du REPL

```
/ask <question>              Poser une question avec RAG et citations
/analyze <sujet>             Générer une analyse structurée
/letter <cible> | <objet>    Rédiger une lettre formelle
/sources <requête>           Voir les chunks récupérés
/index [répertoire]          (Ré)indexer les documents
/monitor                     Vérifier les nouveaux courriels Proton
/verify                      Vérifier l’intégrité du journal d’audit
/status                      État du système
/help                        Aide
/exit                        Quitter
```

Une question sans `/` est traitée comme `/ask`.

## Déterminisme

| Paramètre | Valeur |
|---|---|
| temperature | 0.0 |
| seed | 86849 |
| top_k | 1 |
| top_p | 1.0 |
| num_ctx | 8192 |

Les prompts sont versionnés et hashés dans `prompts/v1/manifest.json`. Chaque appel LLM est enregistré avec le hash du prompt, le hash du contexte et le hash de la réponse.

**Limitation :** le déterminisme bit-à-bit dépend de la version du modèle `qwen2.5-7b-instruct`, de `llama.cpp` et des paramètres de Blackstar. L’audit log permet de reproduire et de vérifier les conditions d’exécution.

## Fichiers de configuration

- `config/resident_ai.json` — paramètres du modèle, chemins, chunking
- `prompts/v1/*.txt` — prompts versionnés
- `prompts/v1/manifest.json` — empreintes SHA-256 des prompts

Les variables d’environnement suivantes peuvent surcharger `config/resident_ai.json` :

- `RESIDENT_AI_MODEL`
- `RESIDENT_AI_EMBED_MODEL`
- `RESIDENT_AI_TEMPERATURE`
- `RESIDENT_AI_SEED`
- `RESIDENT_AI_NUM_CTX`

Les variables suivantes contrôlent la connexion à Blackstar :

- `BLACKSTAR_API_KEY` (obligatoire) — clé API 64 caractères hex
- `BLACKSTAR_BASE_URL` (défaut : `https://localhost:8443`)
- `BLACKSTAR_CHAT_MODEL` (défaut : `qwen2.5-7b-instruct`)
- `BLACKSTAR_VERIFY_SSL` (défaut : `false` pour le certificat auto-signé local)

## Structure du module

```
dossier_pipeline/resident_ai/
├── __init__.py
├── cli.py
├── config.py
├── blackstar_client.py      # client Blackstar + sentence-transformers
├── ollama_client.py         # conservé à titre historique (non utilisé)
├── prompt_registry.py
├── document_index.py
├── retriever.py
├── generators.py
├── repl.py
├── email_monitor.py
└── audit_logger.py
```

## Tests

```bash
python -m pytest tests/
```

## Avertissement

Cet outil produit des documents de préparation juridique. Toute communication officielle doit être relue par un avocat avant envoi.

## Notes d’utilisation

- **Indexation initiale :** comptez ~1–2 minutes pour indexer `red dart/` (637 chunks, 42 fichiers).
- **Recherche multilingue :** les documents sont principalement en anglais. Si une question en français ne retourne pas de résultat, essayez d’inclure les termes anglais clés (ex. `Marie-Eve Jean Medic Axion medical request`).
- **Sorties :** toutes les réponses sont sauvegardées dans `Red dart/resident_ai/` avec le hash du prompt, le hash du contexte et les citations.
