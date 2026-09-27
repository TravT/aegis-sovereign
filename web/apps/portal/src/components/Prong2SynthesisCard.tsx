'use client';

import React from 'react';
import { Brain, ShieldCheck, Lock, Table as TableIcon, BookOpen } from 'lucide-react';
import { CitationPill } from '@aegis/ui';
import { Citation, RouterFastSummary } from '@/types';

export interface Prong2SynthesisCardProps {
  summary: RouterFastSummary;
  latency: number;
  confidenceScore?: number;
  confidenceLevel?: string;
  citations?: Citation[];
  selectedCitationIndex?: number;
  onSelectCitation?: (citation: Citation) => void;
  onInspectTable?: (title: string, markdownTable: string) => void;
  className?: string;
}

export const Prong2SynthesisCard: React.FC<Prong2SynthesisCardProps> = ({
  summary,
  latency,
  confidenceScore = 0.95,
  confidenceLevel = 'HIGH_VERIFIED',
  citations = [],
  selectedCitationIndex,
  onSelectCitation,
  onInspectTable,
  className = '',
}) => {
  const answer = summary.answer || '';
  const mode = summary.execution_mode || 'neural_ollama_local';
  const hasMarkdownTable = answer.includes('|');

  // Format mode badge styling
  const getModeBadgeClass = () => {
    switch (mode) {
      case 'neural_ollama_local':
        return 'bg-[#2979FF]/15 border-[#2979FF]/40 text-[#82B1FF]';
      case 'extractive_template_fallback':
        return 'bg-[#D4AF37]/15 border-[#D4AF37]/40 text-[#F3E5AB]';
      case 'epistemic_refusal':
        return 'bg-[#FF5252]/15 border-[#FF5252]/40 text-[#FF8A80]';
      default:
        return 'bg-[#141A24] border-[#232B38] text-[#8B949E]';
    }
  };

  return (
    <section
      className={`p-4 lg:p-6 rounded-xl bg-gradient-to-b from-[#141A24] to-[#0E121A] border border-[#2979FF]/40 shadow-[0_4px_24px_rgba(0,0,0,0.5)] space-y-4 ${className}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#232B38] pb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-md bg-[#2979FF]/20 text-[#2979FF]">
            <Brain className="w-4 h-4" />
          </div>
          <div>
            <h3 className="font-serif text-xs font-bold text-[#82B1FF] tracking-wide uppercase">
              MINIMAL LLM SYNTHESIS // NANORUNNER
            </h3>
            <span className="text-[10px] text-[#8B949E] font-mono">
              Grounded in local SQLite WAL &amp; Qdrant int8 vectors
            </span>
          </div>
        </div>

        {/* Badges: Model Mode & Confidence Meter */}
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded border ${getModeBadgeClass()}`}
          >
            {mode}
          </span>

          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#00E676]/10 border border-[#00E676]/30 text-[#00E676] flex items-center gap-1">
            <ShieldCheck className="w-3 h-3" />
            <span>CONF: {(confidenceScore * 100).toFixed(0)}% ({confidenceLevel})</span>
          </span>
        </div>
      </div>

      {/* Synthesized Answer Body */}
      <div className="text-xs leading-relaxed text-[#E6EDF3] space-y-3 font-sans">
        <div className="whitespace-pre-line text-justify leading-relaxed">
          {answer}
        </div>

        {/* Table Extraction Jump Button if table exists */}
        {hasMarkdownTable && (
          <div className="p-2.5 rounded-lg bg-[#07090D] border border-[#232B38] flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-mono text-[#00E676]">
              <TableIcon className="w-4 h-4" />
              <span>Multi-column structured table detected in synthesis response.</span>
            </div>
            <button
              type="button"
              onClick={() => onInspectTable?.('Synthesis Structured Table', answer)}
              className="text-xs font-mono px-2.5 py-1 rounded bg-[#00E676]/15 border border-[#00E676]/40 text-[#00E676] hover:bg-[#00E676]/30 transition-colors flex items-center gap-1.5"
            >
              <span>[Open in Table Viewer &amp; CSV Export &rarr;]</span>
            </button>
          </div>
        )}

        {/* Interactive Citation Footnotes */}
        {citations && citations.length > 0 && (
          <div className="pt-3 border-t border-[#232B38]">
            <p className="text-[10px] font-mono text-[#8B949E] uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <BookOpen className="w-3.5 h-3.5 text-[#D4AF37]" />
              <span>CUSTODIED CITATIONS &amp; VERIFIED SOURCES ({citations.length}):</span>
            </p>
            <div className="flex flex-wrap gap-2">
              {citations.map((c) => (
                <CitationPill
                  key={c.citation_index}
                  index={c.citation_index}
                  title={c.title}
                  heading={c.heading}
                  confidence={c.rrf_score}
                  page={c.page}
                  active={selectedCitationIndex === c.citation_index}
                  onClick={() => onSelectCitation?.(c)}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
};
