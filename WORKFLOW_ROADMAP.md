# Marketing Agent Workflow Implementation Roadmap

The workflow in `VAF_AI_Marketing_Agent_Wireframe_v3.html` is the product target,
not a description of features already shipped. The VAF dashboard's **Workflow Map**
visually maps that target and explicitly reports what is implemented.

## Channels

| Channel | Current status | Next backend milestone |
| --- | --- | --- |
| RFP/Public Bids | Partially operational: search engine discovery, PDF extraction, Ollama parsing, limited CPPP public page | Source registry with directly supported official state portals, coverage and corrigenda verification |
| Empanelled Agencies | Not implemented | Agency directory adapter, deduplication, certifications, partner capabilities |
| Developer/Community | Not implemented | Compliant GitHub/API/community signals and early technical intent |
| Awards/SI Tracking | Classification limited, no tracking | Award records, winning SI links, contract status, follow-on opportunity detection |
| Corporate Intelligence | Not implemented | Consent/terms-compliant company news and hiring signals |

## Cross-channel execution

1. Ingestion and normalization into a shared signal schema and provenance store
2. Local Ollama extraction; add cloud fallback only after an opt-in/configuration path exists
3. Fact-level evidence validation, date and official-portal verification
4. Entity/project correlation with explainable relationship matches
5. Explainable qualification score 1–10 (do not score incomplete records as strong leads)
6. Ranking shortlist, aiming for approximately 10 strongest of 100 raw signals
7. Opportunity dossier with tender source, verified status, SI route, VAF fit, and next action
8. Human review and CRM export, with no autonomous external outreach

## UI build order

- **Phase W1 (this commit)**: Navigate full workflow; render five channels and eight stages, use *real selected-run metrics*; visibly mark unimplemented stages.
- **Phase W2.1–W2.2 implemented (initial version)**: `signal_store.py` writes `signals.json` per run, canonicalizes URLs, deduplicates saved source records, retains provenance and provides explainable `accepted` / `needs_review` / `rejected` deterministic triage. Existing runs are backfilled on dashboard load. The sidebar now includes **Signal Intelligence** for review. It is intentionally conservative and is not a lead-scoring model.
- **Phase W2.3 next**: A dedicated government/partner/developer Source Registry with per-source coverage, crawl constraints, confidence, audit history and direct portal adapters.
- **Phase W3**: Add correlation and explainable scores with tests and ground truth data.
- **Phase W4**: Build searchable top-ten list, dossiers and review actions.
- **Phase W5**: Connect more sources and CRM after reliability/privacy checks.

The wireframe uses fictional sample entities, scores, dates and counts. Never show
them as discovered real businesses or currently open tenders.
