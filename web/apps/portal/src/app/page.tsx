'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Search } from 'lucide-react';
import { Button, Drawer } from '@aegis/ui';
import { ApplianceStatus, DomainScope, RouterQueryResult, MonitoredSourceRecord } from '@/types';
import {
  checkHealth,
  executeRouterQuery,
  fetchMonitoredSources,
  addMonitoredSource,
  purgeMonitoredSource,
  DEMO_STATUS,
} from '@/lib/api';
import {
  SearchHeader,
  DomainFilterBar,
  PresetChips,
  RouteBanner,
  Prong1ResultCard,
  Prong2SynthesisCard,
  GraphDossierPanel,
  TableViewerDrawer,
  SourcesManagerModal,
} from '@/components';

export default function SovereignPortalPage() {
  const [status, setStatus] = useState<ApplianceStatus>(DEMO_STATUS);
  const [latency, setLatency] = useState<number>(0.8);
  const [query, setQuery] = useState<string>('ALM-20104');
  const [domain, setDomain] = useState<DomainScope>('all');
  const [routerMode, setRouterMode] = useState<'auto' | 'prong1' | 'prong2'>('auto');
  const [preferNeural, setPreferNeural] = useState<boolean>(false);
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [routerResult, setRouterResult] = useState<RouterQueryResult | null>(null);
  const [selectedCitationIndex, setSelectedCitationIndex] = useState<number>(1);

  // Modals & Drawers
  const [isSourcesOpen, setIsSourcesOpen] = useState<boolean>(false);
  const [isCalibrationOpen, setIsCalibrationOpen] = useState<boolean>(false);
  const [isTableOpen, setIsTableOpen] = useState<boolean>(false);
  const [tableData, setTableData] = useState<{ title: string; content: string }>({ title: '', content: '' });
  const [sources, setSources] = useState<MonitoredSourceRecord[]>([]);

  useEffect(() => {
    async function init() {
      const [h, s] = await Promise.all([checkHealth(), fetchMonitoredSources()]);
      setStatus(h);
      setSources(s);
      handleExecuteQuery('ALM-20104', 'all');
    }
    init();
  }, []);

  const handleExecuteQuery = useCallback(
    async (searchQuery: string, currentDomain = domain) => {
      const q = searchQuery.trim();
      if (!q) return;
      setIsSearching(true);
      const start = performance.now();
      try {
        const synthArg = routerMode === 'prong2' ? true : routerMode === 'prong1' ? false : undefined;
        const res = await executeRouterQuery({
          query: q,
          domain_filter: currentDomain,
          synthesize: synthArg,
          prefer_neural: preferNeural,
        });
        const elapsed = Math.round(performance.now() - start);
        setLatency(res.latency_ms ?? (elapsed > 0 ? elapsed : 0.8));
        setRouterResult(res);
      } catch (err) {
        console.error('Portal query failed:', err);
      } finally {
        setIsSearching(false);
      }
    },
    [domain, routerMode, preferNeural]
  );

  const handleInspectTable = (title: string, content: string) => {
    setTableData({ title, content });
    setIsTableOpen(true);
  };

  const isProng1 =
    routerMode === 'prong1' ||
    (routerMode === 'auto' &&
      (routerResult?.route_type === 'deterministic_direct' || !routerResult?.needs_synthesis));

  return (
    <div className="min-h-screen flex flex-col bg-[#07090D] text-[#E6EDF3]">
      <SearchHeader
        status={status}
        latency={latency}
        onOpenSources={() => setIsSourcesOpen(true)}
        onOpenCalibration={() => setIsCalibrationOpen(true)}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto p-4 lg:p-6 space-y-5">
        <section className="p-4 lg:p-6 rounded-xl bg-[#0E121A] border border-[#232B38] shadow-lg space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <DomainFilterBar
              activeDomain={domain}
              onSelectDomain={(d) => { setDomain(d); handleExecuteQuery(query, d); }}
            />
            <div className="flex items-center gap-2">
              {(['auto', 'prong1', 'prong2'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setRouterMode(m)}
                  className={`text-xs font-mono px-2.5 py-1 rounded transition-colors ${
                    routerMode === m ? 'bg-[#D4AF37] text-black font-bold' : 'bg-[#141A24] text-[#8B949E] hover:text-[#E6EDF3] border border-[#232B38]'
                  }`}
                >
                  {m === 'auto' ? '⚡ Auto Router' : m === 'prong1' ? 'Force Prong 1' : 'Force Prong 2'}
                </button>
              ))}
              <label className="flex items-center gap-1.5 text-xs font-mono text-[#82B1FF] cursor-pointer ml-2">
                <input type="checkbox" checked={preferNeural} onChange={(e) => setPreferNeural(e.target.checked)} className="accent-[#2979FF]" />
                <span className="hidden sm:inline">Local Neural (Ollama)</span>
              </label>
            </div>
          </div>

          <form onSubmit={(e) => { e.preventDefault(); handleExecuteQuery(query); }} className="flex gap-2">
            <div className="relative flex-1">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Insira um identificador exato (ALM-20104, ADR-40, DSP OPTMODULE) ou faça uma pergunta técnica..."
                className="w-full pl-9 pr-3 py-2.5 bg-[#141A24] border border-[#232B38] rounded-lg text-xs font-mono text-[#E6EDF3] placeholder-[#8B949E] focus:outline-none focus:border-[#D4AF37]"
              />
              <Search className="w-4 h-4 text-[#8B949E] absolute left-3 top-3" />
            </div>
            <Button type="submit" variant="gold" size="md" loading={isSearching}>Roteamento</Button>
          </form>

          <PresetChips onSelectPreset={(p) => { setQuery(p); handleExecuteQuery(p); }} />
        </section>

        {routerResult && (
          <RouteBanner
            routeType={routerResult.route_type || 'deterministic_direct'}
            latency={latency}
            isProng1={isProng1}
            confidenceScore={routerResult.confidence_score ?? 0.99}
            confidenceLevel={routerResult.confidence_level ?? 'HIGH_VERIFIED'}
            executionMode={routerResult.execution_mode}
            isMiss={routerResult.status === 'not_found' || routerResult.results?.length === 0}
          />
        )}

        <div className="space-y-4">
          {routerResult?.fast_summary && (
            <Prong2SynthesisCard
              summary={routerResult.fast_summary}
              latency={latency}
              confidenceScore={routerResult.confidence_score}
              confidenceLevel={routerResult.confidence_level}
              citations={routerResult.fast_summary.citations}
              selectedCitationIndex={selectedCitationIndex}
              onSelectCitation={(c) => setSelectedCitationIndex(c.citation_index)}
              onInspectTable={handleInspectTable}
            />
          )}

          {routerResult?.graph_dossier && (
            <GraphDossierPanel dossier={routerResult.graph_dossier} onSelectEntity={(e) => { setQuery(e); handleExecuteQuery(e); }} />
          )}

          {routerResult?.results && routerResult.results.length > 0 && (
            <div className="space-y-3">
              {routerResult.results.map((rec, idx) => (
                <Prong1ResultCard
                  key={rec.id ?? idx}
                  record={rec}
                  index={idx + 1}
                  confidenceScore={routerResult.confidence_score}
                  onOpenSource={() => handleInspectTable(rec.title, rec.content || '')}
                  onJumpCauses={() => handleInspectTable(`Causas: ${rec.title}`, rec.structured_sections?.['Possible Causes'] || '')}
                  onRenderDiagram={() => handleInspectTable(`Diagrama: ${rec.title}`, '### Extracted Signaling Diagram\n| Entity | Target | Signal |\n|---|---|---|\n| M3UA | SCTP | Bearer Drop |\n| SFP+ | Optical | Attenuation |')}
                  onInspectTable={handleInspectTable}
                />
              ))}
            </div>
          )}
        </div>
      </main>

      <TableViewerDrawer isOpen={isTableOpen} onClose={() => setIsTableOpen(false)} title={tableData.title} markdownContent={tableData.content} />

      <SourcesManagerModal
        isOpen={isSourcesOpen}
        onClose={() => setIsSourcesOpen(false)}
        sources={sources}
        onAddSource={async (p, d) => { await addMonitoredSource(p, d); setSources(await fetchMonitoredSources()); }}
        onPurgeSource={async (p) => { await purgeMonitoredSource(p); setSources(await fetchMonitoredSources()); }}
        onResyncSource={async (p, d) => { await addMonitoredSource(p, d); setSources(await fetchMonitoredSources()); }}
      />

      <Drawer isOpen={isCalibrationOpen} onClose={() => setIsCalibrationOpen(false)} title="EXECUTIVE CALIBRATION" subtitle="Mandatory Access Control (MAC)" width="md">
        <div className="space-y-4 text-xs font-mono text-[#E6EDF3]">
          <p className="text-[#D4AF37]">ADR-40 Bifurcated Router Active</p>
          <div className="p-3 rounded bg-[#141A24] border border-[#232B38] space-y-2">
            <p className="text-[11px] text-[#8B949E]">PRONG 1: B-Tree &amp; FTS5 exact catalog (&lt;2ms, 0 tokens)</p>
            <p className="text-[11px] text-[#8B949E]">PRONG 2: Local NanoRunner + Multi-Hop GraphRAG</p>
          </div>
          <Button variant="gold" size="md" className="w-full" onClick={() => setIsCalibrationOpen(false)}>Confirmar Configuração</Button>
        </div>
      </Drawer>
    </div>
  );
}
