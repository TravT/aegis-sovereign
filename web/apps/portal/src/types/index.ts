/**
 * Aegis Sovereign Knowledge Appliance Type Definitions
 * Strict TypeScript interfaces with zero `any` allowance.
 */

export type RetrievalMode = 'high_precision' | 'legal_discovery' | 'exact_entity';

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
  page: number;
  critical?: boolean;
}

export interface Citation {
  citation_index: number;
  title: string;
  file_path: string;
  heading?: string;
  rrf_score: number;
  page?: number;
  excerpt?: string;
  bbox?: BoundingBox;
}

export interface TokenEconomics {
  raw_archive_tokens: number;
  optimized_input_tokens: number;
  advertised_guaranteed_savings: string;
  real_world_token_reduction_pct: string;
  cloud_api_cost_reduction: string;
  estimated_dollars_averted: number;
}

export interface Entity {
  id: number;
  name: string;
  normalized_name?: string;
  entity_type: string;
  document_id?: number;
  context?: string;
}

export interface Relation {
  relation_type: string;
  target_name: string;
  target_type: string;
  direction: 'outgoing' | 'incoming';
}

export interface EntityDate {
  name: string;
  normalized_name?: string;
  context?: string;
}

export interface EntityAmount {
  name: string;
  parsed_value?: number;
  context?: string;
}

export interface DocumentRecord {
  id: number;
  title: string;
  corpus?: string;
  created_date?: string;
  correspondent?: string;
  document_type?: string;
  tags?: string[];
  file_name?: string;
  checksum_sha256?: string;
  risk_level?: 'low' | 'medium' | 'high' | 'warning' | 'critical';
  fatal_deadline?: string;
  content_snippet?: string;
  page_count?: number;
}

export interface EntityDossier {
  entity: Entity | null;
  total_documents: number;
  documents: DocumentRecord[];
  dates: EntityDate[];
  amounts: EntityAmount[];
  total_monetary_amount: number;
  connected_entities: Record<string, Entity[]>;
  relations: Relation[];
}

export type AnalyticalDepth = 'flash_needle' | 'relational_audit' | 'deep_synthesis';
export type EvidenceGrounding = 'verbatim_footnotes' | 'executive_abstract';
export type ClearanceLevelString = 'public' | 'internal' | 'confidential' | 'restricted';
export type CriticalPosture = 'neutral' | 'compliance_auditor' | 'scholarly';
export type PlanTier = 'free' | 'pro' | 'enterprise';

export interface VisualPlate {
  plate_id: string;
  title: string;
  similarity: number;
  description?: string;
  url?: string;
}

export interface OptimizationResult {
  query: string;
  retrieval_mode: RetrievalMode;
  verified_evidence_chunks: number;
  optimized_context: string;
  citations: Citation[];
  token_economics: TokenEconomics;
  graph_dossier?: EntityDossier | null;
  answer_synthesis?: string;
  analytical_depth?: AnalyticalDepth;
  evidence_grounding?: EvidenceGrounding;
  include_visual_plates?: boolean;
  user_clearance?: ClearanceLevelString;
  critical_posture?: CriticalPosture;
  visual_plates?: VisualPlate[];
}

export type IngestionStage = 1 | 2 | 3 | 4 | 5;

export interface IngestionStageInfo {
  stage: IngestionStage;
  name: string;
  description: string;
}

export const INGESTION_STAGES: Record<IngestionStage, IngestionStageInfo> = {
  1: {
    stage: 1,
    name: 'Integrity Hashing',
    description: 'SHA-256 cryptographic verification and duplicate quarantine',
  },
  2: {
    stage: 2,
    name: 'OCR & Layout Parsing',
    description: 'Docling table decomposition and Tesseract text rasterization',
  },
  3: {
    stage: 3,
    name: 'Entity Graph Extraction',
    description: 'Zero-shot NER and relational edge discovery',
  },
  4: {
    stage: 4,
    name: 'Vector Indexing',
    description: 'FastEmbed int8 dual-encoder embeddings and BM25 sparse vectors',
  },
  5: {
    stage: 5,
    name: 'Knowledge Store Linking',
    description: 'Atomic SQLite WAL commit and cross-document reconciliation',
  },
};

export interface IngestionTask {
  id: string;
  fileName: string;
  fileSize: number;
  status: 'queued' | 'processing' | 'completed' | 'failed';
  currentStage: IngestionStage;
  stageProgress: number; // 0 to 100
  logs: string[];
  resultDocId?: number;
  startedAt: string;
  completedAt?: string;
  error?: string;
}

export interface ApplianceStatus {
  status: 'online' | 'degraded' | 'offline';
  uptime_started: string;
  total_queries: number;
  total_optimizations: number;
  total_ingestions: number;
  total_dispatched_actions: number;
  last_ingestion?: {
    doc_id: number;
    title: string;
    timestamp: string;
    actions_triggered: number;
  } | null;
  knowledge_graph?: {
    total_documents: number;
    total_entities: number;
    total_relations: number;
    entity_breakdown?: Record<string, number>;
  };
  vector_target?: string;
  collection?: string;
  air_gap_verified: boolean;
  outbound_bytes: number;
  latency_ms: number;
  cpu_temp_c?: number;
  memory_usage_mb?: number;
}

export interface CalibrationSettings {
  retrieval_mode: RetrievalMode;
  max_chunks: number;
  confidence_floor: number;
  include_graph_dossier: boolean;
  graph_depth: number;
  // The 5 High-Signal Executive Knobs
  analytical_depth: AnalyticalDepth;
  evidence_grounding: EvidenceGrounding;
  include_visual_plates: boolean;
  user_clearance: ClearanceLevelString;
  critical_posture: CriticalPosture;
}

export interface ActiveAlert {
  id: string;
  type: 'critical' | 'warning' | 'info';
  title: string;
  deadline?: string;
  description: string;
  sourceDocId?: number;
  timestamp: string;
}
