'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  ShieldCheck,
  Cpu,
  Database,
  Layers,
  Search,
  UploadCloud,
  Sliders,
  AlertTriangle,
  FileText,
  Clock,
  ExternalLink,
  ChevronRight,
  TrendingDown,
  DollarSign,
  Activity,
  FolderOpen,
  Share2,
  Terminal,
  CheckCircle2,
  AlertCircle,
  Network,
  Lock,
  Eye,
  BookOpen,
  Image as ImageIcon,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  Modal,
  Drawer,
  ProgressBar,
  Odometer,
  CitationPill,
} from '@aegis/ui';
import {
  ApplianceStatus,
  CalibrationSettings,
  Citation,
  DocumentRecord,
  Entity,
  EntityDossier,
  IngestionStage,
  IngestionTask,
  INGESTION_STAGES,
  OptimizationResult,
  RetrievalMode,
  ActiveAlert,
  AnalyticalDepth,
  EvidenceGrounding,
  ClearanceLevelString,
  CriticalPosture,
  VisualPlate,
} from '@/types';
import {
  checkHealth,
  optimizeContext,
  getEntityDossier,
  simulateIngestion,
  DEMO_DOCUMENTS,
  DEMO_ALERTS,
  DEMO_DOSSIER,
  DEMO_STATUS,
} from '@/lib/api';

export default function SovereignPortalPage() {
  // Appliance telemetry & health
  const [status, setStatus] = useState<ApplianceStatus>(DEMO_STATUS);
  const [latency, setLatency] = useState<number>(22);

  // Search & Query state
  const [query, setQuery] = useState<string>('Existe alguma intimação jurídica com prazo iminente?');
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [optimizationResult, setOptimizationResult] = useState<OptimizationResult | null>(null);
  const [selectedCitationIndex, setSelectedCitationIndex] = useState<number>(1);

  // Active Document Viewer state
  const [activeDocId, setActiveDocId] = useState<number>(103);
  const [selectedBboxLabel, setSelectedBboxLabel] = useState<string | null>(null);

  // Calibration Drawer state
  const [isCalibrationOpen, setIsCalibrationOpen] = useState<boolean>(false);
  const [calibration, setCalibration] = useState<CalibrationSettings>({
    retrieval_mode: 'high_precision',
    max_chunks: 3,
    confidence_floor: 0.45,
    include_graph_dossier: true,
    graph_depth: 2,
    analytical_depth: 'flash_needle',
    evidence_grounding: 'verbatim_footnotes',
    include_visual_plates: false,
    user_clearance: 'restricted',
    critical_posture: 'neutral',
  });

  // Entity Dossier Modal state
  const [isDossierOpen, setIsDossierOpen] = useState<boolean>(false);
  const [activeEntityName, setActiveEntityName] = useState<string>('Alpha Holdings Participações S.A.');
  const [dossierData, setDossierData] = useState<EntityDossier>(DEMO_DOSSIER);
  const [isLoadingDossier, setIsLoadingDossier] = useState<boolean>(false);

  // Ingestion Modal & Pipeline state
  const [isIngestModalOpen, setIsIngestModalOpen] = useState<boolean>(false);
  const [ingestionTasks, setIngestionTasks] = useState<IngestionTask[]>([]);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Active Alerts
  const [alerts] = useState<ActiveAlert[]>(DEMO_ALERTS);

  // Initial load: fetch health and execute default query
  useEffect(() => {
    async function init() {
      const healthData = await checkHealth();
      setStatus(healthData);
      setLatency(healthData.latency_ms || 22);

      // Perform default initial query
      handleExecuteQuery('Existe alguma intimação jurídica com prazo iminente?');
    }
    init();
  }, []);

  // Query Execution Handler
  const handleExecuteQuery = useCallback(
    async (searchQuery: string) => {
      if (!searchQuery.trim()) return;
      setIsSearching(true);
      try {
        const start = performance.now();
        const result = await optimizeContext({
          query: searchQuery,
          max_chunks: calibration.max_chunks,
          retrieval_mode: calibration.retrieval_mode,
          confidence_floor: calibration.confidence_floor,
          include_graph_dossier: calibration.include_graph_dossier,
          analytical_depth: calibration.analytical_depth,
          evidence_grounding: calibration.evidence_grounding,
          include_visual_plates: calibration.include_visual_plates,
          user_clearance: calibration.user_clearance,
          critical_posture: calibration.critical_posture,
        });
        const elapsed = Math.round(performance.now() - start);
        setLatency(elapsed > 0 ? elapsed : 18);
        setOptimizationResult(result);
        if (result.citations.length > 0) {
          setSelectedCitationIndex(result.citations[0].citation_index);
          // Set active document matching the top citation
          const topDoc = DEMO_DOCUMENTS.find((d) =>
            result.citations[0].title.toLowerCase().includes(d.title.slice(0, 15).toLowerCase())
          );
          if (topDoc) setActiveDocId(topDoc.id);
        }
      } catch (err) {
        console.error('Query execution error:', err);
      } finally {
        setIsSearching(false);
      }
    },
    [calibration]
  );

  // Handle entity dossier lookup
  const handleOpenDossier = useCallback(async (entityName: string) => {
    setActiveEntityName(entityName);
    setIsDossierOpen(true);
    setIsLoadingDossier(true);
    try {
      const data = await getEntityDossier(entityName);
      setDossierData(data);
    } catch (err) {
      console.error('Failed to load dossier:', err);
    } finally {
      setIsLoadingDossier(false);
    }
  }, []);

  // Handle file ingestion trigger
  const handleFilesAdded = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return;
    setIsIngestModalOpen(true);

    Array.from(files).forEach((file) => {
      simulateIngestion(file, (updatedTask) => {
        setIngestionTasks((prev) => {
          const index = prev.findIndex((t) => t.id === updatedTask.id);
          if (index >= 0) {
            const next = [...prev];
            next[index] = updatedTask;
            return next;
          }
          return [updatedTask, ...prev];
        });

        if (updatedTask.status === 'completed') {
          setStatus((prev) => ({
            ...prev,
            total_ingestions: prev.total_ingestions + 1,
            last_ingestion: {
              doc_id: updatedTask.resultDocId || 105,
              title: updatedTask.fileName,
              timestamp: new Date().toISOString(),
              actions_triggered: 1,
            },
          }));
        }
      });
    });
  }, []);

  const activeDoc = DEMO_DOCUMENTS.find((d) => d.id === activeDocId) || DEMO_DOCUMENTS[0];

  // Averted costs calculations
  const totalTokensSaved = optimizationResult
    ? optimizationResult.token_economics.raw_archive_tokens -
      optimizationResult.token_economics.optimized_input_tokens
    : 38088;
  const dollarsSavedGPT4 = ((totalTokensSaved / 1_000_000) * 5.0).toFixed(4);
  const dollarsSavedClaude = ((totalTokensSaved / 1_000_000) * 3.0).toFixed(4);

  return (
    <div className="min-h-screen flex flex-col bg-[#07090D] text-[#E6EDF3] select-none">
      {/* ========================================================================= */}
      {/* 1. APPLIANCE MASTER HEADER */}
      {/* ========================================================================= */}
      <header className="sticky top-0 z-40 bg-[#0E121A]/95 backdrop-blur-md border-b border-[#232B38] px-4 lg:px-8 py-3 flex flex-wrap items-center justify-between gap-4">
        {/* Brand & Identity */}
        <div className="flex items-center gap-3.5">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-[#D4AF37] to-[#997A15] flex items-center justify-center font-serif font-bold text-black text-xl shadow-[0_0_16px_rgba(212,175,55,0.3)]">
            A
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-serif text-sm lg:text-base font-bold tracking-[0.12em] text-[#F3E5AB]">
                AEGIS SOVEREIGN VAULT
              </h1>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#D4AF37]/15 text-[#F3E5AB] border border-[#D4AF37]/30">
                v2.4
              </span>
            </div>
            <p className="text-[10px] text-[#8B949E] tracking-wider uppercase font-sans">
              Private Enterprise Document Intelligence Appliance
            </p>
          </div>
        </div>

        {/* Air-Gap Telemetry & Status Badges */}
        <div className="flex items-center flex-wrap gap-2.5">
          <Badge variant="sovereign" dot dotPulse size="md">
            100% AIR-GAPPED NODE
          </Badge>

          <Badge variant="success" size="md">
            ZERO EGRESS // 0 BYTES
          </Badge>

          <div className="hidden sm:flex items-center gap-2 px-2.5 py-1 rounded bg-[#141A24] border border-[#232B38] font-mono text-xs text-[#8B949E]">
            <Activity className="w-3.5 h-3.5 text-[#00E676]" />
            <span>LATENCY:</span>
            <span className="text-[#F3E5AB] font-semibold">{latency}ms</span>
          </div>

          <div className="hidden md:flex items-center gap-2 px-2.5 py-1 rounded bg-[#141A24] border border-[#232B38] font-mono text-xs text-[#8B949E]">
            <Cpu className="w-3.5 h-3.5 text-[#D4AF37]" />
            <span>WAL SYNC:</span>
            <span className="text-[#00E676] font-semibold">10ms</span>
          </div>

          {/* Quick Action Buttons */}
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              icon={<UploadCloud className="w-3.5 h-3.5 text-[#D4AF37]" />}
              onClick={() => setIsIngestModalOpen(true)}
            >
              INGESTION
            </Button>

            <Button
              variant="gold"
              size="sm"
              icon={<Sliders className="w-3.5 h-3.5 text-black" />}
              onClick={() => setIsCalibrationOpen(true)}
            >
              CALIBRATION
            </Button>
          </div>
        </div>
      </header>

      {/* ========================================================================= */}
      {/* 2. EXECUTIVE KPI ROW */}
      {/* ========================================================================= */}
      <section className="bg-[#0B0F17] border-b border-[#232B38] px-4 lg:px-8 py-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 lg:gap-5">
          {/* KPI 1: Token Optimization Ratio */}
          <div className="p-3.5 rounded-lg bg-[#0E121A] border border-[#232B38] shadow-[0_4px_20px_rgba(0,0,0,0.3)]">
            <div className="flex items-center justify-between text-[#8B949E] text-xs font-mono mb-1">
              <span className="flex items-center gap-1.5">
                <TrendingDown className="w-3.5 h-3.5 text-[#00E676]" />
                TOKEN OPTIMIZATION
              </span>
              <span className="text-[#00E676] text-[11px] font-semibold">≥ 40% GUARANTEED</span>
            </div>
            <div className="flex items-baseline gap-2">
              <Odometer
                value={
                  optimizationResult
                    ? parseFloat(optimizationResult.token_economics.real_world_token_reduction_pct)
                    : 99.2
                }
                suffix="%"
                decimals={1}
                className="text-xl lg:text-2xl font-bold text-[#F3E5AB]"
              />
              <span className="text-xs text-[#8B949E] font-mono">REDUCTION</span>
            </div>
            <p className="text-[11px] text-[#8B949E] mt-1">
              {totalTokensSaved.toLocaleString()} raw archive tokens compressed to{' '}
              {optimizationResult?.token_economics.optimized_input_tokens || 312} tokens.
            </p>
          </div>

          {/* KPI 2: Averted Cloud API Cost */}
          <div className="p-3.5 rounded-lg bg-[#0E121A] border border-[#D4AF37]/30 shadow-[0_4px_20px_rgba(212,175,55,0.08)]">
            <div className="flex items-center justify-between text-[#8B949E] text-xs font-mono mb-1">
              <span className="flex items-center gap-1.5">
                <DollarSign className="w-3.5 h-3.5 text-[#D4AF37]" />
                AVERTED CLOUD COST
              </span>
              <span className="text-[#D4AF37] text-[11px] font-semibold">ZERO TRANSMISSION</span>
            </div>
            <div className="flex items-baseline gap-2">
              <Odometer
                value={parseFloat(dollarsSavedGPT4)}
                prefix="$"
                decimals={4}
                className="text-xl lg:text-2xl font-bold text-[#D4AF37]"
              />
              <span className="text-xs text-[#8B949E] font-mono">AVERTED / QUERY</span>
            </div>
            <p className="text-[11px] text-[#8B949E] mt-1">
              Vs. Claude 3.5 (${dollarsSavedClaude}) & GPT-4o (${dollarsSavedGPT4}) raw prompt rates.
            </p>
          </div>

          {/* KPI 3: Document Vault Storage */}
          <div className="p-3.5 rounded-lg bg-[#0E121A] border border-[#232B38] shadow-[0_4px_20px_rgba(0,0,0,0.3)]">
            <div className="flex items-center justify-between text-[#8B949E] text-xs font-mono mb-1">
              <span className="flex items-center gap-1.5">
                <Database className="w-3.5 h-3.5 text-[#2979FF]" />
                SEALED VAULT ARCHIVE
              </span>
              <span className="text-[#8B949E] text-[11px]">FAST-EMBED INT8</span>
            </div>
            <div className="flex items-baseline gap-2">
              <Odometer
                value={status.knowledge_graph?.total_documents || 2962}
                decimals={0}
                className="text-xl lg:text-2xl font-bold text-[#E6EDF3]"
              />
              <span className="text-xs text-[#8B949E] font-mono">DOCUMENTS</span>
            </div>
            <p className="text-[11px] text-[#8B949E] mt-1">
              Dense vector 384d + BM25 sparse RRF index in Qdrant WAL.
            </p>
          </div>

          {/* KPI 4: Relational Knowledge Graph */}
          <div className="p-3.5 rounded-lg bg-[#0E121A] border border-[#232B38] shadow-[0_4px_20px_rgba(0,0,0,0.3)]">
            <div className="flex items-center justify-between text-[#8B949E] text-xs font-mono mb-1">
              <span className="flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-[#00E676]" />
                RELATIONAL GRAPH
              </span>
              <span className="text-[#00E676] text-[11px]">SQLITE WAL</span>
            </div>
            <div className="flex items-baseline gap-2">
              <Odometer
                value={status.knowledge_graph?.total_entities || 5503}
                decimals={0}
                className="text-xl lg:text-2xl font-bold text-[#F3E5AB]"
              />
              <span className="text-xs text-[#8B949E] font-mono">ENTITIES</span>
            </div>
            <p className="text-[11px] text-[#8B949E] mt-1">
              Cross-linked by {status.knowledge_graph?.total_relations || 7968} relational edges.
            </p>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 3. MAIN WORKSPACE: TRI-PANE LAYOUT */}
      {/* ========================================================================= */}
      <main className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-px bg-[#232B38] overflow-hidden">
        {/* ===================================================================== */}
        {/* PANE 1: AUDITED CONVERSATION & GROUNDED AI (Cols 1-4) */}
        {/* ===================================================================== */}
        <section className="lg:col-span-4 bg-[#0E121A] flex flex-col h-full border-r border-[#232B38] overflow-hidden">
          {/* Pane Header */}
          <div className="px-4 py-3 border-b border-[#232B38] bg-white/[0.02] flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-[#D4AF37]" />
              <h2 className="font-serif text-xs font-semibold tracking-wider text-[#F3E5AB] uppercase">
                AUDITED GROUNDED INQUIRY
              </h2>
            </div>
            <Badge variant="sovereign" size="sm">
              {calibration.retrieval_mode.replace('_', ' ').toUpperCase()}
            </Badge>
          </div>

          {/* Quick Query Selector Pills */}
          <div className="p-3 border-b border-[#232B38] bg-[#07090D]/50 flex flex-wrap gap-1.5 shrink-0">
            {[
              'Existe alguma intimação jurídica com prazo iminente?',
              'Qual o valor e finalidade do TED do Dr. Carlos Eduardo?',
              'Qual o vencimento do IPTU da Sala 1401 Aspen Tower?',
            ].map((suggestedQuery, idx) => (
              <button
                key={idx}
                onClick={() => {
                  setQuery(suggestedQuery);
                  handleExecuteQuery(suggestedQuery);
                }}
                className="text-[11px] font-sans px-2.5 py-1 rounded bg-[#141A24] border border-[#232B38] text-[#8B949E] hover:text-[#F3E5AB] hover:border-[#D4AF37]/50 hover:bg-[#1A2230] transition-colors truncate max-w-full text-left"
              >
                {suggestedQuery}
              </button>
            ))}
          </div>

          {/* Conversation Feed */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {/* User Message */}
            <div className="p-3.5 rounded-lg bg-[#141A24] border border-[#232B38] text-xs leading-relaxed text-[#E6EDF3] max-w-[92%] ml-auto shadow-md">
              <p className="font-medium text-[#F3E5AB] mb-1 text-[11px] font-mono">SOLICITAÇÃO AUDITADA:</p>
              <p>{query}</p>
            </div>

            {/* Synthesized Vault Response */}
            <div className="p-4 rounded-lg bg-gradient-to-b from-[#141A24] to-[#0E121A] border border-[#D4AF37]/35 shadow-[0_4px_24px_rgba(0,0,0,0.5)]">
              <div className="flex items-center justify-between border-b border-[#232B38] pb-2 mb-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <div className="w-2 h-2 rounded-full bg-[#00E676] shadow-[0_0_6px_#00E676]" />
                  <span className="font-serif text-xs font-bold text-[#F3E5AB] tracking-wide">
                    RESPOSTA VERIFICADA EM COFRE
                  </span>
                  {optimizationResult?.user_clearance && (
                    <span className="font-mono text-[9px] uppercase px-1.5 py-0.5 rounded bg-[#D4AF37]/20 border border-[#D4AF37]/50 text-[#F3E5AB] flex items-center gap-1">
                      <Lock className="w-2.5 h-2.5" />
                      {optimizationResult.user_clearance}
                    </span>
                  )}
                  {optimizationResult?.critical_posture && (
                    <span className="font-mono text-[9px] uppercase px-1.5 py-0.5 rounded bg-[#2979FF]/15 border border-[#2979FF]/30 text-[#82B1FF]">
                      {optimizationResult.critical_posture.replace('_', ' ')}
                    </span>
                  )}
                </div>
                <span className="font-mono text-[10px] text-[#00E676] bg-[#00E676]/10 px-2 py-0.5 rounded border border-[#00E676]/30">
                  ZERO-HALLUCINATION GUARANTEE
                </span>
              </div>

              {/* Body text with markdown-like synthesis */}
              {isSearching ? (
                <div className="py-6 flex flex-col items-center justify-center gap-2 text-xs text-[#8B949E] font-mono">
                  <div className="w-5 h-5 border-2 border-[#D4AF37] border-t-transparent rounded-full animate-spin" />
                  <span>DEEP RETRIEVAL RRF SCANNING...</span>
                </div>
              ) : (
                <div className="text-xs leading-relaxed text-[#E6EDF3] space-y-2.5">
                  <p className="whitespace-pre-line">
                    {optimizationResult?.answer_synthesis ||
                      'Selecione uma consulta para auditar evidências arquivadas.'}
                  </p>

                  {/* Interactive Citation Pills */}
                  {optimizationResult?.citations && optimizationResult.citations.length > 0 && (
                    <div className="pt-3 border-t border-[#232B38]">
                      <p className="text-[10px] font-mono text-[#8B949E] uppercase tracking-wider mb-2">
                        EVIDÊNCIAS E FONTES CUSTODIADAS ({optimizationResult.citations.length}):
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {optimizationResult.citations.map((c) => (
                          <CitationPill
                            key={c.citation_index}
                            index={c.citation_index}
                            title={c.title}
                            heading={c.heading}
                            confidence={c.rrf_score}
                            page={c.page}
                            active={selectedCitationIndex === c.citation_index}
                            onClick={() => {
                              setSelectedCitationIndex(c.citation_index);
                              // Sync to active document
                              const matchDoc = DEMO_DOCUMENTS.find((d) =>
                                c.title.toLowerCase().includes(d.title.slice(0, 15).toLowerCase())
                              );
                              if (matchDoc) {
                                setActiveDocId(matchDoc.id);
                                if (c.bbox) {
                                  setSelectedBboxLabel(c.heading || c.title);
                                }
                              }
                            }}
                          />
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Multimodal Visual Plates (CLIP ViT-B-32) */}
                  {optimizationResult?.visual_plates && optimizationResult.visual_plates.length > 0 && (
                    <div className="pt-3 border-t border-[#232B38]">
                      <div className="flex items-center gap-1.5 mb-2">
                        <ImageIcon className="w-3.5 h-3.5 text-[#00E676]" />
                        <p className="text-[10px] font-mono text-[#8B949E] uppercase tracking-wider">
                          PLACAS VISUAIS CUSTODIADAS (CLIP ViT-B-32):
                        </p>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        {optimizationResult.visual_plates.map((plate) => (
                          <div
                            key={plate.plate_id}
                            className="p-2.5 rounded-lg bg-[#07090D] border border-[#232B38] hover:border-[#D4AF37]/50 transition-colors"
                          >
                            <div className="flex items-center justify-between text-[10px] font-mono mb-1">
                              <span className="text-[#F3E5AB] font-semibold truncate">{plate.title}</span>
                              <span className="text-[#00E676]">{(plate.similarity * 100).toFixed(0)}% sim</span>
                            </div>
                            {plate.description && (
                              <p className="text-[10px] text-[#8B949E] line-clamp-2">{plate.description}</p>
                            )}
                            <div className="mt-1.5 text-[9px] font-mono text-[#8B949E]/70 flex items-center justify-between">
                              <span>ID: {plate.plate_id}</span>
                              <span className="text-[#D4AF37]">Multimodal Proof</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Cross-Link to Knowledge Graph Dossier */}
                  <div className="pt-2">
                    <button
                      onClick={() => handleOpenDossier('Alpha Holdings Participações S.A.')}
                      className="text-[11px] font-mono text-[#D4AF37] hover:text-[#F3E5AB] flex items-center gap-1.5 transition-colors underline decoration-[#D4AF37]/50"
                    >
                      <Network className="w-3.5 h-3.5" />
                      <span>Abrir Dossiê Relacional: Alpha Holdings Participações S.A. &rarr;</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Search Input Bar */}
          <div className="p-3 border-t border-[#232B38] bg-[#0E121A] shrink-0">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleExecuteQuery(query);
              }}
              className="flex gap-2"
            >
              <div className="relative flex-1">
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Consulte o acervo confidencial..."
                  className="w-full pl-9 pr-3 py-2 bg-[#141A24] border border-[#232B38] rounded-md text-xs text-[#E6EDF3] placeholder-[#8B949E] focus:outline-none focus:border-[#D4AF37] focus:ring-1 focus:ring-[#D4AF37]"
                />
                <Search className="w-4 h-4 text-[#8B949E] absolute left-2.5 top-2.5" />
              </div>
              <Button type="submit" variant="gold" size="md" loading={isSearching}>
                Consultar
              </Button>
            </form>
          </div>
        </section>

        {/* ===================================================================== */}
        {/* PANE 2: HIGH-DPI DOCUMENT VIEWER & BOUNDING BOXES (Cols 5-8) */}
        {/* ===================================================================== */}
        <section className="lg:col-span-5 bg-[#07090D] flex flex-col h-full overflow-hidden">
          {/* Document Header & Tabs */}
          <div className="px-4 py-3 border-b border-[#232B38] bg-[#0E121A] flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-[#2979FF]" />
              <h2 className="font-serif text-xs font-semibold tracking-wider text-[#F3E5AB] uppercase truncate max-w-[200px] sm:max-w-xs">
                EVIDENCE VIEWER // DOC #{activeDoc.id}
              </h2>
            </div>
            {activeDoc.fatal_deadline && (
              <Badge variant="danger" size="sm">
                PRAZO FATAL: {activeDoc.fatal_deadline.toUpperCase()}
              </Badge>
            )}
          </div>

          {/* Document Selector Pills */}
          <div className="px-4 py-2 bg-[#0E121A]/70 border-b border-[#232B38] flex items-center gap-2 overflow-x-auto shrink-0">
            {DEMO_DOCUMENTS.map((doc) => (
              <button
                key={doc.id}
                onClick={() => {
                  setActiveDocId(doc.id);
                  setSelectedBboxLabel(null);
                }}
                className={`px-3 py-1 rounded text-xs font-mono transition-colors whitespace-nowrap ${
                  activeDocId === doc.id
                    ? 'bg-[#D4AF37] text-black font-semibold shadow-sm'
                    : 'bg-[#141A24] text-[#8B949E] hover:text-[#E6EDF3] border border-[#232B38]'
                }`}
              >
                Doc #{doc.id}: {doc.document_type}
              </button>
            ))}
          </div>

          {/* Document Canvas Rendering */}
          <div className="flex-1 overflow-y-auto p-4 lg:p-6 flex justify-center bg-[#06080B]">
            <div className="paper-page relative">
              {/* Document Meta Stamp */}
              <div className="absolute top-4 right-4 text-[10px] font-mono text-gray-500 border border-gray-300 px-2 py-0.5 rounded uppercase">
                COFRE SOBERANO #00{activeDoc.id} // VERIFICADO
              </div>

              {/* Rendered Document Body */}
              <div className="space-y-4 font-serif text-gray-900 leading-relaxed text-xs sm:text-sm">
                <div className="text-center pb-3 border-b border-gray-300">
                  <h3 className="font-bold text-sm sm:text-base uppercase tracking-wider text-gray-900">
                    {activeDoc.correspondent}
                  </h3>
                  <p className="text-xs text-gray-600 mt-0.5">{activeDoc.title}</p>
                  <p className="text-[11px] text-gray-500 font-mono mt-1">Data: {activeDoc.created_date}</p>
                </div>

                <div className="whitespace-pre-line text-justify pt-2">
                  {activeDoc.id === 103 ? (
                    <div>
                      <p className="text-right font-bold mb-3">Processo: 0041289-55.2026.8.16.0001</p>
                      <p><strong>EXEQUENTE:</strong> Fazenda Pública Nacional</p>
                      <p>
                        <strong>EXECUTADO:</strong>{' '}
                        <span
                          className={`bbox-highlight ${selectedBboxLabel?.toLowerCase().includes('alpha') ? 'bbox-active' : ''}`}
                          onClick={() => handleOpenDossier('Alpha Holdings Participações S.A.')}
                          title="Clique para inspecionar dossiê"
                        >
                          ALPHA HOLDINGS PARTICIPAÇÕES S.A.
                        </span>{' '}
                        (CNPJ 12.345.678/0001-90)
                      </p>
                      <br />
                      <p>
                        MANDADO DE INTIMAÇÃO E CITAÇÃO ELETRÔNICA: Fica o executado intimado para, no prazo peremptório de{' '}
                        <span
                          className={`bbox-critical ${selectedBboxLabel?.toLowerCase().includes('prazo') || selectedBboxLabel?.toLowerCase().includes('5 dias') ? 'bbox-active' : ''}`}
                          title="Alerta Crítico: Prazo Fatal"
                        >
                          <strong>5 (cinco) dias úteis</strong>
                        </span>
                        , comprovar a quitação integral do débito fiscal consolidado no montante de{' '}
                        <span
                          className={`bbox-highlight ${selectedBboxLabel?.toLowerCase().includes('84.500') ? 'bbox-active' : ''}`}
                        >
                          <strong>R$ 84.500,00</strong>
                        </span>
                        , sob pena de imediata emissão de ordem de penhora online de ativos financeiros via sistema{' '}
                        <span
                          className={`bbox-critical ${selectedBboxLabel?.toLowerCase().includes('sisbajud') ? 'bbox-active' : ''}`}
                          title="Constrição SISBAJUD"
                        >
                          <strong>SISBAJUD</strong>
                        </span>{' '}
                        e indisponibilidade de bens dos administradores.
                      </p>
                    </div>
                  ) : activeDoc.id === 102 ? (
                    <div>
                      <p className="text-right font-bold mb-3 font-mono text-xs text-gray-500">Autenticação: 8F29.C4A1.99E2.B501</p>
                      <p><strong>LIQUIDAÇÃO:</strong> 15/09/2026 - 14:32:10 (TED Bancária)</p>
                      <p>
                        <strong>REMETENTE:</strong>{' '}
                        <span
                          className={`bbox-highlight ${selectedBboxLabel?.toLowerCase().includes('carlos') ? 'bbox-active' : ''}`}
                          onClick={() => handleOpenDossier('Dr. Carlos Eduardo de Mendonça')}
                          title="Clique para inspecionar dossiê"
                        >
                          Dr. Carlos Eduardo de Mendonça
                        </span>{' '}
                        (CPF ***.482.919-**)
                      </p>
                      <p>
                        <strong>FAVORECIDO:</strong>{' '}
                        <span
                          className={`bbox-highlight ${selectedBboxLabel?.toLowerCase().includes('alpha') ? 'bbox-active' : ''}`}
                          onClick={() => handleOpenDossier('Alpha Holdings Participações S.A.')}
                          title="Clique para inspecionar dossiê"
                        >
                          Alpha Holdings Participações S.A.
                        </span>{' '}
                        (CNPJ 12.345.678/0001-90)
                      </p>
                      <br />
                      <p>
                        <strong>FINALIDADE:</strong>{' '}
                        <span
                          className={`bbox-highlight ${selectedBboxLabel?.toLowerCase().includes('aporte') || selectedBboxLabel?.toLowerCase().includes('250.000') ? 'bbox-active' : ''}`}
                        >
                          Aporte de Capital Social - Exercício 2026 (Cláusula Quarta Acordo Acionistas)
                        </span>
                      </p>
                      <p className="mt-2 text-base">
                        <strong>VALOR TOTAL:</strong>{' '}
                        <span
                          className={`bbox-highlight font-bold ${selectedBboxLabel?.toLowerCase().includes('250.000') ? 'bbox-active' : ''}`}
                        >
                          R$ 250.000,00
                        </span>
                      </p>
                    </div>
                  ) : activeDoc.id === 101 ? (
                    <div>
                      <p className="text-center font-bold mb-2">INSTRUMENTO PARTICULAR DE ACORDO DE ACIONISTAS</p>
                      <p className="text-center text-xs text-gray-600 mb-4">ALPHA HOLDINGS PARTICIPAÇÕES S.A.</p>
                      <p>
                        <strong>CLÁUSULA QUARTA - DOS APORTES E EXPANSÃO PATRIMONIAL</strong>
                      </p>
                      <p className="mt-2">
                        Parágrafo Primeiro: Fica estabelecido que o sócio fundador{' '}
                        <span
                          className={`bbox-highlight ${selectedBboxLabel?.toLowerCase().includes('carlos') ? 'bbox-active' : ''}`}
                          onClick={() => handleOpenDossier('Dr. Carlos Eduardo de Mendonça')}
                          title="Clique para inspecionar dossiê"
                        >
                          Dr. Carlos Eduardo de Mendonça
                        </span>{' '}
                        subscreverá{' '}
                        <span
                          className={`bbox-highlight ${selectedBboxLabel?.toLowerCase().includes('aporte') || selectedBboxLabel?.toLowerCase().includes('cláusula') ? 'bbox-active' : ''}`}
                        >
                          <strong>aporte suplementar no valor de até R$ 250.000,00</strong> (duzentos e cinquenta mil reais)
                        </span>{' '}
                        no segundo semestre do exercício social de 2026.
                      </p>
                      <p className="mt-2">
                        Parágrafo Segundo: Os recursos serão integralmente destinados ao pagamento de haveres fiscais e regularização fundiária dos imóveis operacionais do grupo.
                      </p>
                    </div>
                  ) : activeDoc.id === 104 ? (
                    <div>
                      <p className="text-right font-bold mb-2 text-xs font-mono">DAM IPTU 2026 // Inscrição 44.120.890.014-1</p>
                      <p>
                        <strong>CONTRIBUINTE:</strong>{' '}
                        <span
                          className={`bbox-highlight ${selectedBboxLabel?.toLowerCase().includes('alpha') ? 'bbox-active' : ''}`}
                          onClick={() => handleOpenDossier('Alpha Holdings Participações S.A.')}
                          title="Clique para inspecionar dossiê"
                        >
                          Alpha Holdings Participações S.A.
                        </span>
                      </p>
                      <p><strong>IMÓVEL:</strong> Av. Cândido de Abreu, 1400 - Conjunto 1401 - Centro Cívico (Aspen Tower)</p>
                      <br />
                      <p>
                        <strong>VENCIMENTO:</strong>{' '}
                        <span
                          className={`bbox-critical ${selectedBboxLabel?.toLowerCase().includes('vencimento') || selectedBboxLabel?.toLowerCase().includes('21/09') ? 'bbox-active' : ''}`}
                        >
                          <strong>21/09/2026 (Parcela Única c/ Desconto - Prazo: 2 dias)</strong>
                        </span>
                      </p>
                      <p className="mt-2 text-base">
                        <strong>VALOR TOTAL:</strong>{' '}
                        <span
                          className={`bbox-highlight font-bold ${selectedBboxLabel?.toLowerCase().includes('7.840') ? 'bbox-active' : ''}`}
                        >
                          R$ 7.840,50
                        </span>
                      </p>
                    </div>
                  ) : (
                    <p>{activeDoc.content}</p>
                  )}
                </div>

                {/* Bounding Box Info Banner */}
                {selectedBboxLabel && (
                  <div className="mt-6 p-3 rounded bg-amber-50 border border-amber-300 text-amber-900 text-xs font-sans">
                    <strong>Evidência Destacada:</strong> {selectedBboxLabel}
                  </div>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* ===================================================================== */}
        {/* PANE 3: KNOWLEDGE GRAPH & ACTIVE ALERTS (Cols 9-12) */}
        {/* ===================================================================== */}
        <section className="lg:col-span-3 bg-[#0E121A] flex flex-col h-full border-l border-[#232B38] overflow-hidden">
          {/* Pane Header */}
          <div className="px-4 py-3 border-b border-[#232B38] bg-white/[0.02] flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <Network className="w-4 h-4 text-[#00E676]" />
              <h2 className="font-serif text-xs font-semibold tracking-wider text-[#F3E5AB] uppercase">
                GRAPH & ACTIVE ALERTS
              </h2>
            </div>
            <span className="text-[11px] font-mono text-[#00E676]">WAL SYNC: 10ms</span>
          </div>

          {/* Interactive SVG Knowledge Graph Simulation */}
          <div className="h-56 bg-gradient-to-b from-[#141A24] to-[#0A0D12] border-b border-[#232B38] relative flex items-center justify-center p-2">
            <div className="absolute top-2 left-2 text-[10px] font-mono text-[#8B949E] uppercase">
              Grafo de Vínculos Societários
            </div>

            <svg width="100%" height="100%" viewBox="0 0 340 180" className="overflow-visible">
              {/* Edges */}
              <line x1="60" y1="90" x2="170" y2="90" stroke="rgba(212, 175, 55, 0.4)" strokeWidth="2" />
              <line x1="170" y1="90" x2="270" y2="45" stroke="rgba(255, 82, 82, 0.6)" strokeWidth="2" />
              <line x1="170" y1="90" x2="270" y2="135" stroke="rgba(255, 167, 38, 0.6)" strokeWidth="2" />

              {/* Node 1: Dr. Carlos Eduardo */}
              <g
                className="cursor-pointer group"
                onClick={() => handleOpenDossier('Dr. Carlos Eduardo de Mendonça')}
              >
                <circle
                  cx="60"
                  cy="90"
                  r="18"
                  fill="#141A24"
                  stroke="#D4AF37"
                  strokeWidth="2"
                  className="transition-transform group-hover:scale-110"
                />
                <text x="60" y="120" fill="#E6EDF3" fontSize="9" textAnchor="middle" fontFamily="Inter">
                  Dr. Carlos
                </text>
              </g>

              {/* Node 2: Alpha Holdings (Root) */}
              <g
                className="cursor-pointer group"
                onClick={() => handleOpenDossier('Alpha Holdings Participações S.A.')}
              >
                <circle
                  cx="170"
                  cy="90"
                  r="24"
                  fill="#1A2230"
                  stroke="#F3E5AB"
                  strokeWidth="2.5"
                  className="transition-transform group-hover:scale-110"
                />
                <text
                  x="170"
                  y="126"
                  fill="#F3E5AB"
                  fontSize="10"
                  fontWeight="bold"
                  textAnchor="middle"
                  fontFamily="Inter"
                >
                  Alpha Holdings
                </text>
              </g>

              {/* Node 3: TJPR SISBAJUD */}
              <g
                className="cursor-pointer group"
                onClick={() => {
                  setActiveDocId(103);
                  setSelectedBboxLabel('Mandado TJPR SISBAJUD');
                }}
              >
                <circle
                  cx="270"
                  cy="45"
                  r="16"
                  fill="#141A24"
                  stroke="#FF5252"
                  strokeWidth="2"
                  className="transition-transform group-hover:scale-110"
                />
                <text x="270" y="72" fill="#FF5252" fontSize="9" textAnchor="middle" fontFamily="Inter">
                  TJPR (R$ 84.5k)
                </text>
              </g>

              {/* Node 4: IPTU Sala 1401 */}
              <g
                className="cursor-pointer group"
                onClick={() => {
                  setActiveDocId(104);
                  setSelectedBboxLabel('IPTU Sala 1401');
                }}
              >
                <circle
                  cx="270"
                  cy="135"
                  r="16"
                  fill="#141A24"
                  stroke="#FFA726"
                  strokeWidth="2"
                  className="transition-transform group-hover:scale-110"
                />
                <text x="270" y="162" fill="#FFA726" fontSize="9" textAnchor="middle" fontFamily="Inter">
                  IPTU (Vence 2d)
                </text>
              </g>
            </svg>
          </div>

          {/* Action Alerts Feed */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            <p className="text-[10px] font-mono text-[#8B949E] uppercase tracking-wider mb-1">
              ALERTAS ATIVOS DE RISCO E CONFORMIDADE:
            </p>

            {alerts.map((alert) => (
              <div
                key={alert.id}
                onClick={() => {
                  if (alert.sourceDocId) {
                    setActiveDocId(alert.sourceDocId);
                  }
                }}
                className={`p-3 rounded-lg border-l-4 cursor-pointer transition-all hover:translate-x-1 ${
                  alert.type === 'critical'
                    ? 'border-l-[#FF5252] bg-gradient-to-r from-[#FF5252]/10 to-[#141A24] border border-[#FF5252]/30'
                    : 'border-l-[#FFA726] bg-gradient-to-r from-[#FFA726]/10 to-[#141A24] border border-[#FFA726]/30'
                }`}
              >
                <div className="flex items-center justify-between text-xs font-semibold mb-1">
                  <span className={alert.type === 'critical' ? 'text-[#FF5252]' : 'text-[#FFA726]'}>
                    {alert.title}
                  </span>
                  {alert.deadline && (
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-black/40 text-[#E6EDF3]">
                      {alert.deadline}
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-[#8B949E] leading-relaxed">{alert.description}</p>
              </div>
            ))}
          </div>
        </section>
      </main>

      {/* ========================================================================= */}
      {/* 4. BOTTOM STATUS BAR */}
      {/* ========================================================================= */}
      <footer className="bg-[#0E121A] border-t border-[#232B38] px-4 lg:px-8 py-2 text-[11px] font-mono flex flex-wrap items-center justify-between gap-3 text-[#8B949E]">
        <div className="flex items-center flex-wrap gap-4">
          <span>
            MODO:{' '}
            <strong className="text-[#F3E5AB]">SOBERANO AIR-GAPPED</strong>
          </span>
          <span>
            REDUÇÃO DE TOKENS:{' '}
            <strong className="text-[#00E676]">
              {optimizationResult?.token_economics.real_world_token_reduction_pct || '99.2%'}
            </strong>{' '}
            (CONTRATO: ≥ 40%)
          </span>
          <span>
            GASTO EM NUVEM:{' '}
            <strong className="text-[#00E676]">$0.00 / R$ 0,00</strong>
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span>CPU: {status.cpu_temp_c || 44.5}°C</span>
          <span>RAM: {status.memory_usage_mb || 612}MB</span>
          <span className="text-[#F3E5AB]">AEGIS HARDWARE APPLIANCE v2.4</span>
        </div>
      </footer>

      {/* ========================================================================= */}
      {/* 5. EXECUTIVE CALIBRATION DRAWER */}
      {/* ========================================================================= */}
      <Drawer
        isOpen={isCalibrationOpen}
        onClose={() => setIsCalibrationOpen(false)}
        title="EXECUTIVE RETRIEVAL CALIBRATION"
        subtitle="5 High-Signal Executive Knobs, Mandatory Access Control (MAC), and precision gates"
        icon={<Sliders className="w-5 h-5 text-[#D4AF37]" />}
        width="lg"
      >
        <div className="space-y-6 text-xs text-[#E6EDF3]">
          {/* ================================================================= */}
          {/* 1. DIAL 1: ANALYTICAL DEPTH (Cognitive Strata / ADR-38) */}
          {/* ================================================================= */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="font-mono text-[#D4AF37] uppercase tracking-wider font-semibold flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5" />
                <span>DIAL 1: HORIZONTE ANALÍTICO (DEPTH)</span>
              </label>
              <span className="font-mono text-[10px] text-[#8B949E]">COGNITIVE STRATA</span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                {
                  id: 'flash_needle' as AnalyticalDepth,
                  label: 'Flash Needle',
                  badge: 'L1: <20ms',
                  desc: 'Micro-factual lookup direto em HNSW int8',
                },
                {
                  id: 'relational_audit' as AnalyticalDepth,
                  label: 'Relational Audit',
                  badge: 'L2: Meso-Graph',
                  desc: 'Varredura de entidades e 2-hop no SQLite WAL',
                },
                {
                  id: 'deep_synthesis' as AnalyticalDepth,
                  label: 'Deep Synthesis',
                  badge: 'L3: RAPTOR',
                  desc: 'Síntese multi-cluster e raciocínio exaustivo',
                },
              ].map((d) => (
                <button
                  key={d.id}
                  onClick={() => setCalibration((prev) => ({ ...prev, analytical_depth: d.id }))}
                  className={`p-2.5 rounded-lg border text-left transition-all ${
                    calibration.analytical_depth === d.id
                      ? 'bg-[#D4AF37]/20 border-[#D4AF37] text-[#F3E5AB] shadow-sm'
                      : 'bg-[#141A24] border-[#232B38] text-[#8B949E] hover:text-[#E6EDF3] hover:border-[#D4AF37]/40'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <p className="font-semibold text-xs">{d.label}</p>
                    <span className="text-[9px] font-mono px-1 py-0.5 rounded bg-[#07090D] border border-[#232B38] text-[#D4AF37]">
                      {d.badge}
                    </span>
                  </div>
                  <p className="text-[10px] opacity-80 line-clamp-2">{d.desc}</p>
                </button>
              ))}
            </div>
          </div>

          {/* ================================================================= */}
          {/* 2. DIAL 2: EVIDENCE GROUNDING */}
          {/* ================================================================= */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="font-mono text-[#D4AF37] uppercase tracking-wider font-semibold flex items-center gap-1.5">
                <BookOpen className="w-3.5 h-3.5" />
                <span>DIAL 2: ANCORAGEM DE EVIDÊNCIA</span>
              </label>
              <span className="font-mono text-[10px] text-[#8B949E]">CITATION GROUNDING</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {[
                {
                  id: 'verbatim_footnotes' as EvidenceGrounding,
                  label: 'Verbatim Footnotes',
                  desc: 'Citações textuais estritas com offsets de página e bounding boxes',
                },
                {
                  id: 'executive_abstract' as EvidenceGrounding,
                  label: 'Executive Abstract',
                  desc: 'Briefing executivo sintetizado e consolidado em prosa executiva',
                },
              ].map((g) => (
                <button
                  key={g.id}
                  onClick={() => setCalibration((prev) => ({ ...prev, evidence_grounding: g.id }))}
                  className={`p-2.5 rounded-lg border text-left transition-all ${
                    calibration.evidence_grounding === g.id
                      ? 'bg-[#00E676]/15 border-[#00E676] text-[#00E676] shadow-sm'
                      : 'bg-[#141A24] border-[#232B38] text-[#8B949E] hover:text-[#E6EDF3] hover:border-[#00E676]/40'
                  }`}
                >
                  <p className="font-semibold text-xs mb-1">{g.label}</p>
                  <p className="text-[10px] opacity-80">{g.desc}</p>
                </button>
              ))}
            </div>
          </div>

          {/* ================================================================= */}
          {/* 3. DIAL 3: MULTIMODAL VISUAL PLATES (CLIP ViT-B-32) */}
          {/* ================================================================= */}
          <div className="p-3 rounded-lg bg-[#141A24] border border-[#232B38] flex items-center justify-between">
            <div className="flex items-start gap-2.5">
              <ImageIcon className="w-4 h-4 text-[#D4AF37] mt-0.5" />
              <div>
                <div className="flex items-center gap-2">
                  <p className="font-semibold text-[#E6EDF3]">DIAL 3: Placas Visuais Multimodais</p>
                  <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-[#D4AF37]/15 border border-[#D4AF37]/40 text-[#F3E5AB]">
                    CLIP ViT-B-32
                  </span>
                </div>
                <p className="text-[11px] text-[#8B949E] mt-0.5">
                  Extrai diagramas técnicos, carimbos jurídicos autenticados e fluxogramas visuais.
                </p>
              </div>
            </div>
            <input
              type="checkbox"
              checked={calibration.include_visual_plates}
              onChange={(e) =>
                setCalibration((prev) => ({ ...prev, include_visual_plates: e.target.checked }))
              }
              className="w-4 h-4 accent-[#D4AF37] cursor-pointer rounded"
            />
          </div>

          {/* ================================================================= */}
          {/* 4. DIAL 4: SECURITY CLEARANCE (Mandatory Access Control / MAC) */}
          {/* ================================================================= */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="font-mono text-[#D4AF37] uppercase tracking-wider font-semibold flex items-center gap-1.5">
                <Lock className="w-3.5 h-3.5 text-[#FF5252]" />
                <span>DIAL 4: CREDENCIAL DE SEGURANÇA (MAC)</span>
              </label>
              <span className="font-mono text-[9px] text-[#00E676] bg-[#00E676]/10 px-1.5 py-0.5 rounded border border-[#00E676]/30">
                PRE-FILTER GUARANTEE
              </span>
            </div>
            <div className="grid grid-cols-4 gap-2">
              {[
                { id: 'public' as ClearanceLevelString, level: 'L0', name: 'PUBLIC', color: 'border-[#8B949E]' },
                { id: 'internal' as ClearanceLevelString, level: 'L1', name: 'INTERNAL', color: 'border-[#2979FF]' },
                { id: 'confidential' as ClearanceLevelString, level: 'L2', name: 'CONFID.', color: 'border-[#FF9100]' },
                { id: 'restricted' as ClearanceLevelString, level: 'L3', name: 'RESTRICT.', color: 'border-[#FF1744]' },
              ].map((c) => (
                <button
                  key={c.id}
                  onClick={() => setCalibration((prev) => ({ ...prev, user_clearance: c.id }))}
                  className={`p-2 rounded-lg border text-center transition-all ${
                    calibration.user_clearance === c.id
                      ? `bg-[#07090D] ${c.color} text-[#F3E5AB] ring-1 ring-offset-1 ring-offset-[#0E121A] ring-[#D4AF37]`
                      : 'bg-[#141A24] border-[#232B38] text-[#8B949E] hover:text-[#E6EDF3]'
                  }`}
                >
                  <p className="font-mono text-[10px] text-[#8B949E]">{c.level}</p>
                  <p className="font-semibold text-[11px] mt-0.5">{c.name}</p>
                </button>
              ))}
            </div>
            <p className="text-[10px] text-[#8B949E] font-mono">
              Zero Post-Filtering: Qdrant payload e SQLite WAL filtram no banco antes da memória.
            </p>
          </div>

          {/* ================================================================= */}
          {/* 5. DIAL 5: CRITICAL POSTURE */}
          {/* ================================================================= */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="font-mono text-[#D4AF37] uppercase tracking-wider font-semibold flex items-center gap-1.5">
                <Eye className="w-3.5 h-3.5" />
                <span>DIAL 5: POSTURA CRÍTICA (COGNITIVE STANCE)</span>
              </label>
              <span className="font-mono text-[10px] text-[#8B949E]">ANALYSIS TONE</span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                {
                  id: 'neutral' as CriticalPosture,
                  label: 'Neutro / Assessor',
                  desc: 'Avaliação balanceada e estritamente factual',
                },
                {
                  id: 'compliance_auditor' as CriticalPosture,
                  label: 'Auditor de Risco',
                  desc: 'Foco implacável em passivos e conformidade legal',
                },
                {
                  id: 'scholarly' as CriticalPosture,
                  label: 'Doutrinário / Histórico',
                  desc: 'Linhagem teórica e jurisprudência comparada',
                },
              ].map((p) => (
                <button
                  key={p.id}
                  onClick={() => setCalibration((prev) => ({ ...prev, critical_posture: p.id }))}
                  className={`p-2.5 rounded-lg border text-left transition-all ${
                    calibration.critical_posture === p.id
                      ? 'bg-[#2979FF]/15 border-[#2979FF] text-[#82B1FF] shadow-sm'
                      : 'bg-[#141A24] border-[#232B38] text-[#8B949E] hover:text-[#E6EDF3] hover:border-[#2979FF]/40'
                  }`}
                >
                  <p className="font-semibold text-xs mb-1">{p.label}</p>
                  <p className="text-[10px] opacity-80 line-clamp-2">{p.desc}</p>
                </button>
              ))}
            </div>
          </div>

          <div className="border-t border-[#232B38] pt-4 space-y-4">
            <p className="font-mono text-[11px] text-[#8B949E] uppercase tracking-wider font-semibold">
              CALIBRAÇÃO DE RECUPERAÇÃO HÍBRIDA & GRAFO
            </p>

            {/* Preset Retrieval Modes */}
            <div className="space-y-2">
              <label className="font-mono text-[10px] text-[#8B949E] uppercase tracking-wider block">
                MODO DE INDEXAÇÃO DENSE/SPARSE
              </label>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { id: 'high_precision' as RetrievalMode, label: 'High Precision', desc: 'Factual needle, 2-3 chunks' },
                  { id: 'legal_discovery' as RetrievalMode, label: 'Legal Discovery', desc: 'Recall amplo, 8-10 chunks' },
                  { id: 'exact_entity' as RetrievalMode, label: 'Exact Entity', desc: 'Boost léxico de CNPJ/datas' },
                ].map((m) => (
                  <button
                    key={m.id}
                    onClick={() => setCalibration((prev) => ({ ...prev, retrieval_mode: m.id }))}
                    className={`p-2 rounded-lg border text-left transition-all ${
                      calibration.retrieval_mode === m.id
                        ? 'bg-[#D4AF37]/20 border-[#D4AF37] text-[#F3E5AB] shadow-sm'
                        : 'bg-[#141A24] border-[#232B38] text-[#8B949E] hover:text-[#E6EDF3]'
                    }`}
                  >
                    <p className="font-semibold text-xs">{m.label}</p>
                    <p className="text-[9px] opacity-80 mt-0.5">{m.desc}</p>
                  </button>
                ))}
              </div>
            </div>

            {/* Max Chunks Slider */}
            <div className="space-y-1.5">
              <div className="flex justify-between font-mono">
                <span className="text-[#8B949E]">LIMITE DE PASSAGENS:</span>
                <span className="text-[#F3E5AB] font-bold">{calibration.max_chunks} passagens</span>
              </div>
              <input
                type="range"
                min="1"
                max="12"
                value={calibration.max_chunks}
                onChange={(e) =>
                  setCalibration((prev) => ({ ...prev, max_chunks: parseInt(e.target.value, 10) }))
                }
                className="w-full accent-[#D4AF37] cursor-pointer"
              />
            </div>

            {/* Confidence Floor Slider */}
            <div className="space-y-1.5">
              <div className="flex justify-between font-mono">
                <span className="text-[#8B949E]">CORTE DE CONFIANÇA (RRF):</span>
                <span className="text-[#00E676] font-bold">
                  {(calibration.confidence_floor * 100).toFixed(0)}% match
                </span>
              </div>
              <input
                type="range"
                min="0"
                max="90"
                value={calibration.confidence_floor * 100}
                onChange={(e) =>
                  setCalibration((prev) => ({
                    ...prev,
                    confidence_floor: parseFloat(e.target.value) / 100,
                  }))
                }
                className="w-full accent-[#00E676] cursor-pointer"
              />
            </div>

            {/* Relational Graph Dossier Toggle */}
            <div className="p-3 rounded-lg bg-[#141A24] border border-[#232B38] flex items-center justify-between">
              <div>
                <p className="font-semibold text-[#E6EDF3]">Acoplar Dossiê Relacional</p>
                <p className="text-[10px] text-[#8B949E]">
                  Injeta grafo de entidades vizinhas (2-hop) no contexto final.
                </p>
              </div>
              <input
                type="checkbox"
                checked={calibration.include_graph_dossier}
                onChange={(e) =>
                  setCalibration((prev) => ({ ...prev, include_graph_dossier: e.target.checked }))
                }
                className="w-4 h-4 accent-[#D4AF37] cursor-pointer rounded"
              />
            </div>
          </div>

          {/* Apply Calibration Button */}
          <Button
            variant="gold"
            size="lg"
            className="w-full mt-2"
            onClick={() => {
              setIsCalibrationOpen(false);
              handleExecuteQuery(query);
            }}
          >
            Aplicar Calibração Executiva & Auditar
          </Button>
        </div>
      </Drawer>

      {/* ========================================================================= */}
      {/* 6. RELATIONAL ENTITY DOSSIER MODAL */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isDossierOpen}
        onClose={() => setIsDossierOpen(false)}
        title={activeEntityName}
        subtitle="Cross-document intelligence dossier compiled from SQLite WAL knowledge graph"
        icon={<Network className="w-5 h-5" />}
        maxWidth="3xl"
      >
        {isLoadingDossier ? (
          <div className="py-12 flex flex-col items-center justify-center gap-3 text-xs text-[#8B949E] font-mono">
            <div className="w-6 h-6 border-2 border-[#D4AF37] border-t-transparent rounded-full animate-spin" />
            <span>TRAVERSING RELATIONAL EDGES IN WAL...</span>
          </div>
        ) : (
          <div className="space-y-6 text-xs text-[#E6EDF3]">
            {/* Dossier Summary KPIs */}
            <div className="grid grid-cols-3 gap-3">
              <div className="p-3 rounded-lg bg-[#141A24] border border-[#232B38]">
                <p className="text-[10px] font-mono text-[#8B949E]">DOCUMENTOS VINCULADOS</p>
                <p className="text-xl font-bold font-mono text-[#F3E5AB] mt-1">
                  {dossierData.total_documents}
                </p>
              </div>

              <div className="p-3 rounded-lg bg-[#141A24] border border-[#232B38]">
                <p className="text-[10px] font-mono text-[#8B949E]">VOLUME MONETÁRIO IDENTIFICADO</p>
                <p className="text-xl font-bold font-mono text-[#00E676] mt-1">
                  R$ {dossierData.total_monetary_amount.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                </p>
              </div>

              <div className="p-3 rounded-lg bg-[#141A24] border border-[#232B38]">
                <p className="text-[10px] font-mono text-[#8B949E]">RELAÇÕES CRUZADAS</p>
                <p className="text-xl font-bold font-mono text-[#2979FF] mt-1">
                  {dossierData.relations.length}
                </p>
              </div>
            </div>

            {/* Direct Relations */}
            <div>
              <h4 className="font-serif text-xs font-semibold text-[#F3E5AB] uppercase mb-2">
                RELAÇÕES SOCIETÁRIAS E JUDICIAIS
              </h4>
              <div className="space-y-2">
                {dossierData.relations.map((rel, idx) => (
                  <div
                    key={idx}
                    className="p-2.5 rounded bg-[#141A24] border border-[#232B38] flex items-center justify-between text-xs"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[#8B949E] text-[11px] uppercase">
                        [{rel.relation_type.replace(/_/g, ' ')}]
                      </span>
                      <span className="font-semibold text-[#E6EDF3]">{rel.target_name}</span>
                    </div>
                    <Badge variant="sovereign" size="sm">
                      {rel.target_type}
                    </Badge>
                  </div>
                ))}
              </div>
            </div>

            {/* Linked Documents in Vault */}
            <div>
              <h4 className="font-serif text-xs font-semibold text-[#F3E5AB] uppercase mb-2">
                ACERVO DOCUMENTAL RECONCILIADO ({dossierData.documents.length})
              </h4>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {dossierData.documents.map((doc) => (
                  <div
                    key={doc.id}
                    onClick={() => {
                      setActiveDocId(doc.id);
                      setIsDossierOpen(false);
                    }}
                    className="p-2.5 rounded bg-[#141A24] border border-[#232B38] hover:border-[#D4AF37]/50 hover:bg-[#1A2230] cursor-pointer flex items-center justify-between text-xs transition-colors"
                  >
                    <div>
                      <p className="font-medium text-[#E6EDF3]">
                        #{doc.id} — {doc.title}
                      </p>
                      <p className="text-[10px] text-[#8B949E] mt-0.5">
                        {doc.correspondent} // Data: {doc.created_date}
                      </p>
                    </div>
                    {doc.risk_level === 'critical' ? (
                      <Badge variant="danger" size="sm">
                        CRÍTICO
                      </Badge>
                    ) : (
                      <Badge variant="neutral" size="sm">
                        {doc.document_type}
                      </Badge>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* ========================================================================= */}
      {/* 7. LIVE SSE INGESTION DROPZONE MODAL */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isIngestModalOpen}
        onClose={() => setIsIngestModalOpen(false)}
        title="SOVEREIGN INGESTION PIPELINE"
        subtitle="5-stage cryptographic ingestion with real-time SSE event stream"
        icon={<UploadCloud className="w-5 h-5" />}
        maxWidth="3xl"
      >
        <div className="space-y-6">
          {/* Dropzone Area */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setIsDragging(false);
              handleFilesAdded(e.dataTransfer.files);
            }}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
              isDragging
                ? 'border-[#D4AF37] bg-[#D4AF37]/10'
                : 'border-[#232B38] bg-[#141A24]/60 hover:border-[#D4AF37]/60 hover:bg-[#141A24]'
            }`}
          >
            <input
              type="file"
              ref={fileInputRef}
              onChange={(e) => handleFilesAdded(e.target.files)}
              multiple
              className="hidden"
            />
            <UploadCloud className="w-10 h-10 text-[#D4AF37] mx-auto mb-3 animate-pulse" />
            <p className="text-sm font-semibold text-[#F3E5AB]">
              Arraste arquivos confidenciais ou clique para selecionar
            </p>
            <p className="text-xs text-[#8B949E] mt-1">
              Suporta PDF, DOCX, TIFF, TXT, EML. Processamento 100% local com aceleração ONNX int8.
            </p>
          </div>

          {/* Active Ingestion Pipeline Tasks */}
          {ingestionTasks.length > 0 && (
            <div className="space-y-4">
              <h4 className="font-serif text-xs font-semibold text-[#F3E5AB] uppercase">
                TAREFAS DE INGESTÃO EM ANDAMENTO ({ingestionTasks.length})
              </h4>

              {ingestionTasks.map((task) => (
                <div
                  key={task.id}
                  className="p-4 rounded-lg bg-[#141A24] border border-[#232B38] space-y-3"
                >
                  <div className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      <FileText className="w-4 h-4 text-[#D4AF37]" />
                      <span className="font-semibold text-[#E6EDF3]">{task.fileName}</span>
                      <span className="text-[10px] text-[#8B949E] font-mono">
                        ({(task.fileSize / 1024).toFixed(1)} KB)
                      </span>
                    </div>

                    {task.status === 'completed' ? (
                      <Badge variant="success" size="sm">
                        CONCLUÍDO & LACRADO
                      </Badge>
                    ) : (
                      <Badge variant="sovereign" dot size="sm">
                        ESTÁGIO {task.currentStage}/5
                      </Badge>
                    )}
                  </div>

                  {/* 5-Stage Indicators */}
                  <div className="grid grid-cols-5 gap-1 text-[10px] font-mono">
                    {([1, 2, 3, 4, 5] as IngestionStage[]).map((stg) => {
                      const isPast = task.currentStage > stg || task.status === 'completed';
                      const isCurrent = task.currentStage === stg && task.status === 'processing';
                      return (
                        <div
                          key={stg}
                          className={`p-1.5 rounded border text-center truncate ${
                            isPast
                              ? 'bg-[#00E676]/15 border-[#00E676]/40 text-[#00E676]'
                              : isCurrent
                              ? 'bg-[#D4AF37]/20 border-[#D4AF37] text-[#F3E5AB] font-bold shadow-sm'
                              : 'bg-[#0E121A] border-[#232B38] text-[#8B949E]'
                          }`}
                        >
                          {stg}. {INGESTION_STAGES[stg].name.split(' ')[0]}
                        </div>
                      );
                    })}
                  </div>

                  {/* Progress Bar */}
                  <ProgressBar
                    value={task.status === 'completed' ? 100 : (task.currentStage - 1) * 20 + task.stageProgress * 0.2}
                    variant={task.status === 'completed' ? 'emerald' : 'gold'}
                    label={INGESTION_STAGES[task.currentStage].name}
                    stageLabel={INGESTION_STAGES[task.currentStage].description}
                  />

                  {/* Live SSE Event Log Terminal */}
                  <div className="p-2.5 rounded bg-[#07090D] border border-[#232B38] font-mono text-[11px] text-[#8B949E] max-h-24 overflow-y-auto space-y-1">
                    {task.logs.map((log, lIdx) => (
                      <div key={lIdx} className="flex items-start gap-2">
                        <Terminal className="w-3 h-3 text-[#D4AF37] shrink-0 mt-0.5" />
                        <span className="text-[#E6EDF3]">{log}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
