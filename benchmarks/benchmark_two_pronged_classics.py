#!/usr/bin/env python3
"""
Aegis Sovereign Appliance — Multi-Book Classic Literature Benchmark
Evaluating the Two-Pronged Hybrid Router (ADR-06), Multi-Tier Cognitive Engine
(Flat int8+BM25 vs. GraphRAG vs. RAPTOR Tree), and Selective Local LLM Synthesis (NanoRunner).

Corpus (4 Classic Works — Bilingual EN + PT-BR):
1. Alice's Adventures in Wonderland — Lewis Carroll (Gutenberg #11, EN)
2. The Adventures of Sherlock Holmes — Arthur Conan Doyle (Gutenberg #1661, EN)
3. Frankenstein; Or, The Modern Prometheus — Mary Shelley (Gutenberg #84, EN)
4. Dom Casmurro — Machado de Assis (Gutenberg #55752, PT-BR)
"""

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Any, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.router.query_router import SovereignQueryRouter, QueryRouteType
from core.security import ClearanceLevel, PlanTier
from core.graph.store import GraphStore
from desktop.daemon.nano_runner import NanoRunner

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 1. Classic Literature Corpus Loader (Gutenberg + Verified Curated Chapters)
# ---------------------------------------------------------------------------

CLASSICS_CATALOG = [
    {
        "catalog_id": "GUT-0011",
        "title": "Alice's Adventures in Wonderland",
        "author": "Lewis Carroll",
        "language": "EN",
        "year": 1865,
        "clearance": ClearanceLevel.PUBLIC,
        "file_name": "alice.txt",
        "gutenberg_url": "https://www.gutenberg.org/files/11/11-0.txt",
        "thesis": (
            "Lewis Carroll's Alice's Adventures in Wonderland explores the collapse of Victorian "
            "rules, adult authority, and deterministic logic as Alice navigates bodily size instability, "
            "linguistic riddles at the Mad Tea-Party, and judicial absurdity in the Queen of Hearts' courtroom."
        ),
        "curated_excerpts": [
            {
                "chapter": "Chapter I: Down the Rabbit-Hole",
                "abstract": "Alice follows the White Rabbit with a waistcoat-pocket watch down the rabbit-hole, lands in the Hall of Doors, and drinks from a bottle labeled 'DRINK ME'.",
                "text": (
                    "Alice was beginning to get very tired of sitting by her sister on the bank, when suddenly "
                    "a White Rabbit with pink eyes ran close by her, took a watch out of its waistcoat-pocket, "
                    "and hurried on. In the hall of locked doors, Alice found a little bottle on a three-legged "
                    "glass table with the words 'DRINK ME' beautifully printed on it in large letters. It had a "
                    "mixed flavour of cherry-tart, custard, pine-apple, roast turkey, toffy, and hot buttered toast. "
                    "She shrank to ten inches high."
                ),
            },
            {
                "chapter": "Chapter II & VII: Curiouser and the Mad Tea-Party",
                "abstract": "Alice cries a Pool of Tears exclaiming 'Curiouser and curiouser!' and later confronts the Mad Hatter, March Hare, and Dormouse trapped in perpetual 6 o'clock tea.",
                "text": (
                    "\"Curiouser and curiouser!\" cried Alice (she was so much surprised, that for the moment she "
                    "quite forgot how to speak good English). Later, under a tree in front of the house, the March "
                    "Hare and the Hatter were having tea with a Dormouse sitting between them fast asleep. "
                    "\"Why is a raven like a writing-desk?\" asked the Hatter. Time had quarrelled with the Hatter "
                    "at the Queen of Hearts' concert, leaving it always six o'clock."
                ),
            },
            {
                "chapter": "Chapter VIII & XII: The Queen's Croquet-Ground & The Trial",
                "abstract": "The Queen of Hearts shouts 'Off with their heads!' and presides over the trial of the Knave of Hearts, where Alice defies the court as 'nothing but a pack of cards'.",
                "text": (
                    "The Queen of Hearts had only one way of settling all difficulties, great or small: "
                    "\"Off with his head!\" At the trial of the Knave of Hearts over the stolen tarts, the Queen "
                    "demanded \"Sentence first—verdict afterwards!\" Alice grew to her full stature and declared: "
                    "\"Who cares for you? You're nothing but a pack of cards!\""
                ),
            },
        ],
        "entities": [
            ("Alice", "CHARACTER"),
            ("White Rabbit", "CHARACTER"),
            ("Mad Hatter", "CHARACTER"),
            ("March Hare", "CHARACTER"),
            ("Queen of Hearts", "CHARACTER"),
            ("Cheshire Cat", "CHARACTER"),
        ],
        "relations": [
            ("Alice", "FOLLOWED", "White Rabbit"),
            ("Alice", "DEBATED_TIME_WITH", "Mad Hatter"),
            ("Mad Hatter", "SHARED_TEA_WITH", "March Hare"),
            ("Queen of Hearts", "CONDEMNED_AT_CONCERT", "Mad Hatter"),
            ("Alice", "DEFIED_IN_COURT", "Queen of Hearts"),
        ],
    },
    {
        "catalog_id": "GUT-1661",
        "title": "The Adventures of Sherlock Holmes",
        "author": "Arthur Conan Doyle",
        "language": "EN",
        "year": 1892,
        "clearance": ClearanceLevel.PUBLIC,
        "file_name": "sherlock.txt",
        "gutenberg_url": "https://www.gutenberg.org/files/1661/1661-0.txt",
        "thesis": (
            "Arthur Conan Doyle's The Adventures of Sherlock Holmes codifies forensic empiricism and abductive "
            "reasoning from 221B Baker Street, contrasting Holmes's cold analytical observation against human "
            "emotion—most famously when outwitted by Irene Adler in 'A Scandal in Bohemia'."
        ),
        "curated_excerpts": [
            {
                "chapter": "Adventure I: A Scandal in Bohemia (221B Baker Street)",
                "abstract": "Sherlock Holmes and Dr. John Watson receive the King of Bohemia at 221B Baker Street regarding a compromising photograph held by Irene Adler ('the woman').",
                "text": (
                    "To Sherlock Holmes she is always the woman. I have seldom heard him mention her under any "
                    "other name. In his eyes she eclipses and predominates the whole of her sex. At our rooms at "
                    "221B Baker Street, Holmes remarked to Dr. Watson: \"You see, but you do not observe. The "
                    "distinction is clear. For example, you have frequently seen the steps which lead up from the "
                    "hall to this room: there are seventeen steps.\" The King of Bohemia sought to recover a "
                    "cabinet photograph from Irene Adler at Briony Lodge."
                ),
            },
            {
                "chapter": "Adventure II: The Red-Headed League & Jabez Wilson",
                "abstract": "Holmes uncovers John Clay's subterranean tunnel scheme beneath Saxe-Coburg Square aimed at robbing 30,000 napoleons of French gold from the City and Suburban Bank.",
                "text": (
                    "Jabez Wilson, a pawnbroker at Saxe-Coburg Square, was lured away four hours every afternoon "
                    "copying the Encyclopaedia Britannica for the Red-Headed League while his assistant Vincent "
                    "Spaulding (the notorious criminal John Clay) dug a tunnel into the cellar of the City and "
                    "Suburban Bank to steal 30,000 napoleons of French gold."
                ),
            },
        ],
        "entities": [
            ("Sherlock Holmes", "CHARACTER"),
            ("Dr. Watson", "CHARACTER"),
            ("Irene Adler", "CHARACTER"),
            ("King of Bohemia", "CHARACTER"),
            ("221B Baker Street", "LOCATION"),
            ("John Clay", "CHARACTER"),
        ],
        "relations": [
            ("Sherlock Holmes", "RESIDES_AT", "221B Baker Street"),
            ("Dr. Watson", "PARTNERS_WITH", "Sherlock Holmes"),
            ("King of Bohemia", "HIRED_AGAINST", "Irene Adler"),
            ("Irene Adler", "OUTWITTED", "Sherlock Holmes"),
            ("Sherlock Holmes", "FOILED_BANK_TUNNEL_OF", "John Clay"),
        ],
    },
    {
        "catalog_id": "GUT-0084",
        "title": "Frankenstein; Or, The Modern Prometheus",
        "author": "Mary Wollstonecraft Shelley",
        "language": "EN",
        "year": 1818,
        "clearance": ClearanceLevel.PUBLIC,
        "file_name": "frankenstein.txt",
        "gutenberg_url": "https://www.gutenberg.org/files/84/84-0.txt",
        "thesis": (
            "Mary Shelley's Frankenstein examines the moral catastrophe of unchecked scientific hubris and "
            "parental abandonment: Victor Frankenstein animates sentient life in Ingolstadt only to recoil in "
            "horror, transforming an empathetic autodidact creature into a vengeful outcast ending in Arctic ruin."
        ),
        "curated_excerpts": [
            {
                "chapter": "Chapter V: The dreary night of November in Ingolstadt",
                "abstract": "Victor Frankenstein brings the Creature to life on a dreary night of November in Ingolstadt, is horrified by its watery yellow eyes, and flees his laboratory.",
                "text": (
                    "It was on a dreary night of November that I beheld the accomplishment of my toils. By the "
                    "glimmer of the half-extinguished light, I saw the dull yellow eye of the creature open; it "
                    "breathed hard, and a convulsive motion agitated its limbs. Unable to endure the aspect of "
                    "the being I had created, Victor Frankenstein rushed out of the room in Ingolstadt, abandoning "
                    "the newborn creature to solitude and rejection."
                ),
            },
            {
                "chapter": "Chapter XV & XXIV: The Creature's Plea and Arctic Pursuit",
                "abstract": "Educated by reading Paradise Lost and Plutarch's Lives near the De Lacey cottage, the Creature begs Victor for a companion: 'I ought to be thy Adam, but I am rather the fallen angel.'",
                "text": (
                    "The Creature educated himself by reading Milton's Paradise Lost, Plutarch's Lives, and Sorrows "
                    "of Werter in a hovel adjoining the De Lacey family cottage. Confronting Victor on the glacier "
                    "of Montanvert, the Creature declared: \"I am malicious because I am miserable. Remember that I "
                    "am thy creature; I ought to be thy Adam, but I am rather the fallen angel, whom thou drivest "
                    "from joy for no misdeed.\" After Victor destroyed the female mate and Elizabeth Lavenza was "
                    "murdered, Captain Robert Walton recorded their final pursuit across the Arctic ice."
                ),
            },
        ],
        "entities": [
            ("Victor Frankenstein", "CHARACTER"),
            ("The Creature", "CHARACTER"),
            ("Elizabeth Lavenza", "CHARACTER"),
            ("Robert Walton", "CHARACTER"),
            ("Ingolstadt", "LOCATION"),
        ],
        "relations": [
            ("Victor Frankenstein", "ANIMATED_AND_ABANDONED", "The Creature"),
            ("Victor Frankenstein", "STUDIED_AT", "Ingolstadt"),
            ("The Creature", "RETALIATED_AGAINST", "Elizabeth Lavenza"),
            ("Robert Walton", "RESCUED_IN_ARCTIC", "Victor Frankenstein"),
        ],
    },
    {
        "catalog_id": "GUT-55752",
        "title": "Dom Casmurro",
        "author": "Machado de Assis",
        "language": "PT-BR",
        "year": 1899,
        "clearance": ClearanceLevel.PUBLIC,
        "file_name": "dom_casmurro.txt",
        "gutenberg_url": "https://www.gutenberg.org/files/55752/55752-0.txt",
        "thesis": (
            "Dom Casmurro, obra-prima de Machado de Assis, disseca a dúvida epistemológica, a memória "
            "não-confiável e a corrosão pelo ciúme: Bento Santiago (Bentinho), advogado solitário no Engenho "
            "Novo, reconstrói sua paixão juvenil por Capitu ('olhos de ressaca' e 'olhos de cigana oblíqua e "
            "dissimulada') e sua suspeita obsessiva de traição com o amigo Ezequiel de Sousa Escobar."
        ),
        "curated_excerpts": [
            {
                "chapter": "Capítulo XXV & XXXII: Os Olhos de Ressaca e Cigana Oblíqua",
                "abstract": "José Dias define Capitu como tendo 'olhos de cigana oblíqua e dissimulada', enquanto Bentinho batiza seu olhar magnético de 'olhos de ressaca' na Rua de Matacavalos.",
                "text": (
                    "Na casa da Rua de Matacavalos, José Dias alertou Dona Glória que Capitu tinha \"olhos de "
                    "cigana oblíqua e dissimulada\". Bentinho, contemplando Capitolina (Capitu), definiu sua "
                    "expressão imortal: \"Olhos de ressaca? Vá, de ressaca. É o que me dá ideia daquela feição "
                    "nova. Traziam não sei que fluido misterioso e enérgico, uma força que arrastava para dentro, "
                    "como a vaga que se retira da praia, nos dias de ressaca.\""
                ),
            },
            {
                "chapter": "Capítulo CXVIII & CXLVIII: Escobar, Ezequiel e a Dúvida Irresolúvel",
                "abstract": "Após o afogamento de Escobar no mar do Flamengo, o ciúme patológico de Bentinho vê na fisionomia do filho Ezequiel os traços do amigo morto, culminando no exílio de Capitu na Suíça.",
                "text": (
                    "Ezequiel de Sousa Escobar, melhor amigo de Bentinho desde o seminário de São José e marido "
                    "de Sancha, morreu afogado nas ondas do Flamengo. Durante o enterro, o olhar de Capitu para o "
                    "defunto despertou o ciúme implacável de Bento Santiago. À medida que o menino Ezequiel "
                    "crescia, Bentinho enxergava nele os gestos e os olhos de Escobar, banindo Capitu para a "
                    "Suíça e encerrando-se como 'Dom Casmurro' para atar as duas pontas da vida."
                ),
            },
        ],
        "entities": [
            ("Bentinho", "CHARACTER"),
            ("Capitu", "CHARACTER"),
            ("Escobar", "CHARACTER"),
            ("José Dias", "CHARACTER"),
            ("Ezequiel", "CHARACTER"),
        ],
        "relations": [
            ("Bentinho", "CASOU_COM", "Capitu"),
            ("Bentinho", "ESTUDOU_NO_SEMINARIO_COM", "Escobar"),
            ("Bentinho", "SUSPEITOU_TRAICAO_ENTRE", "Capitu"),
            ("Capitu", "TEVE_FILHO", "Ezequiel"),
            ("José Dias", "APELIDOU_OLHOS_DE_CIGANA", "Capitu"),
        ],
    },
]


# ---------------------------------------------------------------------------
# 2. Multi-Tier Hybrid Searcher Mock + Real FastEmbed / Router / NanoRunner
# ---------------------------------------------------------------------------

class ClassicsMultiscaleCorpus:
    """
    Indexes the 4 classic books across:
    1. SovereignQueryRouter (SQLite B-Tree + External FTS5 with MAC pushdown)
    2. GraphStore (SQLite WAL Entity & Multi-Hop Relation Graph)
    3. RAPTOR Multi-Layer Hierarchy (Layer 2 Book Thesis + Layer 1 Chapter Abstracts + Layer 0 Verbatim Excerpts)
    4. NanoRunner (Local LLM Grounded Fast Synthesis Engine)
    """

    def __init__(self):
        self.db_file = DATA_DIR / "classics_router_bench.db"
        self.graph_file = DATA_DIR / "classics_graph_bench.db"
        if self.db_file.exists():
            self.db_file.unlink()
        if self.graph_file.exists():
            self.graph_file.unlink()

        self.graph_store = GraphStore(db_path=self.graph_file)
        self.nano_runner = NanoRunner()
        self.chunks: List[Dict[str, Any]] = []
        self.raptor_theses: List[Dict[str, Any]] = []

        self._build_corpus()
        self.router = SovereignQueryRouter(
            db_path=str(self.db_file),
            searcher=self,
            graph_store=self.graph_store,
            plan=PlanTier.PRO,
        )
        self._index_into_router_and_graph()

    def _build_corpus(self):
        # Also include real Gutenberg Alice chapters if alice.txt exists
        alice_path = DATA_DIR / "alice.txt"
        alice_word_count = 0
        if alice_path.exists():
            raw_alice = alice_path.read_text(encoding="utf-8", errors="ignore")
            alice_word_count = len(raw_alice.split())

        for book in CLASSICS_CATALOG:
            # Layer 2 Book Thesis
            self.raptor_theses.append({
                "title": f"{book['title']} ({book['author']}) [RAPTOR Layer 2 Thesis]",
                "file_path": f"library://{book['catalog_id']}/{book['file_name']}",
                "heading": "Layer 2: Volume Thesis",
                "source_tier": "RAPTOR_L2_THESIS",
                "catalog_id": book["catalog_id"],
                "language": book["language"],
                "score": 0.96,
                "text": book["thesis"],
            })
            # Layer 1 & Layer 0 Chapter Excerpts
            for exc in book["curated_excerpts"]:
                self.chunks.append({
                    "title": f"{book['title']} — {exc['chapter']}",
                    "file_path": f"library://{book['catalog_id']}/{book['file_name']}",
                    "heading": exc["chapter"],
                    "source_tier": "LAYER_0_RAW_AND_L1_ABSTRACT",
                    "catalog_id": book["catalog_id"],
                    "language": book["language"],
                    "score": 0.91,
                    "text": f"[Abstract: {exc['abstract']}] {exc['text']}",
                })

        self.alice_word_count = alice_word_count or 26540

    def _index_into_router_and_graph(self):
        for idx, book in enumerate(CLASSICS_CATALOG, start=1):
            full_book_text = book["thesis"] + "\n\n" + "\n\n".join(
                f"{e['chapter']}: {e['text']}" for e in book["curated_excerpts"]
            )
            # Index in Prong 1 SQLite B-Tree + FTS5
            self.router.index_document(
                doc_identifier=book["catalog_id"],
                title=f"{book['title']} ({book['author']}, {book['year']})",
                content=full_book_text,
                clearance_level=book["clearance"],
                metadata={
                    "author": book["author"],
                    "language": book["language"],
                    "year": book["year"],
                },
            )
            # Index Entities & Relations in SQLite WAL GraphStore
            eid_map = {}
            for ent_name, ent_type in book["entities"]:
                eid = self.graph_store.insert_entity(
                    name=ent_name,
                    entity_type=ent_type,
                    clearance_level=book["clearance"].value,
                )
                eid_map[ent_name] = eid
            for src, rel, dst in book["relations"]:
                src_id = eid_map.get(src) or self.graph_store.insert_entity(name=src, entity_type="CHARACTER")
                dst_id = eid_map.get(dst) or self.graph_store.insert_entity(name=dst, entity_type="CHARACTER")
                self.graph_store.insert_relation(
                    source_entity_id=src_id,
                    target_entity_id=dst_id,
                    relation_type=rel,
                    doc_id=None,
                    clearance_level=book["clearance"].value,
                )

    def search(
        self,
        query: str,
        limit: int = 5,
        retrieval_mode: str = "high_precision",
        confidence_floor: float = 0.0,
        user_clearance: str = "public",
        analytical_depth: str = "flash_needle",
    ) -> List[Dict[str, Any]]:
        """
        Simulates FastEmbed int8 + Sparse BM25 RRF + RAPTOR hierarchical retrieval
        across the 4 classic books.
        """
        t0 = time.perf_counter()
        q_lower = query.lower()
        q_tokens = set(re.findall(r"\b\w{3,}\b", q_lower))

        pool = list(self.chunks)
        if analytical_depth == "deep_synthesis":
            pool = list(self.raptor_theses) + pool

        scored = []
        for item in pool:
            txt_lower = (item["title"] + " " + item["text"] + " " + item["catalog_id"]).lower()
            overlap = sum(1 for tok in q_tokens if tok in txt_lower)
            # Boost exact catalog_id or character match
            if item["catalog_id"].lower() in q_lower:
                overlap += 6
            if analytical_depth == "deep_synthesis" and item["source_tier"] == "RAPTOR_L2_THESIS":
                overlap += 2
            if overlap > 0:
                score = min(0.99, 0.45 + 0.08 * overlap)
                hit = dict(item)
                hit["score"] = round(score, 4)
                hit["retrieval_latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
                scored.append(hit)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]


# ---------------------------------------------------------------------------
# 3. Benchmark Suite Execution
# ---------------------------------------------------------------------------

BENCHMARK_QUERIES = [
    {
        "id": "Q1_PRONG1_CATALOG_ID",
        "category": "Prong 1: Deterministic Catalog ID (<2ms)",
        "query": "GUT-0011",
        "book_target": "Alice in Wonderland (EN)",
        "expected_route": "deterministic_direct",
        "expected_synthesis": False,
    },
    {
        "id": "Q2_PRONG1_EXACT_QUOTE_EN",
        "category": "Prong 1: Exact Literary Quote (<2ms)",
        "query": '"Curiouser and curiouser!"',
        "book_target": "Alice in Wonderland (EN)",
        "expected_route": "deterministic_direct",
        "expected_synthesis": False,
    },
    {
        "id": "Q3_PRONG1_EXACT_QUOTE_PT",
        "category": "Prong 1: Exact Literary Quote PT-BR (<2ms)",
        "query": '"olhos de cigana oblíqua e dissimulada"',
        "book_target": "Dom Casmurro (PT-BR)",
        "expected_route": "deterministic_direct",
        "expected_synthesis": False,
    },
    {
        "id": "Q4_PRONG1_MISSING_ID_SAFE_FAIL",
        "category": "Prong 1: Missing Catalog ID Safe Failure",
        "query": "GUT-99999",
        "book_target": "Non-Existent Book (Anti-Hallucination Guard)",
        "expected_route": "deterministic_direct",
        "expected_synthesis": False,
    },
    {
        "id": "Q5_PRONG2_NEEDLE_FACTUAL_EN",
        "category": "Prong 2 (Tier 1): Factual Needle (No LLM Synthesis)",
        "query": "What words were printed on the bottle Alice drank from and what flavours did it have?",
        "book_target": "Alice in Wonderland (EN)",
        "expected_route": "hybrid_needle",
        "expected_synthesis": False,
    },
    {
        "id": "Q6_PRONG2_NEEDLE_FACTUAL_SHERLOCK",
        "category": "Prong 2 (Tier 1): Factual Needle (Sherlock Holmes)",
        "query": "221B Baker Street seventeen steps Irene Adler photograph",
        "book_target": "Sherlock Holmes (EN)",
        "expected_route": "hybrid_needle",
        "expected_synthesis": False,
    },
    {
        "id": "Q7_PRONG2_ANALYTICAL_FRANKENSTEIN",
        "category": "Prong 2 (Tier 1 + Local LLM): Analytical Inquiry",
        "query": "Why did Victor Frankenstein abandon the creature in Ingolstadt and how did the creature educate himself?",
        "book_target": "Frankenstein (EN)",
        "expected_route": "hybrid_needle",
        "expected_synthesis": True,
    },
    {
        "id": "Q8_PRONG2_RELATIONAL_GRAPH_ALICE",
        "category": "Prong 2 (Tier 2 GraphRAG): Multi-Hop Character Graph",
        "query": "Trace the relationship and connection between Alice, Mad Hatter, March Hare, and Queen of Hearts",
        "book_target": "Alice in Wonderland (EN)",
        "expected_route": "relational_graph",
        "expected_synthesis": True,
    },
    {
        "id": "Q9_PRONG2_RELATIONAL_GRAPH_PT",
        "category": "Prong 2 (Tier 2 GraphRAG PT-BR): Multi-Hop Dom Casmurro",
        "query": "Qual a relação e o vínculo entre Bentinho, Capitu e Escobar em Dom Casmurro?",
        "book_target": "Dom Casmurro (PT-BR)",
        "expected_route": "relational_graph",
        "expected_synthesis": True,
    },
    {
        "id": "Q10_PRONG2_COMPOUND_FUSED_PT",
        "category": "Prong 2 (Compound ID + RAPTOR Synthesis PT-BR)",
        "query": "GUT-55752 Resuma a evolução do ciúme de Bentinho e o significado dos olhos de ressaca de Capitu",
        "book_target": "Dom Casmurro (PT-BR)",
        "expected_route": "compound_fused",
        "expected_synthesis": True,
    },
    {
        "id": "Q11_PRONG2_MACRO_RAPTOR_CROSS_BOOK",
        "category": "Prong 2 (Tier 3 RAPTOR): Cross-Book Macro Thesis",
        "query": "Compare the overarching theme and narrative arc of obsession, authority, and tragic isolation across Frankenstein, Dom Casmurro, and Alice's Adventures in Wonderland",
        "book_target": "All 4 Classics (Cross-Corpus RAPTOR)",
        "expected_route": "macro_synthesis",
        "expected_synthesis": True,
    },
]


def run_benchmark() -> Dict[str, Any]:
    corpus = ClassicsMultiscaleCorpus()
    results_table = []

    prong1_latencies = []
    prong2_retrieval_latencies = []
    llm_synthesis_latencies = []
    llm_calls_avoided = 0
    vector_passes_avoided = 0

    for item in BENCHMARK_QUERIES:
        q = item["query"]
        t_start = time.perf_counter()
        decision = corpus.router.analyze_query(q)
        routed = corpus.router.route_and_execute(q, user_clearance="public", limit=4)
        retrieval_ms = (time.perf_counter() - t_start) * 1000.0

        actual_route = routed.get("route") or decision.route_type.value
        needs_synth = bool(routed.get("needs_synthesis", False))
        hits = routed.get("results", [])

        if decision.bypass_vector_search:
            vector_passes_avoided += 1
            prong1_latencies.append(retrieval_ms)
        else:
            prong2_retrieval_latencies.append(retrieval_ms)

        synth_ms = 0.0
        synth_answer_preview = "SKIPPED (0 LLM Tokens — Direct Verified Record)"
        if needs_synth and hits:
            t_synth = time.perf_counter()
            norm_chunks = [
                {
                    "title": h.get("title", "Classic Book"),
                    "file_path": h.get("file_path", ""),
                    "heading": h.get("heading", "Chapter"),
                    "chunk_index": i,
                    "score": float(h.get("score") or 0.90),
                    "text": h.get("text") or h.get("content") or "",
                }
                for i, h in enumerate(hits, start=1)
            ]
            synth_res = corpus.nano_runner.synthesize(query=q, chunks=norm_chunks)
            synth_ms = (time.perf_counter() - t_synth) * 1000.0
            llm_synthesis_latencies.append(synth_ms)
            clean_ans = synth_res.answer.replace("\n", " ").strip()
            synth_answer_preview = clean_ans[:140] + "..."
        else:
            llm_calls_avoided += 1

        top_hit_title = hits[0].get("title", "NONE (Safe 404)") if hits else "NONE (Safe 404)"

        results_table.append({
            "id": item["id"],
            "category": item["category"],
            "book_target": item["book_target"],
            "query": q,
            "route": actual_route,
            "route_match": actual_route == item["expected_route"],
            "needs_synthesis": needs_synth,
            "synthesis_match": needs_synth == item["expected_synthesis"],
            "bypass_vector": decision.bypass_vector_search,
            "retrieval_ms": round(retrieval_ms, 3),
            "synthesis_ms": round(synth_ms, 3),
            "total_ms": round(retrieval_ms + synth_ms, 3),
            "hits_count": len(hits),
            "top_hit": top_hit_title,
            "summary_preview": synth_answer_preview,
        })

    summary = {
        "books_indexed": len(CLASSICS_CATALOG),
        "total_queries": len(BENCHMARK_QUERIES),
        "route_classification_accuracy_pct": round(
            100.0 * sum(1 for r in results_table if r["route_match"]) / len(results_table), 1
        ),
        "synthesis_gate_accuracy_pct": round(
            100.0 * sum(1 for r in results_table if r["synthesis_match"]) / len(results_table), 1
        ),
        "avg_prong1_deterministic_ms": round(
            sum(prong1_latencies) / max(1, len(prong1_latencies)), 3
        ),
        "avg_prong2_retrieval_ms": round(
            sum(prong2_retrieval_latencies) / max(1, len(prong2_retrieval_latencies)), 3
        ),
        "avg_local_llm_synthesis_ms": round(
            sum(llm_synthesis_latencies) / max(1, len(llm_synthesis_latencies)), 3
        ),
        "vector_forward_passes_avoided": f"{vector_passes_avoided}/{len(BENCHMARK_QUERIES)} ({round(100*vector_passes_avoided/len(BENCHMARK_QUERIES), 1)}%)",
        "llm_generations_avoided_by_gate": f"{llm_calls_avoided}/{len(BENCHMARK_QUERIES)} ({round(100*llm_calls_avoided/len(BENCHMARK_QUERIES), 1)}%)",
        "results": results_table,
    }

    out_json = Path(__file__).resolve().parent / "two_pronged_classics_results.json"
    out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


if __name__ == "__main__":
    res = run_benchmark()
    print(json.dumps({k: v for k, v in res.items() if k != "results"}, indent=2, ensure_ascii=False))
    print("\n--- Per-Query Breakdown ---")
    for r in res["results"]:
        print(
            f"[{r['id']}] Route={r['route']} (Match={r['route_match']}) | "
            f"Synth={r['needs_synthesis']} | Retrieval={r['retrieval_ms']}ms | "
            f"LLM_Synth={r['synthesis_ms']}ms | Top={r['top_hit']}"
        )
