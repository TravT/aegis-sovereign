'use client';

import React from 'react';
import { Zap, Brain, AlertTriangle, ShieldCheck, Clock, TrendingDown } from 'lucide-react';
import { Badge } from '@aegis/ui';

export interface RouteBannerProps {
  routeType: string;
  latency: number;
  isProng1: boolean;
  confidenceScore: number;
  confidenceLevel: string;
  tokensSavedPct?: string;
  executionMode?: string;
  isMiss?: boolean;
  className?: string;
}

export const RouteBanner: React.FC<RouteBannerProps> = ({
  routeType,
  latency,
  isProng1,
  confidenceScore,
  confidenceLevel,
  tokensSavedPct = '99.2%',
  executionMode,
  isMiss = false,
  className = '',
}) => {
  if (isMiss) {
    return (
      <div
        className={`p-3.5 rounded-lg border border-[#FFA726]/40 bg-gradient-to-r from-[#FFA726]/15 via-[#141A24] to-[#0E121A] shadow-md flex flex-wrap items-center justify-between gap-3 ${className}`}
      >
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-md bg-[#FFA726]/20 text-[#FFA726]">
            <AlertTriangle className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-serif text-xs font-bold text-[#FFA726] tracking-wide">
                PRONG 1: IDENTIFIER NOT IN DIRECT B-TREE CATALOG
              </span>
              <Badge variant="warning" size="sm">
                SAFE FAILURE GUARDRAIL
              </Badge>
            </div>
            <p className="text-[11px] text-[#8B949E] mt-0.5 font-sans">
              Zero hallucinations triggered. Neighboring registered procedures and alarms suggested below.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 font-mono text-[11px]">
          <span className="px-2 py-0.5 rounded bg-[#141A24] border border-[#232B38] text-[#8B949E]">
            LATENCY: <strong className="text-[#FFA726]">{latency.toFixed(2)}ms</strong>
          </span>
          <span className="px-2 py-0.5 rounded bg-[#141A24] border border-[#232B38] text-[#8B949E]">
            CONFIDENCE: <strong className="text-[#FFA726]">{(confidenceScore * 100).toFixed(0)}%</strong>
          </span>
        </div>
      </div>
    );
  }

  if (isProng1) {
    return (
      <div
        className={`p-3.5 rounded-lg border border-[#00E676]/40 bg-gradient-to-r from-[#00E676]/15 via-[#141A24] to-[#0E121A] shadow-[0_2px_16px_rgba(0,230,118,0.12)] flex flex-wrap items-center justify-between gap-3 ${className}`}
      >
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-md bg-[#00E676]/20 text-[#00E676] animate-pulse">
            <Zap className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-serif text-xs font-bold text-[#A7F3D0] tracking-wide">
                PRONG 1: DETERMINISTIC FAST-PATH (&lt;2ms)
              </span>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#00E676]/20 border border-[#00E676]/40 text-[#00E676]">
                EXACT B-TREE / FTS5
              </span>
            </div>
            <p className="text-[11px] text-[#8B949E] mt-0.5 font-sans">
              Static exact answer retrieved directly from indexed metadata • 0 LLM tokens consumed.
            </p>
          </div>
        </div>

        <div className="flex items-center flex-wrap gap-2 font-mono text-[11px]">
          <span className="px-2 py-0.5 rounded bg-[#141A24] border border-[#232B38] text-[#8B949E] flex items-center gap-1">
            <Clock className="w-3 h-3 text-[#00E676]" />
            <span>LATENCY:</span>
            <strong className="text-[#00E676]">{latency.toFixed(2)}ms</strong>
          </span>
          <span className="px-2 py-0.5 rounded bg-[#141A24] border border-[#232B38] text-[#8B949E] flex items-center gap-1">
            <TrendingDown className="w-3 h-3 text-[#00E676]" />
            <span>TOKENS SAVED:</span>
            <strong className="text-[#00E676]">{tokensSavedPct}</strong>
          </span>
          <span className="px-2 py-0.5 rounded bg-[#141A24] border border-[#232B38] text-[#8B949E]">
            CONFIDENCE: <strong className="text-[#00E676]">{(confidenceScore * 100).toFixed(0)}%</strong>
          </span>
        </div>
      </div>
    );
  }

  // Prong 2 Semantic & Synthesis Banner
  return (
    <div
      className={`p-3.5 rounded-lg border border-[#2979FF]/40 bg-gradient-to-r from-[#2979FF]/15 via-[#141A24] to-[#0E121A] shadow-[0_2px_16px_rgba(41,121,255,0.12)] flex flex-wrap items-center justify-between gap-3 ${className}`}
    >
      <div className="flex items-center gap-2.5">
        <div className="p-1.5 rounded-md bg-[#2979FF]/20 text-[#2979FF]">
          <Brain className="w-4 h-4" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="font-serif text-xs font-bold text-[#82B1FF] tracking-wide">
              PRONG 2: SEMANTIC &amp; RELATIONAL SYNTHESIS
            </span>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#2979FF]/20 border border-[#2979FF]/40 text-[#82B1FF]">
              {executionMode || 'neural_ollama_local'}
            </span>
          </div>
          <p className="text-[11px] text-[#8B949E] mt-0.5 font-sans">
            Minimal LLM summary grounded in multi-hop GraphRAG and SQLite WAL evidence.
          </p>
        </div>
      </div>

      <div className="flex items-center flex-wrap gap-2 font-mono text-[11px]">
        <span className="px-2 py-0.5 rounded bg-[#141A24] border border-[#232B38] text-[#8B949E] flex items-center gap-1">
          <Clock className="w-3 h-3 text-[#2979FF]" />
          <span>LATENCY:</span>
          <strong className="text-[#82B1FF]">{latency.toFixed(1)}ms</strong>
        </span>
        <span className="px-2 py-0.5 rounded bg-[#141A24] border border-[#232B38] text-[#8B949E] flex items-center gap-1">
          <ShieldCheck className="w-3 h-3 text-[#00E676]" />
          <span>CONFIDENCE:</span>
          <strong className="text-[#00E676]">{(confidenceScore * 100).toFixed(0)}% ({confidenceLevel})</strong>
        </span>
      </div>
    </div>
  );
};
