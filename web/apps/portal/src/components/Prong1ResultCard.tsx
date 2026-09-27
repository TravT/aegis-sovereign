'use client';

import React, { useState } from 'react';
import {
  FileText,
  ExternalLink,
  Copy,
  Check,
  Search,
  Wrench,
  Image as ImageIcon,
  Table as TableIcon,
  Zap,
} from 'lucide-react';
import { RouterResultRecord } from '@/types';

export interface Prong1ResultCardProps {
  record: RouterResultRecord;
  index: number;
  confidenceScore?: number;
  onOpenSource?: (uri: string) => void;
  onJumpCauses?: (uri: string) => void;
  onRenderDiagram?: (uri: string) => void;
  onInspectTable?: (title: string, tableMarkdown: string) => void;
  className?: string;
}

export const Prong1ResultCard: React.FC<Prong1ResultCardProps> = ({
  record,
  index,
  confidenceScore = 0.99,
  onOpenSource,
  onJumpCauses,
  onRenderDiagram,
  onInspectTable,
  className = '',
}) => {
  const [copiedMml, setCopiedMml] = useState<boolean>(false);
  const vUri = record.virtual_uri || record.source_uri || record.file_path || '';
  const secs = record.structured_sections || {};
  const desc = secs['Description'] || record.content || record.snippet || '';
  const causes = secs['Possible Causes'] || '';
  const proc = secs['Procedure'] || '';
  const params = secs['Parameters'] || '';
  const impact = secs['Impact on the System'] || '';

  // Extract MML commands for quick copy if present
  const mmlMatch = proc.match(/(?:DSP|LST|MOD|ADD|RMV|TST|SET)\s+[A-Z0-9_:]+/i);
  const mmlCommand = mmlMatch ? mmlMatch[0] : (proc.length > 0 ? proc.slice(0, 80) : '');

  const handleCopyMml = () => {
    if (mmlCommand) {
      navigator.clipboard?.writeText(mmlCommand);
      setCopiedMml(true);
      setTimeout(() => setCopiedMml(false), 2000);
    }
  };

  // Detect markdown table in any of the sections
  const hasMarkdownTable = (desc + causes + proc + params + impact).includes('|');

  return (
    <article
      id={`source-card-${index}`}
      className={`p-4 lg:p-5 rounded-xl bg-gradient-to-b from-[#141A24] to-[#0E121A] border border-[#00E676]/35 shadow-[0_4px_24px_rgba(0,0,0,0.4)] space-y-4 transition-all hover:border-[#00E676]/60 ${className}`}
    >
      {/* Card Header */}
      <div className="flex items-start justify-between gap-3 border-b border-[#232B38] pb-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-xs font-bold text-[#A7F3D0] px-2 py-0.5 rounded bg-[#00E676]/15 border border-[#00E676]/40 flex items-center gap-1">
              <Zap className="w-3 h-3 text-[#00E676]" />
              PRONG 1 EXACT
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#141A24] border border-[#232B38] text-[#8B949E]">
              0 LLM TOKENS
            </span>
            {record.doc_identifier && (
              <span className="text-xs font-mono font-semibold text-[#F3E5AB]">
                {record.doc_identifier}
              </span>
            )}
          </div>
          <h3 className="font-serif text-sm lg:text-base font-bold text-[#E6EDF3]">
            [{index}] {record.title || record.doc_identifier}
          </h3>
        </div>

        {/* Circular Confidence Meter */}
        <div className="flex items-center gap-2 shrink-0">
          <div className="text-right font-mono text-[10px] hidden sm:block">
            <p className="text-[#8B949E]">VERIFIED</p>
            <p className="text-[#00E676] font-bold">{(confidenceScore * 100).toFixed(0)}%</p>
          </div>
          <div className="w-9 h-9 rounded-full bg-[#0E121A] border-2 border-[#00E676] flex items-center justify-center font-mono text-[11px] font-bold text-[#00E676] shadow-[0_0_8px_rgba(0,230,118,0.3)]">
            {(confidenceScore * 100).toFixed(0)}
          </div>
        </div>
      </div>

      {/* URI Bar */}
      {vUri && (
        <div className="flex items-center justify-between text-xs font-mono p-2 rounded bg-[#07090D] border border-[#232B38] text-[#8B949E]">
          <span className="truncate max-w-[80%] text-[#82B1FF]">
            🔗 {vUri}
          </span>
          <span className="text-[10px] text-[#00E676] bg-[#00E676]/10 px-1.5 py-0.5 rounded shrink-0">
            O_RDONLY ZERO-COPY
          </span>
        </div>
      )}

      {/* Structured Content Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
        {/* Description Section */}
        {desc && (
          <div className="p-3 rounded-lg bg-[#0E121A] border border-[#232B38] space-y-1.5 md:col-span-2">
            <p className="font-mono text-[10px] text-[#D4AF37] uppercase font-semibold">
              📋 Descrição &amp; Especificação
            </p>
            <p className="text-[#E6EDF3] leading-relaxed whitespace-pre-line">
              {desc}
            </p>
          </div>
        )}

        {/* Possible Causes Section */}
        {causes && (
          <div className="p-3 rounded-lg bg-[#0E121A] border border-[#232B38] space-y-1.5">
            <p className="font-mono text-[10px] text-[#FFA726] uppercase font-semibold">
              🔍 Causas Prováveis (Root Cause)
            </p>
            <p className="text-[#E6EDF3] leading-relaxed whitespace-pre-line">
              {causes}
            </p>
          </div>
        )}

        {/* Remediation Procedure */}
        {proc && (
          <div className="p-3 rounded-lg bg-[#0E121A] border border-[#232B38] space-y-1.5">
            <div className="flex items-center justify-between">
              <p className="font-mono text-[10px] text-[#00E676] uppercase font-semibold">
                🛠️ Procedimento de Remediação
              </p>
              {mmlCommand && (
                <button
                  type="button"
                  onClick={handleCopyMml}
                  className="flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded bg-[#00E676]/15 border border-[#00E676]/40 text-[#00E676] hover:bg-[#00E676]/30 transition-colors"
                  title="Copiar comando MML de remediação para clipboard"
                >
                  {copiedMml ? <Check className="w-3 h-3 text-[#00E676]" /> : <Copy className="w-3 h-3" />}
                  <span>{copiedMml ? 'Copiado!' : 'Copiar MML'}</span>
                </button>
              )}
            </div>
            <p className="text-[#E6EDF3] font-mono text-[11px] leading-relaxed whitespace-pre-line">
              {proc}
            </p>
          </div>
        )}

        {/* Parameters & System Impact */}
        {(params || impact) && (
          <div className="p-3 rounded-lg bg-[#0E121A] border border-[#232B38] space-y-1.5 md:col-span-2">
            <p className="font-mono text-[10px] text-[#82B1FF] uppercase font-semibold">
              ⚙️ Parâmetros Técnicos &amp; Impacto Operacional
            </p>
            {params && <p className="text-[#8B949E] font-mono text-[11px]">{params}</p>}
            {impact && <p className="text-[#E6EDF3] text-xs mt-1">{impact}</p>}
          </div>
        )}
      </div>

      {/* Jump Buttons Action Row */}
      <div className="pt-2 border-t border-[#232B38] flex flex-wrap items-center gap-2 text-xs font-mono">
        <button
          type="button"
          onClick={() => onOpenSource?.(vUri)}
          className="px-3 py-1.5 rounded-md bg-[#141A24] border border-[#232B38] hover:border-[#D4AF37] hover:bg-[#1A2230] text-[#F3E5AB] flex items-center gap-1.5 transition-all"
        >
          <FileText className="w-3.5 h-3.5 text-[#D4AF37]" />
          <span>[Open Source]</span>
        </button>

        {causes && (
          <button
            type="button"
            onClick={() => onJumpCauses?.(vUri)}
            className="px-3 py-1.5 rounded-md bg-[#141A24] border border-[#232B38] hover:border-[#FFA726] hover:bg-[#1A2230] text-[#FFA726] flex items-center gap-1.5 transition-all"
          >
            <Search className="w-3.5 h-3.5" />
            <span>[View Causes]</span>
          </button>
        )}

        <button
          type="button"
          onClick={() => onRenderDiagram?.(vUri)}
          className="px-3 py-1.5 rounded-md bg-[#141A24] border border-[#232B38] hover:border-[#2979FF] hover:bg-[#1A2230] text-[#82B1FF] flex items-center gap-1.5 transition-all"
        >
          <ImageIcon className="w-3.5 h-3.5" />
          <span>[Render Diagram]</span>
        </button>

        {hasMarkdownTable && (
          <button
            type="button"
            onClick={() => onInspectTable?.(record.title, desc + '\n' + params)}
            className="px-3 py-1.5 rounded-md bg-[#141A24] border border-[#232B38] hover:border-[#00E676] hover:bg-[#1A2230] text-[#00E676] flex items-center gap-1.5 transition-all ml-auto"
          >
            <TableIcon className="w-3.5 h-3.5" />
            <span>[Inspect Table]</span>
          </button>
        )}
      </div>
    </article>
  );
};
