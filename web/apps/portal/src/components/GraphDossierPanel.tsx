'use client';

import React from 'react';
import { Network, Terminal, Wrench, BarChart2, Image as ImageIcon, ChevronRight } from 'lucide-react';
import { Badge } from '@aegis/ui';
import { RouterGraphDossier, RouterNeighbor } from '@/types';

export interface GraphDossierPanelProps {
  dossier: RouterGraphDossier | null;
  onSelectEntity?: (entityName: string) => void;
  onOpenDossierModal?: (entityName: string) => void;
  className?: string;
}

export const GraphDossierPanel: React.FC<GraphDossierPanelProps> = ({
  dossier,
  onSelectEntity,
  onOpenDossierModal,
  className = '',
}) => {
  if (!dossier || !dossier.neighbors || dossier.neighbors.length === 0) {
    return null;
  }

  const rootName = dossier.name || dossier.entity || 'Root Entity';
  const neighbors = dossier.neighbors;

  // Group neighbors by relation type
  const diagnosedMml = neighbors.filter((n) => n.relation === 'DIAGNOSED_BY_MML');
  const remediatedMml = neighbors.filter((n) => n.relation === 'REMEDIATED_BY_MML');
  const measuredCounter = neighbors.filter((n) => n.relation === 'MEASURED_BY_COUNTER');
  const hasDiagram = neighbors.filter((n) => n.relation === 'HAS_DIAGRAM');
  const otherRelations = neighbors.filter(
    (n) =>
      !['DIAGNOSED_BY_MML', 'REMEDIATED_BY_MML', 'MEASURED_BY_COUNTER', 'HAS_DIAGRAM'].includes(
        n.relation
      )
  );

  return (
    <div
      className={`p-4 rounded-xl bg-gradient-to-b from-[#141A24] to-[#0A0D12] border border-[#D4AF37]/35 shadow-[0_4px_24px_rgba(0,0,0,0.4)] space-y-3.5 ${className}`}
    >
      {/* Dossier Header */}
      <div className="flex items-center justify-between border-b border-[#232B38] pb-2.5">
        <div className="flex items-center gap-2">
          <div className="p-1 rounded bg-[#D4AF37]/20 text-[#D4AF37]">
            <Network className="w-4 h-4" />
          </div>
          <div>
            <h4 className="font-serif text-xs font-bold text-[#F3E5AB] tracking-wide uppercase">
              DOSSIÊ RELACIONAL // {rootName}
            </h4>
            <span className="text-[10px] text-[#8B949E] font-mono">
              Grafo de entidades multi-hop verificado no SQLite WAL
            </span>
          </div>
        </div>

        <Badge variant="sovereign" size="sm">
          {neighbors.length} VÍNCULOS
        </Badge>
      </div>

      {/* Relational Strata Groups */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
        {/* DIAGNOSED_BY_MML Group */}
        {diagnosedMml.length > 0 && (
          <div className="p-2.5 rounded-lg bg-[#0E121A] border border-[#00E676]/30 space-y-1.5">
            <p className="font-mono text-[10px] text-[#00E676] font-semibold uppercase flex items-center gap-1">
              <Terminal className="w-3 h-3" />
              <span>DIAGNOSED_BY_MML ({diagnosedMml.length})</span>
            </p>
            <div className="flex flex-wrap gap-1.5">
              {diagnosedMml.map((node, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onSelectEntity?.(node.name)}
                  className="px-2 py-1 rounded bg-[#141A24] border border-[#00E676]/40 text-[#A7F3D0] hover:bg-[#00E676]/20 transition-all font-mono text-[11px] flex items-center gap-1"
                >
                  <code>{node.name}</code>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* REMEDIATED_BY_MML Group */}
        {remediatedMml.length > 0 && (
          <div className="p-2.5 rounded-lg bg-[#0E121A] border border-[#2979FF]/30 space-y-1.5">
            <p className="font-mono text-[10px] text-[#82B1FF] font-semibold uppercase flex items-center gap-1">
              <Wrench className="w-3 h-3" />
              <span>REMEDIATED_BY_MML ({remediatedMml.length})</span>
            </p>
            <div className="flex flex-wrap gap-1.5">
              {remediatedMml.map((node, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onSelectEntity?.(node.name)}
                  className="px-2 py-1 rounded bg-[#141A24] border border-[#2979FF]/40 text-[#82B1FF] hover:bg-[#2979FF]/20 transition-all font-mono text-[11px] flex items-center gap-1"
                >
                  <code>{node.name}</code>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* MEASURED_BY_COUNTER Group */}
        {measuredCounter.length > 0 && (
          <div className="p-2.5 rounded-lg bg-[#0E121A] border border-[#D4AF37]/30 space-y-1.5">
            <p className="font-mono text-[10px] text-[#D4AF37] font-semibold uppercase flex items-center gap-1">
              <BarChart2 className="w-3 h-3" />
              <span>MEASURED_BY_COUNTER ({measuredCounter.length})</span>
            </p>
            <div className="flex flex-wrap gap-1.5">
              {measuredCounter.map((node, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onSelectEntity?.(node.name)}
                  className="px-2 py-1 rounded bg-[#141A24] border border-[#D4AF37]/40 text-[#F3E5AB] hover:bg-[#D4AF37]/20 transition-all font-mono text-[11px]"
                >
                  {node.name}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* HAS_DIAGRAM Group */}
        {hasDiagram.length > 0 && (
          <div className="p-2.5 rounded-lg bg-[#0E121A] border border-[#A855F7]/30 space-y-1.5">
            <p className="font-mono text-[10px] text-[#C084FC] font-semibold uppercase flex items-center gap-1">
              <ImageIcon className="w-3 h-3" />
              <span>HAS_DIAGRAM ({hasDiagram.length})</span>
            </p>
            <div className="flex flex-wrap gap-1.5">
              {hasDiagram.map((node, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onSelectEntity?.(node.name)}
                  className="px-2 py-1 rounded bg-[#141A24] border border-[#A855F7]/40 text-[#E9D5FF] hover:bg-[#A855F7]/20 transition-all font-mono text-[11px]"
                >
                  {node.name}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Other Relations */}
        {otherRelations.length > 0 && (
          <div className="p-2.5 rounded-lg bg-[#0E121A] border border-[#232B38] space-y-1.5 md:col-span-2">
            <p className="font-mono text-[10px] text-[#8B949E] font-semibold uppercase">
              OUTRAS RELAÇÕES CRUZADAS ({otherRelations.length})
            </p>
            <div className="flex flex-wrap gap-1.5">
              {otherRelations.map((node, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onSelectEntity?.(node.name)}
                  className="px-2 py-1 rounded bg-[#141A24] border border-[#232B38] text-[#8B949E] hover:text-[#E6EDF3] hover:border-[#D4AF37]/40 transition-all text-[11px] font-mono flex items-center gap-1"
                >
                  <span className="text-[#D4AF37]">[{node.relation}]</span>
                  <span>{node.name}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Footer Link to Full Dossier Modal */}
      {onOpenDossierModal && (
        <div className="pt-2 border-t border-[#232B38] flex justify-end">
          <button
            type="button"
            onClick={() => onOpenDossierModal(rootName)}
            className="text-[11px] font-mono text-[#D4AF37] hover:text-[#F3E5AB] flex items-center gap-1 transition-colors"
          >
            <span>Inspecionar Dossiê Societário Completo</span>
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  );
};
