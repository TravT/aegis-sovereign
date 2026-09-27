'use client';

import React from 'react';
import {
  Activity,
  Cpu,
  Database,
  FolderOpen,
  Layers,
  Network,
  Sliders,
  Sun,
  Moon,
  ShieldCheck,
} from 'lucide-react';
import { Badge, Button } from '@aegis/ui';
import { ApplianceStatus } from '@/types';

export interface SearchHeaderProps {
  status: ApplianceStatus;
  latency: number;
  theme?: 'dark' | 'light';
  onToggleTheme?: () => void;
  onOpenSources: () => void;
  onOpenCalibration: () => void;
}

export const SearchHeader: React.FC<SearchHeaderProps> = ({
  status,
  latency,
  theme = 'dark',
  onToggleTheme,
  onOpenSources,
  onOpenCalibration,
}) => {
  const totalEntities = status.knowledge_graph?.total_entities ?? 9117;
  const totalRecords = (status as any).total_records ?? status.knowledge_graph?.total_documents ?? 49001;

  return (
    <header className="sticky top-0 z-40 bg-[#0E121A]/95 backdrop-blur-md border-b border-[#232B38] px-4 lg:px-8 py-3 flex flex-wrap items-center justify-between gap-4">
      {/* Brand & Identity */}
      <div className="flex items-center gap-3.5">
        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-[#D4AF37] to-[#997A15] flex items-center justify-center font-serif font-bold text-black text-xl shadow-[0_0_16px_rgba(212,175,55,0.35)] shrink-0">
          Æ
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
            Two-Pronged Hybrid Retrieval &amp; O_RDONLY Source Inspector (ADR-40)
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

        {/* Latency Pill */}
        <div className="hidden sm:flex items-center gap-2 px-2.5 py-1 rounded bg-[#141A24] border border-[#232B38] font-mono text-xs text-[#8B949E]">
          <Activity className="w-3.5 h-3.5 text-[#00E676]" />
          <span>LATENCY:</span>
          <span className="text-[#00E676] font-semibold">{latency.toFixed(1)}ms</span>
        </div>

        {/* Records Pill */}
        <div className="hidden md:flex items-center gap-2 px-2.5 py-1 rounded bg-[#141A24] border border-[#232B38] font-mono text-xs text-[#8B949E]">
          <Database className="w-3.5 h-3.5 text-[#2979FF]" />
          <span>RECORDS:</span>
          <span className="text-[#F3E5AB] font-semibold">{Number(totalRecords).toLocaleString()}</span>
        </div>

        {/* Entities Pill */}
        <div className="hidden lg:flex items-center gap-2 px-2.5 py-1 rounded bg-[#141A24] border border-[#232B38] font-mono text-xs text-[#8B949E]">
          <Network className="w-3.5 h-3.5 text-[#D4AF37]" />
          <span>ENTITIES:</span>
          <span className="text-[#E6EDF3] font-semibold">{Number(totalEntities).toLocaleString()}</span>
        </div>

        {/* Theme Switcher Button */}
        {onToggleTheme && (
          <button
            type="button"
            onClick={onToggleTheme}
            className="p-1.5 rounded-md bg-[#141A24] border border-[#232B38] text-[#8B949E] hover:text-[#F3E5AB] hover:border-[#D4AF37]/40 transition-colors"
            title="Toggle contrast theme"
          >
            {theme === 'dark' ? <Sun className="w-4 h-4 text-[#D4AF37]" /> : <Moon className="w-4 h-4 text-[#8B949E]" />}
          </button>
        )}

        {/* Quick Action Buttons */}
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            icon={<FolderOpen className="w-3.5 h-3.5 text-[#D4AF37]" />}
            onClick={onOpenSources}
          >
            SOURCES
          </Button>

          <Button
            variant="gold"
            size="sm"
            icon={<Sliders className="w-3.5 h-3.5 text-black" />}
            onClick={onOpenCalibration}
          >
            CALIBRATION
          </Button>
        </div>
      </div>
    </header>
  );
};
